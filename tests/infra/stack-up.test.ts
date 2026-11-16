// The build path of `pnpm stack:up` and of the bare README command (plan D7, PD14): the function
// `pnpm stack:up` runs (stackUp in tools/compose.ts), with only the project, the env file and
// JADE_IMAGE replaced, the last by jade-app:build-<checkout hash>-<run id>, a tag that does not
// exist before the test, and with an APP_VERSION of its own. Compose builds the image from the
// `build:` stanza of `app` in compose.prod.yml, on the run's buildx builder.
import { randomBytes } from 'node:crypto';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { stackUp } from '../../tools/compose.ts';
import {
	docker,
	dockerEnv,
	httpsGet,
	infraContext,
	inspect,
	ledger,
	serviceContainer,
	startStack,
	stopStack,
	type Stack
} from '../support/infra.ts';

const appVersion = `stackup-${randomBytes(4).toString('hex')}`;
let tag: string;
let stack: Stack;
let ca: string;
let tagExistedBefore = true;

beforeAll(async () => {
	const { checkoutHash, runId, builder } = infraContext();
	tag = `jade-app:build-${checkoutHash}-${runId}`;
	tagExistedBefore = (await docker(['image', 'inspect', tag])).code === 0;
	if (tagExistedBefore) throw new Error(`${tag} exists before the test`);
	stack = await startStack('stackup', async (s) => {
		const r = await stackUp({
			project: s.project,
			envFile: s.envFile,
			image: tag,
			env: dockerEnv({ BUILDX_BUILDER: builder, APP_VERSION: appVersion }),
			// The build and the wait together stay inside the infra hookTimeout (15 min).
			timeoutMs: 600_000
		});
		return { code: r.code, stdout: r.output, stderr: '' };
	});
	ca = await stack.ca();
});
afterAll(async () => {
	await stopStack('stackup', stack);
	if (tag && !tagExistedBefore) await docker(['image', 'rm', tag]);
});

describe('pnpm stack:up', () => {
	it('builds the tag it was given', async () => {
		expect(tagExistedBefore).toBe(false);
		expect((await docker(['image', 'inspect', '--format', '{{.Id}}', tag])).code).toBe(0);
	});

	it("app and migrate run that tag's image", async () => {
		const id = (await docker(['image', 'inspect', '--format', '{{.Id}}', tag])).stdout.trim();
		for (const service of ['app', 'migrate']) {
			const image = await inspect<string>(await serviceContainer(stack.project, service), '.Image');
			expect({ service, image }).toEqual({ service, image: id });
		}
	});

	it('/healthz through Caddy reports the APP_VERSION the build was given', async () => {
		const r = await httpsGet(stack.httpsPort, '/healthz', { ca });
		expect(r.status).toBe(200);
		expect(JSON.parse(r.body)).toEqual({ status: 'ok', version: appVersion });
	});

	it('the ledger holds the baseline', async () => {
		expect(await ledger(stack)).toEqual(['0000_baseline']);
	});
});
