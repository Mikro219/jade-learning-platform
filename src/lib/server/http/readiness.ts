// Readiness (plan A3): one query over the app role's pool, with a 2-second limit, comparing the
// ledger with the manifest bundled into the build. A database that is ahead is ready (OB53). No
// host name or error text leaves this module: only fixed check values.
import pg from 'pg';
import shippedJson from '../../../../migrations/manifest.json' with { type: 'json' };
import { getConfig } from '../config/index.ts';
import { createPool, migrationStatus, parseManifest } from '../db/index.ts';

const LIMIT_MS = 2000;

/** The migrations this build ships. */
const shipped = parseManifest(JSON.stringify(shippedJson));

export interface Readiness {
	readonly db: 'ok' | 'fail';
	readonly migrations: 'ok' | 'behind' | 'mismatch' | 'unknown';
}

let pool: pg.Pool | undefined;

function appPool(): pg.Pool {
	pool ??= createPool(getConfig().databaseUrl, {
		max: 4,
		connectionTimeoutMillis: LIMIT_MS,
		query_timeout: LIMIT_MS,
		// The server ends a stalled query too, so no orphan backend keeps a connection slot (B1).
		statement_timeout: LIMIT_MS,
		lock_timeout: LIMIT_MS,
		idleTimeoutMillis: 10_000
	});
	return pool;
}

/**
 * SQLSTATE classes that mean the connection itself failed or was refused: connection exception
 * (08), invalid authorization (28), invalid catalog name (3D), insufficient resources (53) and
 * operator intervention (57: starting, shutting down, cancelled).
 */
const CONNECTION_CLASSES = new Set(['08', '28', '3D', '53', '57']);

/**
 * The readiness of a failed check. The database counts as answering only for an error the server
 * sent (a pg DatabaseError) with a SQLSTATE outside the connection classes; a Node errno code
 * (EPIPE, EBUSY) or a refused connection is `db: fail`. No error text is read.
 */
export function readinessOfFailure(err: unknown): Readiness {
	try {
		if (err instanceof pg.DatabaseError) {
			const code: unknown = err.code;
			if (
				typeof code === 'string' &&
				/^[0-9A-Z]{5}$/.test(code) &&
				!CONNECTION_CLASSES.has(code.slice(0, 2))
			) {
				return { db: 'ok', migrations: 'unknown' };
			}
		}
	} catch {
		// A value whose prototype or `code` cannot be read: a failure.
	}
	return { db: 'fail', migrations: 'unknown' };
}

export async function checkReadiness(): Promise<Readiness> {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const timeout = new Promise<'timeout'>((resolve) => {
		timer = setTimeout(() => resolve('timeout'), LIMIT_MS);
	});
	try {
		const status = await Promise.race([migrationStatus(appPool(), shipped), timeout]);
		if (status === 'timeout') return { db: 'fail', migrations: 'unknown' };
		return { db: 'ok', migrations: status };
	} catch (err) {
		return readinessOfFailure(err);
	} finally {
		clearTimeout(timer);
	}
}

/** End the app pool (on `sveltekit:shutdown`). */
export async function closeDatabase(): Promise<void> {
	const p = pool;
	pool = undefined;
	await p?.end().catch(() => {});
}
