import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { loadEnv } from './tools/load-env.ts';

// `.env` outside production (plan V6), so `pnpm dev` has the app's configuration.
loadEnv();

// loadEnv() is not the only reader of `.env`: SvelteKit itself calls Vite's loadEnv() on `env.dir`
// (default: the project root) for `$env/*`, and Vite core reads `envDir` (default: the root) for
// `import.meta.env`, both whatever NODE_ENV is. JADE_BUILD_ENV_DIR, set only by the blackbox build
// (tests/support/global-setup-blackbox.ts) to an empty directory, points both there, so that build
// sees no env file at all (V3, jade-7yz). Unset (`pnpm dev`, `pnpm build`), both keep their
// defaults.
const buildEnvDir = process.env['JADE_BUILD_ENV_DIR'] || undefined;

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter(),
			version: { name: process.env.APP_VERSION ?? 'dev' },
			...(buildEnvDir === undefined ? {} : { env: { dir: buildEnvDir } })
		})
	],
	...(buildEnvDir === undefined ? {} : { envDir: buildEnvDir }),
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
				// run with NODE_ENV=production and JADE_BUILD_ENV_DIR at an empty directory, so no env
				// file is read, neither by loadEnv() nor by SvelteKit or Vite (jade-b1f, jade-7yz),
				// and gives health.test.ts the database harness of U7.
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
			},
			{
				// The image and the production Compose stack (plan section 11), `pnpm test:infra` only:
				// `pnpm test` excludes this project. Global setup pulls the pinned third-party images
				// and builds the run's image once through `pnpm ci:image` (D7). Files run one at a time:
				// each brings up a whole stack of its own.
				test: {
					name: 'infra',
					environment: 'node',
					include: ['tests/infra/**/*.test.ts'],
					globalSetup: ['tests/infra/global-setup.ts'],
					expect: { requireAssertions: true },
					fileParallelism: false,
					testTimeout: 180_000,
					hookTimeout: 900_000
				}
			}
		]
	}
});
