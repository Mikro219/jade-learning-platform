// Starts the built server (`node build`) for black-box checks (plan V8, PD9, PD11). The child
// runs on the Node running this file (process.execPath), with HOST=127.0.0.1, a PORT from
// freePort() and an explicit environment object: never a copy of process.env.
//
// Run directly (`node tests/support/server.ts --port <p> --origin <url>`), it serves the build in
// the foreground with the harness's `APP_ENV=test` values; Playwright's webServer uses this, and
// passes the URL of the run's e2e database (plan U7) as JADE_E2E_DATABASE_URL.
import { spawn, type ChildProcess } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { freePort } from '../../tools/free-port.ts';
import { testEnv, type ServerEnv } from './env.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const BUILD = fileURLToPath(new URL('../../build', import.meta.url));
const LISTENING = /Listening on /;
const MAX_ATTEMPTS = 3;

function spawnBuild(env: ServerEnv, port: number): ChildProcess {
	return spawn(process.execPath, [BUILD], {
		cwd: root,
		env: { ...env, HOST: '127.0.0.1', PORT: String(port) },
		stdio: ['ignore', 'pipe', 'pipe']
	});
}

export interface ServerRun {
	/** The exit code, or null when the process was stopped by this harness or a signal. */
	code: number | null;
	stdout: string;
	stderr: string;
	/** Whether the adapter's start-up line was printed. */
	listened: boolean;
	/** Whether the run neither exited nor listened within the time limit. */
	timedOut: boolean;
	elapsedMs: number;
}

/**
 * Run `node build` until it exits, listens, or `timeoutMs` passes, whichever comes first; a
 * server that listens or hangs is stopped. For checks of what happens before listen.
 */
export async function runServer(env: ServerEnv, timeoutMs = 5000): Promise<ServerRun> {
	for (let attempt = 1; ; attempt++) {
		const run = await runOnce(env, await freePort(), timeoutMs);
		// The port was taken between freePort() and listen: retry, at most three times (PD11).
		if (run.code !== 0 && /EADDRINUSE/.test(run.stderr) && attempt < MAX_ATTEMPTS) continue;
		return run;
	}
}

function runOnce(env: ServerEnv, port: number, timeoutMs: number): Promise<ServerRun> {
	const started = Date.now();
	const child = spawnBuild(env, port);
	let stdout = '';
	let stderr = '';
	return new Promise((resolve) => {
		let listened = false;
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			child.kill('SIGKILL');
		}, timeoutMs);
		child.stdout!.on('data', (chunk: Buffer) => {
			stdout += chunk.toString();
			if (!listened && LISTENING.test(stdout)) {
				listened = true;
				child.kill('SIGTERM');
			}
		});
		child.stderr!.on('data', (chunk: Buffer) => (stderr += chunk.toString()));
		child.on('close', (code) => {
			clearTimeout(timer);
			resolve({
				code: listened || timedOut ? null : code,
				stdout,
				stderr,
				listened,
				timedOut,
				elapsedMs: Date.now() - started
			});
		});
	});
}

export interface StartedServer {
	url: string;
	stdout(): string;
	stderr(): string;
	stop(): Promise<void>;
}

/**
 * Start `node build` and wait until it listens. A start that fails because the port was taken in
 * between is retried with a new port, at most three times (PD11, RR13).
 */
export async function startServer(env: ServerEnv, timeoutMs = 10_000): Promise<StartedServer> {
	for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
		const port = await freePort();
		const child = spawnBuild(env, port);
		let stdout = '';
		let stderr = '';
		child.stdout!.on('data', (chunk: Buffer) => (stdout += chunk.toString()));
		child.stderr!.on('data', (chunk: Buffer) => (stderr += chunk.toString()));
		const closed = new Promise<void>((resolve) => child.once('close', () => resolve()));
		const outcome = await new Promise<'listening' | 'exited' | 'timeout'>((resolve) => {
			const timer = setTimeout(() => resolve('timeout'), timeoutMs);
			const onData = () => {
				if (LISTENING.test(stdout)) {
					clearTimeout(timer);
					resolve('listening');
				}
			};
			child.stdout!.on('data', onData);
			child.once('close', () => {
				clearTimeout(timer);
				resolve('exited');
			});
		});
		if (outcome === 'listening') {
			return {
				url: `http://127.0.0.1:${port}`,
				stdout: () => stdout,
				stderr: () => stderr,
				stop: async () => {
					if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
					await closed;
				}
			};
		}
		if (outcome === 'timeout') {
			child.kill('SIGKILL');
			await closed;
			throw new Error(`node build did not listen within ${timeoutMs} ms`);
		}
		if (/EADDRINUSE/.test(stderr) && attempt < MAX_ATTEMPTS) continue;
		throw new Error(`node build exited before listening (code ${child.exitCode}):\n${stderr}`);
	}
	throw new Error('node build could not get a free port in three attempts');
}

function flag(argv: readonly string[], name: string): string | undefined {
	const i = argv.indexOf(name);
	return i === -1 ? undefined : argv[i + 1];
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const argv = process.argv.slice(2);
	const port = flag(argv, '--port');
	const origin = flag(argv, '--origin');
	if (!port || !origin) {
		process.stderr.write('usage: server.ts --port <port> --origin <url>\n');
		process.exit(2);
	}
	const env = await testEnv();
	const databaseUrl = process.env['JADE_E2E_DATABASE_URL'];
	if (databaseUrl) env['DATABASE_URL'] = databaseUrl;
	const child = spawn(process.execPath, [BUILD], {
		cwd: root,
		env: { ...env, HOST: '127.0.0.1', PORT: port, ORIGIN: origin },
		stdio: 'inherit'
	});
	for (const signal of ['SIGINT', 'SIGTERM'] as const) {
		process.on(signal, () => child.kill(signal));
	}
	child.on('close', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
}
