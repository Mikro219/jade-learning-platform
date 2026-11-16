// The blackbox project's global setup (jade-b1f): `vite build` runs once per run, before any
// black-box file starts, so parallel files never race on build/. It runs on the pinned Node with
// nothing in the environment, which is also the check that the build needs no secret (V3).
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const root = fileURLToPath(new URL('../../', import.meta.url));

export default async function setup(): Promise<void> {
	await promisify(execFile)(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
		cwd: root,
		env: {},
		maxBuffer: 64 * 1024 * 1024
	});
}
