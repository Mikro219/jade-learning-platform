// The built server stops before it listens when its configuration is unusable, naming the
// variables and never a value (plan V3, V3a, INV1, INV4). From jade-alt on, the names are carried
// by one `config_error` lifecycle line on stdout, written through the logger, and no generic
// error line is written instead. The blackbox project's global setup builds the app with an empty
// environment (jade-b1f), which is also the check that the build needs no secret.
import { describe, expect, it } from 'vitest';
import { loadAppConfig } from '../../src/lib/server/config/index.ts';
import { generatedEnv, testEnv, type ServerEnv } from '../support/env.ts';
import { runServer, startServer, type ServerRun } from '../support/server.ts';

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

/**
 * The run's only output: one `config_error` line on stdout and nothing on stderr. Returns its
 * `missing` and `invalid` arrays.
 */
function configErrorOf(run: ServerRun): { missing: unknown; invalid: unknown } {
	expect(run.stderr).toBe('');
	const lines = run.stdout.split('\n').filter((l) => l !== '');
	expect(lines).toHaveLength(1);
	const line = JSON.parse(lines[0]!) as Record<string, unknown>;
	expect(Object.keys(line)).toEqual(['ts', 'level', 'msg', 'missing', 'invalid']);
	expect(line).toMatchObject({ level: 'error', msg: 'config_error' });
	// No generic error line (the A4 handlers) was written instead.
	expect(run.stdout).not.toMatch(/"msg":"error"/);
	return { missing: line.missing, invalid: line.invalid };
}

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
			expect(configErrorOf(run)).toEqual({ missing: [key], invalid: [] });
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
		expect(configErrorOf(run)).toEqual({
			missing: [],
			invalid: ['DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET']
		});
		for (const value of secretsOf(env)) expect(run.stdout).not.toContain(value);
	});

	it('NODE_ENV=production refuses APP_ENV=development', async () => {
		const env = await generatedEnv('development');
		const run = await runServer({ ...env, NODE_ENV: 'production' }, 5000);
		expect(run.listened).toBe(false);
		expect(run.code).toBe(1);
		expect(configErrorOf(run)).toEqual({ missing: [], invalid: ['APP_ENV'] });
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
