// The app image (plan D1, D7, D8, INV4, INV9): the run's image, built once by the global setup
// through `pnpm ci:image`, is small, runs as `node`, has a health check, runs the pinned Node,
// holds no env file, and every image entry point runs in it.
import { chmodSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { parseEnv } from 'node:util';
import { describe, expect, it } from 'vitest';
import { docker, infraContext, root, tempDir } from '../support/infra.ts';

const STACK_NAMES = [
	'JADE_OWNER_DB_PASSWORD',
	'JADE_APP_DB_PASSWORD',
	'CODE_PEPPER',
	'SESSION_SECRET',
	'LOG_LEVEL',
	'JADE_STACK_APP_ENV',
	'SITE_ADDRESS',
	'JADE_HTTP_PORT',
	'JADE_HTTPS_PORT',
	'JADE_ORIGIN'
];

const STACK_ARGS = ['--profile', 'stack', '--app-env', 'staging', '--site', 'staging.invalid'];

const image = () => infraContext().image;

/** `docker run --rm <run args> <image> <command>`, with no environment passed in. */
const runInImage = (runArgs: readonly string[], command: readonly string[]) =>
	docker(['run', '--rm', ...runArgs, image(), ...command]);

describe('the image', () => {
	it('is under 300,000,000 bytes, as the image store reports it', async () => {
		const r = await docker(['image', 'inspect', '--format', '{{.Size}}', image()]);
		expect(r.code).toBe(0);
		const size = Number(r.stdout.trim());
		const listed = await docker(['images', image()]);
		// Recorded in the bead's notes: the value, and what the image store reports. On the
		// containerd image store this is the compressed content size.
		process.stdout.write(`image size (.Size): ${size} bytes\n${listed.stdout}`);
		expect(size).toBeGreaterThan(0);
		expect(size).toBeLessThan(300_000_000);
	});

	it('is under 300,000,000 bytes unpacked', async () => {
		// Measured inside a container of the image: `du -skx /` sums the blocks of the image's own
		// root filesystem (-x stays off /proc, /sys, /dev and Docker's bind-mounted /etc files), as
		// it is unpacked, whatever the image store and whatever its compression. The engine's own
		// fields differ by store (.Size is compressed on containerd, unpacked on overlay2), so this
		// is the one number that means the same everywhere.
		// As root, for this measurement only: as `node`, du cannot read /root and exits 1.
		const r = await runInImage(['--user', '0:0', '--entrypoint', 'du'], ['-skx', '/']);
		expect(r.code).toBe(0);
		const kib = Number(/^(\d+)\s/.exec(r.stdout)?.[1]);
		const bytes = kib * 1024;
		process.stdout.write(`image size (unpacked, du -skx /): ${bytes} bytes\n`);
		expect(bytes).toBeGreaterThan(0);
		expect(bytes).toBeLessThan(300_000_000);
	});

	it('holds exactly the runtime files under /app (D1)', async () => {
		const app = await runInImage([], ['ls', '-A', '/app']);
		expect(app.stdout.split('\n').filter(Boolean).sort()).toEqual(
			['build', 'migrations', 'node_modules', 'package.json', 'src', 'tools'].sort()
		);
		const server = await runInImage([], ['ls', '-A', '/app/src/lib/server']);
		expect(server.stdout.split('\n').filter(Boolean).sort()).toEqual(['config', 'db', 'log']);
		const lib = await runInImage([], ['sh', '-c', 'ls -A /app/src && ls -A /app/src/lib']);
		expect(lib.stdout.split('\n').filter(Boolean)).toEqual(['lib', 'server']);
	});

	it('runs as node, not root', async () => {
		const user = await docker(['image', 'inspect', '--format', '{{.Config.User}}', image()]);
		expect(user.stdout.trim()).toBe('node');
		const id = await runInImage([], ['id', '-u']);
		expect(id.code).toBe(0);
		expect(id.stdout.trim()).not.toBe('0');
		expect(id.stdout.trim()).toMatch(/^\d+$/);
	});

	it('has a HEALTHCHECK', async () => {
		const r = await docker([
			'image',
			'inspect',
			'--format',
			'{{json .Config.Healthcheck}}',
			image()
		]);
		const check = JSON.parse(r.stdout) as { Test?: string[] } | null;
		expect(check?.Test?.length ?? 0).toBeGreaterThan(1);
		expect(check?.Test?.[0]).not.toBe('NONE');
		expect(check?.Test?.join(' ')).toContain('/healthz');
	});

	it('runs the Node release .nvmrc names', async () => {
		const nvmrc = readFileSync(join(root, '.nvmrc'), 'utf8').trim();
		const r = await runInImage([], ['node', '--version']);
		expect(r.stdout.trim()).toBe(`v${nvmrc}`);
	});

	it('holds no .env file', async () => {
		const r = await runInImage(
			[],
			['sh', '-c', "find / -xdev \\( -name '.env' -o -name '.env.*' \\) 2>/dev/null; true"]
		);
		expect(r.code).toBe(0);
		expect(r.stdout.trim()).toBe('');
	});
});

describe('the image entry points (D1)', () => {
	it('node tools/db/migrate.ts with an empty environment reports the missing variables', async () => {
		const r = await runInImage([], ['node', 'tools/db/migrate.ts']);
		expect(r.code).not.toBe(0);
		const output = r.stdout + r.stderr;
		// Every static import resolved: an ES module links them all before it runs.
		expect(output).not.toContain('ERR_MODULE_NOT_FOUND');
		expect(output).not.toContain('ERR_UNKNOWN_FILE_EXTENSION');
		const line = r.stdout
			.split('\n')
			.filter((l) => l.startsWith('{'))
			.map((l) => JSON.parse(l) as { msg?: string; missing?: string[] })
			.find((l) => l.msg === 'config_error');
		expect(line).toBeDefined();
		expect(line?.missing).toEqual(
			expect.arrayContaining(['APP_ENV', 'MIGRATION_DATABASE_URL', 'DATABASE_URL'])
		);
	});

	it('node tools/env-init.ts --profile stack writes the stack profile names', async () => {
		const r = await runInImage(
			['--tmpfs', '/out:mode=1777'],
			[
				'sh',
				'-c',
				// Names only leave the container, never a value.
				`node tools/env-init.ts ${STACK_ARGS.join(' ')} --out /out/env >/dev/null && sed -n 's/^\\([A-Z_]*\\)=.*/\\1/p' /out/env`
			]
		);
		expect(r.code).toBe(0);
		expect(r.stdout.split('\n').filter(Boolean).sort()).toEqual([...STACK_NAMES].sort());
	});
});

describe('files written through a bind mount (D8, PD16)', () => {
	const writeAs = async (user: string, dir: string, name: string) =>
		runInImage(
			['--user', user, '-v', `${dir}:/out`],
			['node', 'tools/env-init.ts', ...STACK_ARGS, '--out', `/out/${name}`]
		);

	it('--user 4321:4321 gives a file owned by uid 4321, mode 600', async () => {
		const { dir, remove } = tempDir('d8');
		try {
			chmodSync(dir, 0o1777);
			const r = await writeAs('4321:4321', dir, 'env');
			expect(r.code).toBe(0);
			const st = statSync(join(dir, 'env'));
			expect(st.uid).toBe(4321);
			expect(st.mode & 0o777).toBe(0o600);
		} finally {
			remove();
		}
	});

	it('--user of the host user gives a file the host user owns, and it parses', async () => {
		const { dir, remove } = tempDir('d8');
		try {
			chmodSync(dir, 0o1777);
			const uid = process.getuid!();
			const r = await writeAs(`${uid}:${process.getgid!()}`, dir, 'env');
			expect(r.code).toBe(0);
			const path = join(dir, 'env');
			const st = statSync(path);
			expect(st.uid).toBe(uid);
			expect(st.mode & 0o777).toBe(0o600);
			const env = parseEnv(readFileSync(path, 'utf8')) as Record<string, string>;
			expect(Object.keys(env).sort()).toEqual([...STACK_NAMES].sort());
			expect(env['JADE_STACK_APP_ENV']).toBe('staging');
			expect(env['JADE_ORIGIN']).toBe('https://staging.invalid');
		} finally {
			remove();
		}
	});
});

describe('the Dockerfile (D1, D7)', () => {
	const lines = readFileSync(join(root, 'Dockerfile'), 'utf8').split('\n');
	const index = (re: RegExp) => lines.findIndex((l) => re.test(l));

	it('declares ARG APP_VERSION once, in the build stage, between the install and the build', () => {
		const args = lines.filter((l) => /^ARG APP_VERSION\b/.test(l));
		expect(args).toEqual(['ARG APP_VERSION']);
		const build = index(/^FROM .* AS build$/);
		const runtime = lines.findIndex((l, i) => i > build && /^FROM /.test(l));
		const install = index(/^RUN pnpm install --frozen-lockfile --no-runtime$/);
		const arg = index(/^ARG APP_VERSION$/);
		const pnpmBuild = index(/^RUN pnpm build$/);
		expect(build).toBeGreaterThanOrEqual(0);
		expect(install).toBeGreaterThan(build);
		expect(arg).toBeGreaterThan(install);
		expect(pnpmBuild).toBeGreaterThan(arg);
		expect(runtime).toBeGreaterThan(pnpmBuild);
	});
});
