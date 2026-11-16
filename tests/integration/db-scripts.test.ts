// The entry points behind `pnpm db:migrate` and `pnpm db:reset` (plan U3, U6), run as the
// scripts run them, against a scratch database of this run, and the reset guard's refusals
// (PD15): each refused input is one every other check accepts, so only the guard can refuse it.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { loadMigrationConfig } from '../../src/lib/server/config/index.ts';
import { createPool } from '../../src/lib/server/db/index.ts';
import { generatePassword } from '../../tools/env-init.ts';
import { resetGuard } from '../../tools/db/reset.ts';
import { createEmptyDatabase, type TestDatabase } from '../support/db.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));

interface Result {
	code: number;
	stdout: string;
	stderr: string;
	elapsedMs: number;
}

/** Run a tool on the pinned Node with exactly `env` (the tool reads no value of ours). */
async function tool(script: string, env: Record<string, string>): Promise<Result> {
	const started = Date.now();
	try {
		const { stdout, stderr } = await promisify(execFile)(process.execPath, [script], {
			cwd: root,
			env,
			timeout: 60_000
		});
		return { code: 0, stdout, stderr, elapsedMs: Date.now() - started };
	} catch (err) {
		const e = err as { code: number; stdout: string; stderr: string };
		return { code: e.code, stdout: e.stdout, stderr: e.stderr, elapsedMs: Date.now() - started };
	}
}

let db: TestDatabase;
let env: Record<string, string>;
beforeAll(async () => {
	db = await createEmptyDatabase();
	env = { APP_ENV: 'test', MIGRATION_DATABASE_URL: db.ownerUrl, DATABASE_URL: db.appUrl };
});
afterAll(async () => {
	await db?.drop();
});

async function scratchTableExists(): Promise<boolean> {
	const pool = createPool(db.ownerUrl, { max: 1 });
	try {
		const { rows } = await pool.query("SELECT to_regclass('public.scratch_reset') AS t");
		return rows[0].t !== null;
	} finally {
		await pool.end();
	}
}

async function createScratchTable(): Promise<void> {
	const pool = createPool(db.ownerUrl, { max: 1 });
	try {
		await pool.query('CREATE TABLE IF NOT EXISTS scratch_reset (id int)');
	} finally {
		await pool.end();
	}
}

describe('db:migrate and db:reset', () => {
	it('migrate applies the baseline, reset removes a scratch table, and a second migrate is a no-op', async () => {
		// The harness's own pools are not needed here; the tools use the URLs.
		await Promise.all([db.owner.end(), db.app.end()]);

		const first = await tool('tools/db/migrate.ts', env);
		expect(first.code).toBe(0);
		expect(first.stdout).toContain('db:migrate: applied 0000_baseline');

		await createScratchTable();
		expect(await scratchTableExists()).toBe(true);

		const reset = await tool('tools/db/reset.ts', env);
		expect(reset.stderr).toBe('');
		expect(reset.code).toBe(0);
		expect(reset.stdout).toContain(`db:reset: recreated database ${db.name}`);
		expect(reset.stdout).toContain('db:reset: applied 0000_baseline');
		expect(await scratchTableExists()).toBe(false);

		const again = await tool('tools/db/migrate.ts', env);
		expect(again.code).toBe(0);
		expect(again.stdout).toContain('nothing applied');
		expect(again.stdout).not.toContain('applied 0000_baseline');

		for (const run of [first, reset, again]) {
			for (const secret of [db.ownerUrl, db.appUrl, new URL(db.appUrl).password]) {
				expect(run.stdout + run.stderr).not.toContain(secret);
			}
		}
	});
});

describe('the db:reset guard (PD15)', () => {
	const port = () => new URL(db.ownerUrl).port;

	const cases: [string, 'app_env' | 'host', () => Record<string, string>][] = [
		[
			// (1) APP_ENV=production, URLs at the scratch database's loopback host and port, with
			// generated passwords that hold no test-only, as V8 generates them.
			'APP_ENV=production at a loopback host',
			'app_env',
			() => ({
				APP_ENV: 'production',
				MIGRATION_DATABASE_URL: `postgres://jade_owner:${generatePassword()}@127.0.0.1:${port()}/${db.name}`,
				DATABASE_URL: `postgres://jade_app:${generatePassword()}@127.0.0.1:${port()}/${db.name}`
			})
		],
		[
			// (2) APP_ENV=test with the scratch database's own URLs but host 192.0.2.1, an address
			// reserved for documentation that nothing answers.
			'APP_ENV=test at a non-loopback host',
			'host',
			() => {
				const at = (url: string) => {
					const u = new URL(url);
					u.hostname = '192.0.2.1';
					return u.toString();
				};
				return {
					APP_ENV: 'test',
					MIGRATION_DATABASE_URL: at(db.ownerUrl),
					DATABASE_URL: at(db.appUrl)
				};
			}
		]
	];

	it.each(cases)(
		'%s: refused as %s, with the scratch table left in place',
		async (_, half, make) => {
			await createScratchTable();
			const input = make();
			// Every other check on the path accepts this input.
			expect(() => loadMigrationConfig(input)).not.toThrow();
			expect(resetGuard(input)).toBe(half);

			const run = await tool('tools/db/reset.ts', input);
			expect(run.code).toBe(1);
			expect(run.elapsedMs).toBeLessThan(5000);
			expect(run.stderr).toBe(`db:reset: DB_RESET_REFUSED ${half}\n`);
			expect(run.stdout).toBe('');
			expect(run.stdout + run.stderr).not.toMatch(/config_error|Configuration error/);
			for (const value of Object.values(input)) expect(run.stderr).not.toContain(value);
			expect(await scratchTableExists()).toBe(true);
		}
	);

	it.each([
		['MIGRATION_DATABASE_URL', '?host=192.0.2.1'],
		['DATABASE_URL', '?host=192.0.2.1'],
		['MIGRATION_DATABASE_URL', '#x']
	])(
		'%s with %s: refused as query, before any connection, with the scratch table left in place (jade-f1w)',
		async (key, suffix) => {
			await createScratchTable();
			// APP_ENV and the URL's own host (loopback) pass the earlier halves of the guard.
			const input = { ...env, [key]: `${env[key]}${suffix}` };
			expect(resetGuard({ ...input, [key]: env[key] })).toBeNull();
			expect(resetGuard(input)).toBe('query');

			const run = await tool('tools/db/reset.ts', input);
			expect(run.code).toBe(1);
			expect(run.elapsedMs).toBeLessThan(5000);
			expect(run.stderr).toBe('db:reset: DB_RESET_REFUSED query\n');
			expect(run.stdout).toBe('');
			for (const value of Object.values(input)) expect(run.stderr).not.toContain(value);
			expect(await scratchTableExists()).toBe(true);
		}
	);

	it('refuses a URL that does not parse, and accepts development and test on loopback', () => {
		expect(resetGuard({ ...env, DATABASE_URL: 'not a url' })).toBe('host');
		expect(resetGuard({ ...env, MIGRATION_DATABASE_URL: undefined as unknown as string })).toBe(
			'host'
		);
		expect(resetGuard(env)).toBeNull();
		expect(resetGuard({ ...env, APP_ENV: 'development' })).toBeNull();
		expect(resetGuard({ ...env, APP_ENV: 'staging' })).toBe('app_env');
		const v6 = (url: string) => url.replace('127.0.0.1', '[::1]');
		expect(
			resetGuard({
				...env,
				MIGRATION_DATABASE_URL: v6(env.MIGRATION_DATABASE_URL!),
				DATABASE_URL: v6(env.DATABASE_URL!)
			})
		).toBeNull();
	});
});
