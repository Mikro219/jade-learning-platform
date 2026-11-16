// INV9: one Node release, one pnpm, one Postgres 16 image, named everywhere they are pinned.
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const root = new URL('../../', import.meta.url);
const read = (path: string) => readFileSync(new URL(path, root), 'utf8');
const exists = (path: string) => existsSync(new URL(path, root));

interface PackageJson {
	packageManager?: string;
	engines?: { node?: string; pnpm?: string };
	devEngines?: { runtime?: { name?: string; version?: string; onFail?: string } };
}

const pkg = JSON.parse(read('package.json')) as PackageJson;
const nvmrc = read('.nvmrc').trim();

describe('Node pin', () => {
	it('.nvmrc names one exact Node 24 release', () => {
		expect(nvmrc).toMatch(/^24\.\d+\.\d+$/);
	});

	it('package.json devEngines.runtime and engines.node name the .nvmrc release', () => {
		expect(pkg.devEngines?.runtime).toEqual({ name: 'node', version: nvmrc, onFail: 'download' });
		expect(pkg.engines?.node).toBe(nvmrc);
	});

	it('the Node running the scripts is the pinned one', () => {
		expect(process.version).toBe(`v${nvmrc}`);
	});

	it.runIf(exists('Dockerfile'))('the Dockerfile names the same Node and pnpm', () => {
		const dockerfile = read('Dockerfile');
		expect(dockerfile).toMatch(
			new RegExp(`^ARG NODE_VERSION=${nvmrc.replaceAll('.', '\\.')}$`, 'm')
		);
		expect(dockerfile).toMatch(/^FROM node:\$\{NODE_VERSION\}-alpine\d+\.\d+/m);
		const pnpmVersion = pkg.packageManager?.replace(/^pnpm@/, '') ?? '';
		expect(dockerfile).toMatch(
			new RegExp(`^ARG PNPM_VERSION=${pnpmVersion.replaceAll('.', '\\.')}$`, 'm')
		);
	});
});

describe('pnpm pin', () => {
	it('packageManager names one exact pnpm 12 release inside engines.pnpm', () => {
		const match = /^pnpm@(12)\.(\d+)\.(\d+)$/.exec(pkg.packageManager ?? '');
		expect(match).not.toBeNull();
		expect(pkg.engines?.pnpm).toBe(`>=${pkg.packageManager?.replace(/^pnpm@/, '')} <13`);
	});

	it('pnpm-workspace.yaml makes engines strict', () => {
		expect(read('pnpm-workspace.yaml')).toMatch(/^engineStrict: true$/m);
	});
});

describe('Postgres pin', () => {
	// compose.dev.yml exists from jade-urd on; the other two join when jade-80h and jade-xu0 add them.
	const files = ['compose.dev.yml', 'compose.prod.yml', '.github/workflows/ci.yml'].filter(exists);

	it('compose.dev.yml exists and names a Postgres image', () => {
		expect(files).toContain('compose.dev.yml');
		expect(read('compose.dev.yml')).toMatch(/^\s*image:\s*postgres:16\.\d+-bookworm\s*$/m);
	});

	it('every file that names Postgres names one Postgres 16 image', () => {
		const images = new Set<string>();
		for (const file of files) {
			for (const m of read(file).matchAll(/\bpostgres:[\w.-]+/g)) images.add(m[0]);
		}
		expect(images.size).toBe(1);
		expect([...images][0]).toMatch(/^postgres:16\.\d+-/);
	});
});

describe('app build settings', () => {
	it('vite.config.ts uses adapter-node', () => {
		expect(read('vite.config.ts')).toMatch(/from '@sveltejs\/adapter-node'/);
	});

	it('tsconfig.json is strict', () => {
		const tsconfig = JSON.parse(read('tsconfig.json')) as {
			compilerOptions?: Record<string, unknown>;
		};
		expect(tsconfig.compilerOptions?.strict).toBe(true);
		expect(tsconfig.compilerOptions?.noUncheckedIndexedAccess).toBe(true);
	});

	it('TypeScript resolves to 6.0.x', () => {
		const require = createRequire(new URL('package.json', root));
		const { version } = require('typescript/package.json') as { version: string };
		expect(version).toMatch(/^6\.0\.\d+$/);
	});
});
