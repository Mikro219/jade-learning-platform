// Environments for a server under test (plan V8). Every value is passed explicitly: nothing is
// copied from process.env or from a developer's .env.
import { freePort } from '../../tools/free-port.ts';
import { appDatabaseUrl, generatePassword, generateSecret } from '../../tools/env-init.ts';

export type ServerEnv = Record<string, string>;

/**
 * The harness's values for `APP_ENV=test`. They hold `test-only`, which the config module refuses
 * under any other APP_ENV, as the CI job's values do. Until jade-urd gives a test a database,
 * `DATABASE_URL` names a port from freePort() that nothing listens on; nothing connects at start-up.
 */
export async function testEnv(options: { dbPort?: number } = {}): Promise<ServerEnv> {
	const port = options.dbPort ?? (await freePort());
	return {
		APP_ENV: 'test',
		DATABASE_URL: appDatabaseUrl('test-only-app-password', port),
		CODE_PEPPER: 'test-only-code-pepper-0123456789abcdefghijklmnopqrstuvwxyz',
		SESSION_SECRET: 'test-only-session-secret-0123456789abcdefghijklmnopqrstuvwxyz',
		LOG_LEVEL: 'info'
	};
}

/**
 * A generated environment for `APP_ENV` development, staging or production: fresh secrets and a
 * `DATABASE_URL` for role jade_app with a generated password at 127.0.0.1, on a port from
 * freePort() that nothing listens on. No `test-only` value can reach a boot that refuses it.
 */
export async function generatedEnv(
	appEnv: 'development' | 'staging' | 'production'
): Promise<ServerEnv> {
	return {
		APP_ENV: appEnv,
		DATABASE_URL: appDatabaseUrl(generatePassword(), await freePort()),
		CODE_PEPPER: generateSecret(),
		SESSION_SECRET: generateSecret(),
		LOG_LEVEL: 'info'
	};
}
