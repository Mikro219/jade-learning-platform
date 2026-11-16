// Starts the built server (`node build`) for black-box checks (plan V8, PD9, PD11). The child
// runs on the Node running this file (process.execPath), with HOST=127.0.0.1, a PORT from
// freePort() and an explicit environment object: never a copy of process.env.
//
// Run directly (`node tests/support/server.ts --port <p>`), it serves the build in the foreground
// with the harness's `APP_ENV=test` values; Playwright's webServer uses this, waits for its
// CLI_READY line, and passes the URL of the run's e2e database (plan U7) as JADE_E2E_DATABASE_URL.
import { spawn, type ChildProcess } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { freePort } from '../../tools/free-port.ts';
import { testEnv, type ServerEnv } from './env.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const BUILD = fileURLToPath(new URL('../../build', import.meta.url));
const LISTENING = /Listening on /;
const MAX_ATTEMPTS = 3;

/** Chooses the port for one attempt. Tests can inject one to force a collision (PD11). */
export type PortChooser = () => Promise<number>;

/**
 * Whether a failed start was a port collision (PD11). The app's `uncaughtException` handler
 * writes the crash as a closed JSON error line on stdout (`"err_tag":"EADDRINUSE"`) and leaves
 * stderr empty; Node's own crash output (no handler yet) names it on stderr.
 */
export function isAddrInUse(stdout: string, stderr: string): boolean {
	if (/EADDRINUSE/.test(stderr)) return true;
	for (const line of stdout.split('\n')) {
		if (!line.startsWith('{')) continue;
		try {
			const parsed = JSON.parse(line) as { err_tag?: unknown } | null;
			if (parsed?.err_tag === 'EADDRINUSE') return true;
		} catch {
			// Not a log line.
		}
	}
	return false;
}

function exitReport(stdout: string, stderr: string): string {
	return `stdout:\n${stdout}\nstderr:\n${stderr}`;
}

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
export async function runServer(
	env: ServerEnv,
	timeoutMs = 5000,
	choosePort: PortChooser = freePort
): Promise<ServerRun> {
	for (let attempt = 1; ; attempt++) {
		const run = await runOnce(env, await choosePort(), timeoutMs);
		// The port was taken between freePort() and listen: retry, at most three times (PD11).
		if (run.code !== 0 && isAddrInUse(run.stdout, run.stderr) && attempt < MAX_ATTEMPTS) continue;
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

/**
 * Stop `child` (B9): SIGTERM, then SIGKILL if it has not closed within `graceMs`, so a server that
 * ignores SIGTERM cannot hang the caller and outlive the test. With `group`, `child` was spawned
 * `detached` and leads a process group of its own: both signals go to the whole group, and once
 * the leader has closed the group gets a SIGKILL as well, so a child of `child` (the server CLI's
 * `node build`) is never left behind. Resolves once `closed` (the child's 'close') has.
 */
export async function stopChild(
	child: ChildProcess,
	closed: Promise<unknown>,
	{ graceMs = 3_000, group = false }: { graceMs?: number; group?: boolean } = {}
): Promise<void> {
	const send = (signal: NodeJS.Signals) => {
		try {
			if (group && child.pid !== undefined) process.kill(-child.pid, signal);
			else child.kill(signal);
		} catch {
			// Already gone.
		}
	};
	if (group || (child.exitCode === null && child.signalCode === null)) send('SIGTERM');
	let timer: ReturnType<typeof setTimeout> | undefined;
	const graceful = await Promise.race([
		closed.then(() => true),
		new Promise<boolean>((resolve) => (timer = setTimeout(() => resolve(false), graceMs)))
	]);
	clearTimeout(timer);
	if (!graceful) send('SIGKILL');
	await closed;
	if (group) send('SIGKILL');
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
export async function startServer(
	env: ServerEnv,
	timeoutMs = 10_000,
	choosePort: PortChooser = freePort
): Promise<StartedServer> {
	for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
		const port = await choosePort();
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
				stop: () => stopChild(child, closed)
			};
		}
		if (outcome === 'timeout') {
			child.kill('SIGKILL');
			await closed;
			throw new Error(`node build did not listen within ${timeoutMs} ms`);
		}
		if (isAddrInUse(stdout, stderr) && attempt < MAX_ATTEMPTS) continue;
		throw new Error(
			`node build exited before listening (code ${child.exitCode}):\n${exitReport(stdout, stderr)}`
		);
	}
	throw new Error('node build could not get a free port in three attempts');
}

function flag(argv: readonly string[], name: string): string | undefined {
	const i = argv.indexOf(name);
	return i === -1 ? undefined : argv[i + 1];
}

/**
 * The line the CLI prints, once, when its own child listens (jade-r7c). Playwright's webServer
 * waits for exactly this line (`wait.stdout`), never for a URL or a port to answer, so a process
 * that took the port during the build can never be mistaken for the server under test. The named
 * group puts the port the child actually listens on into JADE_E2E_PORT for Playwright's workers.
 */
export const CLI_READY = /^e2e server: listening on port (?<jade_e2e_port>\d+)$/m;

export function cliReadyLine(port: number): string {
	return `e2e server: listening on port ${port}\n`;
}

/**
 * The CLI (`node tests/support/server.ts --port <port>`): serve the build in the foreground with
 * the harness's APP_ENV=test values, the e2e database's URL from JADE_E2E_DATABASE_URL, and ORIGIN
 * built from the port the child listens on. `--port` is the first attempt's port; a start that
 * collides with another process (EADDRINUSE) is retried on a port from freePort(), at most three
 * attempts in all (PD11). The child's output is passed through; CLI_READY is printed when it
 * listens. Exits with the child's code.
 */
async function cli(argv: readonly string[]): Promise<number> {
	const first = Number(flag(argv, '--port'));
	if (!Number.isInteger(first) || first < 1 || first > 65535) {
		process.stderr.write('usage: server.ts --port <port>\n');
		return 2;
	}
	const env = await testEnv();
	const databaseUrl = process.env['JADE_E2E_DATABASE_URL'];
	if (databaseUrl) env['DATABASE_URL'] = databaseUrl;

	for (let attempt = 1; ; attempt++) {
		const port = attempt === 1 ? first : await freePort();
		const child = spawn(process.execPath, [BUILD], {
			cwd: root,
			env: { ...env, HOST: '127.0.0.1', PORT: String(port), ORIGIN: `http://127.0.0.1:${port}` },
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const forward = (signal: NodeJS.Signals) => child.kill(signal);
		process.on('SIGINT', forward);
		process.on('SIGTERM', forward);
		let stdout = '';
		let stderr = '';
		let listened = false;
		child.stdout!.on('data', (chunk: Buffer) => {
			process.stdout.write(chunk);
			stdout += chunk.toString();
			if (!listened && LISTENING.test(stdout)) {
				listened = true;
				process.stdout.write(cliReadyLine(port));
			}
		});
		child.stderr!.on('data', (chunk: Buffer) => {
			process.stderr.write(chunk);
			stderr += chunk.toString();
		});
		const code = await new Promise<number>((resolve) =>
			child.on('close', (c, signal) => resolve(c ?? (signal ? 1 : 0)))
		);
		process.off('SIGINT', forward);
		process.off('SIGTERM', forward);
		if (!listened && code !== 0 && isAddrInUse(stdout, stderr) && attempt < MAX_ATTEMPTS) {
			process.stderr.write(`e2e server: port ${port} is in use; retrying on a new port\n`);
			continue;
		}
		if (!listened && isAddrInUse(stdout, stderr)) {
			process.stderr.write(`e2e server: no free port in ${MAX_ATTEMPTS} attempts\n`);
		}
		return code;
	}
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await cli(process.argv.slice(2));
}
