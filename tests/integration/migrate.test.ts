// The migration runner (plan U3, INV5). Every case uses an empty database of its own, never a
// clone, and migration directories copied to a temporary directory when a case needs others.
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import {
	DbError,
	buildManifest,
	ensureAppRole,
	formatManifest,
	migrate,
	migrationStatus,
	newClient,
	readManifest,
	withDatabase,
	type Manifest
} from '../../src/lib/server/db/index.ts';
import { createEmptyDatabase, type TestDatabase } from '../support/db.ts';
import {
	MIGRATIONS_DIR,
	clusterConfig,
	createTemplateDatabase,
	newRunId
} from '../support/global-setup-db.ts';

const shipped: Manifest = readManifest(MIGRATIONS_DIR);
const created: TestDatabase[] = [];
const dirs: string[] = [];

afterAll(async () => {
	await Promise.all(created.map((db) => db.drop()));
	for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
});

async function emptyDatabase(): Promise<TestDatabase> {
	const db = await createEmptyDatabase();
	created.push(db);
	return db;
}

/** A copy of migrations/ with `extra` files added, and its manifest rewritten to match. */
function migrationsWith(extra: Record<string, string> = {}, edit?: (dir: string) => void): string {
	const dir = mkdtempSync(join(tmpdir(), 'jade-migrations-'));
	dirs.push(dir);
	cpSync(MIGRATIONS_DIR, dir, { recursive: true });
	for (const [file, sql] of Object.entries(extra)) writeFileSync(join(dir, file), sql);
	edit?.(dir);
	writeFileSync(join(dir, 'manifest.json'), formatManifest(buildManifest(dir)));
	return dir;
}

const run = (db: TestDatabase, dir = MIGRATIONS_DIR) =>
	migrate({ ownerUrl: db.ownerUrl, appUrl: db.appUrl, dir });

async function ledger(db: TestDatabase) {
	const { rows } = await db.owner.query('SELECT name, sha256 FROM schema_migrations ORDER BY name');
	return rows as { name: string; sha256: string }[];
}

async function failure(promise: Promise<unknown>): Promise<DbError> {
	try {
		await promise;
	} catch (err) {
		expect(err).toBeInstanceOf(DbError);
		return err as DbError;
	}
	throw new Error('migrate() succeeded');
}

describe('migrate()', () => {
	it('ends a fresh database with the ledger equal to the manifest; a second run applies nothing', async () => {
		const db = await emptyDatabase();
		const first = await run(db);
		expect(first.applied).toEqual(shipped.migrations.map((m) => m.name));
		expect(await ledger(db)).toEqual(shipped.migrations);

		const second = await run(db);
		expect(second.applied).toEqual([]);
		expect(second.ahead).toBe(false);
		expect(await ledger(db)).toEqual(shipped.migrations);
	});

	it('stops with MIGRATION_HISTORY_MISMATCH when an applied file changed by one byte', async () => {
		const db = await emptyDatabase();
		await run(db);
		const before = await ledger(db);
		// The manifest is rewritten to match the edited file, so the manifest check accepts it and
		// only the ledger comparison can refuse it (PD15).
		const dir = migrationsWith({}, (d) => {
			const file = join(d, '0000_baseline.sql');
			writeFileSync(file, `${readFileSync(file, 'utf8')} `);
		});
		expect(buildManifest(dir)).toEqual(readManifest(dir));
		const err = await failure(run(db, dir));
		expect(err.tag).toBe('MIGRATION_HISTORY_MISMATCH');
		expect(err.migration).toBe('0000_baseline');
		expect(await ledger(db)).toEqual(before);
	});

	it('rolls a failing file back, with no ledger row', async () => {
		const db = await emptyDatabase();
		const dir = migrationsWith({
			'0001_fails.sql': 'CREATE TABLE scratch_fails (id int);\nSELECT 1 / 0;\n'
		});
		const err = await failure(run(db, dir));
		expect(err.tag).toBe('MIGRATION_FAILED');
		expect(err.migration).toBe('0001_fails');
		expect(err.sqlstate).toBe('22012');
		expect(await ledger(db)).toEqual(shipped.migrations);
		const { rows } = await db.owner.query("SELECT to_regclass('public.scratch_fails') AS t");
		expect(rows[0].t).toBeNull();
	});

	it('applies each file exactly once when two runners start together', async () => {
		const db = await emptyDatabase();
		const results = await Promise.all([run(db), run(db)]);
		const applied = results.flatMap((r) => r.applied).sort();
		expect(applied).toEqual(shipped.migrations.map((m) => m.name).sort());
		expect(await ledger(db)).toEqual(shipped.migrations);
	});

	it('refuses files that do not match the manifest, before applying anything', async () => {
		const db = await emptyDatabase();
		const dir = migrationsWith();
		writeFileSync(join(dir, '0001_unlisted.sql'), 'SELECT 1;\n');
		const err = await failure(run(db, dir));
		expect(err.tag).toBe('MIGRATION_MANIFEST_MISMATCH');
		const { rows } = await db.owner.query('SELECT count(*)::int AS n FROM schema_migrations');
		expect(rows[0].n).toBe(0);
	});
});

describe('readiness (migrationStatus over the app pool)', () => {
	it('reports ready when the database is ahead of the app, behind when the baseline is missing', async () => {
		const ahead = await emptyDatabase();
		const dir = migrationsWith({
			'0001_extra.sql': "COMMENT ON SCHEMA public IS 'jade-urd readiness test';\n"
		});
		expect((await run(ahead, dir)).applied).toEqual(['0000_baseline', '0001_extra']);
		// An app that ships only the baseline is ready on it, and its runner applies nothing.
		expect(await migrationStatus(ahead.app, shipped)).toBe('ok');
		const again = await run(ahead);
		expect(again).toMatchObject({ applied: [], ahead: true, recorded: 2, shipped: 1 });

		const empty = await emptyDatabase();
		expect(await migrationStatus(empty.app, shipped)).toBe('behind');
		expect(await migrationStatus(empty.owner, shipped)).toBe('behind');
	});

	it('reports mismatch when a shipped migration was applied with another hash', async () => {
		const db = await emptyDatabase();
		await run(db);
		const other: Manifest = {
			migrations: shipped.migrations.map((m) => ({ ...m, sha256: '0'.repeat(64) }))
		};
		expect(await migrationStatus(db.app, other)).toBe('mismatch');
		expect(await migrationStatus(db.app, shipped)).toBe('ok');
	});
});

describe('database URLs with a query string or fragment (jade-f1w)', () => {
	// 192.0.2.1 is reserved for documentation and nothing answers it: a runner that let the query
	// override the host would wait for its 10-second connect timeout instead of refusing at once.
	it('migrate() and ensureAppRole() refuse them before any connection', async () => {
		const db = await emptyDatabase();
		const remote = (url: string) => `${url}?host=192.0.2.1`;
		const started = Date.now();
		await expect(
			migrate({ ownerUrl: remote(db.ownerUrl), appUrl: db.appUrl, dir: MIGRATIONS_DIR })
		).rejects.toMatchObject({ tag: 'MIGRATION_FAILED' });
		await expect(
			migrate({
				ownerUrl: db.ownerUrl,
				appUrl: `${db.appUrl}?user=jade_owner`,
				dir: MIGRATIONS_DIR
			})
		).rejects.toMatchObject({ tag: 'MIGRATION_FAILED' });
		await expect(ensureAppRole(remote(db.ownerUrl), db.appUrl)).rejects.toMatchObject({
			tag: 'ROLE_BOOTSTRAP_FAILED'
		});
		await expect(ensureAppRole(db.ownerUrl, `${db.appUrl}#x`)).rejects.toMatchObject({
			tag: 'ROLE_BOOTSTRAP_FAILED'
		});
		expect(Date.now() - started).toBeLessThan(2000);
		expect(await migrationStatus(db.owner, shipped)).toBe('behind');
	}, 15_000);

	it('withDatabase() drops a query string and fragment', () => {
		const out = withDatabase('postgres://jade_owner:pw@127.0.0.1:5432/jade?host=remote#x', 'other');
		expect(out).toBe('postgres://jade_owner:pw@127.0.0.1:5432/other');
	});
});

describe('advisory lock waits are bounded (B4)', () => {
	// The keys are the ASCII of "jademigr" (per database) and "jaderole" (cluster-wide, held in
	// the postgres database), as src/lib/server/db documents them.
	const key = (ascii: string) => Buffer.from(ascii).readBigInt64BE().toString();

	async function holding<T>(url: string, ascii: string, body: () => Promise<T>): Promise<T> {
		const holder = newClient(url);
		await holder.connect();
		try {
			await holder.query('SELECT pg_advisory_lock($1::bigint)', [key(ascii)]);
			return await body();
		} finally {
			await holder.end();
		}
	}

	it('migrate() fails with MIGRATION_LOCK_TIMEOUT while another session holds the runner lock', async () => {
		const db = await emptyDatabase();
		const started = Date.now();
		await holding(db.ownerUrl, 'jademigr', async () => {
			await expect(
				migrate({
					ownerUrl: db.ownerUrl,
					appUrl: db.appUrl,
					dir: MIGRATIONS_DIR,
					lockTimeoutMs: 600
				})
			).rejects.toMatchObject({ name: 'DbError', tag: 'MIGRATION_LOCK_TIMEOUT' });
		});
		expect(Date.now() - started).toBeLessThan(5000);
		expect(await migrationStatus(db.owner, shipped)).toBe('behind');
	}, 15_000);

	it('ensureAppRole() fails with ROLE_LOCK_TIMEOUT while another session holds the role lock', async () => {
		const db = await emptyDatabase();
		const started = Date.now();
		await holding(withDatabase(db.ownerUrl, 'postgres'), 'jaderole', async () => {
			await expect(
				ensureAppRole(db.ownerUrl, db.appUrl, { lockTimeoutMs: 600 })
			).rejects.toMatchObject({ name: 'DbError', tag: 'ROLE_LOCK_TIMEOUT' });
		});
		expect(Date.now() - started).toBeLessThan(5000);
	}, 15_000);
});

describe("the harness's template database (B5)", () => {
	it('a template whose migration fails is dropped, and the error is its tag only', async () => {
		const config = clusterConfig();
		const name = `jade_tmpl_${newRunId()}`;
		const exists = async () => {
			const client = newClient(withDatabase(config.migrationDatabaseUrl, 'postgres'));
			await client.connect();
			try {
				const { rowCount } = await client.query('SELECT 1 FROM pg_database WHERE datname = $1', [
					name
				]);
				return rowCount === 1;
			} finally {
				await client.end();
			}
		};
		let created = false;
		await expect(
			createTemplateDatabase(config, name, async () => {
				created = await exists();
				throw new DbError('MIGRATION_FAILED', { migration: '0000_baseline' });
			})
		).rejects.toThrow(/^template database: MIGRATION_FAILED$/);
		expect(created).toBe(true);
		expect(await exists()).toBe(false);
	});
});
