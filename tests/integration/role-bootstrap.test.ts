// The app role's bootstrap under concurrency (plan U2, PD12, INV5). Runners on different databases
// of one cluster at once must all succeed: without the cluster-wide lock, two of them could write
// jade_app together and fail with XX000 (tuple concurrently updated) or 23505/42710 (duplicate).
//
// First in the shared cluster, where jade_app is never dropped and its password never changed;
// then in a throwaway Postgres container of this file's own (the image compose.dev.yml names, a
// host port from freePort()), where the role can be removed or given a stale password.
import { execFile } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { migrate, newClient, scramVerifier, withDatabase } from '../../src/lib/server/db/index.ts';
import { generatePassword } from '../../tools/env-init.ts';
import { freePort } from '../../tools/free-port.ts';
import { createEmptyDatabase, type TestDatabase } from '../support/db.ts';
import { MIGRATIONS_DIR, adminQuery, dropDatabase } from '../support/global-setup-db.ts';

const ROUNDS = 5;
const root = fileURLToPath(new URL('../../', import.meta.url));
const docker = promisify(execFile);

/** The Postgres image compose.dev.yml names (INV9 keeps it the one pin). */
function devImage(): string {
	const m = /^\s*image:\s*(postgres:\S+)\s*$/m.exec(readFileSync(`${root}compose.dev.yml`, 'utf8'));
	if (!m) throw new Error('compose.dev.yml names no postgres image');
	return m[1]!;
}

/** Start migrate() on two databases at the same moment. */
function twoAtOnce(urls: { ownerUrl: string; appUrl: string }[]) {
	return Promise.all(urls.map((u) => migrate({ ...u, dir: MIGRATIONS_DIR })));
}

describe('in the shared cluster', () => {
	const created: TestDatabase[] = [];
	afterAll(async () => {
		await Promise.all(created.map((db) => db.drop()));
	});

	it(`two runners on two empty databases at once succeed, ${ROUNDS} times over`, async () => {
		for (let round = 0; round < ROUNDS; round++) {
			const dbs = await Promise.all([createEmptyDatabase(), createEmptyDatabase()]);
			created.push(...dbs);
			const results = await twoAtOnce(dbs);
			for (const result of results) expect(result.applied).toEqual(['0000_baseline']);
		}
	});
});

describe('in a throwaway cluster', () => {
	const name = `jade-test-pg-${randomBytes(4).toString('hex')}`;
	const ownerPassword = generatePassword();
	const appPassword = generatePassword();
	let ownerUrl = '';
	let appUrl = '';
	let started = false;

	beforeAll(async () => {
		// The password reaches the container through the docker CLI's environment (`-e NAME`
		// without a value), never on its command line.
		for (let attempt = 1; ; attempt++) {
			const port = await freePort();
			try {
				await docker(
					'docker',
					[
						'run',
						'-d',
						'--name',
						name,
						'-e',
						'POSTGRES_USER=jade_owner',
						'-e',
						'POSTGRES_PASSWORD',
						'-e',
						'POSTGRES_DB=jade',
						'-p',
						`127.0.0.1:${port}:5432`,
						devImage()
					],
					{ env: { ...process.env, POSTGRES_PASSWORD: ownerPassword } }
				);
				started = true;
				ownerUrl = `postgres://jade_owner:${ownerPassword}@127.0.0.1:${port}/jade`;
				appUrl = `postgres://jade_app:${appPassword}@127.0.0.1:${port}/jade`;
				break;
			} catch (err) {
				// The port was taken between freePort() and docker run: a new port, at most 3 times
				// (PD11). A container that was created but could not start is removed first.
				await docker('docker', ['rm', '-f', '-v', name]).catch(() => {});
				const text = String((err as { stderr?: string }).stderr ?? '');
				if (attempt >= 3 || !/address already in use|port is already allocated/i.test(text)) {
					// eslint-disable-next-line preserve-caught-error -- the cause can carry a URL or a server message (INV4)
					throw new Error(`docker run failed (attempt ${attempt})`);
				}
			}
		}
		// Ready when the owner can log in over TCP (the image's init server listens on a socket only).
		const deadline = Date.now() + 90_000;
		for (;;) {
			const client = newClient(withDatabase(ownerUrl, 'postgres'));
			try {
				await client.connect();
				await client.query('SELECT 1');
				await client.end();
				break;
			} catch {
				await client.end().catch(() => {});
				if (Date.now() > deadline) throw new Error('the throwaway Postgres did not become ready');
				await new Promise((resolve) => setTimeout(resolve, 250));
			}
		}
	}, 150_000);

	afterAll(async () => {
		if (started) await docker('docker', ['rm', '-f', '-v', name]);
	});

	/** Two fresh databases, migrated at once, then dropped so the role can be dropped too. */
	async function round(): Promise<void> {
		const names = [0, 1].map((i) => `jade_rb_${randomBytes(4).toString('hex')}_${i}`);
		for (const db of names) await adminQuery(ownerUrl, `CREATE DATABASE ${db} TEMPLATE template0`);
		try {
			const results = await twoAtOnce(
				names.map((db) => ({
					ownerUrl: withDatabase(ownerUrl, db),
					appUrl: withDatabase(appUrl, db)
				}))
			);
			for (const result of results) expect(result.applied).toEqual(['0000_baseline']);
			expect(results.map((r) => r.role).filter((r) => r !== 'unchanged')).toHaveLength(1);
		} finally {
			for (const db of names) await dropDatabase(ownerUrl, db);
		}
	}

	async function appRoleLogsIn(): Promise<boolean> {
		const client = newClient(withDatabase(appUrl, 'postgres'));
		try {
			await client.connect();
			await client.query('SELECT 1');
			return true;
		} catch {
			return false;
		} finally {
			await client.end().catch(() => {});
		}
	}

	it(`with jade_app absent, ${ROUNDS} times over, every run succeeds`, async () => {
		for (let i = 0; i < ROUNDS; i++) {
			await adminQuery(ownerUrl, 'DROP ROLE IF EXISTS jade_app');
			await round();
		}
		expect(await appRoleLogsIn()).toBe(true);
	});

	it(`with jade_app holding a stale password, ${ROUNDS} times over, every run succeeds`, async () => {
		for (let i = 0; i < ROUNDS; i++) {
			const stale = scramVerifier(generatePassword());
			await adminQuery(ownerUrl, `ALTER ROLE jade_app PASSWORD '${stale}'`);
			expect(await appRoleLogsIn()).toBe(false);
			await round();
		}
		expect(await appRoleLogsIn()).toBe(true);
	});
});
