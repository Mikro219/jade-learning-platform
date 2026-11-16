// The blackbox project's global setup (jade-b1f): `vite build` runs once per run, before any
// black-box file starts, so parallel files never race on build/. It is also the check that the
// build needs no secret (V3), so the build must see no configuration at all (jade-7yz). Three
// readers of env files take part in a build, and each is pointed away from the checkout's `.env`:
//   - vite.config.ts calls loadEnv(), which reads `.env` unless NODE_ENV is production. The build's
//     environment holds NODE_ENV=production (BUILD_ENV, as the image sets it, D1).
//   - SvelteKit calls Vite's loadEnv() on its `env.dir` and Vite core on `envDir`, both the project
//     root by default and both whatever NODE_ENV is. The build's environment also sets
//     JADE_BUILD_ENV_DIR to a fresh empty directory, which vite.config.ts passes as both.
// Before building, both are probed against a sentinel env file that exists: loadEnv() under
// BUILD_ENV must read nothing, and the configuration Vite resolves under the build's environment,
// with its root at a directory holding a sentinel `.env`, must give SvelteKit and Vite an env
// directory whose files hold no sentinel. If either fails, setup stops before building.
import { execFile } from 'node:child_process';
import { mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const root = fileURLToPath(new URL('../../', import.meta.url));
const loadEnvModule = new URL('../../tools/load-env.ts', import.meta.url).href;
const viteConfig = fileURLToPath(new URL('../../vite.config.ts', import.meta.url));

/** The build's environment, but for JADE_BUILD_ENV_DIR (see buildEnv). */
export const BUILD_ENV: Readonly<Record<string, string>> = Object.freeze({
	NODE_ENV: 'production'
});

/** The build's whole environment: BUILD_ENV, and `envDir` (an empty directory) for SvelteKit and Vite. */
export function buildEnv(envDir: string): Record<string, string> {
	return { ...BUILD_ENV, JADE_BUILD_ENV_DIR: envDir };
}

/**
 * What loadEnv() does under `env` with an env file present: `read` is its return value, `leaked`
 * whether the file's variable reached process.env.
 */
export async function loadEnvUnder(
	env: Readonly<Record<string, string>>
): Promise<{ read: boolean; leaked: boolean }> {
	const dir = mkdtempSync(join(tmpdir(), 'jade-build-env-'));
	try {
		const sentinel = join(dir, '.env');
		writeFileSync(sentinel, 'JADE_BUILD_ENV_SENTINEL=read\n');
		const script =
			`const { loadEnv } = await import(${JSON.stringify(loadEnvModule)});` +
			`const read = loadEnv(${JSON.stringify(sentinel)});` +
			`process.stdout.write(JSON.stringify({ read, leaked: process.env.JADE_BUILD_ENV_SENTINEL !== undefined }));`;
		const { stdout } = await promisify(execFile)(
			process.execPath,
			['--input-type=module', '-e', script],
			{ cwd: root, env: { ...env } }
		);
		return JSON.parse(stdout) as { read: boolean; leaked: boolean };
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}

/**
 * What SvelteKit's and Vite's own env loaders would read in a build under `env`, when the project
 * root (their default env directory) holds a `.env` with two sentinels. It resolves the real
 * vite.config.ts for `build` in production mode, with Vite's `root` at a temporary directory that
 * holds that file (and a link to the checkout's `src/`), and reads back the directory SvelteKit's setup plugin resolved as `env.dir`
 * (the one its build and env-vars plugins pass to `loadEnv(mode, dir, '')`) and Vite's `envDir`,
 * then makes that same call on each. `kitLeaked` and `viteLeaked` say whether a sentinel came back;
 * `kitDefault` and `viteDefault` whether each directory is still the root.
 */
export async function kitEnvUnder(env: Readonly<Record<string, string>>): Promise<{
	kitLeaked: boolean;
	viteLeaked: boolean;
	kitDefault: boolean;
	viteDefault: boolean;
}> {
	const dir = mkdtempSync(join(tmpdir(), 'jade-build-root-'));
	try {
		// SvelteKit syncs its generated files from the root's `src/` while it resolves the config.
		symlinkSync(join(root, 'src'), join(dir, 'src'), 'dir');
		writeFileSync(
			join(dir, '.env'),
			'JADE_BUILD_ENV_SENTINEL=read\nVITE_JADE_BUILD_ENV_SENTINEL=read\n'
		);
		const script = `
			const vite = await import('vite');
			const { realpathSync } = await import('node:fs');
			const { resolve } = await import('node:path');
			const root = ${JSON.stringify(dir)};
			const config = await vite.resolveConfig(
				{ configFile: ${JSON.stringify(viteConfig)}, root, logLevel: 'silent' },
				'build',
				'production'
			);
			const setup = config.plugins.find((p) => p.name === 'vite-plugin-sveltekit-setup');
			const kitDir = resolve(root, setup.api.options.env.dir);
			const viteDir = config.envDir === false ? null : resolve(root, config.envDir ?? root);
			const has = (d, name) => d !== null && name in vite.loadEnv('production', d, '');
			const same = (a, b) => a !== null && realpathSync(a) === realpathSync(b);
			process.stdout.write(JSON.stringify({
				kitLeaked: has(kitDir, 'JADE_BUILD_ENV_SENTINEL'),
				viteLeaked: has(viteDir, 'VITE_JADE_BUILD_ENV_SENTINEL'),
				kitDefault: same(kitDir, root),
				viteDefault: same(viteDir, root)
			}));
		`;
		const { stdout } = await promisify(execFile)(
			process.execPath,
			['--input-type=module', '-e', script],
			{ cwd: root, env: { ...env }, maxBuffer: 16 * 1024 * 1024 }
		);
		return JSON.parse(stdout) as {
			kitLeaked: boolean;
			viteLeaked: boolean;
			kitDefault: boolean;
			viteDefault: boolean;
		};
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}

export default async function setup(): Promise<void> {
	const probe = await loadEnvUnder(BUILD_ENV);
	if (probe.read || probe.leaked) {
		throw new Error('blackbox build: loadEnv() would read an env file under BUILD_ENV (V3)');
	}
	const envDir = mkdtempSync(join(tmpdir(), 'jade-build-envdir-'));
	try {
		const env = buildEnv(envDir);
		const kit = await kitEnvUnder(env);
		if (kit.kitLeaked || kit.viteLeaked || kit.kitDefault || kit.viteDefault) {
			throw new Error('blackbox build: SvelteKit or Vite would read an env file (V3)');
		}
		await promisify(execFile)(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
			cwd: root,
			env,
			maxBuffer: 64 * 1024 * 1024
		});
	} finally {
		rmSync(envDir, { recursive: true, force: true });
	}
}
