// The stack, brought up from the env file of the README's path (plan D2, D3, D7, INV7, PD11,
// PD14): `pnpm env:init --out <dir>/.env --http-port <p1> --https-port <p2>`, then
// `docker compose -p jade-infra-<run id>-up -f compose.prod.yml --env-file <file> up -d --wait
// --no-build --pull never` with JADE_IMAGE at the run's tag. Exposure is read from Docker's own
// records, never by probing a fixed host port: the development database may be listening there.
import { copyFileSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { buildManifest } from '../../src/lib/server/db/index.ts';
import {
	UP_FLAGS,
	containerEnvValue,
	docker,
	httpGet,
	httpsGet,
	infraContext,
	inspect,
	ledger,
	projectContainers,
	root,
	serviceContainer,
	startStack,
	stopStack,
	waitFor,
	type Stack
} from '../support/infra.ts';

let stack: Stack;
let ca: string;

beforeAll(async () => {
	stack = await startStack('up');
	ca = await stack.ca();
});
afterAll(async () => {
	await stopStack('up', stack);
});

const get = (path: string, headers: Record<string, string> = {}) =>
	httpsGet(stack.httpsPort, path, { ca, headers });

describe('the stack through Caddy', () => {
	it('serves / and /healthz over HTTPS with a certificate from its CA', async () => {
		expect((await get('/')).status).toBe(200);
		const health = await get('/healthz');
		expect(health.status).toBe(200);
		expect(JSON.parse(health.body)).toMatchObject({ status: 'ok' });
	});

	it('redirects plain HTTP to https with the same path', async () => {
		const r = await httpGet(stack.httpPort, '/some/path?x=1');
		expect([301, 302, 307, 308]).toContain(r.status);
		const location = new URL(r.headers.location ?? '');
		expect(location.protocol).toBe('https:');
		expect(location.pathname).toBe('/some/path');
		expect(location.search).toBe('?x=1');
	});

	it('offers a compressed response', async () => {
		const r = await get('/', { 'accept-encoding': 'zstd, gzip' });
		expect(r.status).toBe(200);
		expect(['zstd', 'gzip']).toContain(r.headers['content-encoding']);
	});

	it('/readyz is 200: migrate ran before the app', async () => {
		expect((await get('/readyz')).status).toBe(200);
		expect(await ledger(stack)).toEqual(['0000_baseline']);
	});
});

describe('the containers', () => {
	it('the app runs as APP_ENV=production', async () => {
		const app = await serviceContainer(stack.project, 'app');
		expect(await containerEnvValue(app, 'APP_ENV')).toBe('production');
	});

	it("app and migrate run the run's image, the one image.test.ts checks (PD14)", async () => {
		const expected = await docker([
			'image',
			'inspect',
			'--format',
			'{{.Id}}',
			infraContext().image
		]);
		expect(expected.code).toBe(0);
		for (const service of ['app', 'migrate']) {
			const id = await inspect<string>(await serviceContainer(stack.project, service), '.Image');
			expect({ service, id }).toEqual({ service, id: expected.stdout.trim() });
		}
		const migrateState = await inspect<{ Status: string; ExitCode: number }>(
			await serviceContainer(stack.project, 'migrate'),
			'.State'
		);
		expect(migrateState).toMatchObject({ Status: 'exited', ExitCode: 0 });
	});
});

describe('exposure, from Docker records (INV7, PD11)', () => {
	it('no container but caddy has a port binding or a published port', async () => {
		const ids = await projectContainers(stack.project);
		expect(ids.length).toBe(4);
		for (const id of ids) {
			const service = await inspect<Record<string, string>>(id, '.Config.Labels').then(
				(l) => l['com.docker.compose.service']
			);
			const bindings = await inspect<Record<string, unknown> | null>(
				id,
				'.HostConfig.PortBindings'
			);
			const ports = await inspect<Record<string, unknown[] | null> | null>(
				id,
				'.NetworkSettings.Ports'
			);
			const published = Object.values(ports ?? {}).filter((v) => Array.isArray(v) && v.length > 0);
			if (service === 'caddy') {
				const hostPorts = Object.values(bindings ?? {})
					.flat()
					.map((b) => (b as { HostPort: string }).HostPort)
					.sort();
				expect(hostPorts).toEqual([String(stack.httpPort), String(stack.httpsPort)].sort());
			} else {
				expect({ service, bindings: Object.keys(bindings ?? {}) }).toEqual({
					service,
					bindings: []
				});
				expect({ service, published: published.length }).toEqual({ service, published: 0 });
			}
		}
	});

	it('docker compose ps lists no published port but caddy, which has exactly p1 and p2', async () => {
		const r = await stack.compose(['ps', '-a', '--format', 'json']);
		expect(r.code).toBe(0);
		const rows = r.stdout
			.trim()
			.split('\n')
			.flatMap((line) => {
				const parsed = JSON.parse(line) as unknown;
				return Array.isArray(parsed) ? parsed : [parsed];
			}) as { Service: string; Publishers?: { PublishedPort: number; TargetPort: number }[] }[];
		expect(rows.map((row) => row.Service).sort()).toEqual(['app', 'caddy', 'db', 'migrate']);
		for (const row of rows) {
			const published = (row.Publishers ?? [])
				.filter((p) => p.PublishedPort !== 0)
				.map((p) => `${p.PublishedPort}:${p.TargetPort}`);
			const expected =
				row.Service === 'caddy' ? [`${stack.httpPort}:80`, `${stack.httpsPort}:443`] : [];
			expect({ service: row.Service, published: [...new Set(published)].sort() }).toEqual({
				service: row.Service,
				published: expected.sort()
			});
		}
	});

	it('docker compose port prints no binding for app 3000 or db 5432; caddy has p1 and p2', async () => {
		const hostPort = (output: string) => /:(\d+)\s*$/.exec(output.trim())?.[1];
		for (const [service, port] of [
			['app', '3000'],
			['db', '5432']
		] as const) {
			const r = await stack.compose(['port', service, port]);
			const bound = hostPort(r.stdout);
			expect({ service, bound: bound === undefined || bound === '0' }).toEqual({
				service,
				bound: true
			});
		}
		expect(hostPort((await stack.compose(['port', 'caddy', '80'])).stdout)).toBe(
			String(stack.httpPort)
		);
		expect(hostPort((await stack.compose(['port', 'caddy', '443'])).stdout)).toBe(
			String(stack.httpsPort)
		);
	});
});

describe('readiness follows the database', () => {
	it('stopping db turns /readyz into 503; starting it brings 200 back', async () => {
		expect((await stack.compose(['stop', 'db'])).code).toBe(0);
		expect(await waitFor(async () => (await get('/readyz')).status === 503, 30_000)).toBe(true);
		expect((await stack.compose(['start', 'db'])).code).toBe(0);
		expect(await waitFor(async () => (await get('/readyz')).status === 200, 90_000)).toBe(true);
	});

	it('a fixture migration mounted over /app/migrations is applied by a second up', async () => {
		// The shipped migrations plus one fixture, with a manifest built the runner's way.
		const migrations = join(stack.dir, 'migrations');
		mkdirSync(migrations, { mode: 0o755 });
		for (const file of readdirSync(join(root, 'migrations')).filter((f) => f.endsWith('.sql'))) {
			copyFileSync(join(root, 'migrations', file), join(migrations, file));
		}
		copyFileSync(
			join(root, 'tests/infra/fixtures/migrations/0001_infra_fixture.sql'),
			join(migrations, '0001_infra_fixture.sql')
		);
		writeFileSync(
			join(migrations, 'manifest.json'),
			`${JSON.stringify(buildManifest(migrations), null, '\t')}\n`
		);
		const override = join(stack.dir, 'override.yml');
		writeFileSync(
			override,
			`services:\n  migrate:\n    volumes:\n      - ${migrations}:/app/migrations:ro\n`
		);
		const up = await stack.compose(UP_FLAGS, [override]);
		expect({ code: up.code, stderr: up.code === 0 ? '' : up.stderr }).toEqual({
			code: 0,
			stderr: ''
		});
		expect(await ledger(stack, [override])).toEqual(['0000_baseline', '0001_infra_fixture']);
		// The database is ahead of the app's bundled manifest, which is ready (A3).
		expect(await waitFor(async () => (await get('/readyz')).status === 200, 30_000)).toBe(true);
	});
});
