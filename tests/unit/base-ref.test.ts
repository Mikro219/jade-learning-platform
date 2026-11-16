// tools/ci/base-ref.ts (plan X1a) on scratch repositories: the base commit of each trigger, the
// forty-zero `before` of a trunk's first push, a base without migrations/manifest.json, the local
// fallbacks (merge base with main, HEAD~1, none), and the refusals (an unfetched commit, CI without
// JADE_CI_BASE, a --base that names nothing).
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { NO_BASE, ZERO_SHA, isCi } from '../../tools/ci/base-ref.ts';

const tool = fileURLToPath(new URL('../../tools/ci/base-ref.ts', import.meta.url));
const root = fileURLToPath(new URL('../../', import.meta.url));

const GIT_ENV = {
	PATH: process.env['PATH'] ?? '/usr/bin:/bin',
	HOME: '/nonexistent',
	GIT_CONFIG_NOSYSTEM: '1',
	GIT_CONFIG_GLOBAL: '/dev/null',
	GIT_AUTHOR_NAME: 'base-ref test',
	GIT_AUTHOR_EMAIL: 'base-ref@example.invalid',
	GIT_COMMITTER_NAME: 'base-ref test',
	GIT_COMMITTER_EMAIL: 'base-ref@example.invalid'
};

const dirs: string[] = [];
afterEach(() => {
	for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** A new repository whose first branch is `branch`. */
function repo(branch = 'main'): string {
	const dir = mkdtempSync(join(tmpdir(), 'jade-base-ref-'));
	dirs.push(dir);
	git(dir, 'init', '--quiet', '--initial-branch', branch);
	return dir;
}

function git(dir: string, ...args: string[]): string {
	return execFileSync('git', args, { cwd: dir, env: GIT_ENV, encoding: 'utf8' }).trim();
}

/** Commit a change (with migrations/manifest.json when `manifest`); returns the commit. */
function commit(dir: string, message: string, manifest = true): string {
	writeFileSync(join(dir, 'file.txt'), `${message}\n`);
	if (manifest) {
		mkdirSync(join(dir, 'migrations'), { recursive: true });
		writeFileSync(join(dir, 'migrations', 'manifest.json'), '{ "migrations": [] }\n');
	}
	git(dir, 'add', '-A');
	git(dir, 'commit', '--quiet', '-m', message);
	return git(dir, 'rev-parse', 'HEAD');
}

/** Run base-ref.ts in `dir` with only `env` (and git's) in the environment. */
function baseRef(dir: string, env: Record<string, string> = {}, args: string[] = []) {
	const r = spawnSync(process.execPath, [tool, ...args], {
		cwd: dir,
		env: { ...GIT_ENV, ...env },
		encoding: 'utf8'
	});
	return { status: r.status, stdout: r.stdout.trim(), stderr: r.stderr };
}

describe('in CI: JADE_CI_BASE from the event', () => {
	it('pull_request: the pull request base commit', () => {
		const dir = repo();
		const base = commit(dir, 'trunk');
		commit(dir, 'trunk moved on');
		git(dir, 'checkout', '--quiet', '-b', 'feature', base);
		commit(dir, 'feature work');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: base });
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(base);
		expect(r.stderr).toContain('(JADE_CI_BASE)');
	});

	it('push: the commit the trunk pointed at before the push', () => {
		const dir = repo();
		commit(dir, 'one');
		const before = commit(dir, 'two');
		commit(dir, 'three');
		commit(dir, 'four');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: before });
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(before);
	});

	it('push with forty zeros (the trunk has no predecessor): no base', () => {
		const dir = repo();
		commit(dir, 'one');
		commit(dir, 'two');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: ZERO_SHA });
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(NO_BASE);
		expect(r.stderr).toContain('forty zeros');
	});

	it('a base without migrations/manifest.json: that commit, reported as having none', () => {
		const dir = repo();
		const old = commit(dir, 'before jade-urd', false);
		commit(dir, 'with migrations');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: old });
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(old);
		expect(r.stderr).toContain('has no migrations/manifest.json');
		const withManifest = baseRef(dir, { CI: 'true', JADE_CI_BASE: git(dir, 'rev-parse', 'HEAD') });
		expect(withManifest.stderr).not.toContain('has no migrations/manifest.json');
	});

	it('a commit that was not fetched is an error, never "no base"', () => {
		const dir = repo();
		commit(dir, 'one');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: 'a'.repeat(40) });
		expect(r.status).toBe(1);
		expect(r.stdout).toBe('');
		expect(r.stderr).toContain('is not present; fetch it first');
	});

	it('a value that is not a SHA is an error', () => {
		const dir = repo();
		commit(dir, 'one');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: 'main' });
		expect(r.status).toBe(1);
		expect(r.stdout).toBe('');
	});

	it('CI=1 (any non-empty CI) without JADE_CI_BASE is an error too', () => {
		const dir = repo();
		commit(dir, 'one');
		commit(dir, 'two');
		for (const ci of ['1', 'TRUE', 'yes', 'on']) {
			const r = baseRef(dir, { CI: ci });
			expect(r.status, ci).toBe(1);
			expect(r.stderr).toContain('JADE_CI_BASE is not set');
		}
	});

	it('CI=false or CI=0 (any case) is not CI: the local rule applies', () => {
		const dir = repo('trunk');
		const parent = commit(dir, 'one');
		commit(dir, 'two');
		for (const ci of ['false', 'FALSE', 'False', '0']) {
			const r = baseRef(dir, { CI: ci });
			expect(r.status, ci).toBe(0);
			expect(r.stdout, ci).toBe(parent);
		}
	});

	it('isCi reads CI the same way', () => {
		expect(isCi({})).toBe(false);
		expect(isCi({ CI: '' })).toBe(false);
		expect(isCi({ CI: 'False' })).toBe(false);
		expect(isCi({ CI: '0' })).toBe(false);
		expect(isCi({ CI: 'true' })).toBe(true);
		expect(isCi({ CI: '1' })).toBe(true);
		expect(isCi({ CI: 'whatever' })).toBe(true);
	});

	it("the workflow's shape: a depth-1 clone, the base fetched at depth 1, then resolved", () => {
		const origin = repo();
		const base = commit(origin, 'trunk before the push');
		commit(origin, 'pushed one');
		commit(origin, 'pushed two');
		const clone = mkdtempSync(join(tmpdir(), 'jade-base-ref-clone-'));
		dirs.push(clone);
		git(clone, 'clone', '--quiet', '--depth=1', `file://${origin}`, '.');
		const before = baseRef(clone, { CI: 'true', JADE_CI_BASE: base });
		expect(before.status).toBe(1);
		expect(before.stderr).toContain('is not present; fetch it first');
		git(clone, 'fetch', '--quiet', '--no-tags', '--depth=1', 'origin', base);
		const r = baseRef(clone, { CI: 'true', JADE_CI_BASE: base });
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(base);
	});

	it('CI without JADE_CI_BASE is an error: the base is never left to a default', () => {
		const dir = repo();
		commit(dir, 'one');
		commit(dir, 'two');
		const r = baseRef(dir, { CI: 'true' });
		expect(r.status).toBe(1);
		expect(r.stdout).toBe('');
		expect(r.stderr).toContain('JADE_CI_BASE is not set');
	});
});

describe('locally', () => {
	it('the merge base of HEAD and main', () => {
		const dir = repo();
		commit(dir, 'one');
		const fork = commit(dir, 'two');
		commit(dir, 'main moved on');
		git(dir, 'checkout', '--quiet', '-b', 'feature', fork);
		commit(dir, 'feature one');
		commit(dir, 'feature two');
		const r = baseRef(dir);
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(fork);
		expect(r.stderr).toContain('merge base of HEAD and main');
	});

	it('on main itself (the merge base is HEAD): HEAD~1, as a push would', () => {
		const dir = repo();
		const parent = commit(dir, 'one');
		commit(dir, 'two');
		const r = baseRef(dir);
		expect(r.stdout).toBe(parent);
		expect(r.stderr).toContain('HEAD~1');
	});

	it('without a main branch: HEAD~1', () => {
		const dir = repo('trunk');
		const parent = commit(dir, 'one');
		commit(dir, 'two');
		const r = baseRef(dir);
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(parent);
		expect(r.stderr).toContain('HEAD~1');
	});

	it('a single commit and no main: no base', () => {
		const dir = repo('trunk');
		commit(dir, 'only');
		const r = baseRef(dir);
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(NO_BASE);
	});

	it('a shallow clone without an explicit base is an error, never "no base"', () => {
		const origin = repo();
		commit(origin, 'one');
		commit(origin, 'two');
		const clone = mkdtempSync(join(tmpdir(), 'jade-base-ref-clone-'));
		dirs.push(clone);
		git(clone, 'clone', '--quiet', '--depth=1', `file://${origin}`, '.');
		const r = baseRef(clone);
		expect(r.status).toBe(1);
		expect(r.stdout).toBe('');
		expect(r.stderr).toContain('shallow repository');
		// --base still works there.
		const head = git(clone, 'rev-parse', 'HEAD');
		expect(baseRef(clone, {}, ['--base', head]).stdout).toBe(head);
	});

	it('an empty JADE_CI_BASE outside CI falls back to the local rule', () => {
		const dir = repo('trunk');
		const parent = commit(dir, 'one');
		commit(dir, 'two');
		expect(baseRef(dir, { JADE_CI_BASE: '' }).stdout).toBe(parent);
	});
});

describe('--base', () => {
	it('names the base explicitly, before JADE_CI_BASE', () => {
		const dir = repo();
		const first = commit(dir, 'one');
		const second = commit(dir, 'two');
		commit(dir, 'three');
		const r = baseRef(dir, { CI: 'true', JADE_CI_BASE: second }, ['--base', first]);
		expect(r.status).toBe(0);
		expect(r.stdout).toBe(first);
	});

	it('a ref that names no commit is an error', () => {
		const dir = repo();
		commit(dir, 'one');
		const r = baseRef(dir, {}, ['--base', 'no-such-ref']);
		expect(r.status).toBe(1);
		expect(r.stdout).toBe('');
	});

	it('anything else is a usage error', () => {
		const dir = repo();
		commit(dir, 'one');
		expect(baseRef(dir, {}, ['--bogus']).status).toBe(2);
		expect(baseRef(dir, {}, ['--base']).status).toBe(2);
	});
});

describe('db-check, on this checkout', () => {
	const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
	const dbCheck = (env: Record<string, string>) => {
		const r = spawnSync(process.execPath, [tool, 'db-check'], {
			cwd: root,
			env: { PATH: process.env['PATH'] ?? '/usr/bin:/bin', ...env },
			encoding: 'utf8'
		});
		return { status: r.status, out: r.stdout + r.stderr };
	};

	it("forty zeros: HEAD's manifest is checked alone", () => {
		const r = dbCheck({ CI: 'true', JADE_CI_BASE: ZERO_SHA });
		expect(r.status).toBe(0);
		expect(r.out).toContain("db:check: no base; HEAD's manifest is checked alone");
		expect(r.out).toContain('no base given; this checkout only');
	});

	it('a base is passed through to db:check --base', () => {
		const r = dbCheck({ CI: 'true', JADE_CI_BASE: head });
		expect(r.status).toBe(0);
		expect(r.out).toContain(`base-ref: ${head} (JADE_CI_BASE)`);
		expect(r.out).toMatch(
			/db:check: ok, \d+ migration\(s\); the base('s \d+ migration\(s\) are an unchanged prefix| has no migrations)/
		);
	});

	it('a base that cannot be resolved fails before db:check runs', () => {
		const r = dbCheck({ CI: 'true', JADE_CI_BASE: 'b'.repeat(40) });
		expect(r.status).toBe(1);
		expect(r.out).toContain('is not present; fetch it first');
		expect(r.out).not.toContain('db:check: ok');
	});
});
