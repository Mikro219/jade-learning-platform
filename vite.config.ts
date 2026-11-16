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
				// Database tests (plan U7): each file gets its own database on the one cluster that
				// MIGRATION_DATABASE_URL names, cloned from a template global setup migrates once per run.
				test: {
					name: 'integration',
					environment: 'node',
					include: ['tests/integration/**/*.test.ts'],
					globalSetup: ['tests/support/global-setup-db.ts'],
					expect: { requireAssertions: true },
					testTimeout: 60_000,
					hookTimeout: 180_000
				}
			},
			{
				// Black-box checks of the built server (plan PD9). Global setup builds the app once per
				// run with an empty environment (jade-b1f), and gives health.test.ts the database
				// harness of U7.
				test: {
					name: 'blackbox',
					environment: 'node',
					include: ['tests/blackbox/**/*.test.ts'],
					globalSetup: [
						'tests/support/global-setup-blackbox.ts',
						'tests/support/global-setup-db.ts'
					],
					expect: { requireAssertions: true },
					testTimeout: 30_000,
					hookTimeout: 240_000
				}
			}
		]
	}
});
