// The migration runner (plan PD4, U3) and the readiness check of the ledger (A3).
//
// Drizzle Kit generates SQL into migrations/; this runner applies it against a ledger table,
// with a lock and hash checks. Drizzle Kit's own `migrate` and `push` are never used (U5).
// Migrations are forward-only: there is no down command and no way to reapply a file.
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type pg from 'pg';
import {
	DbError,
	LOCK_TIMEOUT_MS,
	acquireAdvisoryLock,
	ensureAppRole,
	hasUrlParameters,
	newClient,
	sqlstateOf,
	type AppRoleOutcome
} from './roles.ts';

/** One shipped migration: its name (the file name without `.sql`) and the SHA-256 of its bytes. */
export interface ManifestEntry {
	readonly name: string;
	readonly sha256: string;
}

/** `migrations/manifest.json`: the lock on the files, and what the app ships (U5). */
export interface Manifest {
	readonly migrations: readonly ManifestEntry[];
}

export interface MigrationFile extends ManifestEntry {
	readonly sql: string;
}

/** The ledger (U3 step 3). Bookkeeping, not a DATA-MODEL table; it holds no kit data. */
export const LEDGER_TABLE = 'schema_migrations';

// One fixed key for the per-database runner lock ("jademigr" in ASCII). Postgres keys an
// advisory lock by database, so this serializes runners on one database only.
const MIGRATE_LOCK_KEY = '7665518427551393650';

export function sha256(bytes: Buffer | string): string {
	return createHash('sha256').update(bytes).digest('hex');
}

/** Every `*.sql` file of `dir`, in name order, with its hash. */
export function readMigrations(dir: string): MigrationFile[] {
	return readdirSync(dir)
		.filter((file) => file.endsWith('.sql'))
		.sort()
		.map((file) => {
			const bytes = readFileSync(join(dir, file));
			return { name: file.slice(0, -'.sql'.length), sha256: sha256(bytes), sql: bytes.toString() };
		});
}

/** The manifest of the files in `dir`, as `pnpm db:manifest` writes it. */
export function buildManifest(dir: string): Manifest {
	return { migrations: readMigrations(dir).map(({ name, sha256 }) => ({ name, sha256 })) };
}

/** The text `pnpm db:manifest` writes to `manifest.json`. */
export function formatManifest(manifest: Manifest): string {
	return `${JSON.stringify(manifest, null, '\t')}\n`;
}

/** `dir/manifest.json`, or an empty manifest when there is none. */
export function readManifest(dir: string): Manifest {
	const path = join(dir, 'manifest.json');
	if (!existsSync(path)) return { migrations: [] };
	return parseManifest(readFileSync(path, 'utf8'));
}

export function parseManifest(text: string): Manifest {
	const value = JSON.parse(text) as { migrations?: unknown };
	const entries = Array.isArray(value.migrations) ? value.migrations : null;
	if (
		entries === null ||
		!entries.every(
			(e: { name?: unknown; sha256?: unknown }) =>
				typeof e?.name === 'string' && typeof e?.sha256 === 'string'
		)
	) {
		throw new DbError('MIGRATION_MANIFEST_MISMATCH');
	}
	return { migrations: entries.map((e: ManifestEntry) => ({ name: e.name, sha256: e.sha256 })) };
}

const same = (a: ManifestEntry | undefined, b: ManifestEntry | undefined) =>
	a !== undefined && b !== undefined && a.name === b.name && a.sha256 === b.sha256;

/** The files must equal the manifest, name for name and hash for hash (U3 step 4). */
export function checkAgainstManifest(files: readonly ManifestEntry[], manifest: Manifest): void {
	const n = Math.max(files.length, manifest.migrations.length);
	for (let i = 0; i < n; i++) {
		const file = files[i];
		const entry = manifest.migrations[i];
		if (!same(file, entry)) {
			throw new DbError('MIGRATION_MANIFEST_MISMATCH', { migration: (file ?? entry)?.name });
		}
	}
}

/** Anything with pg's `query`: a client or a pool. */
export interface Queryable {
	query(text: string, values?: unknown[]): Promise<pg.QueryResult>;
}

async function readLedger(db: Queryable): Promise<ManifestEntry[] | null> {
	try {
		const { rows } = await db.query(`SELECT name, sha256 FROM ${LEDGER_TABLE} ORDER BY name`);
		return rows as ManifestEntry[];
	} catch (err) {
		if (sqlstateOf(err) === '42P01') return null; // no ledger yet
		throw err;
	}
}

export type MigrationStatus = 'ok' | 'behind' | 'mismatch';

/**
 * Compare the ledger with the migrations an app ships (A3's readiness check), over any pool,
 * the app role's included. `ok` when every shipped migration is applied with the same hash; a
 * database that is ahead (more rows than shipped) is `ok`, which lets the previous app run after
 * a newer migration. `behind` when a shipped migration is missing; `mismatch` when a row differs.
 * Errors other than a missing ledger propagate.
 */
export async function migrationStatus(db: Queryable, shipped: Manifest): Promise<MigrationStatus> {
	const ledger = (await readLedger(db)) ?? [];
	for (let i = 0; i < shipped.migrations.length; i++) {
		const row = ledger[i];
		if (row === undefined) return 'behind';
		if (!same(row, shipped.migrations[i])) return 'mismatch';
	}
	return 'ok';
}

export interface MigrateOptions {
	/** The owner's URL (jade_owner) for the target database. */
	readonly ownerUrl: string;
	/** The app's URL (jade_app) for the same database, whose password the role bootstrap sets. */
	readonly appUrl: string;
	/** The directory holding the `*.sql` files and `manifest.json`. */
	readonly dir: string;
	/**
	 * How long to wait for each advisory lock (the runner's, then the role bootstrap's) before
	 * failing with MIGRATION_LOCK_TIMEOUT or ROLE_LOCK_TIMEOUT. Default LOCK_TIMEOUT_MS (B4).
	 */
	readonly lockTimeoutMs?: number;
}

export interface MigrateResult {
	/** The names applied by this run, in order. */
	readonly applied: readonly string[];
	/** The ledger's length after the run. */
	readonly recorded: number;
	/** How many migrations `dir` holds. */
	readonly shipped: number;
	/** Whether the ledger holds more than `dir` ships (the database is ahead). */
	readonly ahead: boolean;
	readonly role: AppRoleOutcome;
}

/**
 * Apply the pending migrations of `dir` to the owner URL's database (plan U3):
 * 1. take the database's runner lock (bounded wait, MIGRATION_LOCK_TIMEOUT); 2. `ensureAppRole()` (the cluster lock: database lock
 * first, cluster lock second, so they cannot deadlock); 3. create the ledger if absent;
 * 4. check the files against the manifest; 5. compare with the ledger row by row, stopping with
 * MIGRATION_HISTORY_MISMATCH before applying anything if a name or hash differs, and returning
 * when the database is ahead; 6. apply each pending file in its own transaction with its ledger
 * row. Throws `DbError`.
 */
export async function migrate(options: MigrateOptions): Promise<MigrateResult> {
	if (hasUrlParameters(options.ownerUrl) || hasUrlParameters(options.appUrl)) {
		throw new DbError('MIGRATION_FAILED');
	}
	const files = readMigrations(options.dir);
	const client = newClient(options.ownerUrl);
	try {
		await client.connect();
	} catch (err) {
		await client.end().catch(() => {});
		throw new DbError('MIGRATION_FAILED', { sqlstate: sqlstateOf(err) });
	}
	try {
		const lockTimeoutMs = options.lockTimeoutMs ?? LOCK_TIMEOUT_MS;
		await acquireAdvisoryLock(client, MIGRATE_LOCK_KEY, lockTimeoutMs, 'MIGRATION_LOCK_TIMEOUT');
		const role = await ensureAppRole(options.ownerUrl, options.appUrl, { lockTimeoutMs });
		await client.query(
			`CREATE TABLE IF NOT EXISTS ${LEDGER_TABLE} (` +
				'name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())'
		);
		checkAgainstManifest(files, readManifest(options.dir));

		const ledger = (await readLedger(client)) ?? [];
		for (let i = 0; i < Math.min(ledger.length, files.length); i++) {
			if (!same(ledger[i], files[i])) {
				throw new DbError('MIGRATION_HISTORY_MISMATCH', { migration: files[i]!.name });
			}
		}
		const base = { shipped: files.length, role };
		if (ledger.length >= files.length) {
			return { ...base, applied: [], recorded: ledger.length, ahead: ledger.length > files.length };
		}

		const applied: string[] = [];
		for (const file of files.slice(ledger.length)) {
			try {
				await client.query('BEGIN');
				await client.query(file.sql);
				await client.query(`INSERT INTO ${LEDGER_TABLE} (name, sha256) VALUES ($1, $2)`, [
					file.name,
					file.sha256
				]);
				await client.query('COMMIT');
			} catch (err) {
				await client.query('ROLLBACK').catch(() => {});
				throw new DbError('MIGRATION_FAILED', { migration: file.name, sqlstate: sqlstateOf(err) });
			}
			applied.push(file.name);
		}
		return { ...base, applied, recorded: ledger.length + applied.length, ahead: false };
	} catch (err) {
		if (err instanceof DbError) throw err;
		throw new DbError('MIGRATION_FAILED', { sqlstate: sqlstateOf(err) });
	} finally {
		// Ending the session releases its advisory lock.
		await client.end().catch(() => {});
	}
}
