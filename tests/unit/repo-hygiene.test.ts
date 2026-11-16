// Build, test and gate output is ignored by git, so it cannot be committed or land in a
// bugfix patch (plan H10).
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

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
