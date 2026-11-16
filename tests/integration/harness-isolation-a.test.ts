// Two files, harness-isolation-a and -b, create a scratch table of the same name and write
// different rows into it at the same time; neither sees the other's, and each has a database of
// its own (plan PD5, U7). This is side a; harness-isolation-b.test.ts is the other.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createTestDatabase, harness, type TestDatabase } from '../support/db.ts';

const side = 'a';

let db: TestDatabase;
beforeAll(async () => {
	db = await createTestDatabase();
});
afterAll(async () => {
	await db?.drop();
});

describe(`harness isolation, side ${side}`, () => {
	it('has a database of its own, named for this run', async () => {
		const { rows } = await db.owner.query('SELECT current_database() AS name');
		expect(rows[0].name).toBe(db.name);
		expect(db.name.startsWith(`jade_t_${harness().runId}_`)).toBe(true);
	});

	it('sees only its own rows in a scratch table of the shared name', async () => {
		await db.owner.query('CREATE TABLE scratch_isolation (side text NOT NULL, n int NOT NULL)');
		for (let n = 0; n < 20; n++) {
			await db.owner.query('INSERT INTO scratch_isolation (side, n) VALUES ($1, $2)', [side, n]);
			// Interleave with the other file, which runs in parallel.
			await new Promise((resolve) => setTimeout(resolve, 50));
		}
		const { rows } = await db.owner.query(
			'SELECT DISTINCT side, count(*) OVER ()::int AS total FROM scratch_isolation'
		);
		expect(rows).toEqual([{ side, total: 20 }]);
	});
});
