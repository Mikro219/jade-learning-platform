// Playwright's global setup (plan U7): create and migrate one database, `jade_e2e_<run id>`, for
// the server under test, and drop it at teardown. playwright.config.ts names the database before
// the webServer starts and hands its URL to tests/support/server.ts; the server connects only
// when a request needs the database, and requests start after this setup has finished.
import { DbError } from '../../src/lib/server/db/index.ts';
import { clusterConfig, createMigratedDatabase, dropDatabase } from './global-setup-db.ts';

export default async function setup(): Promise<() => Promise<void>> {
	const name = process.env['JADE_E2E_DATABASE'];
	if (name === undefined || !/^jade_e2e_[a-z0-9]+$/.test(name)) {
		throw new Error('JADE_E2E_DATABASE is not set by playwright.config.ts');
	}
	const config = clusterConfig();
	try {
		await createMigratedDatabase(config, name);
	} catch (err) {
		await dropDatabase(config.migrationDatabaseUrl, name).catch(() => {});
		// eslint-disable-next-line preserve-caught-error -- the cause can carry a URL or a server message (INV4)
		if (err instanceof DbError) throw new Error(`e2e database: ${err.tag}`);
		throw err;
	}
	return async () => {
		await dropDatabase(config.migrationDatabaseUrl, name);
	};
}
