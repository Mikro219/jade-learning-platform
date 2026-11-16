import { defineConfig, devices } from '@playwright/test';
import { freePort } from './tools/free-port.ts';
import { loadEnv } from './tools/load-env.ts';

// `.env` outside production (plan V6). The server under test never sees it: the webServer command
// starts `node build` through tests/support/server.ts, which gives it an explicit environment of
// the harness's APP_ENV=test values (V8), whatever this process's environment holds.
loadEnv();

// The port is chosen once, by the process that loads this config first, and handed to the
// workers (which load it again) through the environment (plan H6, PD11).
const PORT_VAR = 'JADE_E2E_PORT';
if (!process.env[PORT_VAR]) {
	process.env[PORT_VAR] = String(await freePort());
}
const port = Number(process.env[PORT_VAR]);
const origin = `http://127.0.0.1:${port}`;

// Build with Vite and start the built server, both with the Node running this config
// (the project's pinned Node), never a bare `node` from PATH.
const node = JSON.stringify(process.execPath);

export default defineConfig({
	testDir: 'tests/e2e',
	testMatch: '**/*.spec.ts',
	forbidOnly: !!process.env.CI,
	retries: 0,
	reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
	use: {
		baseURL: origin,
		trace: 'retain-on-failure'
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } }
		},
		{
			name: 'webkit',
			use: { ...devices['iPad (gen 7)'] }
		}
	],
	webServer: {
		command: `${node} node_modules/vite/bin/vite.js build && ${node} tests/support/server.ts --port ${port} --origin ${origin}`,
		url: `${origin}/`,
		reuseExistingServer: false,
		timeout: 180_000
	}
});
