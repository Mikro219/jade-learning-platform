// `pnpm db:up` and `pnpm db:down` (plan U1, PD13): the development database through Docker
// Compose, always with an explicit project name (-p), never Compose's own fallbacks:
//   - the exported COMPOSE_PROJECT_NAME when there is one (the bugfix gates, the clean clone);
//   - otherwise `jade-dev-<first 8 hex digits of the sha256 of the checkout's real path>`, so two
//     checkouts never share a development database.
// `up` waits for the health check (`up -d --wait devdb`); `down` keeps the volume.
//
//   node tools/compose.ts up|down
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { realpathSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from './load-env.ts';

const root = fileURLToPath(new URL('../', import.meta.url));

/** The development database's Compose file. */
export const DEV_COMPOSE_FILE = join(root, 'compose.dev.yml');

/** The Compose project of this checkout's development database. */
export function devProjectName(env: Readonly<Record<string, string | undefined>> = process.env) {
	const exported = env['COMPOSE_PROJECT_NAME'];
	if (exported !== undefined && exported !== '') return exported;
	const digest = createHash('sha256').update(realpathSync(root)).digest('hex');
	return `jade-dev-${digest.slice(0, 8)}`;
}

/** The `docker` arguments for `up` or `down`. */
export function composeArgs(command: 'up' | 'down', project: string): string[] {
	const base = ['compose', '-p', project, '-f', DEV_COMPOSE_FILE];
	return command === 'up' ? [...base, 'up', '-d', '--wait', 'devdb'] : [...base, 'down'];
}

export function main(argv: readonly string[]): number {
	const command = argv[0];
	if (command !== 'up' && command !== 'down') {
		process.stderr.write('usage: compose.ts up|down\n');
		return 2;
	}
	// The Compose file interpolates JADE_OWNER_DB_PASSWORD and JADE_DEV_DB_PORT from `.env`.
	loadEnv();
	const project = devProjectName();
	process.stdout.write(`db:${command}: Compose project ${project}, service devdb\n`);
	const result = spawnSync('docker', composeArgs(command, project), {
		cwd: root,
		env: process.env,
		stdio: 'inherit'
	});
	if (result.error) {
		process.stderr.write(`db:${command}: could not run docker\n`);
		return 1;
	}
	return result.status ?? 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = main(process.argv.slice(2));
}
