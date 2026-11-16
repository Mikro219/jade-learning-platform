// `pnpm env:init` (plan V5): write an env file with freshly generated secrets, mode 600, to
// `.env` or to the path given with `--out`. It refuses to overwrite an existing file and prints
// variable names only, never a value. Node built-ins and tools/free-port.ts only, so it also runs
// in the image.
//
// Profiles: `dev` (the default, the README's). jade-urd adds the database owner's variables and
// the `ci` profile; jade-80h adds the local stack's variables and the `stack` profile.
//
//   pnpm env:init [--out <path>] [--profile dev] [--db-port <port>]
import { randomBytes } from 'node:crypto';
import { chmodSync, closeSync, openSync, writeSync } from 'node:fs';
import { connect, createServer } from 'node:net';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { freePort } from './free-port.ts';

export const PROFILES = ['dev'] as const;
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

/** The variables of a profile, in file order. */
export async function profileVariables(
	profile: Profile,
	options: { dbPort?: number } = {}
): Promise<[string, string][]> {
	switch (profile) {
		case 'dev': {
			const port = await chooseDbPort(options.dbPort);
			const appPassword = generatePassword();
			return [
				['APP_ENV', 'development'],
				['JADE_APP_DB_PASSWORD', appPassword],
				['JADE_DEV_DB_PORT', String(port)],
				['DATABASE_URL', appDatabaseUrl(appPassword, port)],
				['CODE_PEPPER', generateSecret()],
				['SESSION_SECRET', generateSecret()],
				['LOG_LEVEL', 'info']
			];
		}
	}
}

class UsageError extends Error {}

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
					'unknown argument; usage: env:init [--out <path>] [--profile dev] [--db-port <port>]'
				);
		}
	}
	return args;
}

const HEADER = [
	'# Written by `pnpm env:init`. Holds secrets: never commit it, never paste it anywhere.',
	'# Every variable is documented in .env.example.'
];

/** Write the env file. Fails, leaving any existing file untouched, if `path` exists. */
export function writeEnvFile(path: string, variables: readonly [string, string][]): void {
	const text = [...HEADER, ...variables.map(([name, value]) => `${name}=${value}`), ''].join('\n');
	// 'wx' fails if the file exists, so an existing file is never truncated or overwritten.
	const fd = openSync(path, 'wx', 0o600);
	try {
		writeSync(fd, text);
	} finally {
		closeSync(fd);
	}
	chmodSync(path, 0o600);
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
	const variables = await profileVariables(args.profile, { dbPort: args.dbPort });
	try {
		writeEnvFile(path, variables);
	} catch (err) {
		if ((err as NodeJS.ErrnoException).code === 'EEXIST') {
			process.stderr.write(`env:init: ${args.out} already exists; it was not changed.\n`);
			return 1;
		}
		process.stderr.write(`env:init: could not write ${args.out}.\n`);
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
