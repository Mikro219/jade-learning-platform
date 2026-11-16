// Helpers for the infra tests (plan section 11, PD11, PD13, PD14). Every stack they bring up has
// a Compose project of its own (`jade-infra-<run id>-<test>`), host ports from freePort() and an
// env file `pnpm env:init` writes into a temporary directory; it runs the run's app image
// (JADE_IMAGE) with `--no-build --pull never`, and its teardown is `down -v` on that project.
//
// Docker commands get an explicit, minimal environment, never a copy of process.env, so nothing
// from the developer's shell (COMPOSE_PROJECT_NAME, a stray APP_VERSION) reaches Compose. Their
// output is captured, never printed whole: `docker compose config` and `docker inspect` carry the
// generated secrets.
import { execFile } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { request as httpRequest, type IncomingHttpHeaders } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inject } from 'vitest';
import { STACK_COMPOSE_FILE, downArgs } from '../../tools/compose.ts';
import { freePort } from '../../tools/free-port.ts';

export const root = fileURLToPath(new URL('../../', import.meta.url));

/** What the infra global setup hands every test file (tests/infra/global-setup.ts). */
export interface InfraContext {
	/** The infra run's id: lower-case letters, digits and hyphens. */
	runId: string;
	/** The first 8 hex digits of the sha256 of the checkout's real path. */
	checkoutHash: string;
	/** The run's app image tag, jade-app:ci-<checkout hash>-<run id>, built by `pnpm ci:image`. */
	image: string;
	/** The buildx builder the run's image was built on. */
	builder: string;
}

declare module 'vitest' {
	export interface ProvidedContext {
		jadeInfra: InfraContext;
	}
}

export function infraContext(): InfraContext {
	return inject('jadeInfra');
}

/** The environment of a docker command: PATH, HOME and the Docker client's own variables. */
export function dockerEnv(extra: Record<string, string> = {}): Record<string, string> {
	const env: Record<string, string> = {};
	for (const name of ['PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG']) {
		const value = process.env[name];
		if (value !== undefined) env[name] = value;
	}
	return { ...env, ...extra };
}

export interface Result {
	code: number;
	stdout: string;
	stderr: string;
}

/** Run `command` with an explicit environment; never throws on a non-zero exit. */
export function exec(
	command: string,
	args: readonly string[],
	env: Record<string, string>,
	timeoutMs = 600_000
): Promise<Result> {
	return new Promise((resolve) => {
		execFile(
			command,
			args,
			{ cwd: root, env, maxBuffer: 64 * 1024 * 1024, timeout: timeoutMs },
			(err, stdout, stderr) => {
				const code = err ? (typeof err.code === 'number' ? err.code : 1) : 0;
				resolve({ code, stdout: String(stdout), stderr: String(stderr) });
			}
		);
	});
}

/** `docker <args>` with the minimal environment plus `extra`. */
export function docker(args: readonly string[], extra: Record<string, string> = {}) {
	return exec('docker', args, dockerEnv(extra));
}

/** `node tools/env-init.ts <args>` on the Node running the tests, with an empty environment. */
export function envInit(args: readonly string[]): Promise<Result> {
	return exec(process.execPath, [join(root, 'tools/env-init.ts'), ...args], {});
}

/** A temporary directory, removed by the returned function. */
export function tempDir(prefix: string): { dir: string; remove: () => void } {
	const dir = mkdtempSync(join(tmpdir(), `jade-infra-${prefix}-`));
	return { dir, remove: () => rmSync(dir, { recursive: true, force: true }) };
}

/** Poll `check` until it returns true or `timeoutMs` passes. */
export async function waitFor(
	check: () => Promise<boolean>,
	timeoutMs: number,
	intervalMs = 500
): Promise<boolean> {
	const deadline = Date.now() + timeoutMs;
	for (;;) {
		if (await check().catch(() => false)) return true;
		if (Date.now() > deadline) return false;
		await new Promise((r) => setTimeout(r, intervalMs));
	}
}

export interface HttpResponse {
	status: number;
	headers: IncomingHttpHeaders;
	body: string;
}

export interface RequestOptions {
	headers?: Record<string, string>;
	/** The CA that signs Caddy's certificate (its internal CA's root). */
	ca?: string;
	timeoutMs?: number;
}

/**
 * GET `https://localhost:<port><path>`, verifying Caddy's certificate against `ca`. The socket
 * goes to 127.0.0.1, the address freePort() checked, never to whatever `localhost` resolves to
 * first (a foreign listener on ::1 could answer there, PD11); SNI and Host say `localhost`.
 */
export function httpsGet(port: number, path: string, options: RequestOptions = {}) {
	return new Promise<HttpResponse>((resolve, reject) => {
		const req = httpsRequest(
			{
				host: '127.0.0.1',
				port,
				path,
				method: 'GET',
				servername: 'localhost',
				ca: options.ca,
				headers: { host: `localhost:${port}`, ...options.headers },
				timeout: options.timeoutMs ?? 15_000
			},
			(res) => collect(res, resolve, reject)
		);
		req.once('timeout', () => req.destroy(new Error('timeout')));
		req.once('error', reject);
		req.end();
	});
}

/** GET `http://127.0.0.1:<port><path>` with Host `localhost:<port>` (PD11, as httpsGet). */
export function httpGet(port: number, path: string, headers: Record<string, string> = {}) {
	return new Promise<HttpResponse>((resolve, reject) => {
		const req = httpRequest(
			{
				host: '127.0.0.1',
				port,
				path,
				method: 'GET',
				headers: { host: `localhost:${port}`, ...headers },
				timeout: 15_000
			},
			(res) => collect(res, resolve, reject)
		);
		req.once('timeout', () => req.destroy(new Error('timeout')));
		req.once('error', reject);
		req.end();
	});
}

function collect(
	res: import('node:http').IncomingMessage,
	resolve: (r: HttpResponse) => void,
	reject: (e: Error) => void
) {
	const chunks: Buffer[] = [];
	res.on('data', (chunk: Buffer) => chunks.push(chunk));
	res.once('error', reject);
	res.once('end', () =>
		resolve({
			status: res.statusCode ?? 0,
			headers: res.headers,
			body: Buffer.concat(chunks).toString('latin1')
		})
	);
}

/** Whether a failed `up` failed because a host port was taken in between (PD11). */
export function isPortTaken(output: string): boolean {
	return /port is already allocated|address already in use|ports are not available/i.test(output);
}

export interface Stack {
	project: string;
	envFile: string;
	dir: string;
	httpPort: number;
	httpsPort: number;
	/** Extra Compose files layered over compose.prod.yml (an override in a test). */
	files: string[];
	/** `docker compose -p <project> -f compose.prod.yml [-f ...] --env-file <file> <args>`. */
	compose: (args: readonly string[], extraFiles?: readonly string[]) => Promise<Result>;
	/** Caddy's internal CA root, read from the caddy container. */
	ca: () => Promise<string>;
	/** `down -v` on this project only, then the temporary directory is removed. */
	down: () => Promise<void>;
	/** Remove the temporary directory (the env file) only. */
	removeDir: () => void;
}

const MAX_ATTEMPTS = 3;

/**
 * Every `<test>` of a Compose project `jade-infra-<run id>-<test>` the infra run creates: the
 * stacks of the test files and the global setup's pull project. infraProject() takes only these,
 * and the global setup's sweep matches only these, so the two cannot drift apart.
 */
export const INFRA_PROJECT_SUFFIXES = [
	'pull',
	'config',
	'up',
	'caddylogs',
	'media',
	'stackup'
] as const;
export type InfraProjectSuffix = (typeof INFRA_PROJECT_SUFFIXES)[number];

/** The project name of a test's stack: jade-infra-<run id>-<test>. */
export function infraProject(test: InfraProjectSuffix, runId: string = infraContext().runId) {
	return `jade-infra-${runId}-${test}`;
}

/** The label and name of media.test.ts's throwaway Caddy container (`docker run`, no Compose). */
export const MEDIA_FILES_LABEL = 'jade-test=media';
export function mediaFilesContainer(runId: string = infraContext().runId): string {
	return `jade-infra-${runId}-mediafiles`;
}

/**
 * A Compose command on `project` with `envFile` (no `up` or `run` implied). JADE_IMAGE is the
 * run's tag: `image`, or the one the global setup provided (inside a test file).
 */
export function composeOn(
	project: string,
	envFile: string,
	args: readonly string[],
	extraFiles: readonly string[] = [],
	image: string = infraContext().image,
	timeoutMs?: number
): Promise<Result> {
	const files = [STACK_COMPOSE_FILE, ...extraFiles].flatMap((f) => ['-f', f]);
	return exec(
		'docker',
		['compose', '-p', project, ...files, '--env-file', envFile, ...args],
		dockerEnv({ JADE_IMAGE: image }),
		timeoutMs
	);
}

/** How long an infra `up --wait` waits for health, in seconds. */
export const INFRA_WAIT_TIMEOUT_SECONDS = 180;

/**
 * The limit on one `up` of a test's stack, in milliseconds: the wait plus a minute. One `up`,
 * plus the quick retries a port collision causes, stays inside the infra hookTimeout (15 min).
 */
export const UP_TIMEOUT_MS = (INFRA_WAIT_TIMEOUT_SECONDS + 60) * 1000;

/** The flags of every `up` of the run's stacks (D7): no build, no pull, wait for health. */
export const UP_FLAGS = [
	'up',
	'-d',
	'--wait',
	'--wait-timeout',
	String(INFRA_WAIT_TIMEOUT_SECONDS),
	'--no-build',
	'--pull',
	'never'
] as const;

/**
 * `docker compose -p <project> down -v`, by the exact project name only: no file and no env
 * file, so it also removes a stack whose `up` never returned (B1).
 */
export async function downProject(project: string): Promise<Result> {
	// An empty project directory: no compose.yaml or .env of this or a parent directory is read,
	// and dockerEnv() carries no COMPOSE_FILE.
	const { dir, remove } = tempDir('down');
	try {
		return await exec('docker', downArgs(project, dir, ['-v']), dockerEnv(), 120_000);
	} finally {
		remove();
	}
}

/**
 * A test file's teardown: `down -v` on `jade-infra-<run id>-<test>` whether or not startStack
 * returned, then the stack's temporary directory, if there is one.
 */
export async function stopStack(test: InfraProjectSuffix, stack: Stack | undefined): Promise<void> {
	await downProject(infraProject(test));
	stack?.removeDir();
}

/**
 * Bring up compose.prod.yml as `jade-infra-<run id>-<test>`, from an env file `pnpm env:init`
 * writes with host ports from freePort(); on a port taken in between, tear down and start again
 * with new ports, at most three times (PD11). `up` brings the stack up; by default it is
 * `up` with UP_FLAGS (the run's image, no build, no pull).
 */
export async function startStack(
	test: InfraProjectSuffix,
	up: (stack: Stack) => Promise<Result> = (stack) =>
		composeOn(stack.project, stack.envFile, UP_FLAGS, [], infraContext().image, UP_TIMEOUT_MS)
): Promise<Stack> {
	const project = infraProject(test);
	// Whatever an interrupted earlier attempt of this exact project left behind (B2).
	await downProject(project);
	let lastOutput = '';
	for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
		const { dir, remove } = tempDir(test);
		const envFile = join(dir, '.env');
		const httpPort = await freePort();
		let httpsPort = await freePort();
		while (httpsPort === httpPort) httpsPort = await freePort();
		const init = await envInit([
			'--out',
			envFile,
			'--http-port',
			String(httpPort),
			'--https-port',
			String(httpsPort)
		]);
		if (init.code !== 0) {
			remove();
			throw new Error(`env:init failed (exit ${init.code}): ${init.stderr}`);
		}
		const stack: Stack = {
			project,
			envFile,
			dir,
			httpPort,
			httpsPort,
			files: [],
			compose: (args, extraFiles = []) => composeOn(project, envFile, args, extraFiles),
			ca: async () => {
				const r = await composeOn(project, envFile, [
					'exec',
					'-T',
					'caddy',
					'cat',
					'/data/caddy/pki/authorities/local/root.crt'
				]);
				if (r.code !== 0) throw new Error(`could not read Caddy's root certificate: ${r.stderr}`);
				return r.stdout;
			},
			down: async () => {
				await downProject(project);
				remove();
			},
			removeDir: remove
		};
		const result = await up(stack);
		if (result.code === 0) return stack;
		lastOutput = `${result.stdout}\n${result.stderr}`;
		await stack.down();
		if (!isPortTaken(lastOutput)) break;
	}
	throw new Error(`up failed for ${project}:\n${lastOutput}`);
}

/** The IDs of every container of `project`, exited ones included. */
export async function projectContainers(project: string): Promise<string[]> {
	const r = await docker([
		'ps',
		'-a',
		'-q',
		'--no-trunc',
		'--filter',
		`label=com.docker.compose.project=${project}`
	]);
	return r.stdout.split('\n').filter(Boolean);
}

/** One field of `docker inspect` for a container, as JSON. */
export async function inspect<T>(container: string, template: string): Promise<T> {
	const r = await docker(['inspect', '--format', `{{json ${template}}}`, container]);
	if (r.code !== 0) throw new Error(`docker inspect failed: ${r.stderr}`);
	return JSON.parse(r.stdout) as T;
}

/** The container of `service` in `project` (the first, exited ones included). */
export async function serviceContainer(project: string, service: string): Promise<string> {
	const r = await docker([
		'ps',
		'-a',
		'-q',
		'--no-trunc',
		'--filter',
		`label=com.docker.compose.project=${project}`,
		'--filter',
		`label=com.docker.compose.service=${service}`
	]);
	const id = r.stdout.split('\n').find(Boolean);
	if (id === undefined) throw new Error(`no ${service} container in ${project}`);
	return id;
}

/** The value of `name` in a container's configured environment; nothing else is returned. */
export async function containerEnvValue(container: string, name: string) {
	const env = await inspect<string[]>(container, '.Config.Env');
	const entry = env.find((e) => e.startsWith(`${name}=`));
	return entry?.slice(name.length + 1);
}

/** The names of the migrations in the stack's ledger, read with psql in the db container. */
export async function ledger(stack: Stack, extraFiles: readonly string[] = []): Promise<string[]> {
	const r = await stack.compose(
		[
			'exec',
			'-T',
			'db',
			'psql',
			'-U',
			'jade_owner',
			'-d',
			'jade',
			'-Atc',
			'SELECT name FROM schema_migrations ORDER BY name'
		],
		extraFiles
	);
	if (r.code !== 0) throw new Error(`psql failed: ${r.stderr}`);
	return r.stdout.split('\n').filter(Boolean);
}
