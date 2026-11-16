// Docker Compose for this checkout, always with an explicit project name (-p), never Compose's
// own fallbacks (plan U1, PD13, D2, D7).
//
// The development database (`pnpm db:up`, `pnpm db:down`), compose.dev.yml, service devdb:
//   - project: the exported COMPOSE_PROJECT_NAME when there is one (the bugfix gates, the clean
//     clone), otherwise `jade-dev-<checkout hash>`, so two checkouts never share a database;
//   - `up` waits for the health check (`up -d --wait devdb`); `down` keeps the volume.
//
// The local production stack (`pnpm stack:up`, `pnpm stack:down`), compose.prod.yml:
//   - project: `jade-stack-<checkout hash>`, whatever COMPOSE_PROJECT_NAME says (a gate's project
//     never receives this stack);
//   - image: JADE_IMAGE=jade-app:local-<checkout hash>, built by Compose from the `build:` stanza
//     of `app` (`up -d --wait --wait-timeout 300 --build`); interpolation variables from the
//     checkout's `.env`;
//   - `down` names the project only (no file, no env file, an empty project directory, no
//     COMPOSE_FILE), so it works without a valid `.env` and reads no other Compose file, and keeps
//     the volumes.
//
// `with-stack-env <command...>` runs a command (`pnpm ci:image`: docker buildx bake) with the
// variables compose.prod.yml interpolates taken from a throwaway env file that env:init writes,
// so the file can be loaded without a real `.env`; only APP_VERSION reaches the build. It refuses
// to run without JADE_IMAGE, so `pnpm ci:image` never builds (and retags) the shared
// jade-app:local; it is always asked for the tag it builds.
//
// JADE_CI_IMAGE_CACHE (imageCacheArgs): unset or empty, no cache flags; `gha`, the two flags of
// the CI `image` job (plan X2, D7), which the infra global setup appends to `pnpm ci:image`;
// any other value is refused.
//
// <checkout hash> is the first 8 hex digits of the sha256 of the checkout's real path.
//
//   node tools/compose.ts up|down|stack-up|stack-down
//   node tools/compose.ts with-stack-env <command> [args...]
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';
import { main as envInit } from './env-init.ts';
import { loadEnv } from './load-env.ts';

type Env = Readonly<Record<string, string | undefined>>;

const root = fileURLToPath(new URL('../', import.meta.url));

/** The development database's Compose file. */
export const DEV_COMPOSE_FILE = join(root, 'compose.dev.yml');

/** The production stack's Compose file. */
export const STACK_COMPOSE_FILE = join(root, 'compose.prod.yml');

/** The checkout's own env file, which `pnpm stack:up` interpolates from. */
export const CHECKOUT_ENV_FILE = join(root, '.env');

/** The first 8 hex digits of the sha256 of the checkout's real path. */
export function checkoutHash(checkout: string = root): string {
	return createHash('sha256').update(realpathSync(checkout)).digest('hex').slice(0, 8);
}

/** The Compose project of this checkout's development database. */
export function devProjectName(env: Env = process.env) {
	const exported = env['COMPOSE_PROJECT_NAME'];
	if (exported !== undefined && exported !== '') return exported;
	return `jade-dev-${checkoutHash()}`;
}

/** The Compose project of this checkout's local production stack. Never the exported one. */
export function stackProjectName(): string {
	return `jade-stack-${checkoutHash()}`;
}

/** The app image tag `pnpm stack:up` builds: used by this checkout only (D7). */
export function localStackImage(): string {
	return `jade-app:local-${checkoutHash()}`;
}

/** The `docker` arguments for `up` or `down` of the development database. */
export function composeArgs(command: 'up' | 'down', project: string): string[] {
	const base = ['compose', '-p', project, '-f', DEV_COMPOSE_FILE];
	return command === 'up' ? [...base, 'up', '-d', '--wait', 'devdb'] : [...base, 'down'];
}

/** How long `up --wait` waits for the stack's health checks, in seconds (not the build). */
export const STACK_WAIT_TIMEOUT_SECONDS = 300;

/**
 * The `docker` arguments for `up` of the stack: build, then wait for health, at most
 * STACK_WAIT_TIMEOUT_SECONDS.
 */
export function stackUpArgs(project: string, envFile: string): string[] {
	return [
		'compose',
		'-p',
		project,
		'-f',
		STACK_COMPOSE_FILE,
		'--env-file',
		envFile,
		'up',
		'-d',
		'--wait',
		'--wait-timeout',
		String(STACK_WAIT_TIMEOUT_SECONDS),
		'--build'
	];
}

/**
 * The `docker` arguments for a `down` by project name only: no Compose file and no env file, and
 * an empty project directory, so no compose.yaml or .env of the current or a parent directory is
 * read. `extra` is `['-v']` to remove the volumes too.
 */
export function downArgs(project: string, projectDir: string, extra: readonly string[] = []) {
	return ['compose', '-p', project, '--project-directory', projectDir, 'down', ...extra];
}

/**
 * The environment of a docker command that must read no Compose configuration of the caller's:
 * PATH, HOME and the Docker client's own variables only (no COMPOSE_FILE, COMPOSE_PATH_SEPARATOR
 * or COMPOSE_PROJECT_NAME).
 */
export function minimalDockerEnv(env: Env = process.env): Record<string, string> {
	const out: Record<string, string> = {};
	for (const name of ['PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG']) {
		const value = env[name];
		if (value !== undefined) out[name] = value;
	}
	return out;
}

/** The variable that selects the CI image cache (plan X2). */
export const IMAGE_CACHE_VARIABLE = 'JADE_CI_IMAGE_CACHE';

/** Thrown for a JADE_CI_IMAGE_CACHE value other than unset, empty or `gha`; names no value. */
export class ImageCacheError extends Error {
	constructor() {
		super(`${IMAGE_CACHE_VARIABLE} must be unset, empty or gha`);
	}
}

/**
 * The extra `pnpm ci:image` arguments JADE_CI_IMAGE_CACHE selects: none when it is unset or
 * empty; for `gha`, exactly the GitHub Actions cache flags of the CI `image` job (X2).
 */
export function imageCacheArgs(env: Env): string[] {
	const value = env[IMAGE_CACHE_VARIABLE];
	if (value === undefined || value === '') return [];
	if (value === 'gha') {
		return ['--set', 'app.cache-from=type=gha', '--set', 'app.cache-to=type=gha,mode=max'];
	}
	throw new ImageCacheError();
}

export interface RunResult {
	/** The exit status; 1 when the command could not run, 124 when it was stopped by the timeout. */
	code: number;
	/** stdout and stderr together (also written to this process's own unless `quiet`). */
	output: string;
}

export interface RunOptions {
	/** Kill the command's whole process group after this many milliseconds. */
	timeoutMs?: number;
	/** Capture the output without writing it to this process's own. */
	quiet?: boolean;
	/**
	 * Start the command in a process group of its own (default true). False keeps it in the
	 * caller's group: for a run() nested inside another run() (with-stack-env under `pnpm
	 * ci:image` under the infra global setup), so the outer group's signals reach the innermost
	 * process (`docker buildx bake`) and the outer wait for its group covers it; from a terminal,
	 * Ctrl-C then reaches the command directly.
	 */
	newGroup?: boolean;
}

/** Signal every process of the group `pgid`; whether one was there to signal. */
function signalGroup(pgid: number, signal: NodeJS.Signals | 0): boolean {
	try {
		process.kill(-pgid, signal);
		return true;
	} catch {
		return false;
	}
}

/** Wait until no process of the group `pgid` is left, at most `ms`. */
async function groupGone(pgid: number, ms: number): Promise<boolean> {
	const deadline = Date.now() + ms;
	while (signalGroup(pgid, 0)) {
		if (Date.now() > deadline) return false;
		await new Promise((r) => setTimeout(r, 100));
	}
	return true;
}

/**
 * Run `command` with `args`, stdin closed, by default in a process group of its own (see
 * RunOptions.newGroup). A timeout, or a SIGINT or SIGTERM this process receives meanwhile, is
 * passed on: to the whole group (`docker buildx bake` under pnpm under node included) or, with
 * newGroup false, to the child (its own group, the caller's, gets the caller's signals anyway):
 * SIGTERM, then SIGKILL after 10 s. After a timeout or a signal the result waits until the group is
 * gone (at most 15 s more). On the child's exit, its output is read to the end (the pipes close),
 * for at most 2 s, so trailing output is kept and a grandchild holding the pipes cannot stall the
 * result. A timeout gives code 124; a forwarded signal ends this process with 130 (SIGINT) or 143
 * (SIGTERM) once the command is gone.
 */
export function run(
	command: string,
	args: readonly string[],
	env: Env,
	options: RunOptions = {}
): Promise<RunResult> {
	const newGroup = options.newGroup ?? true;
	return new Promise((resolve) => {
		const child = spawn(command, args, {
			cwd: root,
			env,
			detached: newGroup,
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const pid = child.pid;
		let output = '';
		let timedOut = false;
		let received: NodeJS.Signals | undefined;
		let killTimer: NodeJS.Timeout | undefined;
		const signal = (sig: NodeJS.Signals) => {
			if (pid === undefined) return;
			if (newGroup) signalGroup(pid, sig);
			else child.kill(sig);
		};
		const stop = () => {
			signal('SIGTERM');
			killTimer ??= setTimeout(() => signal('SIGKILL'), 10_000);
		};
		const timer =
			options.timeoutMs === undefined
				? undefined
				: setTimeout(() => {
						timedOut = true;
						stop();
					}, options.timeoutMs);
		const onSignal = (sig: NodeJS.Signals) => {
			received = sig;
			stop();
		};
		process.on('SIGINT', onSignal);
		process.on('SIGTERM', onSignal);
		const closed = (stream: NodeJS.ReadableStream) =>
			new Promise<void>((done) => stream.once('close', () => done()));
		const streamsClosed = Promise.all([closed(child.stdout), closed(child.stderr)]);
		child.stdout.on('data', (d: Buffer) => {
			output += d.toString();
			if (!options.quiet) process.stdout.write(d);
		});
		child.stderr.on('data', (d: Buffer) => {
			output += d.toString();
			if (!options.quiet) process.stderr.write(d);
		});
		let finished = false;
		const finish = async (code: number) => {
			if (finished) return;
			finished = true;
			clearTimeout(timer);
			// Read the output to its end, unless a grandchild keeps the pipes open past 2 s.
			let wait: NodeJS.Timeout | undefined;
			await Promise.race([
				streamsClosed,
				new Promise<void>((done) => (wait = setTimeout(done, 2000)))
			]);
			clearTimeout(wait);
			child.stdout.destroy();
			child.stderr.destroy();
			if ((timedOut || received) && newGroup && pid !== undefined) {
				if (!(await groupGone(pid, 15_000))) signalGroup(pid, 'SIGKILL');
			}
			clearTimeout(killTimer);
			process.off('SIGINT', onSignal);
			process.off('SIGTERM', onSignal);
			if (received) process.exit(received === 'SIGINT' ? 130 : 143);
			resolve(timedOut ? { code: 124, output: `${output}\ntimed out` } : { code, output });
		};
		child.once('error', () => void finish(1));
		child.once('exit', (code) => void finish(code ?? 1));
	});
}

export interface StackOptions {
	/** The Compose project; `pnpm stack:up` uses stackProjectName(). */
	project: string;
	/** The env file Compose interpolates from; `pnpm stack:up` uses the checkout's `.env`. */
	envFile: string;
	/** The app image tag (JADE_IMAGE); `pnpm stack:up` uses localStackImage(). */
	image: string;
	/** The environment of the Compose command (BUILDX_BUILDER and APP_VERSION pass through). */
	env: Env;
	/** A limit on the whole command (build included), in milliseconds; none by default. */
	timeoutMs?: number;
}

/** The environment of a stack command: `env` with JADE_IMAGE set and no exported project. */
function stackEnv(options: StackOptions): Record<string, string | undefined> {
	const env: Record<string, string | undefined> = { ...options.env, JADE_IMAGE: options.image };
	delete env['COMPOSE_PROJECT_NAME'];
	return env;
}

/** What `pnpm stack:up` runs: build the app image from compose.prod.yml, migrate, serve. */
export function stackUp(options: StackOptions): Promise<RunResult> {
	return run('docker', stackUpArgs(options.project, options.envFile), stackEnv(options), {
		timeoutMs: options.timeoutMs
	});
}

/** What `pnpm stack:down` runs: stop and remove the project's containers; keep its volumes. */
export async function stackDown(project: string, env: Env = process.env): Promise<RunResult> {
	const dir = mkdtempSync(join(tmpdir(), 'jade-stack-down-'));
	// run() ends the process on a forwarded signal; the empty directory goes with it.
	const cleanup = () => rmSync(dir, { recursive: true, force: true });
	process.once('exit', cleanup);
	try {
		return await run('docker', downArgs(project, dir), minimalDockerEnv(env));
	} finally {
		process.off('exit', cleanup);
		cleanup();
	}
}

/** `docker compose config --format json`, parsed: the services and their resolved images. */
export interface ComposeConfig {
	services: Record<string, { image?: string }>;
}

/**
 * The services whose image is not the app image (D7): the third-party images a stack pulls
 * explicitly before an `up` or `run` with `--pull never`. Today `db` and `caddy`.
 */
export function thirdPartyServices(config: ComposeConfig, appImage: string): string[] {
	return Object.entries(config.services)
		.filter(([, service]) => service.image !== appImage)
		.map(([name]) => name)
		.sort();
}

/**
 * The variables compose.prod.yml interpolates, from a throwaway env file written by env:init
 * (profile stack) into a temporary directory that is removed again. Values never printed.
 */
export async function throwawayStackEnv(): Promise<Record<string, string>> {
	const dir = mkdtempSync(join(tmpdir(), 'jade-stack-env-'));
	try {
		const file = join(dir, '.env');
		const status = await envInit([
			'--profile',
			'stack',
			'--app-env',
			'production',
			'--site',
			'localhost',
			'--out',
			file
		]);
		if (status !== 0) throw new Error('with-stack-env: env:init failed');
		return parseEnv(readFileSync(file, 'utf8')) as Record<string, string>;
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}

async function withStackEnv(argv: readonly string[]): Promise<number> {
	const [command, ...args] = argv;
	if (command === undefined) {
		process.stderr.write('usage: compose.ts with-stack-env <command> [args...]\n');
		return 2;
	}
	const image = process.env['JADE_IMAGE'];
	if (image === undefined || image === '') {
		// Never fall back to the shared jade-app:local of the bare README command (PD14).
		process.stderr.write(
			'with-stack-env: JADE_IMAGE must name the tag to build; nothing was built\n'
		);
		return 2;
	}
	const stackVars = await throwawayStackEnv();
	// The caller's JADE_IMAGE, APP_VERSION and BUILDX_BUILDER pass through; the throwaway file
	// supplies only what the caller has not set.
	// newGroup false: the command (`docker buildx bake`) stays in this process's group, which is
	// its caller's (the infra global setup's build group, or the terminal's), so a timeout or
	// Ctrl-C there reaches it too, and a wait for that group covers it.
	return (await run(command, args, { ...stackVars, ...process.env }, { newGroup: false })).code;
}

async function stackCommand(command: 'up' | 'down'): Promise<number> {
	const name = `stack:${command}`;
	if (command === 'up' && !existsSync(CHECKOUT_ENV_FILE)) {
		process.stderr.write(`${name}: no .env in this checkout; run \`pnpm env:init\` first\n`);
		return 1;
	}
	const exported = process.env['COMPOSE_PROJECT_NAME'];
	if (exported !== undefined && exported !== '') {
		process.stderr.write(
			`${name}: ignoring the exported COMPOSE_PROJECT_NAME; the stack's project is its own\n`
		);
	}
	const options: StackOptions = {
		project: stackProjectName(),
		envFile: CHECKOUT_ENV_FILE,
		image: localStackImage(),
		env: process.env
	};
	process.stdout.write(`${name}: Compose project ${options.project}, app image ${options.image}\n`);
	const { code: status } = await (command === 'up'
		? stackUp(options)
		: stackDown(options.project, process.env));
	if (command === 'down' && status === 0) {
		process.stdout.write(
			`${name}: volumes kept; after the passwords in .env change, \`docker compose -p ${options.project} down -v\` (destroys the stack's data) is needed\n`
		);
	}
	if (status === 0 && command === 'up') {
		// JADE_ORIGIN is not a secret; nothing else from the file is printed.
		const origin = (parseEnv(readFileSync(CHECKOUT_ENV_FILE, 'utf8')) as Record<string, string>)[
			'JADE_ORIGIN'
		];
		if (origin) process.stdout.write(`${name}: serving ${origin}\n`);
	}
	return status;
}

export async function main(argv: readonly string[]): Promise<number> {
	const command = argv[0];
	switch (command) {
		case 'up':
		case 'down': {
			// compose.dev.yml interpolates JADE_OWNER_DB_PASSWORD and JADE_DEV_DB_PORT from `.env`.
			loadEnv();
			const project = devProjectName();
			process.stdout.write(`db:${command}: Compose project ${project}, service devdb\n`);
			const result = spawnSync('docker', composeArgs(command, project), {
				cwd: root,
				env: process.env,
				stdio: 'inherit'
			});
			if (result.error) {
				process.stderr.write(`db:${command}: could not run docker\n`);
				return 1;
			}
			return result.status ?? 1;
		}
		case 'stack-up':
			return stackCommand('up');
		case 'stack-down':
			return stackCommand('down');
		case 'with-stack-env':
			return withStackEnv(argv.slice(1));
		default:
			process.stderr.write(
				'usage: compose.ts up|down|stack-up|stack-down|with-stack-env <command...>\n'
			);
			return 2;
	}
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main(process.argv.slice(2));
}
