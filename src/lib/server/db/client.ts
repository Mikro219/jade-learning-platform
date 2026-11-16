// The app's database client (ADR 0003): a pg pool for the app role (jade_app, plan PD3) and
// Drizzle ORM over it as the query layer. Nothing connects until the first query, so the server
// starts without a database (V8). The owner's URL is never used here.
import { drizzle, type NodePgDatabase } from 'drizzle-orm/node-postgres';
import pg from 'pg';
import * as schema from './schema.ts';

export type Database = NodePgDatabase<typeof schema>;

/** A pool for `databaseUrl`. The caller ends it (`pool.end()`). */
export function createPool(databaseUrl: string, options: pg.PoolConfig = {}): pg.Pool {
	const pool = new pg.Pool({
		connectionTimeoutMillis: 10_000,
		...options,
		connectionString: databaseUrl
	});
	pool.on('error', () => {
		// An idle client lost its connection; the pool replaces it and the next query reports.
	});
	return pool;
}

/** Drizzle over `pool`, typed by src/lib/server/db/schema.ts. */
export function createDatabase(pool: pg.Pool): Database {
	return drizzle(pool, { schema });
}
