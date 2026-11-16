// `pnpm db:migrate` (plan U3): apply the pending files of migrations/ to the database named in
// MIGRATION_DATABASE_URL, as the owner, after making sure the app role is right (U2).
//
// Output is fixed phrases, migration file names, counts and SQLSTATEs only: never a URL, a
// password or a server message. A configuration problem is reported by reportConfigError (V3a).
import { fileURLToPath } from 'node:url';
import {
	ConfigError,
	loadMigrationConfig,
	reportConfigError,
	type MigrationConfig
} from '../../src/lib/server/config/index.ts';
import { DbError, migrate } from '../../src/lib/server/db/index.ts';
import { loadEnv } from '../load-env.ts';

/** The checkout's migrations directory. */
export const MIGRATIONS_DIR = fileURLToPath(new URL('../../migrations', import.meta.url));

/** One line for a failure: a fixed tag, a migration name, a SQLSTATE. Nothing else. */
export function describeFailure(err: unknown): string {
	if (err instanceof DbError) {
		const details = [err.migration, err.sqlstate && `SQLSTATE ${err.sqlstate}`].filter(Boolean);
		return details.length > 0 ? `${err.tag} (${details.join(', ')})` : err.tag;
	}
	return 'failed (unexpected error)';
}

/** The migration tool's configuration, or null after reporting a ConfigError (V3a). */
export function migrationConfigOrReport(
	env: Readonly<Record<string, string | undefined>>
): MigrationConfig | null {
	try {
		return loadMigrationConfig(env);
	} catch (err) {
		if (err instanceof ConfigError) {
			reportConfigError(err);
			return null;
		}
		throw err;
	}
}

/** Migrate the database `config` names, writing the outcome as `<tool>: ...` lines. */
export async function runMigrate(config: MigrationConfig, tool: string): Promise<number> {
	try {
		const result = await migrate({
			ownerUrl: config.migrationDatabaseUrl,
			appUrl: config.databaseUrl,
			dir: MIGRATIONS_DIR
		});
		if (result.role !== 'unchanged') {
			const what = result.role === 'created' ? 'created' : 'password set';
			process.stdout.write(`${tool}: role jade_app ${what}\n`);
		}
		for (const name of result.applied) process.stdout.write(`${tool}: applied ${name}\n`);
		if (result.ahead) {
			process.stdout.write(
				`${tool}: the database is ahead (${result.recorded} recorded, ${result.shipped} shipped); nothing applied\n`
			);
		} else if (result.applied.length === 0) {
			process.stdout.write(`${tool}: up to date (${result.recorded} applied); nothing applied\n`);
		}
		return 0;
	} catch (err) {
		process.stderr.write(`${tool}: ${describeFailure(err)}\n`);
		return 1;
	}
}

export async function main(): Promise<number> {
	loadEnv();
	const config = migrationConfigOrReport(process.env);
	if (config === null) return 1;
	return runMigrate(config, 'db:migrate');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main();
}
