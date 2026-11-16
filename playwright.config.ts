import { defineConfig, devices } from '@playwright/test';
import { withDatabase } from './src/lib/server/db/index.ts';
import { newRunId } from './tests/support/global-setup-db.ts';
import { CLI_READY } from './tests/support/server.ts';
import { freePort } from './tools/free-port.ts';
import { loadEnv } from './tools/load-env.ts';

// `.env` outside production (plan V6). The server under test never sees it: the webServer command
// starts `node build` through tests/support/server.ts, which gives it an explicit environment of
// the harness's APP_ENV=test values (V8) and the e2e database's URL, whatever this process's
// environment holds.
loadEnv();

// The port is chosen once, by the process that loads this config first, and handed to the
// workers (which load it again) through the environment (plan H6, PD11). It is the server's first
// attempt only: if another process takes it before the server listens, tests/support/server.ts
// retries on a new port, and the webServer's `wait.stdout` (CLI_READY) writes the port the server
// actually listens on back into JADE_E2E_PORT before any worker starts (jade-r7c).
const PORT_VAR = 'JADE_E2E_PORT';
if (!process.env[PORT_VAR]) {
	process.env[PORT_VAR] = String(await freePort());
}
const port = Number(process.env[PORT_VAR]);
const origin = `http://127.0.0.1:${port}`;

// The server under test gets a database of this run, `jade_e2e_<run id>` (plan U7), named here,
// once, so the webServer (started before global setup) and the global setup that creates and
// migrates it agree. It is on the development cluster, reached with DATABASE_URL's role and
// password, so the role bootstrap never changes jade_app there (PD12).
const DB_VAR = 'JADE_E2E_DATABASE';
if (!process.env[DB_VAR]) {
	process.env[DB_VAR] = `jade_e2e_${newRunId()}`;
}
const appUrl = process.env['DATABASE_URL'];
const serverEnv: Record<string, string> = appUrl
	? { JADE_E2E_DATABASE_URL: withDatabase(appUrl, process.env[DB_VAR]!) }
	: {};

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
	globalSetup: './tests/support/global-setup-e2e.ts',
	webServer: {
		command: `${node} node_modules/vite/bin/vite.js build && ${node} tests/support/server.ts --port ${port}`,
		env: serverEnv,
		// Ready when the server under test says so on its own stdout, never when something answers
		// on the port: a process that bound the port during the build is not this server (PD11).
		// No `url` or `port` here: Playwright would race it against `wait` and take the first.
		wait: { stdout: CLI_READY },
		reuseExistingServer: false,
		timeout: 180_000
	}
});
