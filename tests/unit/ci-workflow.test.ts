// The CI workflow's contract (plan section 12.1 X1 to X4, PD11, PD14, D7, INV4, INV9), on the
// parsed .github/workflows/ci.yml and on package.json's stage scripts. The file is also linted
// with actionlint from its pinned container image; that test is skipped, saying so in its name,
// only when Docker is not available, and never in CI.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { parse } from 'yaml';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = (path: string) => readFileSync(join(root, path), 'utf8');

/** actionlint's image, pinned by tag and digest (release v1.7.12, 2026-03-30). */
export const ACTIONLINT_IMAGE =
	'rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667';

const WORKFLOW = '.github/workflows/ci.yml';
const text = read(WORKFLOW);

interface Step {
	name?: string;
	'continue-on-error'?: unknown;
	id?: string;
	if?: string;
	uses?: string;
	run?: string;
	with?: Record<string, unknown>;
	env?: Record<string, unknown>;
}
interface Service {
	image?: string;
	env?: Record<string, unknown>;
	ports?: unknown[];
	options?: string;
}
interface Job {
	'runs-on'?: string;
	if?: string;
	'continue-on-error'?: unknown;
	'timeout-minutes'?: number;
	services?: Record<string, Service>;
	env?: Record<string, unknown>;
	steps: Step[];
}
interface Workflow {
	on: Record<string, unknown>;
	permissions?: Record<string, string>;
	concurrency?: { group?: string; 'cancel-in-progress'?: unknown };
	env?: Record<string, unknown>;
	jobs: Record<string, Job>;
}

const workflow = parse(text) as Workflow;
const jobs = workflow.jobs;
const pkg = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
const scripts = pkg.scripts;

/** The Postgres pin of compose.dev.yml (INV9), which the service containers must name. */
const postgresPin = /^\s*image:\s*(postgres:\S+)\s*$/m.exec(read('compose.dev.yml'))?.[1];

const DB_JOBS = ['check', 'e2e', 'migration-compat'] as const;
const STAGE: Record<string, string> = {
	check: 'pnpm ci:check',
	e2e: 'pnpm ci:e2e',
	image: 'pnpm test:infra',
	'migration-compat': 'pnpm ci:compat'
};
const ENV_INIT = "pnpm env:init --profile ci --db-port ${{ job.services.postgres.ports['5432'] }}";
const FETCH_BASE = 'git fetch --no-tags --depth=1 origin "$JADE_CI_BASE"';
/** The lines before FETCH_BASE: the header is masked and reaches git through its environment. */
const FETCH_AUTH = [
	'header="AUTHORIZATION: basic $(printf \'x-access-token:%s\' "$GITHUB_TOKEN" | base64 -w0)"',
	'echo "::add-mask::$header"',
	'# The header reaches git through its environment, never its arguments.',
	'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.$GITHUB_SERVER_URL/.extraheader" GIT_CONFIG_VALUE_0="$header" \\'
];

const runs = (job: Job) => job.steps.map((s) => s.run ?? '');
const stepIndex = (job: Job, pred: (s: Step) => boolean) => job.steps.findIndex(pred);
const runIndex = (job: Job, command: string) =>
	stepIndex(job, (s) => (s.run ?? '').split('\n').some((line) => line.trim() === command));
const usesIndex = (job: Job, action: string) =>
	stepIndex(job, (s) => (s.uses ?? '').startsWith(`${action}@`));

/** Every `env:` map of the file: the workflow's, each job's, each service's and each step's. */
function envMaps(): { where: string; env: Record<string, unknown> }[] {
	const out: { where: string; env: Record<string, unknown> }[] = [];
	if (workflow.env) out.push({ where: 'workflow', env: workflow.env });
	for (const [name, job] of Object.entries(jobs)) {
		if (job.env) out.push({ where: name, env: job.env });
		for (const [svc, service] of Object.entries(job.services ?? {})) {
			if (service.env) out.push({ where: `${name}.services.${svc}`, env: service.env });
		}
		job.steps.forEach((step, i) => {
			if (step.env) out.push({ where: `${name}.steps[${i}]`, env: step.env });
		});
	}
	return out;
}

describe('triggers, permissions, runner', () => {
	it('runs on pull_request and on push to main, nothing else', () => {
		expect(Object.keys(workflow.on).sort()).toEqual(['pull_request', 'push']);
		expect(workflow.on['pull_request']).toBeNull();
		expect(workflow.on['push']).toEqual({ branches: ['main'] });
	});

	it('has contents: read and nothing more', () => {
		expect(workflow.permissions).toEqual({ contents: 'read' });
	});

	it('cancels superseded runs of a pull request, and push runs never share a group', () => {
		// Under pull_request the group is the pull request's; under push it is the run's own id,
		// unique per run, so a later push can neither cancel nor displace a pending push run.
		expect(workflow.concurrency?.group).toBe(
			"${{ github.event_name == 'pull_request' && format('ci-pr-{0}', github.event.pull_request.number) || format('ci-push-{0}', github.run_id) }}"
		);
		expect(workflow.concurrency?.['cancel-in-progress']).toBe(
			"${{ github.event_name == 'pull_request' }}"
		);
		for (const job of Object.values(jobs)) expect(job).not.toHaveProperty('concurrency');
	});

	it('no job or step may continue on error', () => {
		expect(text).not.toMatch(/continue-on-error/);
		for (const job of Object.values(jobs)) {
			expect(job['continue-on-error']).toBeUndefined();
			for (const step of job.steps) expect(step['continue-on-error']).toBeUndefined();
		}
	});

	it('has exactly the four jobs, on the pinned runner image, each within 9 minutes (X3)', () => {
		expect(Object.keys(jobs).sort()).toEqual(['check', 'e2e', 'image', 'migration-compat']);
		for (const job of Object.values(jobs)) {
			expect(job['runs-on']).toBe('ubuntu-24.04');
			expect(job['timeout-minutes']).toBeGreaterThan(0);
			expect(job['timeout-minutes']).toBeLessThanOrEqual(9);
			// No job waits on another: they run in parallel.
			expect(job).not.toHaveProperty('needs');
		}
	});

	it('every job runs its stage script', () => {
		for (const [name, command] of Object.entries(STAGE)) {
			expect(runIndex(jobs[name]!, command), name).toBeGreaterThanOrEqual(0);
		}
	});
});

describe('action pins', () => {
	const lines = text.split('\n').filter((line) => /^\s*-?\s*uses:/.test(line));

	it('every action is pinned to a full 40-character commit SHA, its tag in a comment', () => {
		expect(lines.length).toBeGreaterThan(0);
		for (const line of lines) {
			expect(line).toMatch(
				/^\s*-?\s*uses: [A-Za-z0-9_.-]+\/[A-Za-z0-9_./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$/
			);
		}
		for (const job of Object.values(jobs)) {
			for (const step of job.steps) {
				if (step.uses !== undefined) expect(step.uses).toMatch(/@[0-9a-f]{40}$/);
			}
		}
	});

	it('pnpm comes from packageManager and Node from .nvmrc, with the pnpm store cached', () => {
		for (const [name, job] of Object.entries(jobs)) {
			const pnpm = usesIndex(job, 'pnpm/action-setup');
			const node = usesIndex(job, 'actions/setup-node');
			const install = runIndex(job, 'pnpm install --frozen-lockfile --no-runtime');
			expect(pnpm, name).toBeGreaterThanOrEqual(0);
			expect(node, name).toBeGreaterThan(pnpm);
			expect(install, name).toBeGreaterThan(node);
			// One source of truth for the versions: no version input here.
			expect(job.steps[pnpm]!.with?.['version'], name).toBeUndefined();
			expect(job.steps[node]!.with).toEqual({ 'node-version-file': '.nvmrc', cache: 'pnpm' });
		}
	});
});

describe('database service (PD11, INV9)', () => {
	it('the jobs that need a database have a Postgres service with the pinned image', () => {
		expect(postgresPin).toMatch(/^postgres:16\./);
		for (const name of DB_JOBS) {
			const services = jobs[name]!.services ?? {};
			expect(Object.keys(services), name).toEqual(['postgres']);
			expect(services['postgres']!.image, name).toBe(postgresPin);
		}
	});

	it('the service publishes no fixed host port: the runner maps 5432 to a port it chooses', () => {
		for (const name of DB_JOBS) {
			expect(jobs[name]!.services!['postgres']!.ports, name).toEqual([5432]);
		}
	});

	it('each runs env:init --profile ci with the mapped port before its stage script (V5)', () => {
		for (const name of DB_JOBS) {
			const job = jobs[name]!;
			const init = runIndex(job, ENV_INIT);
			expect(init, name).toBeGreaterThanOrEqual(0);
			expect(init, name).toBeLessThan(runIndex(job, STAGE[name]!));
		}
	});
});

describe('secrets (INV4, X2)', () => {
	const SECRET_NAME =
		/^(CODE_PEPPER|SESSION_SECRET|DATABASE_URL|MIGRATION_DATABASE_URL|JADE_\w*PASSWORD)$/;

	it('no secrets. expression appears in the file', () => {
		expect(text).not.toMatch(/\bsecrets\s*\./);
		expect(text).not.toMatch(/\bsecrets\s*\[/);
	});

	it('the only secret-shaped variable written is JADE_OWNER_DB_PASSWORD, the test-only literal', () => {
		const written = envMaps().flatMap(({ where, env }) =>
			Object.entries(env)
				.filter(([key]) => SECRET_NAME.test(key))
				.map(([key, value]) => ({ where, key, value }))
		);
		expect(written.length).toBeGreaterThan(0);
		for (const { where, key, value } of written) {
			expect(key, where).toBe('JADE_OWNER_DB_PASSWORD');
			expect(typeof value).toBe('string');
			expect(value as string).toContain('test-only');
			expect(value as string).not.toContain('${{');
		}
	});

	it("JADE_OWNER_DB_PASSWORD equals the job's service POSTGRES_PASSWORD", () => {
		for (const name of DB_JOBS) {
			const job = jobs[name]!;
			const password = job.services!['postgres']!.env?.['POSTGRES_PASSWORD'];
			expect(password).toMatch(/^[A-Za-z0-9_-]+$/);
			expect(password).toContain('test-only');
			const init = job.steps[runIndex(job, ENV_INIT)]!;
			expect(init.env).toEqual({ JADE_OWNER_DB_PASSWORD: password });
		}
	});
});

describe('base commit (X1a)', () => {
	it('JADE_CI_BASE is the pull request base under pull_request and github.event.before under push', () => {
		expect(workflow.env?.['JADE_CI_BASE']).toBe(
			"${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event.before }}"
		);
		// No job or step redefines it.
		for (const { where, env } of envMaps()) {
			if (where !== 'workflow') expect(env, where).not.toHaveProperty('JADE_CI_BASE');
		}
	});

	it('check and migration-compat fetch the base commit before using it', () => {
		for (const name of ['check', 'migration-compat']) {
			const job = jobs[name]!;
			const fetch = runIndex(job, FETCH_BASE);
			expect(fetch, name).toBeGreaterThanOrEqual(0);
			expect(fetch, name).toBeLessThan(runIndex(job, STAGE[name]!));
			// Only forty zeros skips the fetch; a fetch that fails fails the step.
			expect(job.steps[fetch]!.run).toContain(
				'if [ "$JADE_CI_BASE" = 0000000000000000000000000000000000000000 ]; then'
			);
		}
		// migration-compat diffs against the base only after fetching it.
		const compat =
			jobs['migration-compat']!.steps[runIndex(jobs['migration-compat']!, FETCH_BASE)]!;
		const body = compat.run ?? '';
		expect(body.indexOf(FETCH_BASE)).toBeLessThan(
			body.indexOf('git diff --name-only "$JADE_CI_BASE" HEAD -- migrations/')
		);
	});

	it('the base fetch cannot swallow a failure', () => {
		for (const name of ['check', 'migration-compat']) {
			const job = jobs[name]!;
			const body = job.steps[runIndex(job, FETCH_BASE)]!.run ?? '';
			expect(body, name).not.toMatch(/set \+e|\|\|\s*true|\|\|\s*:/);
		}
	});

	it("the token is masked and never in git's arguments", () => {
		expect(text).not.toMatch(/git\s+-c\b/);
		for (const name of ['check', 'migration-compat']) {
			const job = jobs[name]!;
			const lines = (job.steps[runIndex(job, FETCH_BASE)]!.run ?? '')
				.split('\n')
				.map((l) => l.trim());
			const at = lines.indexOf(FETCH_BASE);
			expect(lines.slice(at - FETCH_AUTH.length, at), name).toEqual(FETCH_AUTH);
		}
	});

	it('no checkout persists its token; only the base fetches get the read-only job token', () => {
		for (const [name, job] of Object.entries(jobs)) {
			const checkout = job.steps[usesIndex(job, 'actions/checkout')]!;
			expect(checkout.with?.['persist-credentials'], name).toBe(false);
			job.steps.forEach((step, i) => {
				const fetches = (step.run ?? '').includes(FETCH_BASE);
				if (fetches)
					expect(step.env, `${name}[${i}]`).toEqual({ GITHUB_TOKEN: '${{ github.token }}' });
				else
					expect(JSON.stringify(step), `${name}[${i}]`).not.toMatch(/github\.token|GITHUB_TOKEN/);
			});
		}
		expect(runIndex(jobs['e2e']!, FETCH_BASE)).toBe(-1);
		expect(runIndex(jobs['image']!, FETCH_BASE)).toBe(-1);
	});

	it('migration-compat always starts and runs ci:compat only when migrations/ changed', () => {
		const job = jobs['migration-compat']!;
		// No job-level condition: the job always runs, so it can be a required check.
		expect(job.if).toBeUndefined();
		const changes = job.steps.findIndex((s) => s.id === 'changes');
		expect(changes).toBeGreaterThan(usesIndex(job, 'actions/checkout'));
		expect(job.steps[changes]!.if).toBeUndefined();
		for (const step of job.steps.slice(changes + 1)) {
			expect(step.if).toBe("steps.changes.outputs.run == 'true'");
		}
	});
});

describe('stage scripts (X1)', () => {
	it('ci:check is lint, type check, db:check against the base, then the tests', () => {
		expect(scripts['ci:check']).toBe(
			'pnpm lint && pnpm check && node tools/ci/base-ref.ts db-check && pnpm test'
		);
	});

	it('lint fails on warnings (--max-warnings 0)', () => {
		expect(scripts['lint']).toMatch(/\beslint \. --max-warnings 0\b/);
		expect(runIndex(jobs['check']!, 'pnpm ci:check')).toBeGreaterThanOrEqual(0);
	});

	it('ci:e2e runs both browser projects, and the e2e job installs both browsers', () => {
		expect(scripts['ci:e2e']).toBe('playwright test --project chromium --project webkit');
		expect(runIndex(jobs['e2e']!, 'pnpm exec playwright install --with-deps chromium webkit')).toBe(
			runIndex(jobs['e2e']!, 'pnpm ci:e2e') - 2
		);
		const config = read('playwright.config.ts');
		expect(config).toMatch(/name: 'chromium'/);
		expect(config).toMatch(/name: 'webkit'/);
	});

	it('ci:compat and ci:local are the scripts of tools/ci', () => {
		expect(scripts['ci:compat']).toBe('bash tools/ci/migration-compat.sh');
		expect(scripts['ci:local']).toBe('bash tools/ci/local.sh');
		const local = read('tools/ci/local.sh');
		expect(local).toMatch(/^stages=\(ci:check ci:e2e test:infra ci:compat\)$/m);
	});
});

describe('the e2e report (OB12)', () => {
	it('is uploaded on failure, playwright-report/ and test-results/, kept 7 days', () => {
		const job = jobs['e2e']!;
		const upload = usesIndex(job, 'actions/upload-artifact');
		expect(upload).toBeGreaterThan(runIndex(job, 'pnpm ci:e2e'));
		const step = job.steps[upload]!;
		expect(step.if).toBe('failure()');
		const paths = String(step.with?.['path'])
			.split('\n')
			.map((p) => p.trim())
			.filter(Boolean);
		expect(paths.sort()).toEqual(['playwright-report/', 'test-results/']);
		expect(step.with?.['retention-days']).toBe(7);
	});
});

describe('the image job (PD14, D7, X2)', () => {
	const job = jobs['image']!;
	const infra = runIndex(job, 'pnpm test:infra');
	const BUILDS =
		/\bdocker\s+(?:image\s+)?build\b|\bbuildx\s+(?:build|bake)\b|\bcompose\b[^\n]*\bbuild\b|--build\b|\bci:image\b|\bdocker\s+(?:image\s+)?pull\b/;

	it('its only building step is pnpm test:infra; no separate ci:image, build or pull step', () => {
		expect(infra).toBeGreaterThanOrEqual(0);
		for (const [i, command] of runs(job).entries()) {
			if (i === infra) continue;
			expect(command).not.toMatch(BUILDS);
		}
		expect(job.steps[infra]!.run).toBe('pnpm test:infra');
	});

	it('has no service container: the infra global setup pulls db and caddy itself', () => {
		expect(job.services).toBeUndefined();
	});

	it('sets JADE_INFRA_RUN_ID, JADE_INFRA_KEEP_IMAGE=1 and the gha cache for test:infra', () => {
		const env = job.steps[infra]!.env ?? {};
		expect(env['JADE_INFRA_RUN_ID']).toBe('${{ github.run_id }}-${{ github.run_attempt }}');
		expect(env['JADE_INFRA_KEEP_IMAGE']).toBe('1');
		expect(env['JADE_CI_IMAGE_CACHE']).toBe('gha');
	});

	it('sets up buildx and the Actions runtime variables before test:infra, building nothing', () => {
		for (const action of ['docker/setup-buildx-action', 'crazy-max/ghaction-github-runtime']) {
			const i = usesIndex(job, action);
			expect(i, action).toBeGreaterThanOrEqual(0);
			expect(i, action).toBeLessThan(infra);
			expect(job.steps[i]!.uses).toMatch(/@[0-9a-f]{40}$/);
			expect(job.steps[i]!.with ?? {}).not.toHaveProperty('push');
		}
	});

	it('pushes, if at all, the tag test:infra kept, and builds nothing after test:infra (Z3)', () => {
		expect(infra).toBeGreaterThanOrEqual(0);
		job.steps.forEach((step, i) => {
			const body = `${step.uses ?? ''}\n${step.run ?? ''}`;
			if (/\bdocker\s+(?:image\s+)?push\b|build-push-action/.test(body)) {
				expect(i).toBeGreaterThan(infra);
				expect(step.run ?? '').toContain('test-results/infra-image-tag.txt');
			}
			if (i > infra) expect(body).not.toMatch(BUILDS);
		});
	});
});

describe('actionlint', () => {
	const dockerUp =
		spawnSync('docker', ['version', '--format', '{{.Server.Version}}'], {
			stdio: 'ignore',
			timeout: 20_000
		}).status === 0;
	const inCi = process.env['CI'] === 'true';
	const title = dockerUp
		? `the workflow passes actionlint (${ACTIONLINT_IMAGE})`
		: `SKIPPED: Docker is not available, so actionlint (${ACTIONLINT_IMAGE}) did not run`;

	it.skipIf(!dockerUp && !inCi)(
		title,
		() => {
			expect(dockerUp, 'Docker is required in CI').toBe(true);
			const result = spawnSync(
				'docker',
				[
					'run',
					'--rm',
					'--quiet',
					'--network',
					'none',
					'-v',
					`${join(root, '.github')}:/repo/.github:ro`,
					'-w',
					'/repo',
					ACTIONLINT_IMAGE,
					'-no-color',
					WORKFLOW
				],
				{ encoding: 'utf8', timeout: 170_000 }
			);
			// actionlint prints its findings on stdout, nothing when the file is clean.
			expect(result.stdout).toBe('');
			expect(result.status, result.stderr).toBe(0);
		},
		180_000
	);
});
