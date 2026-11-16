// /media (plan D5, C1, INV7): closed with 403 through the stack until jade-u8z adds the signed-URL
// entitlement check; and deploy/caddy/media-files.caddy, which the site block does not import,
// serves byte ranges when a Caddy imports it (here a throwaway container over a fixture file).
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { freePort } from '../../tools/free-port.ts';
import {
	docker,
	httpGet,
	httpsGet,
	MEDIA_FILES_LABEL,
	mediaFilesContainer,
	isPortTaken,
	root,
	startStack,
	stopStack,
	tempDir,
	waitFor,
	type Stack
} from '../support/infra.ts';

describe('/media through the stack', () => {
	let stack: Stack;
	let ca: string;
	beforeAll(async () => {
		stack = await startStack('media');
		ca = await stack.ca();
	});
	afterAll(async () => {
		await stopStack('media', stack);
	});

	it('/media/x.mp4 is 403, with and without a Range header', async () => {
		const plain = await httpsGet(stack.httpsPort, '/media/x.mp4', { ca });
		expect(plain.status).toBe(403);
		const ranged = await httpsGet(stack.httpsPort, '/media/x.mp4', {
			ca,
			headers: { range: 'bytes=0-99' }
		});
		expect(ranged.status).toBe(403);
		expect(ranged.headers['content-range']).toBeUndefined();
	});
});

describe('media-files.caddy in a throwaway Caddy', () => {
	const fixture = Buffer.from(Array.from({ length: 1000 }, (_, i) => i % 251));
	let name: string;
	let port: number;
	let remove: () => void;

	beforeAll(async () => {
		const tmp = tempDir('media');
		remove = tmp.remove;
		writeFileSync(join(tmp.dir, 'x.mp4'), fixture);
		name = mediaFilesContainer();
		// Whatever an interrupted earlier start of this exact container left behind.
		await docker(['rm', '-f', '-v', name]);
		// The Caddy image compose.prod.yml pins; `docker run` pulls it if it is missing.
		const image = /^\s*image:\s*(caddy:\S+)\s*$/m.exec(
			readFileSync(join(root, 'compose.prod.yml'), 'utf8')
		)![1]!;
		for (let attempt = 1; attempt <= 3; attempt++) {
			port = await freePort();
			const r = await docker([
				'run',
				'-d',
				'--name',
				name,
				'--label',
				MEDIA_FILES_LABEL,
				'-p',
				`127.0.0.1:${port}:8080`,
				'-v',
				`${join(root, 'tests/infra/fixtures/caddy/Caddyfile')}:/etc/caddy/Caddyfile:ro`,
				'-v',
				`${join(root, 'deploy/caddy/media-files.caddy')}:/etc/caddy/media-files.caddy:ro`,
				'-v',
				`${tmp.dir}:/srv/media:ro`,
				image
			]);
			if (r.code === 0) break;
			await docker(['rm', '-f', name]);
			// A port taken in between is retried with a new one, at most three times (PD11).
			if (!isPortTaken(r.stderr) || attempt === 3) {
				throw new Error(`docker run failed: ${r.stderr}`);
			}
		}
		const up = await waitFor(
			async () => (await httpGet(port, '/media/x.mp4')).status === 200,
			30_000
		);
		if (!up) throw new Error('the throwaway Caddy did not serve the fixture');
	});
	afterAll(async () => {
		await docker(['rm', '-f', '-v', name]).catch(() => {});
		remove?.();
	});

	it('answers Range: bytes=0-99 with 206 and the right Content-Range', async () => {
		const r = await httpGet(port, '/media/x.mp4', { range: 'bytes=0-99' });
		expect(r.status).toBe(206);
		expect(r.headers['content-range']).toBe(`bytes 0-99/${fixture.length}`);
		expect(Buffer.from(r.body, 'latin1')).toEqual(fixture.subarray(0, 100));
	});
});
