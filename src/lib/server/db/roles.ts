// The app role's bootstrap (plan PD3, PD12, U2). `ensureAppRole()` runs as the owner (jade_owner)
// and makes sure that `jade_app` exists and logs in with the password in DATABASE_URL.
//
// A role is cluster-wide while the runner's lock is per database, so all of this work happens
// under one session advisory lock held in the cluster's `postgres` maintenance database: every
// runner on the cluster, whatever its target database, waits on the same lock. Two runners
// therefore never write the role at the same time, which could fail with `tuple concurrently
// updated` (XX000) or a duplicate role (23505, 42710). Those errors are prevented, not retried:
// no SQLSTATE is caught and retried here.
//
// The password is sent as a SCRAM-SHA-256 verifier computed here, never as plain text in SQL, so
// it cannot reach a Postgres log even when a statement fails. No error raised here carries a URL,
// a password or a server message: only a fixed tag and, where useful, a SQLSTATE.
import { createHash, createHmac, pbkdf2Sync, randomBytes } from 'node:crypto';
import pg from 'pg';

/** The role the app connects as. Fixed, because migration files grant to it by name (U2). */
export const APP_ROLE = 'jade_app';

/** The fixed tags a database tool writes on failure. Never a URL or a value. */
export type DbErrorTag =
	| 'MIGRATION_HISTORY_MISMATCH'
	| 'MIGRATION_MANIFEST_MISMATCH'
	| 'MIGRATION_FAILED'
	| 'ROLE_BOOTSTRAP_FAILED';

/** A database tool's failure: a fixed tag, the migration it concerns, the SQLSTATE if any. */
export class DbError extends Error {
	readonly tag: DbErrorTag;
	readonly migration: string | undefined;
	readonly sqlstate: string | undefined;

	constructor(tag: DbErrorTag, details: { migration?: string; sqlstate?: string } = {}) {
		super(tag);
		this.name = 'DbError';
		this.tag = tag;
		this.migration = details.migration;
		this.sqlstate = sqlstateOf({ code: details.sqlstate });
	}
}

/** A SQLSTATE (five upper-case letters or digits) from a driver error, or undefined. */
export function sqlstateOf(err: unknown): string | undefined {
	const code = (err as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[0-9A-Z]{5}$/.test(code) ? code : undefined;
}

// One fixed key for the cluster-wide role lock ("jaderole" in ASCII). It is held in the
// `postgres` maintenance database, so every runner on the cluster shares it.
const ROLE_LOCK_KEY = '7665518427635674213';

const SCRAM_ITERATIONS = 4096;

/**
 * The SCRAM-SHA-256 verifier Postgres stores for `password` (RFC 5802, RFC 7677), in the form
 * `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>`. Postgres accepts it in
 * `PASSWORD '...'` and stores it as given. Passwords from `pnpm env:init` are `[A-Za-z0-9_-]`, for
 * which SASLprep changes nothing.
 */
export function scramVerifier(password: string, salt: Buffer = randomBytes(16)): string {
	const salted = pbkdf2Sync(password.normalize('NFKC'), salt, SCRAM_ITERATIONS, 32, 'sha256');
	const clientKey = createHmac('sha256', salted).update('Client Key').digest();
	const storedKey = createHash('sha256').update(clientKey).digest();
	const serverKey = createHmac('sha256', salted).update('Server Key').digest();
	return (
		`SCRAM-SHA-256$${SCRAM_ITERATIONS}:${salt.toString('base64')}` +
		`$${storedKey.toString('base64')}:${serverKey.toString('base64')}`
	);
}

/** `url` with its database replaced by `database`. */
export function withDatabase(url: string, database: string): string {
	const u = new URL(url);
	u.pathname = `/${encodeURIComponent(database)}`;
	return u.toString();
}

/** A client that never throws an unhandled 'error' event; connect errors still reject. */
export function newClient(url: string): pg.Client {
	const client = new pg.Client({ connectionString: url, connectionTimeoutMillis: 10_000 });
	client.on('error', () => {
		// A connection lost while idle; the next query on it fails and is reported there.
	});
	return client;
}

async function canLogIn(appUrl: string): Promise<'ok' | 'wrong_password' | 'failed'> {
	const client = newClient(appUrl);
	try {
		await client.connect();
		await client.query('SELECT 1');
		return 'ok';
	} catch (err) {
		return sqlstateOf(err) === '28P01' ? 'wrong_password' : 'failed';
	} finally {
		await client.end().catch(() => {});
	}
}

export type AppRoleOutcome = 'created' | 'password_set' | 'unchanged';

/**
 * Make sure `jade_app` exists, can log in, and has the password `appUrl` carries (plan U2).
 * Runs as the owner (`ownerUrl`, role jade_owner) under the cluster-wide lock. A cluster whose
 * role is already right sees no write. Throws `DbError('ROLE_BOOTSTRAP_FAILED')` otherwise.
 */
export async function ensureAppRole(ownerUrl: string, appUrl: string): Promise<AppRoleOutcome> {
	const password = decodeURIComponent(new URL(appUrl).password);
	if (password === '') throw new DbError('ROLE_BOOTSTRAP_FAILED');

	const admin = newClient(withDatabase(ownerUrl, 'postgres'));
	try {
		await admin.connect();
	} catch (err) {
		await admin.end().catch(() => {});
		throw new DbError('ROLE_BOOTSTRAP_FAILED', { sqlstate: sqlstateOf(err) });
	}
	try {
		await admin.query('SELECT pg_advisory_lock($1::bigint)', [ROLE_LOCK_KEY]);
		const found = await admin.query('SELECT 1 FROM pg_roles WHERE rolname = $1', [APP_ROLE]);
		let outcome: AppRoleOutcome = 'unchanged';
		if (found.rowCount === 0) {
			await admin.query(
				`CREATE ROLE ${APP_ROLE} LOGIN PASSWORD ${admin.escapeLiteral(scramVerifier(password))}`
			);
			outcome = 'created';
		} else {
			const login = await canLogIn(appUrl);
			if (login === 'ok') return 'unchanged';
			if (login === 'failed') throw new DbError('ROLE_BOOTSTRAP_FAILED');
			await admin.query(
				`ALTER ROLE ${APP_ROLE} LOGIN PASSWORD ${admin.escapeLiteral(scramVerifier(password))}`
			);
			outcome = 'password_set';
		}
		if ((await canLogIn(appUrl)) !== 'ok') throw new DbError('ROLE_BOOTSTRAP_FAILED');
		return outcome;
	} catch (err) {
		if (err instanceof DbError) throw err;
		throw new DbError('ROLE_BOOTSTRAP_FAILED', { sqlstate: sqlstateOf(err) });
	} finally {
		// Ending the session releases its advisory lock.
		await admin.end().catch(() => {});
	}
}
