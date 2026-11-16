// The integration project's global setup (plan U7, PD12). Once per run, it migrates a template
// database, `jade_tmpl_<run id>`, with this checkout's runner, closes every connection to it, and
// hands the run id and the cluster's URLs to the test files; global teardown drops this run's
// databases only.
//
// When JADE_TEST_TEMPLATE names a database (the CI compatibility run, plan X4), that database is
// the template instead: this checkout's migrate() runs on it and must apply nothing (the run
// fails if it applies a file or reports a mismatch), and it is left in place at teardown.
//
// The cluster is the one MIGRATION_DATABASE_URL and DATABASE_URL name (`.env`, written by
// `pnpm env:init`; `pnpm db:up` starts it).
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import type { TestProject } from 'vitest/node';
import {
	ConfigError,
	formatConfigError,
	loadMigrationConfig,
	type MigrationConfig
} from '../../src/lib/server/config/index.ts';
import { DbError, migrate, newClient, withDatabase } from '../../src/lib/server/db/index.ts';
import { loadEnv } from '../../tools/load-env.ts';
import type { HarnessContext } from './db.ts';

export const MIGRATIONS_DIR = fileURLToPath(new URL('../../migrations', import.meta.url));

/** A database name as an SQL identifier. */
export const quoteIdentifier = (name: string) => `"${name.replaceAll('"', '""')}"`;

/** Run `sql` as the owner in the cluster's `postgres` maintenance database. */
export async function adminQuery(ownerUrl: string, sql: string): Promise<void> {
	const client = newClient(withDatabase(ownerUrl, 'postgres'));
	try {
		await client.connect();
		await client.query(sql);
	} finally {
		await client.end().catch(() => {});
	}
}

/** Drop `name` if it exists, closing any session still on it. */
export async function dropDatabase(ownerUrl: string, name: string): Promise<void> {
	await adminQuery(ownerUrl, `DROP DATABASE IF EXISTS ${quoteIdentifier(name)} WITH (FORCE)`);
}

/** A run id: lower-case letters and digits, short enough for a 63-byte database name. */
export function newRunId(): string {
	return `${Date.now().toString(36)}${randomBytes(3).toString('hex')}`;
}

/** The migration tool's configuration from the environment, with a names-only error. */
export function clusterConfig(): MigrationConfig {
	loadEnv();
	try {
		return loadMigrationConfig(process.env);
	} catch (err) {
		if (err instanceof ConfigError) {
			// eslint-disable-next-line preserve-caught-error -- the cause can carry a URL or a server message (INV4)
			throw new Error(
				`The database tests need the development database (pnpm env:init, pnpm db:up). ${formatConfigError(err.missing, err.invalid, err.reasons)}`
			);
		}
		throw err;
	}
}

/** Create `name` from template0 and migrate it with this checkout's runner. */
export async function createMigratedDatabase(config: MigrationConfig, name: string) {
	await adminQuery(
		config.migrationDatabaseUrl,
		`CREATE DATABASE ${quoteIdentifier(name)} TEMPLATE template0`
	);
	return migrate({
		ownerUrl: withDatabase(config.migrationDatabaseUrl, name),
		appUrl: withDatabase(config.databaseUrl, name),
		dir: MIGRATIONS_DIR
	});
}

/** Names of this run's databases still in the cluster. */
async function runDatabases(ownerUrl: string, runId: string): Promise<string[]> {
	const client = newClient(withDatabase(ownerUrl, 'postgres'));
	try {
		await client.connect();
		const { rows } = await client.query<{ datname: string }>(
			'SELECT datname FROM pg_database WHERE datname LIKE $1',
			[`jade\\_t\\_${runId}\\_%`]
		);
		return rows.map((r) => r.datname);
	} finally {
		await client.end().catch(() => {});
	}
}

export default async function setup(project: TestProject): Promise<() => Promise<void>> {
	const config = clusterConfig();
	const runId = newRunId();
	const given = process.env['JADE_TEST_TEMPLATE'];
	let template: string;
	if (given !== undefined && given !== '') {
		template = given;
		try {
			const result = await migrate({
				ownerUrl: withDatabase(config.migrationDatabaseUrl, template),
				appUrl: withDatabase(config.databaseUrl, template),
				dir: MIGRATIONS_DIR
			});
			if (result.applied.length > 0) {
				throw new Error(`JADE_TEST_TEMPLATE: this checkout applied ${result.applied.join(', ')}`);
			}
		} catch (err) {
			// eslint-disable-next-line preserve-caught-error -- the cause can carry a URL or a server message (INV4)
			if (err instanceof DbError) throw new Error(`JADE_TEST_TEMPLATE: ${err.tag}`);
			throw err;
		}
	} else {
		template = `jade_tmpl_${runId}`;
		try {
			await createMigratedDatabase(config, template);
		} catch (err) {
			// eslint-disable-next-line preserve-caught-error -- the cause can carry a URL or a server message (INV4)
			if (err instanceof DbError) throw new Error(`template database: ${err.tag}`);
			throw err;
		}
	}
	// migrate() has ended its sessions; nothing else of this run is connected to the template.

	const context: HarnessContext = {
		runId,
		template,
		ownerUrl: config.migrationDatabaseUrl,
		appUrl: config.databaseUrl
	};
	project.provide('jadeDb', context);

	return async () => {
		for (const name of await runDatabases(config.migrationDatabaseUrl, runId)) {
			await dropDatabase(config.migrationDatabaseUrl, name);
		}
		if (template !== given) await dropDatabase(config.migrationDatabaseUrl, template);
	};
}
