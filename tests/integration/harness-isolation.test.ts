// Two sides, a and b, create a scratch table of the same name and write different rows into it at
// the same time; neither sees the other's, and each has a database of its own (plan PD5, U7).
//
// Both sides are concurrent tests of this one file, so they overlap in every run, with one worker
// or many, and in watch mode (A7). The overlap is proved, not assumed: the sides meet at a barrier
// after creating their databases, and again after both have written all their rows and before
// either reads them back. A harness that handed both sides one database fails here: the second
// CREATE TABLE of the shared name fails, and otherwise each side would read 40 rows, not its 20.
// If the two tests ever ran one after the other, the first barrier fails on its deadline.
// (Plan section 9 names this pair harness-isolation-a and -b; it is one file now, a name-only
// deviation.)
import { afterAll, describe, expect, it } from 'vitest';
import { createTestDatabase, harness, type TestDatabase } from '../support/db.ts';

const SIDES = ['a', 'b'] as const;
const ROWS = 20;
const BARRIER_WAIT_MS = 30_000;

/** A meeting point for `parties` concurrent tests: each `arrive()` resolves once all have arrived. */
function barrier(parties: number, label: string): { arrive(): Promise<void> } {
	let arrived = 0;
	let release!: () => void;
	const all = new Promise<void>((resolve) => (release = resolve));
	return {
		async arrive() {
			arrived += 1;
			if (arrived === parties) release();
			let timer: ReturnType<typeof setTimeout> | undefined;
			const deadline = new Promise<never>((_, reject) => {
				timer = setTimeout(
					() => reject(new Error(`harness isolation: the sides did not meet at ${label}`)),
					BARRIER_WAIT_MS
				);
			});
			try {
				await Promise.race([all, deadline]);
			} finally {
				clearTimeout(timer);
			}
		}
	};
}

const created = barrier(SIDES.length, 'created');
const written = barrier(SIDES.length, 'written');
const databases = new Map<string, string>();
const opened: TestDatabase[] = [];

afterAll(async () => {
	await Promise.all(opened.map((db) => db.drop()));
});

describe.concurrent('harness isolation: two concurrent sides', () => {
	for (const side of SIDES) {
		it(`side ${side} has its own database and sees only its own rows`, async () => {
			const db = await createTestDatabase();
			opened.push(db);
			databases.set(side, db.name);
			const { rows: current } = await db.owner.query('SELECT current_database() AS name');
			expect(current[0].name).toBe(db.name);
			expect(db.name.startsWith(`jade_t_${harness().runId}_`)).toBe(true);

			await created.arrive();
			await db.owner.query('CREATE TABLE scratch_isolation (side text NOT NULL, n int NOT NULL)');
			for (let n = 0; n < ROWS; n++) {
				await db.owner.query('INSERT INTO scratch_isolation (side, n) VALUES ($1, $2)', [side, n]);
				// Interleave with the other side.
				await new Promise((resolve) => setTimeout(resolve, 10));
			}
			// Both sides have written all their rows before either reads.
			await written.arrive();

			const { rows } = await db.owner.query(
				'SELECT side, count(*)::int AS total FROM scratch_isolation GROUP BY side'
			);
			expect(rows).toEqual([{ side, total: ROWS }]);
			const other = databases.get(side === 'a' ? 'b' : 'a');
			expect(other).toBeDefined();
			expect(other).not.toBe(db.name);
		});
	}
});
