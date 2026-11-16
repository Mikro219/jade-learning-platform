// The built server stops before it listens when its configuration is unusable, naming the
// variables and never a value (plan V3, V3a, INV1, INV4). It builds the app itself, with an empty
// environment, which is also the check that the build needs no secret.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { beforeAll, describe, expect, it } from 'vitest';
import { loadAppConfig } from '../../src/lib/server/config/index.ts';
import { generatedEnv, testEnv, type ServerEnv } from '../support/env.ts';
import { runServer, startServer } from '../support/server.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const REQUIRED = ['APP_ENV', 'DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET'] as const;

function without(env: ServerEnv, key: string): ServerEnv {
	const copy = { ...env };
	delete copy[key];
	return copy;
}

/** Every value of `env` long enough to be distinctive, and the parts of its database URL. */
function secretsOf(env: ServerEnv): string[] {
	const url = new URL(env.DATABASE_URL!);
	return [env.DATABASE_URL!, env.CODE_PEPPER!, env.SESSION_SECRET!, url.password];
}

beforeAll(async () => {
	// `pnpm build` is `vite build`; run it on the pinned Node with nothing in the environment.
	await promisify(execFile)(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
		cwd: root,
		env: {},
		maxBuffer: 64 * 1024 * 1024
	});
}, 240_000);

describe('node build with a required variable missing', () => {
	it.each(REQUIRED)(
		'%s missing: exits non-zero within 5 s, names it, prints no value',
		async (key) => {
			const env = await generatedEnv('development');
			// Every other check accepts this environment: only the missing variable refuses it (PD15).
			expect(() => loadAppConfig(env)).not.toThrow();

			const run = await runServer(without(env, key), 5000);
			expect(run.timedOut).toBe(false);
			expect(run.listened).toBe(false);
			expect(run.code).not.toBe(0);
			expect(run.code).not.toBeNull();
			expect(run.elapsedMs).toBeLessThan(5000);
			expect(run.stdout).not.toMatch(/Listening on/);
			expect(run.stderr).toBe(`Configuration error. Missing: ${key}. See .env.example.\n`);
			for (const value of secretsOf(env)) {
				expect(run.stdout).not.toContain(value);
				expect(run.stderr).not.toContain(value);
			}
		}
	);

	it('a test-only value under APP_ENV=development exits with the test-only refusal', async () => {
		const env = { ...(await testEnv()), APP_ENV: 'test' };
		expect(() => loadAppConfig(env)).not.toThrow();
		const run = await runServer({ ...env, APP_ENV: 'development' }, 5000);
		expect(run.listened).toBe(false);
		expect(run.code).toBe(1);
		expect(run.stderr).toBe(
			'Configuration error. Invalid: DATABASE_URL (a test-only value is refused unless APP_ENV is test), ' +
				'CODE_PEPPER (a test-only value is refused unless APP_ENV is test), ' +
				'SESSION_SECRET (a test-only value is refused unless APP_ENV is test). See .env.example.\n'
		);
		for (const value of secretsOf(env)) expect(run.stderr).not.toContain(value);
	});

	it('NODE_ENV=production refuses APP_ENV=development', async () => {
		const env = await generatedEnv('development');
		const run = await runServer({ ...env, NODE_ENV: 'production' }, 5000);
		expect(run.listened).toBe(false);
		expect(run.code).toBe(1);
		expect(run.stderr).toBe(
			'Configuration error. Invalid: APP_ENV (must be staging or production when NODE_ENV is production). See .env.example.\n'
		);
	});
});

describe('node build with every variable set', () => {
	const cases: [string, () => Promise<ServerEnv>][] = [
		['APP_ENV=test, harness values', () => testEnv()],
		['APP_ENV=development, generated', () => generatedEnv('development')],
		[
			'APP_ENV=production, NODE_ENV=production, generated',
			async () => ({ ...(await generatedEnv('production')), NODE_ENV: 'production' })
		]
	];
	it.each(cases)('%s: listens and answers', async (_label, makeEnv) => {
		const env = await makeEnv();
		const server = await startServer(env);
		try {
			const response = await fetch(`${server.url}/`);
			expect(response.status).toBe(200);
			for (const value of secretsOf(env)) {
				expect(server.stdout()).not.toContain(value);
				expect(server.stderr()).not.toContain(value);
			}
		} finally {
			await server.stop();
		}
	});
});
