// `pnpm env:init` (plan V5). Grows with the variables each bead adds: jade-urd the database
// owner's variables and the `ci` profile, jade-80h the stack's variables and the `stack` profile.
import { execFile } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { createServer, type Server } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEnv, promisify } from 'node:util';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { loadAppConfig } from '../../src/lib/server/config/index.ts';

const run = promisify(execFile);
const root = fileURLToPath(new URL('../../', import.meta.url));
const tool = join(root, 'tools/env-init.ts');

const DEV_NAMES = [
	'APP_ENV',
	'JADE_APP_DB_PASSWORD',
	'JADE_DEV_DB_PORT',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET',
	'LOG_LEVEL'
];
const GENERATED = ['JADE_APP_DB_PASSWORD', 'DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET'];

interface Result {
	code: number;
	stdout: string;
	stderr: string;
}

/** Run the tool with an explicit, empty environment: nothing comes from this process's env. */
async function envInit(...args: string[]): Promise<Result> {
	try {
		const { stdout, stderr } = await run(process.execPath, [tool, ...args], { cwd: dir, env: {} });
		return { code: 0, stdout, stderr };
	} catch (err) {
		const e = err as { code: number; stdout: string; stderr: string };
		return { code: e.code, stdout: e.stdout, stderr: e.stderr };
	}
}

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

function assertNoValuePrinted(result: Result, values: Record<string, string>) {
	for (const name of GENERATED) {
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

		expect(env.JADE_APP_DB_PASSWORD).toMatch(/^[A-Za-z0-9_-]{32,}$/);
		expect(env.CODE_PEPPER).not.toBe(env.SESSION_SECRET);
		// The file is a configuration the app accepts as it stands.
		expect(loadAppConfig(env).appEnv).toBe('development');

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

	it('refuses a profile that does not exist yet, and writes nothing', async () => {
		const out = join(dir, '.env');
		for (const profile of ['ci', 'stack', 'nope']) {
			const result = await envInit('--out', out, '--profile', profile);
			expect(result.code).toBe(2);
			expect(result.stderr).toContain('--profile must be one of: dev');
		}
		expect(() => statSync(out)).toThrow();
	});

	it('does not echo an unknown argument', async () => {
		const result = await envInit('CanaryArgument');
		expect(result.code).toBe(2);
		expect(result.stderr).not.toContain('CanaryArgument');
	});
});
