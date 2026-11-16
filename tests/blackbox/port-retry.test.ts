// PD11: a start that fails because the port was taken between freePort() and listen is retried
// with a new port, at most three times. Since jade-alt the crash is a closed JSON error line on
// stdout (`"err_tag":"EADDRINUSE"`) with an empty stderr, so the harness must read stdout.
import { createServer, type Server } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { freePort } from '../../tools/free-port.ts';
import { testEnv } from '../support/env.ts';
import { isAddrInUse, runServer, startServer } from '../support/server.ts';

let holder: Server;
let held: number;

beforeAll(async () => {
	holder = createServer();
	await new Promise<void>((resolve) => holder.listen(0, '127.0.0.1', resolve));
	held = (holder.address() as { port: number }).port;
});

afterAll(async () => {
	await new Promise<void>((resolve) => holder.close(() => resolve()));
});

describe('EADDRINUSE retry (PD11)', () => {
	it('a held first port is retried on a new port', async () => {
		const chosen: number[] = [];
		const server = await startServer(await testEnv(), 10_000, async () => {
			const port = chosen.length === 0 ? held : await freePort();
			chosen.push(port);
			return port;
		});
		try {
			expect(chosen).toHaveLength(2);
			expect(chosen[0]).toBe(held);
			const port = Number(new URL(server.url).port);
			expect(port).toBe(chosen[1]);
			expect(port).not.toBe(held);
			expect((await fetch(`${server.url}/healthz`)).status).toBe(200);
		} finally {
			await server.stop();
		}
	});

	it('the collision is detected from the stdout error line, and retries stop after three', async () => {
		let attempts = 0;
		const run = await runServer(await testEnv(), 10_000, async () => {
			attempts++;
			return held;
		});
		expect(attempts).toBe(3);
		expect(run.code).toBe(1);
		expect(run.listened).toBe(false);
		expect(run.stderr).toBe('');
		expect(run.stdout).toMatch(/"err_tag":"EADDRINUSE"/);
		expect(isAddrInUse(run.stdout, run.stderr)).toBe(true);
	});

	it('startServer reports stdout and stderr when every attempt collides', async () => {
		await expect(startServer(await testEnv(), 10_000, async () => held)).rejects.toThrow(
			/stdout:\n[\s\S]*"err_tag":"EADDRINUSE"[\s\S]*\nstderr:/
		);
	});

	it('isAddrInUse: stderr text, the JSON line, and nothing else', () => {
		expect(isAddrInUse('', 'Error: listen EADDRINUSE: address already in use')).toBe(true);
		expect(isAddrInUse('{"level":"error","msg":"error","err_tag":"EADDRINUSE"}\n', '')).toBe(true);
		expect(isAddrInUse('{"level":"error","msg":"error","err_tag":"EACCES"}\n', '')).toBe(false);
		expect(isAddrInUse('not json EADDRINUSE\n{broken', '')).toBe(false);
		expect(isAddrInUse('', '')).toBe(false);
	});
});
