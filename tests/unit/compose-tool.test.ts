// tools/compose.ts (plan D2, D7, X2): the stack's `up` and `down` arguments, the CI image cache
// flags JADE_CI_IMAGE_CACHE selects, and `with-stack-env` refusing to build without JADE_IMAGE.
// No Docker is needed: nothing here starts a container.
import { execFile } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { describe, expect, it } from 'vitest';
import {
	ImageCacheError,
	STACK_COMPOSE_FILE,
	STACK_WAIT_TIMEOUT_SECONDS,
	downArgs,
	imageCacheArgs,
	minimalDockerEnv,
	run as runTool,
	stackUpArgs
} from '../../tools/compose.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const run = promisify(execFile);

describe('imageCacheArgs (JADE_CI_IMAGE_CACHE)', () => {
	it('unset or empty: no flags', () => {
		expect(imageCacheArgs({})).toEqual([]);
		expect(imageCacheArgs({ JADE_CI_IMAGE_CACHE: '' })).toEqual([]);
	});

	it('gha: exactly the two GitHub Actions cache flags of the CI image job', () => {
		expect(imageCacheArgs({ JADE_CI_IMAGE_CACHE: 'gha' })).toEqual([
			'--set',
			'app.cache-from=type=gha',
			'--set',
			'app.cache-to=type=gha,mode=max'
		]);
	});

	it.each(['GHA', 'registry', 'gha,mode=max', ' gha', 'type=gha'])(
		'%j is refused, and the message names no value',
		(value) => {
			expect(() => imageCacheArgs({ JADE_CI_IMAGE_CACHE: value })).toThrow(ImageCacheError);
			expect(() => imageCacheArgs({ JADE_CI_IMAGE_CACHE: value })).toThrow(
				'JADE_CI_IMAGE_CACHE must be unset, empty or gha'
			);
		}
	);
});

describe('stack arguments', () => {
	it('up builds, waits for health with a timeout, from the given env file', () => {
		expect(stackUpArgs('jade-stack-x', '/tmp/x/.env')).toEqual([
			'compose',
			'-p',
			'jade-stack-x',
			'-f',
			STACK_COMPOSE_FILE,
			'--env-file',
			'/tmp/x/.env',
			'up',
			'-d',
			'--wait',
			'--wait-timeout',
			String(STACK_WAIT_TIMEOUT_SECONDS),
			'--build'
		]);
	});

	it('down names the project only: no file, no env file, an empty project directory', () => {
		expect(downArgs('jade-stack-x', '/tmp/empty')).toEqual([
			'compose',
			'-p',
			'jade-stack-x',
			'--project-directory',
			'/tmp/empty',
			'down'
		]);
		expect(downArgs('p', '/tmp/empty', ['-v']).slice(-2)).toEqual(['down', '-v']);
	});

	it("down's environment carries no Compose configuration of the caller's", () => {
		const env = minimalDockerEnv({
			PATH: '/bin',
			HOME: '/home/x',
			DOCKER_HOST: 'unix:///x.sock',
			COMPOSE_FILE: '/elsewhere/compose.yaml',
			COMPOSE_PATH_SEPARATOR: ':',
			COMPOSE_PROJECT_NAME: 'gate',
			APP_VERSION: 'x'
		});
		expect(env).toEqual({ PATH: '/bin', HOME: '/home/x', DOCKER_HOST: 'unix:///x.sock' });
	});
});

describe('run (process groups, B-M1)', () => {
	it('a timeout kills the whole group, grandchildren included, and returns 124 promptly', async () => {
		const started = Date.now();
		// The shell prints its background child's pid, then waits; both must die.
		const result = await runTool(
			'sh',
			['-c', 'sleep 30 & echo "bg=$!"; sleep 30'],
			{ PATH: process.env['PATH'] ?? '' },
			{
				timeoutMs: 500,
				quiet: true
			}
		);
		expect(result.code).toBe(124);
		expect(Date.now() - started).toBeLessThan(15_000);
		const bg = Number(/bg=(\d+)/.exec(result.output)?.[1]);
		expect(bg).toBeGreaterThan(0);
		// Gone, or at most a zombie waiting for init to reap it.
		const state = existsSync(`/proc/${bg}/stat`)
			? readFileSync(`/proc/${bg}/stat`, 'utf8').split(') ')[1]?.[0]
			: undefined;
		expect([undefined, 'Z']).toContain(state);
	}, 30_000);

	it('nested: an outer timeout also kills what with-stack-env started (newGroup false)', async () => {
		// The shape of the infra build: run() (own group) -> node tools/compose.ts with-stack-env
		// -> run(newGroup: false) -> the command. The innermost shell and its background child
		// stay in the outer group, so the outer timeout and its wait for the group cover them.
		const started = Date.now();
		const result = await runTool(
			process.execPath,
			[
				join(root, 'tools/compose.ts'),
				'with-stack-env',
				'sh',
				'-c',
				// SIGTERM is ignored (and inherited ignored by the background sleep), so only the
				// outer group's SIGKILL, 10 s after the timeout, ends them: in a group of their own
				// they would outlive the inner node, which that SIGKILL ends first.
				'trap "" TERM; sleep 60 & echo "bg=$! pg=$(cut -d" " -f5 /proc/$$/stat) ppid=$PPID"; sleep 60'
			],
			{ PATH: process.env['PATH'] ?? '', JADE_IMAGE: 'jade-app:never-built-by-this-test' },
			{ timeoutMs: 3000, quiet: true }
		);
		expect(result.code).toBe(124);
		expect(Date.now() - started).toBeLessThan(30_000);
		const bg = Number(/bg=(\d+)/.exec(result.output)?.[1]);
		expect(bg).toBeGreaterThan(0);
		const stat = existsSync(`/proc/${bg}/stat`)
			? readFileSync(`/proc/${bg}/stat`, 'utf8').split(') ')[1]
			: undefined;
		const state = stat?.[0];
		const pg = Number(/pg=(\d+)/.exec(result.output)?.[1]);
		const ppid = Number(/ppid=(\d+)/.exec(result.output)?.[1]);
		if (stat !== undefined && state !== 'Z') {
			// A failing run must not leave its sleeps behind: kill their process group, but only
			// if the pid still is this test's `sleep 60` (not a reused pid) and the group is one
			// this test created, never vitest's own.
			const pgid = Number(stat.split(' ')[2]);
			const ownPgid = Number(readFileSync('/proc/self/stat', 'utf8').split(') ')[1]!.split(' ')[2]);
			let cmdline = '';
			try {
				cmdline = readFileSync(`/proc/${bg}/cmdline`, 'utf8');
			} catch {
				// Already gone.
			}
			if (cmdline === 'sleep\u000060\u0000' && pgid !== ownPgid && [pg, ppid, bg].includes(pgid)) {
				try {
					process.kill(-pgid, 'SIGKILL');
				} catch {
					// Already gone.
				}
			}
		}
		// Deterministic: the shell is in the process group of its parent, the with-stack-env node,
		// which the outer run() started as a group leader. In a group of its own (newGroup true)
		// its group would be its own pid, and only a race between two SIGKILL timers decides
		// whether it outlives the inner node.
		expect(ppid).toBeGreaterThan(0);
		expect(pg).toBe(ppid);
		expect([undefined, 'Z']).toContain(state);
	}, 40_000);

	it('keeps output written just before the exit', async () => {
		// Many small writes right before exiting: none may be lost to an early stream destroy.
		for (let i = 0; i < 5; i++) {
			const result = await runTool(
				'sh',
				[
					'-c',
					'i=0; while [ $i -lt 200 ]; do echo "line $i"; i=$((i+1)); done; echo tail >&2; exit 0'
				],
				{ PATH: process.env['PATH'] ?? '' },
				{ quiet: true }
			);
			expect(result.code).toBe(0);
			expect(result.output.split('\n').filter((l) => l.startsWith('line ')).length).toBe(200);
			expect(result.output).toContain('tail');
		}
	});

	it('a command that ends by itself returns its own exit status', async () => {
		const result = await runTool(
			'sh',
			['-c', 'echo out; exit 3'],
			{ PATH: process.env['PATH'] ?? '' },
			{
				quiet: true
			}
		);
		expect(result).toEqual({ code: 3, output: 'out\n' });
	});
});

describe('with-stack-env', () => {
	it.each([{}, { JADE_IMAGE: '' }])(
		'refuses without JADE_IMAGE (%j), so the shared jade-app:local is never built',
		async (extra) => {
			const env = { PATH: process.env['PATH'] ?? '', ...extra };
			// `false` would exit 1 if it ran; the refusal's exit 2 and message show it did not.
			const result = await run(
				process.execPath,
				[join(root, 'tools/compose.ts'), 'with-stack-env', 'false'],
				{ cwd: root, env }
			).then(
				() => ({ code: 0, stderr: '' }),
				(err: { code: number; stderr: string }) => ({ code: err.code, stderr: err.stderr })
			);
			expect(result.code).toBe(2);
			expect(result.stderr).toContain(
				'with-stack-env: JADE_IMAGE must name the tag to build; nothing was built'
			);
		}
	);
});
