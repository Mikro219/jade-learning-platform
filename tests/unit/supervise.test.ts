// tools/ci/lib/supervise.sh (plan X4; the signal handling of pnpm ci:compat), with no database or
// Docker: a fixture script sources it and runs a fake long child that starts grandchildren and
// records their pids. A SIGTERM or SIGINT to the script must end it at once with 143 or 130, run
// its cleanup (the temporary directory goes) and leave no recorded process behind, also when the
// signal lands between the fork and `child=$!`. And every long or database-touching command of
// migration-compat.sh must go through run().
//
// JADE_SUPERVISE_LIB names another library to test instead (used once to show that the round-0
// design, a foreground child with plain traps, fails these tests).
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

const root = fileURLToPath(new URL('../../', import.meta.url));
const LIB = process.env['JADE_SUPERVISE_LIB'] || join(root, 'tools/ci/lib/supervise.sh');

const FIXTURE = `#!/usr/bin/env bash
set -euo pipefail
source "$LIB"
work=$(mktemp -d "$OUT/work-XXXXXX")
cleanup() { rm -rf "$work"; echo "cleanup $1" >>"$OUT/log"; }
supervise_init fixture cleanup
if [ "\${EARLY-}" = 1 ]; then supervise_after_fork() { kill -TERM $$; }; fi
run bash -c '
  echo $$ >>"$OUT/pids"
  sleep "$DUR" & echo $! >>"$OUT/pids"
  (sleep "$DUR"; :) & echo $! >>"$OUT/pids"
  (trap "touch \\"\\$OUT/termed\\"; exit 0" TERM; touch "$OUT/trap-ready"; sleep "$DUR" & wait) &
  echo $! >>"$OUT/pids"
  while [ ! -e "$OUT/trap-ready" ]; do sleep 0.01; done
  touch "$OUT/ready"
  wait'
echo finished >>"$OUT/log"
`;

const dirs: string[] = [];
afterEach(() => {
	for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});
function mkdtempDir() {
	const dir = mkdtempSync(join(tmpdir(), 'jade-supervise-'));
	dirs.push(dir);
	return dir;
}

const alive = (pid: number) => {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
};
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Run the fixture, send `signal` (after the child is ready, unless `early`); KILL at 10 s. */
async function drive(signal: NodeJS.Signals | null, early = false) {
	const out = mkdtempSync(join(tmpdir(), 'jade-supervise-'));
	dirs.push(out);
	const script = join(out, 'fixture.sh');
	writeFileSync(script, FIXTURE);
	// A duration no other process uses, to find stray sleeps by their arguments.
	const dur = String(300000 + Math.floor(Math.random() * 600000));
	const child = spawn('bash', [script], {
		env: {
			PATH: process.env['PATH'] ?? '/usr/bin:/bin',
			LIB,
			OUT: out,
			DUR: dur,
			EARLY: early ? '1' : ''
		},
		stdio: ['ignore', 'pipe', 'pipe']
	});
	let stderr = '';
	child.stderr.on('data', (d: Buffer) => (stderr += d.toString()));
	const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve) =>
		child.once('exit', (code, sig) => resolve({ code, signal: sig }))
	);
	if (!early) {
		const deadline = Date.now() + 10_000;
		while (!existsSync(join(out, 'ready')) && Date.now() < deadline) await sleep(50);
		expect(existsSync(join(out, 'ready')), 'the fake child started').toBe(true);
	}
	const sent = Date.now();
	if (signal !== null) child.kill(signal);
	const killer = setTimeout(() => child.kill('SIGKILL'), 10_000);
	const result = await exited;
	clearTimeout(killer);
	const took = Date.now() - sent;
	await sleep(300);
	const pids = existsSync(join(out, 'pids'))
		? readFileSync(join(out, 'pids'), 'utf8').split('\n').filter(Boolean).map(Number)
		: [];
	const strays = readdirSync('/proc')
		.filter((p) => /^\d+$/.test(p))
		.filter((p) => {
			try {
				return readFileSync(`/proc/${p}/cmdline`, 'utf8').includes(dur);
			} catch {
				return false;
			}
		});
	for (const p of [...pids, ...strays.map(Number)]) {
		try {
			process.kill(p, 'SIGKILL'); // never leave a test's sleep behind
		} catch {
			// gone
		}
	}
	const works = readdirSync(out).filter((n) => n.startsWith('work-'));
	const log = existsSync(join(out, 'log')) ? readFileSync(join(out, 'log'), 'utf8') : '';
	// Written by a grandchild's TERM trap: the TERM itself reached the group, not only the KILL.
	const termed = existsSync(join(out, 'termed'));
	const alivePids = pids.filter(alive);
	return { ...result, took, pids, strays, works, log, stderr, termed, alivePids };
}

describe('run() under a signal', () => {
	it.each([
		['SIGTERM', 143, 'stopped by SIGTERM'],
		['SIGINT', 130, 'stopped by SIGINT']
	] as const)(
		'%s: exits %i within seconds, cleans up, leaves no child or grandchild',
		async (signal, code, message) => {
			const r = await drive(signal);
			expect(r.signal, 'the script was not SIGKILLed').toBeNull();
			expect(r.code).toBe(code);
			expect(r.took).toBeLessThan(6_000);
			expect(r.stderr).toContain(`fixture: ${message}`);
			expect(r.pids.length).toBe(4);
			expect(r.termed, 'TERM reached the grandchildren').toBe(true);
			expect(r.strays).toEqual([]);
			expect(r.alivePids).toEqual([]);
			expect(r.works).toEqual([]);
			expect(r.log).toBe(`cleanup ${code}\n`);
		},
		20_000
	);

	it('a TERM between the fork and child=$! is held, then acted on: the child is stopped', async () => {
		const r = await drive(null, true);
		expect(r.signal).toBeNull();
		expect(r.code).toBe(143);
		expect(r.took).toBeLessThan(6_000);
		expect(r.strays).toEqual([]);
		expect(r.alivePids).toEqual([]);
		expect(r.works).toEqual([]);
		expect(r.log).toBe('cleanup 143\n');
	}, 20_000);
});

/** Run `body` in a bash script that sources the library; resolves with its exit code and output. */
function bashWithLib(
	body: string,
	opts: { detached?: boolean; env?: Record<string, string> } = {}
) {
	const child = spawn('bash', ['-c', `set -euo pipefail\nsource "$LIB"\n${body}`], {
		env: { PATH: process.env['PATH'] ?? '/usr/bin:/bin', LIB, ...opts.env },
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: opts.detached ?? false
	});
	let out = '';
	child.stdout.on('data', (d: Buffer) => (out += d.toString()));
	child.stderr.on('data', (d: Buffer) => (out += d.toString()));
	const done = new Promise<{ code: number | null; out: string }>((resolve) =>
		child.once('exit', (code) => resolve({ code, out }))
	);
	return { child, done };
}

describe('run() exit status', () => {
	it("returns the command's own status, after it has finished (setsid -w)", async () => {
		const { done } = bashWithLib(
			[
				'supervise_init fixture true',
				'run sh -c \'exit 7\' || echo "status $?"',
				'run true && echo "status-true $?"',
				// Without -w a forked setsid would return at once, before the marker is written.
				`run sh -c 'sleep 0.3; echo late >"$OUT/marker"' && cat "$OUT/marker"`
			].join('\n'),
			{ env: { OUT: mkdtempDir() } }
		);
		const r = await done;
		expect(r.code).toBe(0);
		expect(r.out).toContain('status 7');
		expect(r.out).toContain('status-true 0');
		expect(r.out).toContain('late');
	});
});

describe('cleanup under a second Ctrl-C', () => {
	// migration-compat.sh drops its databases in cleanup with `setsid -w node ...` (R1): bash
	// ignores INT there, but Node resets inherited dispositions at start-up, so only a session of
	// its own keeps a second terminal SIGINT (sent to the whole foreground group) from killing it.
	it.each([
		['setsid -w node', true],
		['plain node (the failure this guards against)', false]
	] as const)(
		'%s: the cleanup step survives: %s',
		async (_label, isolated) => {
			const out = mkdtempDir();
			const node = JSON.stringify(process.execPath);
			const step = `${isolated ? 'setsid -w ' : ''}${node} -e 'setTimeout(()=>require("fs").writeFileSync(process.env.OUT+"/dropped",""),800)'`;
			const { child, done } = bashWithLib(
				[
					`cleanup() { touch "$OUT/cleanup-started"; ${step}; }`,
					'supervise_init fixture cleanup',
					`run sh -c 'touch "$OUT/ready"; sleep 30'`
				].join('\n'),
				{ detached: true, env: { OUT: out } }
			);
			const pgid = child.pid!;
			const wait = async (file: string) => {
				const deadline = Date.now() + 10_000;
				while (!existsSync(join(out, file)) && Date.now() < deadline) await sleep(20);
			};
			await wait('ready');
			process.kill(-pgid, 'SIGINT'); // the first Ctrl-C, to the whole foreground group
			await wait('cleanup-started');
			await sleep(200);
			process.kill(-pgid, 'SIGINT'); // the second Ctrl-C, during cleanup
			const r = await done;
			expect(r.code).toBe(130);
			expect(existsSync(join(out, 'dropped'))).toBe(isolated);
		},
		20_000
	);
});

describe('the library refuses what it cannot supervise', () => {
	it('under job control (set -m)', async () => {
		const r = spawn('bash', ['-c', `set -m; source "${LIB}"; echo sourced`], {
			stdio: ['ignore', 'pipe', 'pipe']
		});
		let out = '';
		r.stdout.on('data', (d: Buffer) => (out += d.toString()));
		r.stderr.on('data', (d: Buffer) => (out += d.toString()));
		const code = await new Promise((resolve) => r.once('exit', resolve));
		expect(code).toBe(2);
		expect(out).toContain('refusing to run under job control');
		expect(out).not.toContain('sourced');
	});
});

describe('migration-compat.sh', () => {
	const script = readFileSync(join(root, 'tools/ci/migration-compat.sh'), 'utf8');
	const lines = script.split('\n').map((l) => l.trim());
	const DB_COMMANDS = 'prepare|readyz|step3|ledger|leftovers|drop';
	const LONG = new RegExp(
		`\\bpnpm\\b|\\bvitest\\b|node build|compat\\.ts (${DB_COMMANDS})\\b|\\b(compat|db) (${DB_COMMANDS})\\b`
	);

	it('sources the library and installs its traps', () => {
		expect(lines).toContain('source tools/ci/lib/supervise.sh');
		expect(lines).toContain('supervise_init ci:compat cleanup');
		expect(script).not.toMatch(/^\s*trap /m);
	});

	it('runs every pnpm, vitest, node build and database-touching compat.ts command through run()', () => {
		const offending = lines.filter(
			(line) =>
				!line.startsWith('#') &&
				!line.startsWith('echo ') &&
				!line.startsWith('"') &&
				!line.startsWith("breaking='") &&
				LONG.test(line) &&
				!/^(run|db) /.test(line) &&
				line !== 'db() { run node tools/ci/compat.ts "$@"; }' &&
				// The drop in cleanup: in the foreground, in a session of its own (R1).
				line !== 'drop_databases() { setsid -w node tools/ci/compat.ts drop "$@"; }'
		);
		expect(offending).toEqual([]);
		expect(lines.filter((l) => l.startsWith('run ')).length).toBeGreaterThanOrEqual(3);
	});

	it('calls compat directly only for file-only subcommands, and drop in cleanup', () => {
		const code = lines.filter(
			(l) => !l.startsWith('#') && !l.startsWith('echo ') && !l.startsWith("breaking='")
		);
		const direct = code.flatMap((l) =>
			[...l.matchAll(/(?:^|[\s(])compat ([a-z-]+)/g)].map((m) => m[1])
		);
		expect(new Set(direct)).toEqual(new Set(['count-at', 'count-dir', 'manifest']));
		// The drop runs only in cleanup, twice (before and after stop_child), in its own session.
		const cleanup = /\ncleanup\(\) \{\n([\s\S]*?)\n\}\n/.exec(script)?.[1] ?? '';
		const uses = (s: string) => s.split(/\bdrop_databases \$\{databases/).length - 1;
		expect(uses(cleanup)).toBe(2);
		expect(uses(script)).toBe(2);
		expect(lines).toContain('drop_databases() { setsid -w node tools/ci/compat.ts drop "$@"; }');
	});

	it('installs its traps before it creates the temporary directory (R4)', () => {
		const init = script.indexOf('\nsupervise_init ci:compat cleanup\n');
		const mktemp = script.indexOf('work=$(mktemp');
		expect(init).toBeGreaterThan(0);
		expect(mktemp).toBeGreaterThan(init);
	});

	it('reads CI as tools/ci/base-ref.ts does: empty, false and 0 are not CI', () => {
		expect(script).toContain(
			'case "${ci,,}" in\n\'\' | false | 0) ;;\n*) install_flags+=(--no-runtime) ;;'
		);
	});
});
