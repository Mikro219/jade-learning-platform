// compose.prod.yml's contract (plan D2, D7, INV4, INV6, INV7, INV9, PD13, PD14), on the file's
// text and on `docker compose -p <test project> -f compose.prod.yml --env-file <file> config`,
// once with a `dev`-profile env file and once with a `stack`-profile one, both written by
// `pnpm env:init` into a temporary directory. Values read from `config` are compared piecemeal
// (a user name, a host), never printed: they include the generated secrets.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseEnv } from 'node:util';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { checkoutHash, thirdPartyServices, type ComposeConfig } from '../../tools/compose.ts';
import { infraImageTag, isRunProject, newInfraRunId } from './global-setup.ts';
import {
	INFRA_PROJECT_SUFFIXES,
	dockerEnv,
	envInit,
	exec,
	infraContext,
	infraProject,
	root,
	tempDir
} from '../support/infra.ts';

const text = readFileSync(join(root, 'compose.prod.yml'), 'utf8');
const devText = readFileSync(join(root, 'compose.dev.yml'), 'utf8');
const SECRETS = ['JADE_OWNER_DB_PASSWORD', 'JADE_APP_DB_PASSWORD', 'CODE_PEPPER', 'SESSION_SECRET'];

interface Service {
	image?: string;
	build?: { context?: string; dockerfile?: string; args?: Record<string, string> };
	environment?: Record<string, string>;
	ports?: { target: number; published: string; protocol: string; host_ip?: string }[];
	networks?: Record<string, unknown>;
	volumes?: { type: string; source?: string; target: string; read_only?: boolean }[];
}
interface Config extends ComposeConfig {
	services: Record<string, Service>;
	networks?: Record<string, { internal?: boolean; name?: string }>;
	volumes?: Record<string, unknown>;
}

const project = () => infraProject('config');

/** `docker compose config --format json` on compose.prod.yml; JADE_IMAGE only when given. */
async function config(envFile: string, image?: string) {
	return exec(
		'docker',
		[
			'compose',
			'-p',
			project(),
			'-f',
			'compose.prod.yml',
			'--env-file',
			envFile,
			'config',
			'--format',
			'json'
		],
		dockerEnv(image === undefined ? {} : { JADE_IMAGE: image })
	);
}

async function parsedConfig(envFile: string, image?: string): Promise<Config> {
	const r = await config(envFile, image);
	if (r.code !== 0) throw new Error(`docker compose config failed: ${r.stderr}`);
	return JSON.parse(r.stdout) as Config;
}

let dir: string;
let remove: () => void;
const files: Record<'dev' | 'stack', string> = { dev: '', stack: '' };
const envs: Record<'dev' | 'stack', Record<string, string>> = { dev: {}, stack: {} };

beforeAll(async () => {
	({ dir, remove } = tempDir('config'));
	files.dev = join(dir, 'dev.env');
	files.stack = join(dir, 'stack.env');
	const dev = await envInit(['--out', files.dev, '--http-port', '18080', '--https-port', '18443']);
	const stack = await envInit([
		'--out',
		files.stack,
		'--profile',
		'stack',
		'--app-env',
		'staging',
		'--site',
		'staging.invalid'
	]);
	if (dev.code !== 0 || stack.code !== 0) throw new Error('env:init failed');
	for (const p of ['dev', 'stack'] as const) {
		envs[p] = parseEnv(readFileSync(files[p], 'utf8')) as Record<string, string>;
	}
});
afterAll(() => remove?.());

describe('the file text', () => {
	it('every secret is a ${NAME:?} reference, and is referenced', () => {
		for (const name of SECRETS) {
			const refs = [...text.matchAll(new RegExp(`\\$\\{${name}([^}]*)\\}`, 'g'))];
			expect({ name, count: refs.length > 0 }).toEqual({ name, count: true });
			for (const m of refs) expect({ name, ref: m[1] }).toEqual({ name, ref: ':?' });
		}
	});

	it('names none of the development variables', () => {
		for (const ref of [
			'${APP_ENV',
			'${DATABASE_URL',
			'${MIGRATION_DATABASE_URL',
			'${JADE_DEV_DB_PORT'
		]) {
			expect(text).not.toContain(ref);
		}
	});

	it('app and migrate name the same image expression, from JADE_IMAGE', () => {
		const block = (service: string) =>
			new RegExp(`^  ${service}:\\n((?:    .*\\n|\\s*\\n)*)`, 'm').exec(text)?.[1] ?? '';
		for (const service of ['app', 'migrate']) {
			expect(block(service)).toMatch(/^ {4}image: \$\{JADE_IMAGE:-jade-app:local\}$/m);
		}
		expect(block('migrate')).not.toMatch(/^ {4}build:/m);
		expect(block('app')).toMatch(/^ {4}build:/m);
	});

	it('has no unbraced $NAME interpolation (every one is ${NAME...})', () => {
		// `$$` is Compose's escape for a literal `$`; anything else after `$` must be `{`.
		const unbraced = [...text.matchAll(/(?<!\$)\$(?!\{|\$)[A-Za-z_][A-Za-z0-9_]*/g)].map(
			(m) => m[0]
		);
		expect(unbraced).toEqual([]);
	});

	it('has the top-level name jade-stack', () => {
		expect(text).toMatch(/^name: jade-stack$/m);
	});
});

describe.each(['dev', 'stack'] as const)('docker compose config with a %s env file', (profile) => {
	let c: Config;
	beforeAll(async () => {
		c = await parsedConfig(files[profile], infraContext().image);
	});

	it('only caddy has ports: JADE_HTTP_PORT and JADE_HTTPS_PORT to 80 and 443 over TCP', () => {
		const withPorts = Object.entries(c.services)
			.filter(([, s]) => (s.ports ?? []).length > 0)
			.map(([name]) => name);
		expect(withPorts).toEqual(['caddy']);
		const ports = c.services['caddy']!.ports!.map((p) => ({
			target: p.target,
			published: String(p.published),
			protocol: p.protocol
		}));
		expect(ports).toEqual([
			{ target: 80, published: envs[profile]['JADE_HTTP_PORT'], protocol: 'tcp' },
			{ target: 443, published: envs[profile]['JADE_HTTPS_PORT'], protocol: 'tcp' }
		]);
	});

	it('db, migrate and app are on backend only, which is internal; caddy is on edge and backend', () => {
		for (const name of ['db', 'migrate', 'app']) {
			expect({ name, networks: Object.keys(c.services[name]!.networks ?? {}) }).toEqual({
				name,
				networks: ['backend']
			});
		}
		expect(Object.keys(c.services['caddy']!.networks ?? {}).sort()).toEqual(['backend', 'edge']);
		expect(c.networks?.['backend']?.internal).toBe(true);
		expect(c.networks?.['edge']?.internal ?? false).toBe(false);
	});

	it('no service is on the default network', () => {
		for (const [name, s] of Object.entries(c.services)) {
			expect({ name, onDefault: 'default' in (s.networks ?? {}) }).toEqual({
				name,
				onDefault: false
			});
		}
		expect(Object.keys(c.networks ?? {})).not.toContain('default');
	});

	it('the database URLs name jade_app and jade_owner at host db', () => {
		for (const name of ['app', 'migrate']) {
			const url = new URL(c.services[name]!.environment!['DATABASE_URL']!);
			expect({ name, user: url.username, host: url.host, db: url.pathname }).toEqual({
				name,
				user: 'jade_app',
				host: 'db:5432',
				db: '/jade'
			});
			// Built from the file's password variable, not from the development URL.
			expect(url.password === envs[profile]['JADE_APP_DB_PASSWORD']).toBe(true);
		}
		const owner = new URL(c.services['migrate']!.environment!['MIGRATION_DATABASE_URL']!);
		expect({ user: owner.username, host: owner.host }).toEqual({
			user: 'jade_owner',
			host: 'db:5432'
		});
		expect(owner.password === envs[profile]['JADE_OWNER_DB_PASSWORD']).toBe(true);
	});

	it('app and migrate run as the stack APP_ENV, never development or test', () => {
		const expected = profile === 'dev' ? 'production' : 'staging';
		for (const name of ['app', 'migrate']) {
			const appEnv = c.services[name]!.environment!['APP_ENV'];
			expect({ name, appEnv }).toEqual({ name, appEnv: expected });
			expect(['development', 'test']).not.toContain(appEnv);
		}
	});

	it('each service receives exactly its listed variables', () => {
		expect(Object.keys(c.services['migrate']!.environment!).sort()).toEqual(
			['APP_ENV', 'DATABASE_URL', 'MIGRATION_DATABASE_URL'].sort()
		);
		expect(Object.keys(c.services['app']!.environment!).sort()).toEqual(
			['APP_ENV', 'CODE_PEPPER', 'DATABASE_URL', 'LOG_LEVEL', 'ORIGIN', 'SESSION_SECRET'].sort()
		);
		expect(Object.keys(c.services['caddy']!.environment!)).toEqual(['SITE_ADDRESS']);
		expect(c.services['app']!.environment!['ORIGIN'] === envs[profile]['JADE_ORIGIN']).toBe(true);
	});

	it('app has no MIGRATION_DATABASE_URL and never the owner password', () => {
		const env = c.services['app']!.environment!;
		expect(Object.keys(env)).not.toContain('MIGRATION_DATABASE_URL');
		const owner = envs[profile]['JADE_OWNER_DB_PASSWORD']!;
		const leaks = Object.entries(env)
			.filter(([, value]) => value.includes(owner))
			.map(([key]) => key);
		expect(leaks).toEqual([]);
	});

	it('app and migrate resolve to the run tag; the other images match the pins', () => {
		expect(c.services['app']!.image).toBe(infraContext().image);
		expect(c.services['migrate']!.image).toBe(infraContext().image);
		const devPin = /^\s*image:\s*(postgres:\S+)\s*$/m.exec(devText)?.[1];
		expect(c.services['db']!.image).toBe('postgres:16.16-bookworm');
		expect(c.services['db']!.image).toBe(devPin);
		expect(c.services['caddy']!.image).toBe('caddy:2.11.9-alpine');
	});

	it('the third-party services are exactly db and caddy (D7)', () => {
		expect(thirdPartyServices(c, infraContext().image)).toEqual(['caddy', 'db']);
	});

	it('app has the one build stanza: context ., one argument APP_VERSION; migrate has none', () => {
		const build = c.services['app']!.build!;
		expect(build.context).toBe(root.replace(/\/$/, ''));
		expect(Object.keys(build.args ?? {})).toEqual(['APP_VERSION']);
		expect(c.services['migrate']!.build).toBeUndefined();
	});

	it('the media volume is mounted read-only in caddy', () => {
		const media = c.services['caddy']!.volumes!.find((v) => v.source === 'media');
		expect(media?.read_only).toBe(true);
	});

	it.each([...new Set([...text.matchAll(/\$\{([A-Z_]+):\?\}/g)].map((m) => m[1]!))])(
		'config fails when %s is unset',
		async (name) => {
			const file = join(dir, `${profile}-without-${name}.env`);
			const kept = readFileSync(files[profile], 'utf8')
				.split('\n')
				.filter((line) => !line.startsWith(`${name}=`))
				.join('\n');
			writeFileSync(file, kept, { mode: 0o600 });
			const r = await config(file, infraContext().image);
			expect(r.code).not.toBe(0);
			expect(r.stderr).toContain(name);
		}
	);
});

describe('the required variables include every secret', () => {
	it('each secret is required', () => {
		const required = new Set([...text.matchAll(/\$\{([A-Z_]+):\?\}/g)].map((m) => m[1]!));
		for (const name of SECRETS) expect(required.has(name)).toBe(true);
	});
});

describe('JADE_IMAGE (D7, PD14)', () => {
	it('unset, app and migrate resolve to jade-app:local', async () => {
		const c = await parsedConfig(files.dev);
		expect(c.services['app']!.image).toBe('jade-app:local');
		expect(c.services['migrate']!.image).toBe('jade-app:local');
	});

	it('the run tag is jade-app:ci-<checkout hash>-<run id>; two runs or checkouts differ', () => {
		const { image, runId } = infraContext();
		expect(image).toBe(`jade-app:ci-${checkoutHash()}-${runId}`);
		expect(infraImageTag('aaaaaaaa', newInfraRunId())).not.toBe(
			infraImageTag('aaaaaaaa', newInfraRunId())
		);
		const id = newInfraRunId();
		expect(id).toMatch(/^[0-9a-f]{16}$/);
		expect(infraImageTag('aaaaaaaa', id)).not.toBe(infraImageTag('bbbbbbbb', id));
	});
});

describe("the run's own projects (B2: cleanup of an interrupted run)", () => {
	it('match exactly jade-infra-<this run id>-<known suffix>, nothing broader', () => {
		const id = 'abc123';
		expect(isRunProject('jade-infra-abc123-up', id)).toBe(true);
		expect(isRunProject('jade-infra-abc123-caddylogs', id)).toBe(true);
		for (const suffix of INFRA_PROJECT_SUFFIXES) {
			expect(isRunProject(`jade-infra-${id}-${suffix}`, id)).toBe(true);
		}
		expect(isRunProject('jade-infra-123-1-up', '123')).toBe(false);
		for (const other of [
			'jade-infra-abc1234-up',
			'jade-infra-abc12-up',
			'jade-infra-abc123-',
			'jade-infra-abc123',
			'jade-infra-xyz-up',
			'jade-stack-abc123-up',
			'jade-dev-255efdb2',
			'docker',
			'x-jade-infra-abc123-up',
			// Another run whose id has this one as a hyphenated prefix (run 123 against 123-1).
			'jade-infra-abc123-1-up',
			'jade-infra-abc123-up-2',
			'jade-infra-abc123-other'
		]) {
			expect({ other, matched: isRunProject(other, id) }).toEqual({ other, matched: false });
		}
	});
});

describe('compose.prod.yml and compose.dev.yml share no name (PD13)', () => {
	it('services, volumes and networks are disjoint', async () => {
		const prod = await parsedConfig(files.dev, infraContext().image);
		const dev = await exec(
			'docker',
			[
				'compose',
				'-p',
				project(),
				'-f',
				'compose.dev.yml',
				'--env-file',
				files.dev,
				'config',
				'--format',
				'json'
			],
			dockerEnv()
		);
		expect(dev.code).toBe(0);
		const devConfig = JSON.parse(dev.stdout) as Config;
		for (const key of ['services', 'volumes', 'networks'] as const) {
			const prodNames = Object.keys(prod[key] ?? {});
			const devNames = Object.keys(devConfig[key] ?? {});
			expect({ key, shared: prodNames.filter((n) => devNames.includes(n)) }).toEqual({
				key,
				shared: []
			});
		}
	});
});

describe('package.json builds the image in one place (D7)', () => {
	const scripts = (
		JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')) as {
			scripts: Record<string, string>;
		}
	).scripts;

	it('ci:image bakes the app target of compose.prod.yml, with nothing of its own', () => {
		const script = scripts['ci:image']!;
		expect(script).toMatch(/\bdocker buildx bake --file compose\.prod\.yml --load app$/);
		// No Dockerfile, context, tag or build argument of its own.
		expect(script).not.toMatch(/Dockerfile|--set|--tag|\s-t\s|build-arg|context|\.args|\.tags/);
	});

	it('no other script builds an image', () => {
		const builders = Object.entries(scripts)
			.filter(([, s]) => /buildx|docker build|--build\b|stack-up/.test(s))
			.map(([name]) => name)
			.sort();
		expect(builders).toEqual(['ci:image', 'stack:up']);
	});
});
