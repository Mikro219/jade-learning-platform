// `pnpm db:reset` (plan U6): drop and recreate the database named in the URLs, then migrate it.
//
// Its guard runs first, before loadMigrationConfig and before any connection, on the raw APP_ENV
// and on the host of each of MIGRATION_DATABASE_URL and DATABASE_URL: unless APP_ENV is
// development or test and every host is a loopback address, it writes the fixed tag
// DB_RESET_REFUSED with the half that failed (`app_env`, `host` or `query`), never a value or a
// URL, and exits 1. A URL that does not parse, or is missing, is refused as `host`. A URL with a
// query string or fragment is refused as `query` (jade-f1w): pg would let a `host` or `port`
// parameter override the loopback host checked here.
import { fileURLToPath } from 'node:url';
import { newClient, sqlstateOf, withDatabase } from '../../src/lib/server/db/index.ts';
import { hasQueryOrFragment } from '../../src/lib/server/config/index.ts';
import { registerErrorTags } from '../../src/lib/server/log/index.ts';
import { loadEnv } from '../load-env.ts';
import { migrationConfigOrReport, runMigrate } from './migrate.ts';

type Env = Readonly<Record<string, string | undefined>>;

/** The fixed tags db:reset writes (on stderr), registered with the logger too (jade-zwq). */
export const RESET_TAGS = ['DB_RESET_REFUSED', 'DB_RESET_FAILED'] as const;
registerErrorTags(RESET_TAGS);

const LOOPBACK = new Set(['127.0.0.1', '[::1]', '::1', 'localhost']);

/** The half of the guard that refuses `env`, or null when it may be reset (U6). */
export function resetGuard(env: Env): 'app_env' | 'host' | 'query' | null {
	const appEnv = env['APP_ENV'];
	if (appEnv !== 'development' && appEnv !== 'test') return 'app_env';
	for (const key of ['MIGRATION_DATABASE_URL', 'DATABASE_URL']) {
		const value = env[key] ?? '';
		let host: string;
		try {
			host = new URL(value).hostname;
		} catch {
			return 'host';
		}
		if (!LOOPBACK.has(host)) return 'host';
		if (hasQueryOrFragment(value)) return 'query';
	}
	return null;
}

/** Databases a reset never drops, whatever the URLs say. */
const PROTECTED = new Set(['postgres', 'template0', 'template1']);
const IDENTIFIER = /^[a-z_][a-z0-9_]{0,62}$/;

export async function main(): Promise<number> {
	loadEnv();
	const refused = resetGuard(process.env);
	if (refused !== null) {
		process.stderr.write(`db:reset: DB_RESET_REFUSED ${refused}\n`);
		return 1;
	}
	const config = migrationConfigOrReport(process.env);
	if (config === null) return 1;

	const database = decodeURIComponent(new URL(config.migrationDatabaseUrl).pathname.slice(1));
	if (!IDENTIFIER.test(database) || PROTECTED.has(database)) {
		process.stderr.write('db:reset: DB_RESET_REFUSED database\n');
		return 1;
	}

	const admin = newClient(withDatabase(config.migrationDatabaseUrl, 'postgres'));
	try {
		await admin.connect();
		const name = admin.escapeIdentifier(database);
		await admin.query(`DROP DATABASE IF EXISTS ${name} WITH (FORCE)`);
		await admin.query(`CREATE DATABASE ${name} TEMPLATE template0`);
	} catch (err) {
		const sqlstate = sqlstateOf(err);
		process.stderr.write(`db:reset: DB_RESET_FAILED${sqlstate ? ` (SQLSTATE ${sqlstate})` : ''}\n`);
		return 1;
	} finally {
		await admin.end().catch(() => {});
	}
	process.stdout.write(`db:reset: recreated database ${database}\n`);
	return runMigrate(config, 'db:reset');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main();
}
