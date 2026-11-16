// The infra project's global setup (plan D7, PD14). Once per run, before any test file starts:
//   1. pull the stack's third-party images (every service whose resolved image is not the run's
//      app image: today db and caddy), explicitly, because every later `up` passes --pull never;
//   2. build the run's app image once, by calling `pnpm ci:image` (docker buildx bake on the `app`
//      stanza of compose.prod.yml) with JADE_IMAGE set to jade-app:ci-<checkout hash>-<run id>,
//      on the current buildx builder;
//   3. fail the run unless both exited 0 and `docker image inspect` finds each pinned image and
//      the run's tag.
// It hands the run id, the tag and the builder to every test file (inject('jadeInfra'), and
// JADE_IMAGE and BUILDX_BUILDER in the environment). At teardown it removes the tag, unless
// JADE_INFRA_KEEP_IMAGE=1 (CI, for the push of plan Z3): then it writes the tag to
// test-results/infra-image-tag.txt.
//
// The run id is JADE_INFRA_RUN_ID when set (CI), otherwise 16 random hex digits. Before it starts
// and at teardown it runs `down -v` on every Compose project of this run that Docker still lists
// (jade-infra-<this run id>-<suffix>, matched exactly against INFRA_PROJECT_SUFFIXES) and removes
// media.test.ts's throwaway container, so an interrupted test file leaves nothing.
// JADE_CI_IMAGE_CACHE=gha adds the GitHub Actions cache flags to `pnpm ci:image` (plan X2).
import { randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { TestProject } from 'vitest/node';
import {
	checkoutHash,
	imageCacheArgs,
	run,
	thirdPartyServices,
	type ComposeConfig
} from '../../tools/compose.ts';
import {
	INFRA_PROJECT_SUFFIXES,
	MEDIA_FILES_LABEL,
	composeOn,
	docker,
	dockerEnv,
	downProject,
	envInit,
	exec,
	infraProject,
	mediaFilesContainer,
	root,
	tempDir,
	type InfraContext
} from '../support/infra.ts';

/** A new infra run id: 16 random hex digits. */
export function newInfraRunId(): string {
	return randomBytes(8).toString('hex');
}

/** The run id: JADE_INFRA_RUN_ID (lower-cased; letters, digits, hyphens) or a new one. */
export function infraRunId(env: Readonly<Record<string, string | undefined>>): string {
	const given = env['JADE_INFRA_RUN_ID'];
	if (given === undefined || given === '') return newInfraRunId();
	const id = given.toLowerCase();
	if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(id)) {
		throw new Error('JADE_INFRA_RUN_ID must be letters, digits and hyphens, at most 40');
	}
	return id;
}

/** The run's app image tag (D7): used by one checkout and one run only. */
export function infraImageTag(hash: string, runId: string): string {
	return `jade-app:ci-${hash}-${runId}`;
}

/** The current buildx builder's name. */
async function currentBuilder(): Promise<string> {
	const r = await docker(['buildx', 'inspect']);
	const name = /^Name:\s*(\S+)/m.exec(r.stdout)?.[1];
	if (r.code !== 0 || name === undefined) throw new Error('infra setup: no buildx builder');
	return name;
}

/** The limit on the one image build of a run, in milliseconds. */
const CI_IMAGE_TIMEOUT_MS = 20 * 60 * 1000;

/**
 * `pnpm ci:image` with JADE_IMAGE and BUILDX_BUILDER set, plus the cache flags
 * JADE_CI_IMAGE_CACHE selects (imageCacheArgs; `gha` in CI); its output only on failure. It runs
 * through run() in tools/compose.ts, in a process group of its own: a build still running after
 * CI_IMAGE_TIMEOUT_MS is stopped as a whole group (pnpm, node and `docker buildx bake`), and the
 * result (code 124) comes only once the group is gone.
 */
function ciImage(image: string, builder: string, cacheArgs: readonly string[]) {
	const env: Record<string, string | undefined> = {
		...process.env,
		JADE_IMAGE: image,
		BUILDX_BUILDER: builder
	};
	delete env['COMPOSE_PROJECT_NAME'];
	return run('pnpm', ['ci:image', ...cacheArgs], env, {
		timeoutMs: CI_IMAGE_TIMEOUT_MS,
		quiet: true
	});
}

/**
 * Whether `name` is a Compose project of this infra run: exactly jade-infra-<run id>-<suffix>,
 * with one of the suffixes the infra run uses (INFRA_PROJECT_SUFFIXES). A run id that is a
 * hyphenated prefix of another (`123` and `123-1`) cannot match the other's projects.
 */
export function isRunProject(name: string, runId: string): boolean {
	return INFRA_PROJECT_SUFFIXES.some((suffix) => name === infraProject(suffix, runId));
}

/**
 * Remove what this run may have left (an interrupted run, a crashed test file), each by its exact
 * name: every Compose project Docker lists that isRunProject() accepts (`down -v`), and
 * media.test.ts's throwaway Caddy container (its exact name and label). Never a broader prefix:
 * another run's or another checkout's resources are not this run's to remove.
 */
async function sweepRun(runId: string): Promise<void> {
	const ls = await exec('docker', ['compose', 'ls', '-a', '--format', 'json'], dockerEnv(), 60_000);
	let listed: { Name?: unknown }[] = [];
	if (ls.code === 0) {
		try {
			const parsed = JSON.parse(ls.stdout || '[]') as unknown;
			if (Array.isArray(parsed)) listed = parsed as { Name?: unknown }[];
		} catch {
			listed = [];
		}
	}
	for (const { Name } of listed) {
		if (typeof Name === 'string' && isRunProject(Name, runId)) await downProject(Name);
	}
	const name = mediaFilesContainer(runId);
	const found = await docker([
		'ps',
		'-a',
		'-q',
		'--filter',
		`name=^/${name}$`,
		'--filter',
		`label=${MEDIA_FILES_LABEL}`
	]);
	if (found.stdout.trim() !== '') await docker(['rm', '-f', '-v', name]);
}

export default async function setup(project: TestProject) {
	const runId = infraRunId(process.env);
	const hash = checkoutHash();
	const image = infraImageTag(hash, runId);
	const builder = await currentBuilder();
	// Refused before anything starts: a value other than unset, empty or `gha`.
	const cacheArgs = imageCacheArgs(process.env);
	// A run id given twice (CI's re-run of the same attempt) finds its own leftovers here.
	await sweepRun(runId);

	// The pull needs an env file for interpolation; a throwaway one, removed at once.
	const { dir, remove } = tempDir('pull');
	try {
		const envFile = join(dir, '.env');
		const init = await envInit(['--out', envFile, '--http-port', '80', '--https-port', '443']);
		if (init.code !== 0) throw new Error(`infra setup: env:init failed: ${init.stderr}`);
		const pullProject = infraProject('pull', runId);
		const config = await composeOn(pullProject, envFile, ['config', '--format', 'json'], [], image);
		if (config.code !== 0) throw new Error('infra setup: docker compose config failed');
		const parsed = JSON.parse(config.stdout) as ComposeConfig;
		const services = thirdPartyServices(parsed, image);
		const pinned = services.map((name) => parsed.services[name]!.image!);
		process.stdout.write(`infra setup: pulling ${services.join(', ')} (${pinned.join(', ')})\n`);
		const pull = await composeOn(pullProject, envFile, ['pull', ...services], [], image);
		process.stdout.write(pull.stdout + pull.stderr);
		if (pull.code !== 0) throw new Error(`infra setup: pull exited ${pull.code}`);

		process.stdout.write(`infra setup: building ${image} with pnpm ci:image on ${builder}\n`);
		const build = await ciImage(image, builder, cacheArgs);
		if (build.code !== 0) {
			// On a timeout run() returns only once the build's process group is gone, so a tag
			// loaded at the last moment is removed here too.
			await docker(['image', 'rm', image]);
			throw new Error(
				`infra setup: pnpm ci:image exited ${build.code}\n${build.output.slice(-8000)}`
			);
		}
		for (const ref of [...pinned, image]) {
			const found = await docker(['image', 'inspect', '--format', '{{.Id}}', ref]);
			if (found.code !== 0) {
				// The run's own tag only; the pinned third-party tags are never removed here.
				await docker(['image', 'rm', image]);
				throw new Error(`infra setup: image ${ref} not found after setup`);
			}
		}
	} finally {
		remove();
	}

	const context: InfraContext = { runId, checkoutHash: hash, image, builder };
	project.provide('jadeInfra', context);
	process.env['JADE_IMAGE'] = image;
	process.env['BUILDX_BUILDER'] = builder;

	return async () => {
		try {
			// Stacks a crashed or interrupted test file left behind, this run's only.
			await sweepRun(runId);
		} finally {
			// Whatever the sweep did, the tag is kept or removed.
			if (process.env['JADE_INFRA_KEEP_IMAGE'] === '1') {
				const out = join(root, 'test-results');
				mkdirSync(out, { recursive: true });
				writeFileSync(join(out, 'infra-image-tag.txt'), `${image}\n`);
			} else {
				await docker(['image', 'rm', image]);
			}
		}
	};
}
