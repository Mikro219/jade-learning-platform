// Drizzle Kit generates migration SQL from src/lib/server/db/schema.ts into migrations/ (plan
// U4, U5). It is used for `generate` only: `pnpm db:migrate` is the project's own runner
// (src/lib/server/db/migrate.ts), and Drizzle Kit's `migrate` and `push` are never used, so this
// file names no database and reads no credential.
import { defineConfig } from 'drizzle-kit';
import { loadEnv } from './tools/load-env.ts';

// `.env` outside production (plan V6), like every other tool's entry point.
loadEnv();

export default defineConfig({
	dialect: 'postgresql',
	schema: './src/lib/server/db/schema.ts',
	out: './migrations'
});
