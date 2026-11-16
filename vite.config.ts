import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { loadEnv } from './tools/load-env.ts';

// `.env` outside production (plan V6), so `pnpm dev` has the app's configuration. The build itself
// reads no secret: the init hook checks nothing while building (V3).
loadEnv();

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter(),
			version: { name: process.env.APP_VERSION ?? 'dev' }
		})
	],
	test: {
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'unit',
					environment: 'node',
					include: ['tests/unit/**/*.test.ts', 'src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			},
			{
				// Black-box checks of the built server (plan PD9). They build the app themselves.
				test: {
					name: 'blackbox',
					environment: 'node',
					include: ['tests/blackbox/**/*.test.ts'],
					expect: { requireAssertions: true },
					testTimeout: 30_000,
					hookTimeout: 240_000
				}
			}
		]
	}
});
