// `pnpm env:init` (plan V5): write an env file with freshly generated secrets, mode 600, to
// `.env` or to the path given with `--out`. It refuses to overwrite an existing file and prints
// variable names only, never a value. Node built-ins and tools/free-port.ts only, so it also runs
// in the image.
//
// Profiles (jade-80h adds the local stack's variables and the `stack` profile):
//   - `dev`, the default and the README's: APP_ENV=development, both database passwords and both
//     URLs, written from the same generated values, the app's secrets.
//   - `ci`, for a CI job (X2): APP_ENV=test; JADE_OWNER_DB_PASSWORD taken from the job's
//     environment (the service container's literal password), refused unless it contains
//     `test-only`; the app password and the app's secrets generated; both URLs at
//     127.0.0.1:<--db-port>, which is required.
//
//   pnpm env:init [--out <path>] [--profile dev|ci] [--db-port <port>]
import { randomBytes } from 'node:crypto';
import {
	closeSync,
	fchmodSync,
	fsyncSync,
	linkSync,
	openSync,
	unlinkSync,
	writeFileSync
} from 'node:fs';
import { connect, createServer } from 'node:net';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { freePort } from './free-port.ts';

export const PROFILES = ['dev', 'ci'] as const;
export type Profile = (typeof PROFILES)[number];

/** A secret: 32 random bytes in base64url, 43 characters of `[A-Za-z0-9_-]`. */
export function generateSecret(): string {
	return randomBytes(32).toString('base64url');
}

/** A database password: 24 random bytes in base64url, so it sits in a URL unescaped. */
export function generatePassword(): string {
	return randomBytes(24).toString('base64url');
}

/** The development database URL for role `jade_app`. */
export function appDatabaseUrl(password: string, port: number): string {
	return `postgres://jade_app:${password}@127.0.0.1:${port}/jade`;
}

/** The development database URL for role `jade_owner`, which only the migration tool reads. */
export function ownerDatabaseUrl(password: string, port: number): string {
	return `postgres://jade_owner:${password}@127.0.0.1:${port}/jade`;
}

const DEFAULT_DB_PORT = 5432;

/** Whether something accepts a TCP connection on 127.0.0.1:`port`. */
function answers(port: number): Promise<boolean> {
	return new Promise((done) => {
		const socket = connect({ host: '127.0.0.1', port });
		const finish = (result: boolean) => {
			socket.destroy();
			done(result);
		};
		socket.setTimeout(500, () => finish(true));
		socket.once('connect', () => finish(true));
		socket.once('error', (err: NodeJS.ErrnoException) => finish(err.code !== 'ECONNREFUSED'));
	});
}

/** Whether 127.0.0.1:`port` can be bound now. */
function bindable(port: number): Promise<boolean> {
	return new Promise((done) => {
		const server = createServer();
		server.once('error', () => done(false));
		server.listen(port, '127.0.0.1', () => server.close(() => done(true)));
	});
}

/**
 * JADE_DEV_DB_PORT (PD11): `--db-port` when given, else 5432 when nothing answers on
 * 127.0.0.1:5432 and the port can be bound, else a port from freePort(), so a second worktree
 * gets a database of its own.
 */
export async function chooseDbPort(given?: number): Promise<number> {
	if (given !== undefined) return given;
	if (!(await answers(DEFAULT_DB_PORT)) && (await bindable(DEFAULT_DB_PORT))) {
		return DEFAULT_DB_PORT;
	}
	return freePort();
}

class UsageError extends Error {}

/** A refusal of the input: a fixed message naming variables, never a value. */
class RefusedError extends Error {}

/** The variables of a profile, in file order. */
export async function profileVariables(
	profile: Profile,
	options: { dbPort?: number; env?: Readonly<Record<string, string | undefined>> } = {}
): Promise<[string, string][]> {
	switch (profile) {
		case 'dev': {
			const port = await chooseDbPort(options.dbPort);
			const ownerPassword = generatePassword();
			const appPassword = generatePassword();
			return [
				['APP_ENV', 'development'],
				['JADE_OWNER_DB_PASSWORD', ownerPassword],
				['JADE_APP_DB_PASSWORD', appPassword],
				['JADE_DEV_DB_PORT', String(port)],
				['MIGRATION_DATABASE_URL', ownerDatabaseUrl(ownerPassword, port)],
				['DATABASE_URL', appDatabaseUrl(appPassword, port)],
				['CODE_PEPPER', generateSecret()],
				['SESSION_SECRET', generateSecret()],
				['LOG_LEVEL', 'info']
			];
		}
		case 'ci': {
			const port = options.dbPort;
			if (port === undefined) throw new UsageError('--profile ci needs --db-port');
			const ownerPassword = options.env?.['JADE_OWNER_DB_PASSWORD'] ?? '';
			// It sits in a URL unescaped, and it is a CI-only literal (X2): test-only, or refused.
			if (!/^[A-Za-z0-9_-]+$/.test(ownerPassword) || !ownerPassword.includes('test-only')) {
				throw new RefusedError(
					'JADE_OWNER_DB_PASSWORD must be set to a [A-Za-z0-9_-] value containing test-only'
				);
			}
			const appPassword = generatePassword();
			return [
				['APP_ENV', 'test'],
				['JADE_OWNER_DB_PASSWORD', ownerPassword],
				['JADE_APP_DB_PASSWORD', appPassword],
				['MIGRATION_DATABASE_URL', ownerDatabaseUrl(ownerPassword, port)],
				['DATABASE_URL', appDatabaseUrl(appPassword, port)],
				['CODE_PEPPER', generateSecret()],
				['SESSION_SECRET', generateSecret()],
				['LOG_LEVEL', 'info']
			];
		}
	}
}

interface Args {
	out: string;
	profile: Profile;
	dbPort?: number;
}

function parsePort(text: string | undefined, flag: string): number {
	const port = Number(text);
	if (!/^\d+$/.test(text ?? '') || port < 1 || port > 65535) {
		throw new UsageError(`${flag} needs a port number from 1 to 65535`);
	}
	return port;
}

function parseArgs(argv: readonly string[]): Args {
	const args: Args = { out: '.env', profile: 'dev' };
	for (let i = 0; i < argv.length; i++) {
		const flag = argv[i];
		const value = argv[i + 1];
		switch (flag) {
			case '--out':
				if (!value) throw new UsageError('--out needs a path');
				args.out = value;
				i++;
				break;
			case '--profile':
				if (!(PROFILES as readonly string[]).includes(value ?? '')) {
					throw new UsageError(`--profile must be one of: ${PROFILES.join(', ')}`);
				}
				args.profile = value as Profile;
				i++;
				break;
			case '--db-port':
				args.dbPort = parsePort(value, '--db-port');
				i++;
				break;
			default:
				// The flag itself is not echoed: it might be a value pasted in the wrong place.
				throw new UsageError(
					'unknown argument; usage: env:init [--out <path>] [--profile dev|ci] [--db-port <port>]'
				);
		}
	}
	return args;
}

const HEADER = [
	'# Written by `pnpm env:init`. Holds secrets: never commit it, never paste it anywhere.',
	'# Every variable is documented in .env.example.'
];

/**
 * The temporary file's name for `target`: `<basename>.tmp-<pid>-<hex>`, in the target's directory.
 * For `.env` that is `.env.tmp-…`, which `.gitignore`'s `.env.*` covers, so a write killed
 * part-way leaves no untracked file of secrets that git would offer to add (B1).
 */
export function tempEnvFileName(
	target: string,
	pid: number = process.pid,
	hex: string = randomBytes(6).toString('hex')
): string {
	return join(dirname(target), `${basename(target)}.tmp-${pid}-${hex}`);
}

/** Link errors after which writeEnvFile writes the file in place instead (B8). */
const NO_LINK = new Set(['EPERM', 'ENOTSUP', 'EOPNOTSUPP', 'EXDEV']);

function writeFd(fd: number, text: string, write: (fd: number, text: string) => void): void {
	try {
		fchmodSync(fd, 0o600);
		write(fd, text);
		fsyncSync(fd);
	} finally {
		closeSync(fd);
	}
}

/**
 * Write the env file atomically (B8). Fails, leaving any existing file untouched, if `path`
 * exists. The text goes to a temporary file in the same directory (opened `wx`, mode 600), is
 * flushed to disk, and is then hard-linked to `path`: the link fails if `path` exists, so an
 * existing file is never truncated or overwritten, and `path` appears only complete. Where the
 * file system has no hard links (the link fails with EPERM, ENOTSUP, EOPNOTSUPP or EXDEV), `path`
 * itself is opened `wx` (mode 600), written and flushed, and removed again if that fails. The
 * temporary file is removed on every outcome, so a failure leaves no file at all.
 * `options.write` and `options.link` replace the write and the link themselves (tests).
 */
export function writeEnvFile(
	path: string,
	variables: readonly [string, string][],
	options: {
		readonly write?: (fd: number, text: string) => void;
		readonly link?: (existing: string, target: string) => void;
	} = {}
): void {
	const text = [...HEADER, ...variables.map(([name, value]) => `${name}=${value}`), ''].join('\n');
	const write = options.write ?? ((fd: number, data: string) => writeFileSync(fd, data));
	const link = options.link ?? linkSync;
	const tmp = tempEnvFileName(path);
	const fd = openSync(tmp, 'wx', 0o600);
	try {
		writeFd(fd, text, write);
		try {
			link(tmp, path);
		} catch (err) {
			if (!NO_LINK.has(String((err as NodeJS.ErrnoException).code))) throw err;
			const direct = openSync(path, 'wx', 0o600);
			try {
				writeFd(direct, text, write);
			} catch (writeErr) {
				try {
					unlinkSync(path);
				} catch {
					// Nothing more to do; the original error is what matters.
				}
				throw writeErr;
			}
		}
	} finally {
		try {
			unlinkSync(tmp);
		} catch {
			// Already gone; nothing to clean up.
		}
	}
}

/** An error's code as fixed text: an `E…` code, or `unknown`, never a message or a value. */
export function errorCodeOf(err: unknown): string {
	const code = (err as NodeJS.ErrnoException | null)?.code;
	return typeof code === 'string' && /^E[A-Z0-9_]{1,30}$/.test(code) ? code : 'unknown';
}

export async function main(argv: readonly string[]): Promise<number> {
	let args: Args;
	try {
		args = parseArgs(argv);
	} catch (err) {
		if (err instanceof UsageError) {
			process.stderr.write(`env:init: ${err.message}\n`);
			return 2;
		}
		throw err;
	}
	const path = resolve(args.out);
	let variables: [string, string][];
	try {
		variables = await profileVariables(args.profile, { dbPort: args.dbPort, env: process.env });
	} catch (err) {
		if (err instanceof UsageError) {
			process.stderr.write(`env:init: ${err.message}\n`);
			return 2;
		}
		if (err instanceof RefusedError) {
			process.stderr.write(`env:init: ${err.message}; nothing was written.\n`);
			return 1;
		}
		throw err;
	}
	try {
		writeEnvFile(path, variables);
	} catch (err) {
		if ((err as NodeJS.ErrnoException).code === 'EEXIST') {
			process.stderr.write(`env:init: ${args.out} already exists; it was not changed.\n`);
			return 1;
		}
		process.stderr.write(`env:init: could not write ${args.out} (${errorCodeOf(err)}).\n`);
		return 1;
	}
	process.stdout.write(
		`env:init: wrote ${args.out} (mode 600, profile ${args.profile}) with: ${variables
			.map(([name]) => name)
			.join(', ')}\n`
	);
	return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.exitCode = await main(process.argv.slice(2));
}
