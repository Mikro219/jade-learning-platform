// INV8 (second half), PD8, A5: every `public` route answers without a session; every `dev-only`
// route is 404 under APP_ENV=production and reachable under test; every route id containing
// `/dev/` is `dev-only`.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { routes } from '../authz/route-registry.ts';
import { generatedEnv, testEnv } from '../support/env.ts';
import { startServer, type StartedServer } from '../support/server.ts';

let test: StartedServer;
let production: StartedServer;

beforeAll(async () => {
	[test, production] = await Promise.all([
		startServer(await testEnv()),
		startServer({ ...(await generatedEnv('production')), NODE_ENV: 'production' })
	]);
});

afterAll(async () => {
	await Promise.all([test?.stop(), production?.stop()]);
});

const status = async (server: StartedServer, path: string) =>
	(await fetch(`${server.url}${path}`, { redirect: 'manual' })).status;

describe('the registry', () => {
	it('every route id containing /dev/ is dev-only, and every dev-only route is under /dev/', () => {
		for (const route of routes) {
			expect(route.id.includes('/dev/'), route.id).toBe(route.access === 'dev-only');
		}
		expect(routes.some((r) => r.access === 'dev-only')).toBe(true);
	});
});

describe.each(routes.filter((r) => r.access === 'public'))('public $id', (route) => {
	it.each(['test', 'production'] as const)('answers without a session under %s', async (env) => {
		const code = await status(env === 'test' ? test : production, route.sample);
		expect([401, 403, 404]).not.toContain(code);
	});
});

describe.each(routes.filter((r) => r.access === 'dev-only'))('dev-only $id', (route) => {
	it('is 404 under APP_ENV=production', async () => {
		expect(await status(production, route.sample)).toBe(404);
	});

	it('is reachable under APP_ENV=test', async () => {
		expect(await status(test, route.sample)).not.toBe(404);
	});
});
