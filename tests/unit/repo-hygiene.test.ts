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
