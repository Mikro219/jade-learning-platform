// Build, test and gate output is ignored by git, so it cannot be committed or land in a
// bugfix patch (plan H10).
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { tempEnvFileName } from '../../tools/env-init.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));

function ignored(path: string): boolean {
	try {
		execFileSync('git', ['check-ignore', '--no-index', '-q', path], { cwd: root });
		return true;
	} catch {
		return false;
	}
}

describe('gate output is ignored', () => {
	it.each([
		'node_modules/x',
		'.svelte-kit/x',
		'build/x',
		'test-results/x',
		'playwright-report/index.html',
		'blob-report/x',
		'coverage/x',
		'vite.config.ts.timestamp-1700000000000-abc.mjs'
	])('%s', (path) => {
		expect(ignored(path)).toBe(true);
	});

	it('source is not ignored', () => {
		expect(ignored('src/app.html')).toBe(false);
		expect(ignored('package.json')).toBe(false);
	});
});

// Env files hold secrets (plan V4, INV4): .env and its variants are ignored, and the only env
// file git tracks is the documented example.
describe('env files', () => {
	it.each(['.env', '.env.local', '.env.production', 'tests/.env'])('%s is ignored', (path) => {
		expect(ignored(path)).toBe(true);
	});

	// B1: a write of `pnpm env:init` killed part-way leaves its temporary file of secrets.
	it.each(['.env', 'tests/.env'])("env:init's temporary file for %s is ignored", (target) => {
		const tmp = relative(root, tempEnvFileName(join(root, target), 4242, '0123456789ab'));
		expect(tmp).toBe(`${target}.tmp-4242-0123456789ab`);
		expect(ignored(tmp)).toBe(true);
		expect(ignored(relative(root, tempEnvFileName(join(root, target))))).toBe(true);
	});

	it('.env.example is not ignored', () => {
		expect(ignored('.env.example')).toBe(false);
	});

	it('git tracks no .env* file but .env.example', () => {
		const tracked = execFileSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' })
			.split('\0')
			.filter((path) => /(^|\/)\.env/.test(path));
		expect(tracked.filter((path) => path !== '.env.example')).toEqual([]);
	});
});

// INV4, plan D1: the image's build context holds no env file or other local credential or key,
// no repository metadata, no dependencies installed on the host, and none of the documents, plans
// or tests.
describe('.dockerignore', () => {
	const entries = readFileSync(`${root}.dockerignore`, 'utf8')
		.split('\n')
		.map((line) => line.trim())
		.filter((line) => line !== '' && !line.startsWith('#'));

	it.each([
		'.env',
		'.env.*',
		'.git',
		'node_modules',
		'docs',
		'plans',
		'.beads',
		'.claude',
		'tests',
		'.mcp.json',
		'.npmrc',
		'*.pem',
		'*.key'
	])('excludes %s', (entry) => {
		expect(entries).toContain(entry);
	});

	it('re-includes nothing', () => {
		expect(entries.filter((line) => line.startsWith('!'))).toEqual([]);
	});
});

// B3: tools/ci/clean-clone.sh curls `pnpm dev` only once its log shows Vite's ready line naming
// the chosen port, so a 200 from another process that took the port cannot pass.
describe('clean-clone waits for the dev server it started', () => {
	const script = readFileSync(`${root}tools/ci/clean-clone.sh`, 'utf8');
	const fn = /^vite_ready\(\) \{\n[\s\S]*?\n\}\n/m.exec(script)?.[0];

	function ready(log: string, port: number): boolean {
		const dir = mkdtempSync(join(tmpdir(), 'jade-clean-clone-'));
		try {
			const file = join(dir, 'dev.log');
			writeFileSync(file, log);
			execFileSync('bash', ['-c', `${fn}\nvite_ready "$1" "$2"`, 'bash', file, String(port)]);
			return true;
		} catch {
			return false;
		} finally {
			rmSync(dir, { recursive: true, force: true });
		}
	}

	// Vite 8's log for `vite dev --host 127.0.0.1 --port <port> --strictPort`.
	const vite = (port: number, host = '127.0.0.1') =>
		`$ vite dev --host 127.0.0.1 --port ${port} --strictPort\n\n` +
		`  \x1b[32mVITE v8.3.8\x1b[39m  ready in 2735 ms\n\n` +
		`  ➜  \x1b[1mLocal\x1b[22m:   \x1b[36mhttp://${host}:${port}/\x1b[39m\n`;

	it('the script defines vite_ready and calls it before curl', () => {
		expect(fn).toBeDefined();
		const loop = script.slice(script.indexOf('for attempt in 1 2 3; do'));
		expect(loop.indexOf('vite_ready "$log" "$port"')).toBeGreaterThan(-1);
		expect(loop.indexOf('vite_ready "$log" "$port"')).toBeLessThan(loop.indexOf('curl '));
	});

	it('starts pnpm dev on 127.0.0.1 with --strictPort, and curl has a time limit (A8, B5)', () => {
		const loop = script.slice(script.indexOf('for attempt in 1 2 3; do'));
		expect(loop).toContain('pnpm dev --host 127.0.0.1 --port "$port" --strictPort');
		expect(loop).toMatch(/curl -s --max-time 10 [^\n]*"http:\/\/127\.0\.0\.1:\$port\/"/);
	});

	it("is ready only on Vite's ready line naming the chosen port", () => {
		expect(ready(vite(36539), 36539)).toBe(true);
		// The same log without colour codes.
		const plain = vite(36539)
			.split('\u001b')
			.map((part, i) => (i === 0 ? part : part.replace(/^\[[0-9;]*m/, '')))
			.join('');
		expect(ready(plain, 36539)).toBe(true);
		expect(ready(vite(36540), 36539)).toBe(false);
		// Another address than the one the server was started on is not its ready line.
		expect(ready(vite(36539, 'localhost'), 36539)).toBe(false);
		expect(ready(vite(36539, '127.0.0.10'), 36539)).toBe(false);
		expect(ready(vite(36539, '[::1]'), 36539)).toBe(false);
		expect(ready(vite(365390), 36539)).toBe(false);
		expect(ready('$ vite dev --port 36539 --strictPort\n', 36539)).toBe(false);
		expect(ready('Error: Port 36539 is already in use\n', 36539)).toBe(false);
	});
});

// B6: the role-bootstrap test's throwaway Postgres container is labelled and always removed.
describe("the role-bootstrap test's container", () => {
	const source = readFileSync(`${root}tests/integration/role-bootstrap.test.ts`, 'utf8');

	it('is labelled jade-test=role-bootstrap', () => {
		expect(source).toMatch(/'run',[\s\S]*'--label',\s*'jade-test=role-bootstrap'/);
	});

	it('is removed by name in afterAll unconditionally, ignoring errors', () => {
		const hook = /afterAll\(async \(\) => \{\n([\s\S]*?)\n\t\}\);/g;
		const bodies = [...source.matchAll(hook)].map((m) => m[1]!);
		const removal = bodies.find((b) => b.includes("'rm', '-f', '-v', name"));
		expect(removal).toBeDefined();
		expect(removal!.trim()).toBe(
			"await docker('docker', ['rm', '-f', '-v', name]).catch(() => {});"
		);
	});
});
