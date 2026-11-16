// The integration tests' database harness (plan PD5, PD12, U7). One Postgres cluster serves every
// parallel test file of a run, so each file gets its own database:
//   - createTestDatabase(): a clone of the run's migrated template (`jade_tmpl_<run id>`);
//   - createEmptyDatabase(): a database with nothing in it, for the runner's own tests.
// Every database the harness creates is named `jade_t_<run id>_<n>`, so two runs against one
// cluster never touch each other's databases, and global teardown drops this run's only.
// The app role's password is the one DATABASE_URL carries: no test drops jade_app or changes its
// password in the shared cluster.
import { randomBytes } from 'node:crypto';
import type pg from 'pg';
import { inject } from 'vitest';
import { createPool, sqlstateOf, withDatabase } from '../../src/lib/server/db/index.ts';
import { adminQuery, dropDatabase, quoteIdentifier as quote } from './global-setup-db.ts';

/** What global setup hands every test file (tests/support/global-setup-db.ts). */
export interface HarnessContext {
	/** This run's id: lower-case letters and digits. */
	runId: string;
	/** The migrated template database the clones come from. */
	template: string;
	/** The owner's URL (jade_owner) on the shared cluster; its database is not used. */
	ownerUrl: string;
	/** The app's URL (jade_app) on the shared cluster; its database is not used. */
	appUrl: string;
}

declare module 'vitest' {
	export interface ProvidedContext {
		jadeDb: HarnessContext;
	}
}

export function harness(): HarnessContext {
	return inject('jadeDb');
}

export interface TestDatabase {
	readonly name: string;
	readonly ownerUrl: string;
	readonly appUrl: string;
	/** A pool for the owner role. */
	readonly owner: pg.Pool;
	/** A pool for the app role (jade_app). */
	readonly app: pg.Pool;
	/** End both pools and drop the database. Call it in afterAll. */
	drop(): Promise<void>;
}

/** A new database name of this run: `jade_t_<run id>_<n>`. */
export function testDatabaseName(runId: string): string {
	return `jade_t_${runId}_${randomBytes(4).toString('hex')}`;
}

function open(ctx: HarnessContext, name: string): TestDatabase {
	const ownerUrl = withDatabase(ctx.ownerUrl, name);
	const appUrl = withDatabase(ctx.appUrl, name);
	const owner = createPool(ownerUrl, { max: 4 });
	const app = createPool(appUrl, { max: 4 });
	return {
		name,
		ownerUrl,
		appUrl,
		owner,
		app,
		drop: async () => {
			await Promise.all([owner.end().catch(() => {}), app.end().catch(() => {})]);
			await dropDatabase(ctx.ownerUrl, name);
		}
	};
}

const CLONE_ATTEMPTS = 50;

/**
 * A new database cloned from the run's migrated template. Retries on SQLSTATE 55006, the
 * template briefly in use by another file's clone, which is the harness's only retry (U7).
 */
export async function createTestDatabase(ctx: HarnessContext = harness()): Promise<TestDatabase> {
	const name = testDatabaseName(ctx.runId);
	for (let attempt = 1; ; attempt++) {
		try {
			await adminQuery(
				ctx.ownerUrl,
				`CREATE DATABASE ${quote(name)} TEMPLATE ${quote(ctx.template)}`
			);
			return open(ctx, name);
		} catch (err) {
			if (sqlstateOf(err) !== '55006' || attempt >= CLONE_ATTEMPTS) throw err;
			await new Promise((resolve) => setTimeout(resolve, 50 + Math.random() * 100));
		}
	}
}

/** A new database with nothing in it (no ledger, no grants), for the runner's own tests. */
export async function createEmptyDatabase(ctx: HarnessContext = harness()): Promise<TestDatabase> {
	const name = testDatabaseName(ctx.runId);
	await adminQuery(ctx.ownerUrl, `CREATE DATABASE ${quote(name)} TEMPLATE template0`);
	return open(ctx, name);
}
