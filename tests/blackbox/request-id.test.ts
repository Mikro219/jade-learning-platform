// A2, A4: every response that passes through `handle` carries a fresh `X-Request-Id`, every error
// body carries the same id, a client-sent id is ignored, and no Phase 1 response sets a cookie.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { generatedEnv, testEnv } from '../support/env.ts';
import { startServer, type StartedServer } from '../support/server.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const responses: Response[] = [];

async function request(server: StartedServer, path: string, init: RequestInit = {}) {
	const response = await fetch(`${server.url}${path}`, { redirect: 'manual', ...init });
	responses.push(response);
	const id = response.headers.get('x-request-id');
	expect(id).toMatch(UUID);
	return { response, id: id!, text: await response.text() };
}

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

describe('X-Request-Id and the body', () => {
	it('a 404 page (HTML) shows the id of its header', async () => {
		const { response, id, text } = await request(test, '/no-such-page', {
			headers: { accept: 'text/html' }
		});
		expect(response.status).toBe(404);
		expect(response.headers.get('content-type')).toMatch(/text\/html/);
		expect(text).toContain(`Request id: <code>${id}</code>`);
		expect(text).toContain(`requestId:"${id}"`);
	});

	it('a 404 (JSON) from an endpoint carries the id of its header', async () => {
		// Under production, the dev-only endpoint answers 404 through error() (PD8).
		const { response, id, text } = await request(production, '/dev/boom', {
			headers: { accept: 'application/json' }
		});
		expect(response.status).toBe(404);
		expect(JSON.parse(text)).toEqual({ status: 404, message: 'Not Found', requestId: id });
	});

	it('a 405 carries the id of its header', async () => {
		const { response, id, text } = await request(test, '/', {
			method: 'POST',
			headers: { accept: 'application/json', 'content-type': 'application/json' },
			body: '{}'
		});
		expect(response.status).toBe(405);
		const body = JSON.parse(text) as { error: Record<string, unknown> };
		expect(body.error).toEqual({ status: 405, message: 'Method Not Allowed', requestId: id });
	});

	it('a 503 from /readyz carries the id of its header', async () => {
		const { response, id, text } = await request(test, '/readyz');
		expect(response.status).toBe(503);
		expect((JSON.parse(text) as { requestId: string }).requestId).toBe(id);
	});

	it('a 500 from /dev/boom carries the id of its header and no part of the message', async () => {
		const { response, id, text } = await request(test, '/dev/boom?probe=1');
		expect(response.status).toBe(500);
		expect(JSON.parse(text)).toEqual({ status: 500, message: 'Internal Error', requestId: id });
		expect(text).not.toContain('probe');
		// The error line and the request line in the server's log carry the same id (A4). The pipe
		// can deliver them after the response, so wait for them briefly.
		await vi.waitFor(
			() => {
				const logged = test
					.stdout()
					.split('\n')
					.filter((l) => l.startsWith('{'))
					.map((l) => JSON.parse(l) as Record<string, unknown>)
					.filter((l) => l.request_id === id);
				const errorLines = logged.filter((l) => l.msg === 'error');
				const requestLines = logged.filter((l) => l.msg === 'request');
				expect(errorLines).toHaveLength(1);
				expect(errorLines[0]).toMatchObject({ kind: 'unknown', route: '/dev/boom' });
				expect(requestLines).toHaveLength(1);
				expect(requestLines[0]).toMatchObject({ status: 500, route: '/dev/boom' });
			},
			{ timeout: 2000 }
		);
	});
});

describe('request ids', () => {
	it('two requests get different ids', async () => {
		const a = await request(test, '/healthz');
		const b = await request(test, '/healthz');
		expect(a.id).not.toBe(b.id);
	});

	it('a client-sent id is not used', async () => {
		const sent = crypto.randomUUID();
		const { id, text } = await request(test, '/dev/boom', { headers: { 'x-request-id': sent } });
		expect(id).not.toBe(sent);
		expect(text).not.toContain(sent);
		expect(test.stdout()).not.toContain(sent);
	});

	it('no Phase 1 response sets a cookie', async () => {
		await request(test, '/');
		expect(responses.length).toBeGreaterThan(5);
		for (const response of responses) {
			expect(response.headers.get('set-cookie')).toBeNull();
			expect(response.headers.getSetCookie()).toEqual([]);
		}
	});
});
