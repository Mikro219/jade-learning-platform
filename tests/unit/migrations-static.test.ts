// Static rules for migrations/ (plan INV5, U5): names, contiguous numbers, manifest.json equals
// the files, Drizzle Kit's journal lists them in file order, a destructive statement carries a
// `-- jade:contract <bead>` marker, no domain table in Phase 1. The checks of `pnpm db:check` are
// run here on the real directory, and each is shown to catch what it is for on a broken copy.
import { execFile } from 'node:child_process';
import {
	cpSync,
	existsSync,
	mkdtempSync,
	readdirSync,
	readFileSync,
	rmSync,
	writeFileSync
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { afterAll, describe, expect, it } from 'vitest';
import {
	buildManifest,
	formatManifest,
	readManifest,
	sha256
} from '../../src/lib/server/db/index.ts';
import {
	checkMigrationsDir,
	checkPrefix,
	hasTransactionControl,
	isDestructive
} from '../../tools/db/check-migrations.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const dir = join(root, 'migrations');
const sqlFiles = readdirSync(dir)
	.filter((f) => f.endsWith('.sql'))
	.sort();
const copies: string[] = [];

afterAll(() => {
	for (const copy of copies) rmSync(copy, { recursive: true, force: true });
});

function copy(): string {
	const target = mkdtempSync(join(tmpdir(), 'jade-migrations-static-'));
	copies.push(target);
	cpSync(dir, target, { recursive: true });
	return target;
}

describe('migrations/', () => {
	it('has the baseline, named NNNN_<snake_case>.sql and numbered from 0000 without gaps', () => {
		expect(sqlFiles[0]).toBe('0000_baseline.sql');
		sqlFiles.forEach((file, i) => {
			expect(file).toMatch(/^\d{4}_[a-z0-9]+(_[a-z0-9]+)*\.sql$/);
			expect(Number(file.slice(0, 4))).toBe(i);
		});
	});

	it('manifest.json lists every file, in order, with its SHA-256', () => {
		const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8')) as {
			migrations: { name: string; sha256: string }[];
		};
		expect(manifest.migrations).toEqual(
			sqlFiles.map((file) => ({
				name: file.replace(/\.sql$/, ''),
				sha256: sha256(readFileSync(join(dir, file)))
			}))
		);
		expect(readFileSync(join(dir, 'manifest.json'), 'utf8')).toBe(formatManifest(manifest));
	});

	it("Drizzle Kit's journal lists the files in file order", () => {
		const journal = JSON.parse(readFileSync(join(dir, 'meta', '_journal.json'), 'utf8')) as {
			dialect: string;
			entries: { idx: number; tag: string }[];
		};
		expect(journal.dialect).toBe('postgresql');
		expect(journal.entries.map((e) => e.tag)).toEqual(sqlFiles.map((f) => f.replace(/\.sql$/, '')));
		expect(journal.entries.map((e) => e.idx)).toEqual(sqlFiles.map((_, i) => i));
	});

	it('every destructive file carries a jade:contract marker; the baseline is marked', () => {
		for (const file of sqlFiles) {
			const sql = readFileSync(join(dir, file), 'utf8');
			if (isDestructive(sql))
				expect({ file, sql }).toMatchObject({
					sql: expect.stringMatching(/^-- jade:contract jade-[a-z0-9]+/m)
				});
		}
		expect(isDestructive(readFileSync(join(dir, '0000_baseline.sql'), 'utf8'))).toBe(true);
	});

	it('creates no table in Phase 1, and schema.ts declares none', () => {
		for (const file of sqlFiles) {
			expect(readFileSync(join(dir, file), 'utf8')).not.toMatch(/create\s+table/i);
		}
		expect(readFileSync(join(root, 'src/lib/server/db/schema.ts'), 'utf8')).not.toMatch(/pgTable/);
	});

	it('passes every check of pnpm db:check', () => {
		expect(checkMigrationsDir(dir)).toEqual([]);
	});

	it('has no down migrations', () => {
		expect(readdirSync(dir).filter((f) => /down|rollback|revert/i.test(f))).toEqual([]);
		expect(existsSync(join(dir, 'down'))).toBe(false);
	});
});

describe('the checks catch what they are for', () => {
	it('an edited file without a new manifest', () => {
		const c = copy();
		writeFileSync(
			join(c, '0000_baseline.sql'),
			`${readFileSync(join(c, '0000_baseline.sql'), 'utf8')}\n`
		);
		expect(checkMigrationsDir(c)).toContain(
			'manifest.json: does not equal the files (run pnpm db:manifest)'
		);
	});

	it('a gap in the numbers, and a file missing from the journal', () => {
		const c = copy();
		writeFileSync(join(c, '0002_skipped.sql'), 'SELECT 1;\n');
		writeFileSync(join(c, 'manifest.json'), formatManifest(buildManifest(c)));
		const problems = checkMigrationsDir(c);
		expect(problems).toContain('0002_skipped: number is not 0001');
		expect(problems).toContain('meta/_journal.json: entries do not list the files in order');
	});

	it('a destructive statement without a marker', () => {
		const c = copy();
		writeFileSync(join(c, '0001_drop.sql'), '-- drops a thing\nDROP INDEX IF EXISTS x;\n');
		const problems = checkMigrationsDir(c);
		expect(problems).toContain(
			'0001_drop: destructive statement without a -- jade:contract <bead> marker'
		);
		expect(isDestructive('-- DROP in a comment only\nSELECT 1;')).toBe(false);
		for (const sql of [
			'TRUNCATE t',
			'ALTER TABLE t RENAME TO u',
			'ALTER TABLE t ALTER COLUMN c TYPE text',
			'ALTER TABLE t ALTER COLUMN c SET NOT NULL',
			'DELETE FROM t',
			'REVOKE SELECT ON t FROM jade_app'
		]) {
			expect({ sql, destructive: isDestructive(sql) }).toEqual({ sql, destructive: true });
		}
		expect(isDestructive('CREATE INDEX i ON t (c); GRANT SELECT ON t TO jade_app;')).toBe(false);
	});

	it('a column type change without COLUMN, or on quoted identifiers with spaces (A4)', () => {
		for (const sql of [
			'ALTER TABLE t ALTER c TYPE text',
			'alter table t alter c set data type bigint',
			'ALTER TABLE "my table" ALTER COLUMN "my col" TYPE text',
			'ALTER TABLE "my table" ALTER "my col" SET DATA TYPE text',
			'ALTER TABLE t\n  ALTER\n  c\n  TYPE integer USING c::integer',
			// A6: a block comment between the name and TYPE, and a quoted name with doubled quotes.
			'ALTER TABLE t ALTER COLUMN c /* widen */ TYPE bigint',
			'ALTER TABLE t ALTER COLUMN "my ""x"" col" TYPE text',
			// A6: a comment marker inside a string does not hide what follows it.
			"COMMENT ON TABLE t IS '-- note'; DROP TABLE u;"
		]) {
			expect({ sql, destructive: isDestructive(sql) }).toEqual({ sql, destructive: true });
		}
		for (const sql of [
			"ALTER TYPE mood ADD VALUE 'meh'",
			'ALTER TABLE t ADD COLUMN c text',
			'ALTER TABLE t ALTER COLUMN c SET DEFAULT 1'
		]) {
			expect({ sql, destructive: isDestructive(sql) }).toEqual({ sql, destructive: false });
		}
	});

	it('a transaction-control statement (B7)', () => {
		const c = copy();
		writeFileSync(
			join(c, '0001_tx.sql'),
			'BEGIN;\nGRANT USAGE ON SCHEMA public TO jade_app;\nCOMMIT;\n'
		);
		writeFileSync(join(c, 'manifest.json'), formatManifest(buildManifest(c)));
		expect(checkMigrationsDir(c)).toContain(
			'0001_tx: transaction-control statement (the runner wraps each file in one transaction)'
		);
		for (const sql of [
			'BEGIN;',
			'begin transaction isolation level serializable;',
			'SELECT 1; COMMIT;',
			'SELECT 1;\n--> statement-breakpoint\nROLLBACK;',
			'END;',
			'START TRANSACTION;',
			'SAVEPOINT s1;',
			'RELEASE SAVEPOINT s1;',
			'release s1',
			'ROLLBACK TO SAVEPOINT s1;',
			'ABORT;',
			'COMMIT AND CHAIN;',
			'/* a block comment */ COMMIT;',
			// A5: an escape string whose backslash escapes a quote ends where Postgres ends it.
			"SELECT E'\\''; COMMIT;",
			"SELECT E'\\''; COMMIT; SELECT 'x';",
			"SELECT e'a\\\\'; COMMIT; SELECT 'x';"
		]) {
			expect({ sql, tx: hasTransactionControl(sql) }).toEqual({ sql, tx: true });
		}
		for (const sql of [
			'-- BEGIN; in a comment\nSELECT 1;',
			'/* COMMIT; */ SELECT 1;',
			"SELECT 'BEGIN; COMMIT;';",
			'DO $$ BEGIN PERFORM 1; END $$;',
			'CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $body$\nBEGIN\n  IF true THEN RETURN; END IF;\nEND;\n$body$;',
			'GRANT SELECT ON t TO jade_app;',
			'CREATE TABLE begin_log (ended boolean);',
			// A5: a dollar tag with digits; an escape string holding a quote and a keyword.
			'CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $f1$\nBEGIN\n  RETURN;\nEND;\n$f1$;',
			"SELECT E'BEGIN; \\' COMMIT;';"
		]) {
			expect({ sql, tx: hasTransactionControl(sql) }).toEqual({ sql, tx: false });
		}
	});

	it('--base: a base manifest that is not an unchanged prefix', () => {
		const head = readManifest(dir);
		const entry = head.migrations[0]!;
		expect(checkPrefix({ migrations: [] }, head)).toEqual([]);
		expect(
			checkPrefix(head, {
				migrations: [...head.migrations, { name: '0001_x', sha256: 'f'.repeat(64) }]
			})
		).toEqual([]);
		expect(checkPrefix(head, { migrations: [] })).toEqual([
			`${entry.name}: removed since the base`
		]);
		expect(checkPrefix(head, { migrations: [{ ...entry, sha256: '0'.repeat(64) }] })).toEqual([
			`${entry.name}: edited since the base`
		]);
		expect(checkPrefix(head, { migrations: [{ ...entry, name: '0000_renamed' }] })).toEqual([
			`${entry.name}: renamed or reordered since the base`
		]);
	});
});

// Each case starts the tool on Node; under a parallel gate that can take more than 5 seconds.
describe('pnpm db:check', { timeout: 30_000 }, () => {
	const run = (...args: string[]) =>
		promisify(execFile)(process.execPath, ['tools/db/check-migrations.ts', ...args], {
			cwd: root,
			env: {}
		});

	it('passes on this checkout, alone and against HEAD as its base', async () => {
		expect((await run()).stdout).toMatch(/^db:check: ok, \d+ migration\(s\)/);
		expect((await run('--base', 'HEAD')).stdout).toMatch(/^db:check: ok/);
	});

	it('fails on a base that is not a commit', async () => {
		await expect(run('--base', 'no-such-ref-jade')).rejects.toMatchObject({ code: 1 });
	});
});
