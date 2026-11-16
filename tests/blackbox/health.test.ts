// A3: /healthz and /readyz on the built server. /healthz answers with no database; /readyz is 200
// only when the database answers within 2 seconds and every shipped migration is applied with the
// same hash, and 503 otherwise, with fixed check values and no host name or error text.
import { createServer, type Server, type Socket } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { freePort } from '../../tools/free-port.ts';
import { createEmptyDatabase, createTestDatabase, type TestDatabase } from '../support/db.ts';
import { testEnv, type ServerEnv } from '../support/env.ts';
import { startServer } from '../support/server.ts';

async function get(env: ServerEnv, path: string) {
	const server = await startServer(env);
	try {
		const started = Date.now();
		const response = await fetch(`${server.url}${path}`);
		const elapsedMs = Date.now() - started;
		const text = await response.text();
		return { response, text, body: JSON.parse(text) as Record<string, unknown>, elapsedMs };
	} finally {
		await server.stop();
	}
}

/** The fixed 503 body of A3: only `status`, `checks` and `requestId`. */
function expectNotReady(
	result: Awaited<ReturnType<typeof get>>,
	checks: { db: string; migrations: string }
) {
	expect(result.response.status).toBe(503);
	expect(result.response.headers.get('cache-control')).toBe('no-store');
	expect(Object.keys(result.body).sort()).toEqual(['checks', 'requestId', 'status']);
	expect(result.body.status).toBe('not_ready');
	expect(result.body.checks).toEqual(checks);
	expect(result.body.requestId).toBe(result.response.headers.get('x-request-id'));
	expect(result.text).not.toMatch(/127\.0\.0\.1|localhost|jade_|ECONN|timeout/i);
}

describe('/healthz', () => {
	it('is 200 with no database and touches nothing else', async () => {
		const result = await get(await testEnv(), '/healthz');
		expect(result.response.status).toBe(200);
		expect(result.response.headers.get('cache-control')).toBe('no-store');
		expect(result.body).toEqual({ status: 'ok', version: 'dev' });
	});
});

describe('/readyz', () => {
	let migrated: TestDatabase;
	let empty: TestDatabase;
	beforeAll(async () => {
		[migrated, empty] = await Promise.all([createTestDatabase(), createEmptyDatabase()]);
	});
	afterAll(async () => {
		await Promise.all([migrated?.drop(), empty?.drop()]);
	});

	it('is 200 on a migrated database', async () => {
		const result = await get({ ...(await testEnv()), DATABASE_URL: migrated.appUrl }, '/readyz');
		expect(result.response.status).toBe(200);
		expect(result.response.headers.get('cache-control')).toBe('no-store');
		expect(result.body).toEqual({ status: 'ready' });
	});

	it('is 503 with db: fail within 3 s when nothing listens on the port', async () => {
		// testEnv() points DATABASE_URL at a port from freePort() whose socket is already closed.
		const result = await get(await testEnv({ dbPort: await freePort() }), '/readyz');
		expectNotReady(result, { db: 'fail', migrations: 'unknown' });
		expect(result.elapsedMs).toBeLessThan(3000);
	});

	it('is 503 with db: fail within 3 s when the database accepts and never answers', async () => {
		const sockets: Socket[] = [];
		const silent: Server = createServer((socket) => {
			sockets.push(socket); // accept, read nothing, answer nothing
		});
		await new Promise<void>((resolve) => silent.listen(0, '127.0.0.1', resolve));
		const port = (silent.address() as { port: number }).port;
		try {
			const result = await get(await testEnv({ dbPort: port }), '/readyz');
			expectNotReady(result, { db: 'fail', migrations: 'unknown' });
			expect(result.elapsedMs).toBeLessThan(3000);
		} finally {
			for (const socket of sockets) socket.destroy();
			await new Promise((resolve) => silent.close(resolve));
		}
	});

	it('is 503 with migrations: behind on an empty database', async () => {
		const result = await get({ ...(await testEnv()), DATABASE_URL: empty.appUrl }, '/readyz');
		expectNotReady(result, { db: 'ok', migrations: 'behind' });
	});
});
