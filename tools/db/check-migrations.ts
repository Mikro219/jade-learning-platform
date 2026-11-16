// `pnpm db:check [--base <ref>]` (plan INV5, U5): the migration files keep the forward-only rules.
//   - names are `NNNN_<snake_case>.sql`, numbered contiguously from 0000;
//   - manifest.json equals the files, name for name and hash for hash;
//   - Drizzle Kit's journal (meta/_journal.json) lists the same names in the same order;
//   - a destructive statement (DROP, TRUNCATE, RENAME, REVOKE, DELETE, a column type change,
//     SET NOT NULL) needs a `-- jade:contract <bead>` marker line in its file;
//   - no file has a transaction-control statement (BEGIN, COMMIT, ROLLBACK, END, ABORT,
//     START TRANSACTION, SAVEPOINT, RELEASE): the runner applies each file in one transaction with
//     its ledger row, and a COMMIT inside the file would commit the file without its row (B7);
//   - with --base, the base commit's manifest is an unchanged prefix of this one: no merged file
//     was edited, renamed, reordered or removed. A base without a manifest has an empty one.
// tests/unit/migrations-static.test.ts runs the same checks.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
	buildManifest,
	parseManifest,
	readManifest,
	readMigrations,
	type Manifest
} from '../../src/lib/server/db/index.ts';
import { MIGRATIONS_DIR } from './migrate.ts';

export const MIGRATION_NAME = /^(\d{4})_[a-z0-9]+(?:_[a-z0-9]+)*$/;
export const CONTRACT_MARKER = /^-- jade:contract jade-[a-z0-9]+\b/m;

const DESTRUCTIVE = [
	/\bdrop\b/i,
	/\btruncate\b/i,
	/\brename\b/i,
	/\brevoke\b/i,
	/\bdelete\s+from\b/i,
	// ALTER [COLUMN] <name> [SET DATA] TYPE, with a plain or a double-quoted name, whose quotes
	// may be doubled inside it (A4, A6).
	/\balter\s+(?:column\s+)?(?:"(?:[^"]|"")+"|\S+)\s+(?:set\s+data\s+)?type\b/i,
	/\bset\s+not\s+null\b/i
];

// One SQL token that is not a statement keyword (A5, A6), in the order the lexer tries them:
//   1. a `--` comment, 2. a `/* */` comment (Postgres nests these; no migration does),
//   3. an escape string `E'...'`, where a backslash escapes the next character, so `E'\''` is
//      one string; the E must not end an identifier,
//   4. a plain string `'...'` (standard_conforming_strings: a backslash is literal),
//   5. a double-quoted identifier, 6. a dollar-quoted body `$$ ... $$` or `$tag$ ... $tag$`,
//      where the tag is a letter or `_` and then letters, digits or `_`.
const NON_CODE =
	/(--[^\n]*|\/\*[\s\S]*?\*\/)|(?<![A-Za-z0-9_$])[Ee]'(?:[^'\\]|\\[\s\S]|'')*'|'(?:[^']|'')*'|"(?:[^"]|"")*"|(\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$)[\s\S]*?\2/g;

/**
 * The SQL of a file with its `--` and `/* *\/` comments replaced by a space. Strings, quoted
 * identifiers and dollar-quoted bodies are kept as they are, and a comment marker inside one of
 * them is not a comment.
 */
export function stripComments(sql: string): string {
	return sql.replace(NON_CODE, (match, comment: string | undefined) =>
		comment === undefined ? match : ' '
	);
}

/** Whether a file's SQL has a destructive statement. */
export function isDestructive(sql: string): boolean {
	const code = stripComments(sql);
	return DESTRUCTIVE.some((pattern) => pattern.test(code));
}

/**
 * The SQL with everything that is not a statement keyword blanked out: `--` and `/* *\/`
 * comments, escape and plain strings, double-quoted identifiers and dollar-quoted bodies
 * (`$$ ... $$`, `$tag$ ... $tag$`, where PL/pgSQL's own BEGIN and END live). Each is replaced by a
 * space, so the statements around it stay apart.
 */
export function stripNonCode(sql: string): string {
	return sql.replace(NON_CODE, ' ');
}

const TRANSACTION_CONTROL =
	/^(?:begin|commit|rollback|end|abort|start\s+transaction|savepoint|release|prepare\s+transaction)\b/i;

/**
 * Whether a file's SQL has a transaction-control statement (B7): a statement, after comments,
 * strings and dollar-quoted bodies are removed, that starts with one of the keywords above. A
 * SQL-standard function body (`BEGIN ATOMIC ... END`) would be refused too; none is needed yet.
 */
export function hasTransactionControl(sql: string): boolean {
	return stripNonCode(sql)
		.split(';')
		.some((statement) => TRANSACTION_CONTROL.test(statement.trim()));
}

/** Every problem with the migrations of `dir`, as fixed phrases and file names. */
export function checkMigrationsDir(dir: string): string[] {
	const problems: string[] = [];
	const files = readMigrations(dir);
	files.forEach((file, i) => {
		const m = MIGRATION_NAME.exec(file.name);
		if (!m) problems.push(`${file.name}: name is not NNNN_<snake_case>`);
		else if (Number(m[1]) !== i)
			problems.push(`${file.name}: number is not ${String(i).padStart(4, '0')}`);
		if (isDestructive(file.sql) && !CONTRACT_MARKER.test(file.sql)) {
			problems.push(`${file.name}: destructive statement without a -- jade:contract <bead> marker`);
		}
		if (hasTransactionControl(file.sql)) {
			problems.push(
				`${file.name}: transaction-control statement (the runner wraps each file in one transaction)`
			);
		}
	});

	let manifest: Manifest;
	try {
		manifest = readManifest(dir);
	} catch {
		problems.push('manifest.json: not a manifest');
		manifest = { migrations: [] };
	}
	const expected = JSON.stringify(buildManifest(dir));
	if (JSON.stringify(manifest) !== expected) {
		problems.push('manifest.json: does not equal the files (run pnpm db:manifest)');
	}

	const journalPath = join(dir, 'meta', '_journal.json');
	if (!existsSync(journalPath)) {
		problems.push('meta/_journal.json: missing');
	} else {
		const journal = JSON.parse(readFileSync(journalPath, 'utf8')) as {
			entries?: { idx?: number; tag?: string }[];
		};
		const tags = (journal.entries ?? []).map((e) => e.tag);
		const idx = (journal.entries ?? []).map((e) => e.idx);
		if (JSON.stringify(tags) !== JSON.stringify(files.map((f) => f.name))) {
			problems.push('meta/_journal.json: entries do not list the files in order');
		}
		if (JSON.stringify(idx) !== JSON.stringify(files.map((_, i) => i))) {
			problems.push('meta/_journal.json: idx is not 0, 1, 2, ...');
		}
	}
	return problems;
}

/** Problems with `head` given the base's manifest: the base must be an unchanged prefix. */
export function checkPrefix(base: Manifest, head: Manifest): string[] {
	const problems: string[] = [];
	base.migrations.forEach((entry, i) => {
		const now = head.migrations[i];
		if (now === undefined) problems.push(`${entry.name}: removed since the base`);
		else if (now.name !== entry.name)
			problems.push(`${entry.name}: renamed or reordered since the base`);
		else if (now.sha256 !== entry.sha256) problems.push(`${entry.name}: edited since the base`);
	});
	return problems;
}

/** The manifest at `ref` (a commit), or an empty one when that commit has none. */
export function manifestAt(ref: string, cwd: string): Manifest {
	const commit = execFileSync('git', ['rev-parse', '--verify', '--quiet', `${ref}^{commit}`], {
		cwd,
		encoding: 'utf8'
	}).trim();
	try {
		execFileSync('git', ['cat-file', '-e', `${commit}:migrations/manifest.json`], {
			cwd,
			stdio: 'ignore'
		});
	} catch {
		return { migrations: [] };
	}
	const text = execFileSync('git', ['show', `${commit}:migrations/manifest.json`], {
		cwd,
		encoding: 'utf8'
	});
	return parseManifest(text);
}

export function main(argv: readonly string[], dir: string = MIGRATIONS_DIR): number {
	let base: string | undefined;
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === '--base' && argv[i + 1]) base = argv[++i];
		else {
			process.stderr.write('usage: db:check [--base <ref>]\n');
			return 2;
		}
	}
	const problems = checkMigrationsDir(dir);
	let note = 'no base given; this checkout only';
	if (base !== undefined) {
		let baseManifest: Manifest;
		try {
			baseManifest = manifestAt(base, join(dir, '..'));
		} catch {
			process.stderr.write('db:check: the base is not a commit of this repository\n');
			return 1;
		}
		problems.push(...checkPrefix(baseManifest, buildManifest(dir)));
		note =
			baseManifest.migrations.length === 0
				? 'the base has no migrations'
				: `the base's ${baseManifest.migrations.length} migration(s) are an unchanged prefix`;
	}
	if (problems.length > 0) {
		for (const problem of problems) process.stderr.write(`db:check: ${problem}\n`);
		return 1;
	}
	process.stdout.write(`db:check: ok, ${readMigrations(dir).length} migration(s); ${note}\n`);
	return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = main(process.argv.slice(2));
}
