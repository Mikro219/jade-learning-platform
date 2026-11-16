// `pnpm db:manifest` (plan U5): write migrations/manifest.json, the name and SHA-256 of every
// migration file in name order. The manifest is the lock on the files, and what the app ships.
// `pnpm db:generate` runs it after `drizzle-kit generate`.
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildManifest, formatManifest } from '../../src/lib/server/db/index.ts';
import { MIGRATIONS_DIR } from './migrate.ts';

export function main(dir: string = MIGRATIONS_DIR): number {
	const manifest = buildManifest(dir);
	writeFileSync(join(dir, 'manifest.json'), formatManifest(manifest));
	process.stdout.write(`db:manifest: ${manifest.migrations.length} migration(s) recorded\n`);
	return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = main();
}
