// `pnpm env:init` (plan V5). Grows with the variables each bead adds: jade-urd added the database
// owner's variables and the `ci` profile; jade-80h adds the stack's variables and the `stack`
// profile.
import { execFile } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createServer, type Server } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEnv, promisify } from 'node:util';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { loadAppConfig, loadMigrationConfig } from '../../src/lib/server/config/index.ts';
import { errorCodeOf, tempEnvFileName, writeEnvFile } from '../../tools/env-init.ts';

const run = promisify(execFile);
const root = fileURLToPath(new URL('../../', import.meta.url));
const tool = join(root, 'tools/env-init.ts');

const DEV_NAMES = [
	'APP_ENV',
	'JADE_OWNER_DB_PASSWORD',
	'JADE_APP_DB_PASSWORD',
	'JADE_DEV_DB_PORT',
	'MIGRATION_DATABASE_URL',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET',
	'LOG_LEVEL'
];
const CI_NAMES = [
	'APP_ENV',
	'JADE_OWNER_DB_PASSWORD',
	'JADE_APP_DB_PASSWORD',
	'MIGRATION_DATABASE_URL',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET',
	'LOG_LEVEL'
];
const GENERATED = [
	'JADE_OWNER_DB_PASSWORD',
	'JADE_APP_DB_PASSWORD',
	'MIGRATION_DATABASE_URL',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET'
];
const CI_GENERATED = GENERATED.filter((name) => name !== 'JADE_OWNER_DB_PASSWORD');
const CI_OWNER_PASSWORD = 'ci-test-only-owner-password';

interface Result {
	code: number;
	stdout: string;
	stderr: string;
}

/** Run the tool with an explicit environment, empty by default: nothing from this process's env. */
async function envInitWith(env: Record<string, string>, ...args: string[]): Promise<Result> {
	try {
		const { stdout, stderr } = await run(process.execPath, [tool, ...args], { cwd: dir, env });
		return { code: 0, stdout, stderr };
	} catch (err) {
		const e = err as { code: number; stdout: string; stderr: string };
		return { code: e.code, stdout: e.stdout, stderr: e.stderr };
	}
}

const envInit = (...args: string[]) => envInitWith({}, ...args);

let dir: string;
beforeEach(() => {
	dir = mkdtempSync(join(tmpdir(), 'jade-env-init-'));
});
afterEach(() => {
	rmSync(dir, { recursive: true, force: true });
});

function readEnv(path: string): Record<string, string> {
	return parseEnv(readFileSync(path, 'utf8')) as Record<string, string>;
}

function assertNoValuePrinted(
	result: Result,
	values: Record<string, string>,
	names: readonly string[] = GENERATED
) {
	for (const name of names) {
		expect(result.stdout).not.toContain(values[name]);
		expect(result.stderr).not.toContain(values[name]);
	}
}

describe('dev profile', () => {
	it('writes a mode-600 file with exactly the profile names, and the URL agrees', async () => {
		const out = join(dir, '.env');
		const result = await envInit('--out', out);
		expect(result.code).toBe(0);
		expect(statSync(out).mode & 0o777).toBe(0o600);

		const env = readEnv(out);
		expect(Object.keys(env).sort()).toEqual([...DEV_NAMES].sort());
		expect(env.APP_ENV).toBe('development');
		expect(env.LOG_LEVEL).toBe('info');

		const url = new URL(env.DATABASE_URL!);
		expect(url.protocol).toBe('postgres:');
		expect(url.username).toBe('jade_app');
		expect(url.password).toBe(env.JADE_APP_DB_PASSWORD);
		expect(url.host).toBe(`127.0.0.1:${env.JADE_DEV_DB_PORT}`);
		expect(url.pathname).toBe('/jade');

		const owner = new URL(env.MIGRATION_DATABASE_URL!);
		expect(owner.protocol).toBe('postgres:');
		expect(owner.username).toBe('jade_owner');
		expect(owner.password).toBe(env.JADE_OWNER_DB_PASSWORD);
		expect(owner.host).toBe(`127.0.0.1:${env.JADE_DEV_DB_PORT}`);
		expect(owner.pathname).toBe('/jade');
		// No query string or fragment, which the config schemas refuse (jade-f1w).
		for (const value of [env.DATABASE_URL!, env.MIGRATION_DATABASE_URL!]) {
			expect(value).not.toMatch(/[?#]/);
		}

		expect(env.JADE_APP_DB_PASSWORD).toMatch(/^[A-Za-z0-9_-]{32,}$/);
		expect(env.JADE_OWNER_DB_PASSWORD).toMatch(/^[A-Za-z0-9_-]{32,}$/);
		expect(env.JADE_OWNER_DB_PASSWORD).not.toBe(env.JADE_APP_DB_PASSWORD);
		expect(env.CODE_PEPPER).not.toBe(env.SESSION_SECRET);
		// The file is a configuration the app and the migration tool accept as it stands.
		expect(loadAppConfig(env).appEnv).toBe('development');
		expect(loadMigrationConfig(env).appEnv).toBe('development');

		// Names only on the output, never a value.
		expect(result.stdout).toContain(DEV_NAMES.join(', '));
		assertNoValuePrinted(result, env);
	});

	it('takes --db-port when given', async () => {
		const out = join(dir, 'given.env');
		expect((await envInit('--out', out, '--db-port', '6543')).code).toBe(0);
		const env = readEnv(out);
		expect(env.JADE_DEV_DB_PORT).toBe('6543');
		expect(new URL(env.DATABASE_URL!).port).toBe('6543');
		expect(new URL(env.MIGRATION_DATABASE_URL!).port).toBe('6543');
	});

	it('chooses another port when 5432 is held', async () => {
		// Hold 5432 with a listener of our own; if something else already holds it, that serves too.
		const server: Server = createServer((socket) => socket.end());
		await new Promise<void>((resolve) => {
			server.once('error', () => resolve());
			server.listen(5432, '127.0.0.1', () => resolve());
		});
		try {
			const out = join(dir, 'held.env');
			expect((await envInit('--out', out)).code).toBe(0);
			const port = Number(readEnv(out).JADE_DEV_DB_PORT);
			expect(port).not.toBe(5432);
			expect(port).toBeGreaterThan(0);
		} finally {
			await new Promise<void>((resolve) =>
				server.listening ? server.close(() => resolve()) : resolve()
			);
		}
	});

	it('two runs generate different secrets', async () => {
		await envInit('--out', join(dir, 'a.env'), '--db-port', '6000');
		await envInit('--out', join(dir, 'b.env'), '--db-port', '6000');
		const a = readEnv(join(dir, 'a.env'));
		const b = readEnv(join(dir, 'b.env'));
		for (const name of GENERATED) expect(a[name]).not.toBe(b[name]);
	});
});

describe('ci profile', () => {
	it('APP_ENV=test, the owner password from the environment, generated app values', async () => {
		const out = join(dir, '.env');
		const result = await envInitWith(
			{ JADE_OWNER_DB_PASSWORD: CI_OWNER_PASSWORD },
			'--out',
			out,
			'--profile',
			'ci',
			'--db-port',
			'54321'
		);
		expect(result.code).toBe(0);
		expect(statSync(out).mode & 0o777).toBe(0o600);

		const env = readEnv(out);
		expect(Object.keys(env).sort()).toEqual([...CI_NAMES].sort());
		expect(env.APP_ENV).toBe('test');
		expect(env.JADE_OWNER_DB_PASSWORD).toBe(CI_OWNER_PASSWORD);
		// No stack variable and no development port.
		expect(Object.keys(env).filter((k) => /STACK|SITE|HTTP|ORIGIN|DEV_DB_PORT/.test(k))).toEqual(
			[]
		);

		const owner = new URL(env.MIGRATION_DATABASE_URL!);
		expect(owner.username).toBe('jade_owner');
		expect(owner.password).toBe(CI_OWNER_PASSWORD);
		expect(owner.host).toBe('127.0.0.1:54321');
		const app = new URL(env.DATABASE_URL!);
		expect(app.username).toBe('jade_app');
		expect(app.password).toBe(env.JADE_APP_DB_PASSWORD);
		expect(app.host).toBe('127.0.0.1:54321');

		// Accepted under APP_ENV=test, as the CI job uses it.
		expect(loadAppConfig(env).appEnv).toBe('test');
		expect(loadMigrationConfig(env).appEnv).toBe('test');

		expect(result.stdout).toContain(CI_NAMES.join(', '));
		assertNoValuePrinted(result, env, CI_GENERATED);
		expect(result.stdout).not.toContain(CI_OWNER_PASSWORD);
	});

	it('refuses an owner password without test-only, or none, and writes nothing', async () => {
		const out = join(dir, '.env');
		const envs: Record<string, string>[] = [{ JADE_OWNER_DB_PASSWORD: 'CanaryOwnerPassword' }, {}];
		for (const env of envs) {
			const result = await envInitWith(env, '--out', out, '--profile', 'ci', '--db-port', '5000');
			expect(result.code).toBe(1);
			expect(result.stderr).toContain('JADE_OWNER_DB_PASSWORD must be set');
			expect(result.stderr).not.toContain('CanaryOwnerPassword');
			expect(result.stdout).not.toContain('CanaryOwnerPassword');
		}
		expect(() => statSync(out)).toThrow();
	});

	it('needs --db-port', async () => {
		const out = join(dir, '.env');
		const result = await envInitWith(
			{ JADE_OWNER_DB_PASSWORD: CI_OWNER_PASSWORD },
			'--out',
			out,
			'--profile',
			'ci'
		);
		expect(result.code).toBe(2);
		expect(result.stderr).toContain('--profile ci needs --db-port');
		expect(() => statSync(out)).toThrow();
	});
});

describe('refusals', () => {
	it('a second run onto the same path fails and leaves the file unchanged', async () => {
		const out = join(dir, '.env');
		expect((await envInit('--out', out)).code).toBe(0);
		const before = readFileSync(out, 'utf8');
		const second = await envInit('--out', out);
		expect(second.code).toBe(1);
		expect(second.stderr).toContain('already exists; it was not changed.');
		expect(readFileSync(out, 'utf8')).toBe(before);
		assertNoValuePrinted(second, readEnv(out));
	});

	it('a second run leaves no temporary file behind (B8)', async () => {
		const out = join(dir, '.env');
		expect((await envInit('--out', out)).code).toBe(0);
		expect((await envInit('--out', out)).code).toBe(1);
		expect(readdirSync(dir)).toEqual(['.env']);
	});

	it('a write that fails leaves no file at all, and a rerun succeeds (B8)', () => {
		const out = join(dir, '.env');
		const variables: [string, string][] = [['APP_ENV', 'development']];
		expect(() =>
			writeEnvFile(out, variables, {
				write: () => {
					throw new Error('simulated write failure');
				}
			})
		).toThrow('simulated write failure');
		expect(readdirSync(dir)).toEqual([]);

		writeEnvFile(out, variables);
		expect(readdirSync(dir)).toEqual(['.env']);
		expect(statSync(out).mode & 0o777).toBe(0o600);
		expect(readEnv(out)).toEqual({ APP_ENV: 'development' });
	});

	it('the temporary file is `<name>.tmp-<pid>-<hex>` beside the target (B1)', () => {
		expect(tempEnvFileName(join(dir, '.env'), 123, 'ab12')).toBe(join(dir, '.env.tmp-123-ab12'));
		expect(tempEnvFileName(join(dir, '.env'))).toMatch(/\/\.env\.tmp-\d+-[0-9a-f]{12}$/);
	});

	it.each(['EPERM', 'ENOTSUP', 'EXDEV'])(
		'where the link fails with %s, the file is written in place, mode 600 (B8)',
		(code) => {
			const out = join(dir, '.env');
			const link = () => {
				throw Object.assign(new Error('simulated link failure'), { code });
			};
			writeEnvFile(out, [['APP_ENV', 'development']], { link });
			expect(readdirSync(dir)).toEqual(['.env']);
			expect(statSync(out).mode & 0o777).toBe(0o600);
			expect(readEnv(out)).toEqual({ APP_ENV: 'development' });

			// The fallback still never overwrites.
			const before = readFileSync(out, 'utf8');
			expect(() => writeEnvFile(out, [['APP_ENV', 'test']], { link })).toThrow(
				expect.objectContaining({ code: 'EEXIST' })
			);
			expect(readFileSync(out, 'utf8')).toBe(before);
			expect(readdirSync(dir)).toEqual(['.env']);
		}
	);

	it('a fallback write that fails leaves no file at all (B8)', () => {
		const out = join(dir, '.env');
		let writes = 0;
		expect(() =>
			writeEnvFile(out, [['APP_ENV', 'development']], {
				link: () => {
					throw Object.assign(new Error('no links here'), { code: 'EPERM' });
				},
				write: (fd, text) => {
					writes += 1;
					if (writes === 2) throw new Error('simulated write failure');
					writeFileSync(fd, text);
				}
			})
		).toThrow('simulated write failure');
		expect(readdirSync(dir)).toEqual([]);
	});

	it('another link error is not hidden by the fallback, and leaves no file', () => {
		const out = join(dir, '.env');
		expect(() =>
			writeEnvFile(out, [['APP_ENV', 'development']], {
				link: () => {
					throw Object.assign(new Error('simulated'), { code: 'EACCES' });
				}
			})
		).toThrow(expect.objectContaining({ code: 'EACCES' }));
		expect(readdirSync(dir)).toEqual([]);
	});

	it('a failed write names the error code, never its message (B8)', async () => {
		const result = await envInit('--out', join(dir, 'missing', '.env'));
		expect(result.code).toBe(1);
		expect(result.stderr).toMatch(/could not write .*\(ENOENT\)\.\n$/);
		expect(result.stderr).not.toContain('no such file');
		expect(errorCodeOf(new Error('x'))).toBe('unknown');
		expect(errorCodeOf(Object.assign(new Error('x'), { code: 'secret value' }))).toBe('unknown');
	});

	it('refuses a profile that does not exist yet, and writes nothing', async () => {
		const out = join(dir, '.env');
		for (const profile of ['stack', 'nope']) {
			const result = await envInit('--out', out, '--profile', profile);
			expect(result.code).toBe(2);
			expect(result.stderr).toContain('--profile must be one of: dev, ci');
		}
		expect(() => statSync(out)).toThrow();
	});

	it('does not echo an unknown argument', async () => {
		const result = await envInit('CanaryArgument');
		expect(result.code).toBe(2);
		expect(result.stderr).not.toContain('CanaryArgument');
	});
});
