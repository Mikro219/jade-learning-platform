// The database and app half of `pnpm ci:compat` (tools/ci/migration-compat.sh, plan X4). Each
// command exits 0, or with the code of the step that failed (COMPAT_EXIT), which the shell script
// passes on and the self-test reads. It runs on this checkout's code: the migration runner, the
// harness's cluster configuration (`.env`) and its admin helpers.
//
//   node tools/ci/compat.ts count-at <commit>                 migrations in the commit's manifest
//   node tools/ci/compat.ts count-dir <migrations dir>        migrations in the dir's manifest
//   node tools/ci/compat.ts manifest <migrations dir>         rewrite the dir's manifest.json
//   node tools/ci/compat.ts prepare <dir> <fresh> <template>  step 1
//   node tools/ci/compat.ts readyz <base dir> <fresh>         step 2
//   node tools/ci/compat.ts step3 <vitest json report> <vitest exit status>
//   node tools/ci/compat.ts ledger <dir> <template>           the ledger check after step 3
//   node tools/ci/compat.ts leftovers                         warn about jade_compat_% databases
//   node tools/ci/compat.ts drop <database>...                drop each, whatever the others do
//
// Output is fixed phrases, database and migration names, counts and HTTP statuses: never a URL
// or a password.
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
	DbError,
	LEDGER_TABLE,
	buildManifest,
	formatManifest,
	migrate,
	newClient,
	readManifest,
	withDatabase,
	type ManifestEntry
} from '../../src/lib/server/db/index.ts';
import type { MigrationConfig } from '../../src/lib/server/config/index.ts';
import { freePort } from '../free-port.ts';
import { manifestAt } from '../db/check-migrations.ts';

/** The exit codes of the steps (the shell script and the self-test read them). */
export const COMPAT_EXIT = {
	ok: 0,
	/** Step 1: the head's runner failed, or a ledger is not the head's manifest. */
	step1: 11,
	/** Step 2: the base app answered /readyz 503 with `migrations` not ok: the schema broke it. */
	step2: 12,
	/** Step 3: the base's harness started, and test files failed on the head's schema. */
	step3: 13,
	/** After step 3: the template's ledger changed. */
	afterStep3: 14,
	/** Step 2 could not run: the base app did not start (timeout, exit, ports exhausted). */
	baseNotStarted: 15,
	/** Step 2: /readyz was not 200 for another reason (no answer, db fail, 500, ...). */
	step2Other: 16,
	/** Step 3 could not run: the base's harness failed (global setup, no report, no files). */
	step3Harness: 17
} as const;

export class CompatFailure extends Error {
	readonly code: number;
	constructor(code: number, message: string) {
		super(message);
		this.code = code;
	}
}

/** Whether the ledger rows equal the manifest, name for name and hash for hash, in order. */
export function ledgerMatches(
	have: readonly ManifestEntry[],
	want: readonly ManifestEntry[]
): boolean {
	return (
		have.length === want.length &&
		have.every((row, i) => row.name === want[i]!.name && row.sha256 === want[i]!.sha256)
	);
}

/** Step 2's verdict on what /readyz answered (status 0: no answer). */
export function classifyReadyz(status: number, body: string): { code: number; detail: string } {
	if (status === 200) return { code: COMPAT_EXIT.ok, detail: 'answered 200' };
	let db: unknown;
	let migrations: unknown;
	try {
		const checks = (JSON.parse(body) as { checks?: { db?: unknown; migrations?: unknown } })
			?.checks;
		db = checks?.db;
		migrations = checks?.migrations;
	} catch {
		db = migrations = undefined;
	}
	const detail =
		`answered ${status || 'nothing'}` +
		(typeof db === 'string' && typeof migrations === 'string'
			? ` (db: ${db}, migrations: ${migrations})`
			: '');
	// Only a base that reached its database and found the ledger unreadable or wrong is broken by
	// the schema; db: fail (no connection, the 2-second limit) says nothing about compatibility.
	if (status === 503 && db === 'ok' && typeof migrations === 'string' && migrations !== 'ok') {
		return { code: COMPAT_EXIT.step2, detail };
	}
	return { code: COMPAT_EXIT.step2Other, detail };
}

/** The parts of Vitest's JSON report step 3 reads. */
export interface VitestReport {
	numTotalTestSuites?: number;
	numFailedTestSuites?: number;
	numFailedTests?: number;
	numPassedTests?: number;
	testResults?: { status?: string }[];
}

/**
 * Step 3's verdict: `report` is the base's Vitest JSON report (null when none was written) and
 * `status` its exit status. Only a run whose harness started (a report listing test files) and
 * whose files failed is a compatibility failure; a run that could not start is a harness failure.
 */
export function classifyStep3(
	report: VitestReport | null,
	status: number
): { code: number; detail: string } {
	const files = report?.testResults?.length ?? 0;
	if (report === null || files === 0) {
		return {
			code: COMPAT_EXIT.step3Harness,
			detail: "the base's integration harness did not run any test file"
		};
	}
	const failedFiles = report.testResults!.filter((r) => r.status === 'failed').length;
	const failedTests = report.numFailedTests ?? 0;
	if (failedFiles > 0 || failedTests > 0) {
		return {
			code: COMPAT_EXIT.step3,
			detail: `${failedTests} test(s) in ${failedFiles} of ${files} file(s) failed on the head's schema`
		};
	}
	if (status !== 0) {
		return {
			code: COMPAT_EXIT.step3Harness,
			detail: `every test passed but Vitest exited ${status} (setup or teardown failed)`
		};
	}
	return { code: COMPAT_EXIT.ok, detail: `${files} file(s) passed` };
}

const say = (line: string) => process.stdout.write(`ci:compat: ${line}\n`);
const tagOf = (err: unknown) => (err instanceof DbError ? err.tag : 'unexpected error');

async function harness() {
	return import('../../tests/support/global-setup-db.ts');
}

async function config(): Promise<MigrationConfig> {
	return (await harness()).clusterConfig();
}

async function ledger(cfg: MigrationConfig, name: string): Promise<ManifestEntry[]> {
	const client = newClient(withDatabase(cfg.migrationDatabaseUrl, name));
	try {
		await client.connect();
		const { rows } = await client.query(`SELECT name, sha256 FROM ${LEDGER_TABLE} ORDER BY name`);
		return rows.map((r: { name: string; sha256: string }) => ({ name: r.name, sha256: r.sha256 }));
	} finally {
		await client.end().catch(() => {});
	}
}

async function checkLedger(
	cfg: MigrationConfig,
	dir: string,
	name: string,
	when: string,
	code: number
) {
	const want = readManifest(dir).migrations;
	let have: ManifestEntry[];
	try {
		have = await ledger(cfg, name);
	} catch (err) {
		throw new CompatFailure(code, `${when}: could not read the ledger of ${name} (${tagOf(err)})`);
	}
	if (!ledgerMatches(have, want)) {
		throw new CompatFailure(
			code,
			`${when}: the ledger of ${name} (${have.map((r) => r.name).join(', ') || 'empty'}) ` +
				`does not equal the head's manifest (${want.map((r) => r.name).join(', ')})`
		);
	}
	say(`${when}: ${name} holds the head's ${want.length} migration(s)`);
}

async function prepare(dir: string, fresh: string, template: string) {
	const cfg = await config();
	const { adminQuery, quoteIdentifier } = await harness();
	for (const name of [fresh, template]) {
		try {
			await adminQuery(
				cfg.migrationDatabaseUrl,
				`CREATE DATABASE ${quoteIdentifier(name)} TEMPLATE template0`
			);
			const result = await migrate({
				ownerUrl: withDatabase(cfg.migrationDatabaseUrl, name),
				appUrl: withDatabase(cfg.databaseUrl, name),
				dir
			});
			say(`step 1: the head's runner applied ${result.applied.join(', ') || 'nothing'} to ${name}`);
		} catch (err) {
			throw new CompatFailure(
				COMPAT_EXIT.step1,
				`step 1: the head's runner failed on ${name} (${tagOf(err)})`
			);
		}
		await checkLedger(cfg, dir, name, 'step 1', COMPAT_EXIT.step1);
	}
}

/** Stop the server: SIGTERM, SIGKILL after 3 s; resolves once it has closed. */
async function stopServer(child: ChildProcess, closed: Promise<unknown>) {
	child.kill('SIGTERM');
	const timer = setTimeout(() => child.kill('SIGKILL'), 3_000);
	await closed;
	clearTimeout(timer);
}

async function readyz(baseDir: string, name: string) {
	const cfg = await config();
	const env = {
		APP_ENV: 'test',
		DATABASE_URL: withDatabase(cfg.databaseUrl, name),
		CODE_PEPPER: 'test-only-code-pepper-0123456789abcdefghijklmnopqrstuvwxyz',
		SESSION_SECRET: 'test-only-session-secret-0123456789abcdefghijklmnopqrstuvwxyz',
		LOG_LEVEL: 'info',
		HOST: '127.0.0.1'
	};
	let outcome = 'not started';
	// A port from freePort(); a start that loses it to another process is retried (PD11).
	for (let attempt = 1; attempt <= 3; attempt++) {
		const port = await freePort();
		// In this process's group, which run() of tools/ci/lib/supervise.sh made: the shell's
		// group TERM and KILL reach the server too. On SIGINT or SIGTERM it is killed here as well.
		const child = spawn(process.execPath, ['build'], {
			cwd: baseDir,
			env: { ...env, PORT: String(port) },
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const onSignal = (sig: NodeJS.Signals) => {
			child.kill('SIGKILL');
			process.exit(sig === 'SIGINT' ? 130 : 143);
		};
		process.once('SIGINT', onSignal);
		process.once('SIGTERM', onSignal);
		let out = '';
		const closed = new Promise((r) => child.once('close', r));
		const started = await new Promise<'listening' | 'exited' | 'timeout'>((resolve) => {
			const timer = setTimeout(() => resolve('timeout'), 30_000);
			const onData = (d: Buffer) => {
				out += d.toString();
				if (/Listening on /.test(out)) {
					clearTimeout(timer);
					resolve('listening');
				}
			};
			child.stdout!.on('data', onData);
			child.stderr!.on('data', (d: Buffer) => (out += d.toString()));
			child.once('close', () => {
				clearTimeout(timer);
				resolve('exited');
			});
		});
		try {
			if (started === 'listening') {
				let status = 0;
				let body = '';
				try {
					const res = await fetch(`http://127.0.0.1:${port}/readyz`, {
						signal: AbortSignal.timeout(10_000)
					});
					status = res.status;
					body = (await res.text()).slice(0, 300);
				} catch {
					status = 0;
				}
				const verdict = classifyReadyz(status, body);
				if (verdict.code !== COMPAT_EXIT.ok) {
					throw new CompatFailure(verdict.code, `step 2: the base app's /readyz ${verdict.detail}`);
				}
				say(`step 2: the base app's /readyz answered 200 on ${name}`);
				return;
			}
			outcome = started;
		} finally {
			await stopServer(child, closed);
			process.off('SIGINT', onSignal);
			process.off('SIGTERM', onSignal);
		}
		if (/EADDRINUSE/.test(out) && attempt < 3) continue;
		break;
	}
	throw new CompatFailure(
		COMPAT_EXIT.baseNotStarted,
		`step 2: the base app did not start (${outcome})`
	);
}

function readReport(path: string): VitestReport | null {
	if (!existsSync(path)) return null;
	try {
		return JSON.parse(readFileSync(path, 'utf8')) as VitestReport;
	} catch {
		return null;
	}
}

async function leftovers() {
	const cfg = await config();
	const client = newClient(withDatabase(cfg.migrationDatabaseUrl, 'postgres'));
	try {
		await client.connect();
		const { rows } = await client.query<{ datname: string }>(
			"SELECT datname FROM pg_database WHERE datname LIKE 'jade\\_compat\\_%' ORDER BY 1"
		);
		if (rows.length > 0) {
			process.stderr.write(
				`ci:compat: warning: databases of an earlier run remain (not dropped): ${rows.map((r) => r.datname).join(', ')}\n`
			);
		}
	} finally {
		await client.end().catch(() => {});
	}
}

async function drop(names: readonly string[]): Promise<number> {
	const cfg = await config();
	const { dropDatabase } = await harness();
	const failed: string[] = [];
	for (const name of names) {
		try {
			await dropDatabase(cfg.migrationDatabaseUrl, name);
		} catch {
			failed.push(name);
		}
	}
	if (failed.length > 0) {
		process.stderr.write(`ci:compat: warning: could not drop ${failed.join(', ')}\n`);
		return 1;
	}
	return 0;
}

export async function main(argv: readonly string[]): Promise<number> {
	const [command, ...args] = argv;
	try {
		switch (command) {
			case 'count-at':
				process.stdout.write(`${manifestAt(args[0]!, process.cwd()).migrations.length}\n`);
				return 0;
			case 'count-dir':
				process.stdout.write(`${readManifest(args[0]!).migrations.length}\n`);
				return 0;
			case 'manifest':
				writeFileSync(join(args[0]!, 'manifest.json'), formatManifest(buildManifest(args[0]!)));
				return 0;
			case 'prepare':
				await prepare(args[0]!, args[1]!, args[2]!);
				return 0;
			case 'readyz':
				await readyz(args[0]!, args[1]!);
				return 0;
			case 'step3': {
				const verdict = classifyStep3(readReport(args[0]!), Number(args[1]));
				if (verdict.code !== COMPAT_EXIT.ok) {
					throw new CompatFailure(verdict.code, `step 3: ${verdict.detail}`);
				}
				say(`step 3: ${verdict.detail}`);
				return 0;
			}
			case 'ledger':
				await checkLedger(
					await config(),
					args[0]!,
					args[1]!,
					'after step 3',
					COMPAT_EXIT.afterStep3
				);
				return 0;
			case 'leftovers':
				await leftovers();
				return 0;
			case 'drop':
				return await drop(args);
			default:
				process.stderr.write('usage: compat.ts <command> [args...] (see the header)\n');
				return 2;
		}
	} catch (err) {
		if (err instanceof CompatFailure) {
			process.stderr.write(`ci:compat: ${err.message}\n`);
			return err.code;
		}
		process.stderr.write(`ci:compat: ${command}: ${tagOf(err)}\n`);
		return 1;
	}
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main(process.argv.slice(2));
}
