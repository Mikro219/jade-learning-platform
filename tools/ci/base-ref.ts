// The base commit of a CI stage (plan X1a): what `pnpm db:check --base <ref>` and `pnpm ci:compat`
// compare HEAD with. It is never left to a default:
//   - `--base <ref>`: that commit (it must be one of this repository's);
//   - JADE_CI_BASE (the workflow sets it from the event): under `pull_request` the pull request's
//     base commit, under `push` the commit the trunk pointed at before the push. Forty zeros (the
//     first push of the trunk) means there is no base. Any other value must be a commit that is
//     present here: the job fetches it first (`git fetch --no-tags --depth=1 origin <sha>`), and a
//     commit that is missing is an error, never "no base";
//   - in CI (CI set to anything but empty, false or 0) without JADE_CI_BASE: an error;
//   - locally: the merge base of HEAD and the trunk (`main`), else HEAD~1, else no base, which only
//     a root commit has; a shallow repository, or a git error, is an error, never "no base". When the
//     merge base is HEAD itself (HEAD is on the trunk, or behind it), HEAD~1 is used, as a push
//     would.
// A base with no migrations/manifest.json (from before jade-urd) has an empty manifest: db:check
// then says "the base has no migrations", and ci:compat passes saying the same.
//
//   node tools/ci/base-ref.ts [--base <ref>]            prints the base commit, or `no base`
//   node tools/ci/base-ref.ts db-check [--base <ref>]   runs db:check against that base
//
// The reason goes to stderr, the answer alone to stdout. Git runs in the current directory.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

type Env = Readonly<Record<string, string | undefined>>;

/** What stdout says when there is no base. */
export const NO_BASE = 'no base';

/** github.event.before on the first push of a branch. */
export const ZERO_SHA = '0'.repeat(40);

/** The trunk the local fallback measures from. */
export const TRUNK = 'main';

/** The variable the workflow passes the event's base commit in. */
export const BASE_VARIABLE = 'JADE_CI_BASE';

export interface BaseRef {
	/** The base commit, or null when there is none. */
	commit: string | null;
	/** Why this commit (or none) was chosen. */
	reason: string;
	/** Whether the base commit holds migrations/manifest.json (false when there is no base). */
	hasManifest: boolean;
}

/** A base that was asked for but cannot be used; the message names no value but a commit. */
export class BaseRefError extends Error {}

interface GitResult {
	status: number;
	stdout: string;
}

function gitRun(args: readonly string[], cwd: string): GitResult {
	const r = spawnSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
	return { status: r.error ? -1 : (r.status ?? -1), stdout: (r.stdout ?? '').trim() };
}

/** The commit `ref` names, or null when it names none here. */
function commitOf(ref: string, cwd: string): string | null {
	const r = gitRun(['rev-parse', '--verify', '--quiet', `${ref}^{commit}`], cwd);
	return r.status === 0 && r.stdout !== '' ? r.stdout : null;
}

function withManifest(commit: string, reason: string, cwd: string): BaseRef {
	const r = gitRun(['ls-tree', '--name-only', commit, '--', 'migrations/manifest.json'], cwd);
	if (r.status !== 0) throw new BaseRefError(`git ls-tree failed on ${commit}`);
	return { commit, reason, hasManifest: r.stdout !== '' };
}

const none = (reason: string): BaseRef => ({ commit: null, reason, hasManifest: false });

/**
 * Whether this is a CI run: CI set to anything but empty, `false` or `0` (case-insensitive), so an
 * unusual value fails closed.
 */
export function isCi(env: Env): boolean {
	const value = (env['CI'] ?? '').toLowerCase();
	return value !== '' && value !== 'false' && value !== '0';
}

/** The base commit for this run (see the header). Throws BaseRefError. */
export function resolveBase(options: { cwd: string; env: Env; base?: string }): BaseRef {
	const { cwd, env } = options;
	if (options.base !== undefined) {
		const commit = commitOf(options.base, cwd);
		if (commit === null) throw new BaseRefError('--base does not name a commit of this repository');
		return withManifest(commit, '--base', cwd);
	}

	const given = env[BASE_VARIABLE];
	if (given !== undefined && given !== '') {
		if (given === ZERO_SHA) {
			return none(`${BASE_VARIABLE} is forty zeros: the push has no predecessor`);
		}
		if (!/^[0-9a-f]{40}$/.test(given)) {
			throw new BaseRefError(`${BASE_VARIABLE} is not a 40-digit commit SHA`);
		}
		const commit = commitOf(given, cwd);
		if (commit === null) {
			throw new BaseRefError(
				`${BASE_VARIABLE} commit ${given} is not present; fetch it first (git fetch --no-tags --depth=1 origin ${given})`
			);
		}
		return withManifest(commit, BASE_VARIABLE, cwd);
	}
	if (isCi(env)) {
		throw new BaseRefError(
			`${BASE_VARIABLE} is not set: in CI the base is never left to a default`
		);
	}

	// Locally. A shallow clone's missing history must not look like "no base".
	const shallow = gitRun(['rev-parse', '--is-shallow-repository'], cwd);
	if (shallow.status !== 0) throw new BaseRefError('not a git repository');
	if (shallow.stdout === 'true') {
		throw new BaseRefError(
			`a shallow repository has no reliable local base; name it with --base or ${BASE_VARIABLE}`
		);
	}
	const head = commitOf('HEAD', cwd);
	if (head === null) throw new BaseRefError('HEAD names no commit');
	const trunk =
		commitOf(`refs/heads/${TRUNK}`, cwd) ?? commitOf(`refs/remotes/origin/${TRUNK}`, cwd);
	if (trunk !== null) {
		const mb = gitRun(['merge-base', head, trunk], cwd);
		// Exit 1 with no output: no common ancestor. Anything else but success is an error.
		if (mb.status === 0 && mb.stdout !== '') {
			if (mb.stdout !== head) {
				return withManifest(mb.stdout, `the merge base of HEAD and ${TRUNK}`, cwd);
			}
		} else if (!(mb.status === 1 && mb.stdout === '')) {
			throw new BaseRefError(`git merge-base failed (exit ${mb.status})`);
		}
	}
	const parent = commitOf('HEAD~1', cwd);
	if (parent !== null) return withManifest(parent, 'HEAD~1', cwd);
	// "No base" only for a true root commit.
	const roots = gitRun(['rev-list', '--max-parents=0', 'HEAD'], cwd);
	if (roots.status === 0 && roots.stdout.split('\n').includes(head)) {
		return none('HEAD is a root commit and has no merge base with main other than itself');
	}
	throw new BaseRefError('HEAD~1 names no commit, yet HEAD is not a root commit');
}

/** One line for stderr: the base and why, or why there is none. */
export function describeBase(base: BaseRef): string {
	if (base.commit === null) return `base-ref: ${NO_BASE} (${base.reason})`;
	const manifest = base.hasManifest ? '' : '; it has no migrations/manifest.json';
	return `base-ref: ${base.commit} (${base.reason})${manifest}`;
}

export async function main(argv: readonly string[], env: Env = process.env): Promise<number> {
	const args = [...argv];
	const dbCheck = args[0] === 'db-check';
	if (dbCheck) args.shift();
	let ref: string | undefined;
	if (args.length === 2 && args[0] === '--base' && args[1]) ref = args[1];
	else if (args.length !== 0) {
		process.stderr.write('usage: base-ref.ts [db-check] [--base <ref>]\n');
		return 2;
	}

	let base: BaseRef;
	try {
		base = resolveBase({ cwd: process.cwd(), env, base: ref });
	} catch (err) {
		if (err instanceof BaseRefError) {
			process.stderr.write(`base-ref: ${err.message}\n`);
			return 1;
		}
		throw err;
	}
	process.stderr.write(`${describeBase(base)}\n`);
	if (!dbCheck) {
		process.stdout.write(`${base.commit ?? NO_BASE}\n`);
		return 0;
	}
	// `pnpm db:check --base <commit>`, or HEAD's manifest alone when there is no base (X1a).
	const { main: checkMigrations } = await import('../db/check-migrations.ts');
	if (base.commit === null) {
		process.stdout.write("db:check: no base; HEAD's manifest is checked alone\n");
		return checkMigrations([]);
	}
	return checkMigrations(['--base', base.commit]);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main(process.argv.slice(2));
}
