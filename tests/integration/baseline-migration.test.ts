// The sample integration test (plan U4, INV6): a database cloned from the run's migrated
// template, reached as the app role, which may read the ledger and nothing more.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { newClient, readManifest, sqlstateOf } from '../../src/lib/server/db/index.ts';
import { createTestDatabase, type TestDatabase } from '../support/db.ts';
import { MIGRATIONS_DIR } from '../support/global-setup-db.ts';

let db: TestDatabase;
beforeAll(async () => {
	db = await createTestDatabase();
});
afterAll(async () => {
	await db?.drop();
});

async function refusal(promise: Promise<unknown>): Promise<string | undefined> {
	try {
		await promise;
	} catch (err) {
		return sqlstateOf(err);
	}
	throw new Error('the statement was accepted');
}

describe('0000_baseline', () => {
	it('is in the ledger, as every shipped migration is', async () => {
		const { rows } = await db.owner.query('SELECT name, sha256 FROM schema_migrations');
		expect(rows.map((r) => r.name)).toContain('0000_baseline');
		for (const entry of readManifest(MIGRATIONS_DIR).migrations) expect(rows).toContainEqual(entry);
	});

	it('lets the app role read the ledger', async () => {
		const { rows } = await db.app.query('SELECT name FROM schema_migrations');
		expect(rows.map((r) => r.name)).toContain('0000_baseline');
		const { rows: who } = await db.app.query('SELECT current_user AS u');
		expect(who[0].u).toBe('jade_app');
	});

	it('refuses DDL and writes to the ledger over the app pool', async () => {
		expect(await refusal(db.app.query('CREATE TABLE app_may_not (id int)'))).toBe('42501');
		expect(
			await refusal(db.app.query("INSERT INTO schema_migrations (name, sha256) VALUES ('x', 'y')"))
		).toBe('42501');
	});

	// On Postgres 15 and later PUBLIC has no CREATE on schema public by default, so the 42501
	// above would hold without the baseline's REVOKE; the REVOKE is defensive there, for a cluster
	// created by an older initdb or changed by hand. This checks its effect directly (A5).
	it('leaves PUBLIC and the app role without CREATE on schema public', async () => {
		const { rows } = await db.owner.query(
			"SELECT has_schema_privilege('public', 'public', 'CREATE') AS pub," +
				" has_schema_privilege('jade_app', 'public', 'CREATE') AS app"
		);
		expect(rows[0]).toEqual({ pub: false, app: false });
	});

	it('the privilege check is live: a CREATE granted to PUBLIC shows, and the REVOKE removes it', async () => {
		const check = async () =>
			(await db.owner.query("SELECT has_schema_privilege('public', 'public', 'CREATE') AS p"))
				.rows[0].p;
		await db.owner.query('GRANT CREATE ON SCHEMA public TO PUBLIC');
		try {
			expect(await check()).toBe(true);
		} finally {
			// The baseline's own statement.
			await db.owner.query('REVOKE CREATE ON SCHEMA public FROM PUBLIC');
		}
		expect(await check()).toBe(false);
	});

	it("accepts the app URL's password and refuses a wrong one", async () => {
		const good = newClient(db.appUrl);
		await good.connect();
		expect((await good.query('SELECT 1 AS one')).rows[0].one).toBe(1);
		await good.end();

		const url = new URL(db.appUrl);
		url.password = 'wrong-password';
		const bad = newClient(url.toString());
		expect(await refusal(bad.connect())).toBe('28P01');
		await bad.end().catch(() => {});
	});
});
