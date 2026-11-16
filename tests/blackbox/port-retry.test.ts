// PD11: a start that fails because the port was taken between freePort() and listen is retried
// with a new port, at most three times. Since jade-alt the crash is a closed JSON error line on
// stdout (`"err_tag":"EADDRINUSE"`) with an empty stderr, so the harness must read stdout.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:net';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { freePort } from '../../tools/free-port.ts';
import { testEnv } from '../support/env.ts';
import { CLI_READY, isAddrInUse, runServer, startServer, stopChild } from '../support/server.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));

/**
 * Run the server CLI (Playwright's webServer command) with `--port first` until it prints its
 * ready line or exits; returns the port it names and a stop function.
 */
async function runCli(
	first: number
): Promise<{ port: number | null; code: number | null; out: string; stop: () => Promise<void> }> {
	// Detached, so the CLI leads a process group with its `node build`: stop() signals both (B9).
	const child = spawn(process.execPath, ['tests/support/server.ts', '--port', String(first)], {
		cwd: root,
		env: {},
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: true
	});
	let out = '';
	const closed = new Promise<number | null>((resolve) => child.on('close', (c) => resolve(c)));
	const stop = () => stopChild(child, closed, { group: true });
	running.add(stop);
	void closed.then(() => running.delete(stop));
	const port = await new Promise<number | null>((resolve) => {
		const timer = setTimeout(() => resolve(null), 20_000);
		child.stdout!.on('data', (chunk: Buffer) => {
			out += chunk.toString();
			const m = CLI_READY.exec(out);
			if (m) {
				clearTimeout(timer);
				resolve(Number(m.groups!['jade_e2e_port']));
			}
		});
		child.stderr!.on('data', (chunk: Buffer) => (out += chunk.toString()));
		void closed.then(() => {
			clearTimeout(timer);
			resolve(null);
		});
	});
	return { port, code: child.exitCode, out, stop };
}

// Every CLI still running, stopped in afterAll as well: a test that times out before its own
// stop() leaves no `node build` behind (B9).
const running = new Set<() => Promise<void>>();
afterAll(async () => {
	await Promise.all([...running].map((stop) => stop()));
});

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

	it('the server CLI retries a held first port and names the port it listens on (jade-r7c)', async () => {
		const cli = await runCli(held);
		try {
			expect(cli.port).not.toBeNull();
			expect(cli.port).not.toBe(held);
			expect(cli.out).toMatch(/"err_tag":"EADDRINUSE"/);
			expect((await fetch(`http://127.0.0.1:${cli.port}/healthz`)).status).toBe(200);
		} finally {
			await cli.stop();
		}
	}, 40_000);

	it('the server CLI names its first port when that port is free', async () => {
		const first = await freePort();
		const cli = await runCli(first);
		try {
			expect(cli.port).toBe(first);
		} finally {
			await cli.stop();
		}
	}, 40_000);

	it("Playwright's webServer waits for the CLI's own line, never for a URL or port (jade-r7c)", () => {
		const source = readFileSync(`${root}playwright.config.ts`, 'utf8');
		const webServer = source.slice(source.indexOf('webServer: {'));
		expect(webServer).toMatch(/wait: \{ stdout: CLI_READY \}/);
		expect(webServer).not.toMatch(/^\s*(url|port):/m);
		expect(webServer).not.toMatch(/--origin/);
	});

	it('isAddrInUse: stderr text, the JSON line, and nothing else', () => {
		expect(isAddrInUse('', 'Error: listen EADDRINUSE: address already in use')).toBe(true);
		expect(isAddrInUse('{"level":"error","msg":"error","err_tag":"EADDRINUSE"}\n', '')).toBe(true);
		expect(isAddrInUse('{"level":"error","msg":"error","err_tag":"EACCES"}\n', '')).toBe(false);
		expect(isAddrInUse('not json EADDRINUSE\n{broken', '')).toBe(false);
		expect(isAddrInUse('', '')).toBe(false);
	});
});

describe('stopping a server that ignores SIGTERM (B9)', () => {
	const alive = (pid: number) => {
		try {
			process.kill(pid, 0);
			return true;
		} catch {
			return false;
		}
	};
	const gone = async (pid: number) => {
		for (let i = 0; i < 40 && alive(pid); i++) await new Promise((r) => setTimeout(r, 50));
		return !alive(pid);
	};

	it('SIGKILLs the child and its own child after the grace period', async () => {
		// A parent and a child that both ignore SIGTERM, as a hung `node build` under the CLI would.
		const script = `
			const { spawn } = require('node:child_process');
			process.on('SIGTERM', () => {});
			const sub = spawn(process.execPath, ['-e', "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)"], { stdio: 'ignore' });
			process.stdout.write(String(sub.pid) + '\\n');
			setInterval(() => {}, 1000);
		`;
		const child = spawn(process.execPath, ['-e', script], {
			stdio: ['ignore', 'pipe', 'ignore'],
			detached: true
		});
		const closed = new Promise<void>((resolve) => child.once('close', () => resolve()));
		const sub = await new Promise<number>((resolve) =>
			child.stdout!.once('data', (chunk: Buffer) => resolve(Number(String(chunk).trim())))
		);
		expect(alive(child.pid!)).toBe(true);
		expect(alive(sub)).toBe(true);

		const started = Date.now();
		await stopChild(child, closed, { group: true, graceMs: 300 });
		expect(Date.now() - started).toBeLessThan(5_000);
		expect(await gone(child.pid!)).toBe(true);
		expect(await gone(sub)).toBe(true);
	}, 10_000);
});
