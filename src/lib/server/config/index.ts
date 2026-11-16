// The app's configuration (plan section 8, V1 to V3a). One module, no SvelteKit import, so the
// tools can use it too. `loadAppConfig(env)` is pure; `getConfig()` parses `process.env` once.
// No other file under src/ reads `process.env` (ESLint no-restricted-properties).
//
// Error text is built from variable names and fixed phrases only: never a value, never zod's own
// message text (INV4).
import { z } from 'zod';

export const APP_ENVS = ['development', 'test', 'staging', 'production'] as const;
export const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;

export type AppEnv = (typeof APP_ENVS)[number];
export type LogLevel = (typeof LOG_LEVELS)[number];

/** Every variable the config schemas read. jade-urd adds MIGRATION_DATABASE_URL. */
export const CONFIG_KEYS = [
	'APP_ENV',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET',
	'LOG_LEVEL'
] as const;
export type ConfigKey = (typeof CONFIG_KEYS)[number];

/** Keys whose values are secret. None of them has a default, in any APP_ENV. */
export const SECRET_KEYS = ['DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET'] as const;

/** Keys that must be present (non-empty). */
const REQUIRED_KEYS: readonly ConfigKey[] = [
	'APP_ENV',
	'DATABASE_URL',
	'CODE_PEPPER',
	'SESSION_SECRET'
];

/** 32 random bytes in base64, base64url or hex is at least 43 characters of this alphabet. */
const SECRET_PATTERN = /^[A-Za-z0-9_+/=-]{43,}$/;

/** The database role the app connects as (plan PD3). */
const APP_DB_ROLE = 'jade_app';

function isAppDatabaseUrl(value: string): boolean {
	let url: URL;
	try {
		url = new URL(value);
	} catch {
		return false;
	}
	if (url.protocol !== 'postgres:' && url.protocol !== 'postgresql:') return false;
	if (url.hostname === '') return false;
	let user: string;
	try {
		user = decodeURIComponent(url.username);
	} catch {
		return false;
	}
	return user === APP_DB_ROLE;
}

// One field per line. Only LOG_LEVEL has a default; tests/unit/config.test.ts checks that no
// secret key has one, both in this source and by parsing `undefined`.
const fields = {
	APP_ENV: z.enum(APP_ENVS),
	DATABASE_URL: z.string().refine(isAppDatabaseUrl),
	CODE_PEPPER: z.string().regex(SECRET_PATTERN),
	SESSION_SECRET: z.string().regex(SECRET_PATTERN),
	LOG_LEVEL: z.enum(LOG_LEVELS).default('info')
} as const;

export const configSchema = z.object(fields);

/** Why a variable was refused: a closed set of codes, each with one fixed phrase. */
export type InvalidReason =
	| 'app_env'
	| 'app_env_node_production'
	| 'database_url'
	| 'secret_format'
	| 'log_level'
	| 'test_only';

const REASON_PHRASES: Record<InvalidReason, string> = {
	app_env: 'must be one of development, test, staging, production',
	app_env_node_production: 'must be staging or production when NODE_ENV is production',
	database_url: 'must be a postgres URL for role jade_app',
	secret_format: 'must be at least 43 characters of A-Z a-z 0-9 _ + / = -',
	log_level: 'must be one of debug, info, warn, error',
	test_only: 'a test-only value is refused unless APP_ENV is test'
};

const FORMAT_REASON: Record<ConfigKey, InvalidReason> = {
	APP_ENV: 'app_env',
	DATABASE_URL: 'database_url',
	CODE_PEPPER: 'secret_format',
	SESSION_SECRET: 'secret_format',
	LOG_LEVEL: 'log_level'
};

const KEY_SET: ReadonlySet<string> = new Set<string>(CONFIG_KEYS);
const REASON_SET: ReadonlySet<string> = new Set<string>(Object.keys(REASON_PHRASES));

/** A name from the schemas' key set, or `[invalid]` in its place. */
function safeName(name: unknown): string {
	return typeof name === 'string' && KEY_SET.has(name) ? name : '[invalid]';
}

/**
 * The V3 sentence, rebuilt from validated names and fixed phrases only: anything that is not a
 * key of the config schemas is written as `[invalid]`, and a reason outside the fixed set is left
 * out.
 */
export function formatConfigError(
	missing: readonly unknown[],
	invalid: readonly unknown[],
	reasons: Readonly<Record<string, unknown>> = {}
): string {
	const parts = ['Configuration error.'];
	if (missing.length > 0) parts.push(`Missing: ${missing.map(safeName).join(', ')}.`);
	if (invalid.length > 0) {
		const items = invalid.map((name) => {
			const safe = safeName(name);
			const reason = safe === '[invalid]' ? undefined : reasons[safe];
			return typeof reason === 'string' && REASON_SET.has(reason)
				? `${safe} (${REASON_PHRASES[reason as InvalidReason]})`
				: safe;
		});
		parts.push(`Invalid: ${items.join(', ')}.`);
	}
	parts.push('See .env.example.');
	return parts.join(' ');
}

/** The configuration is unusable. Carries names only, never a value. */
export class ConfigError extends Error {
	readonly missing: readonly string[];
	readonly invalid: readonly string[];
	readonly reasons: Readonly<Record<string, InvalidReason>>;

	constructor(
		missing: readonly string[],
		invalid: readonly string[],
		reasons: Readonly<Record<string, InvalidReason>> = {}
	) {
		super(formatConfigError(missing, invalid, reasons));
		this.name = 'ConfigError';
		this.missing = Object.freeze([...missing]);
		this.invalid = Object.freeze([...invalid]);
		this.reasons = Object.freeze({ ...reasons });
	}
}

export interface AppConfig {
	readonly appEnv: AppEnv;
	readonly databaseUrl: string;
	/** Opaque; how key bytes are derived from it is jade-fd5's decision (V7). */
	readonly codePepper: string;
	/** Opaque; nothing reads it before Phase 3 (V7). */
	readonly sessionSecret: string;
	readonly logLevel: LogLevel;
}

type Env = Readonly<Record<string, string | undefined>>;

/**
 * Parse and validate the app's configuration from `env`. Returns a frozen object or throws a
 * `ConfigError` that lists every problem at once. `NODE_ENV` is read from `env`, never as the
 * literal `process.env.NODE_ENV`, which a bundler may replace.
 */
export function loadAppConfig(env: Env): AppConfig {
	const missing: ConfigKey[] = [];
	const invalid: ConfigKey[] = [];
	const reasons: Partial<Record<ConfigKey, InvalidReason>> = {};
	const refuse = (key: ConfigKey, reason: InvalidReason) => {
		if (!invalid.includes(key)) invalid.push(key);
		reasons[key] ??= reason;
	};

	const raw: Partial<Record<ConfigKey, string>> = {};
	for (const key of CONFIG_KEYS) {
		const value = env[key];
		// An empty value counts as unset: .env.example leaves every secret empty.
		if (value !== undefined && value !== '') raw[key] = value;
		else if (REQUIRED_KEYS.includes(key)) missing.push(key);
	}

	const parsed: Partial<Record<ConfigKey, unknown>> = {};
	for (const key of CONFIG_KEYS) {
		if (raw[key] === undefined && REQUIRED_KEYS.includes(key)) continue;
		const result = fields[key].safeParse(raw[key]);
		if (result.success) parsed[key] = result.data;
		else refuse(key, FORMAT_REASON[key]);
	}

	const appEnv = parsed.APP_ENV as AppEnv | undefined;

	// The image sets NODE_ENV=production (D1): it cannot run as development or test.
	if (env['NODE_ENV'] === 'production' && appEnv !== undefined) {
		if (appEnv !== 'staging' && appEnv !== 'production')
			refuse('APP_ENV', 'app_env_node_production');
	}

	// A value marked test-only (the CI job's throwaway credentials) is refused outside test.
	if (appEnv !== 'test') {
		for (const key of CONFIG_KEYS) {
			if (raw[key]?.includes('test-only')) refuse(key, 'test_only');
		}
	}

	if (missing.length > 0 || invalid.length > 0) throw new ConfigError(missing, invalid, reasons);

	return Object.freeze({
		appEnv: appEnv as AppEnv,
		databaseUrl: parsed.DATABASE_URL as string,
		codePepper: parsed.CODE_PEPPER as string,
		sessionSecret: parsed.SESSION_SECRET as string,
		logLevel: parsed.LOG_LEVEL as LogLevel
	});
}

let cached: AppConfig | undefined;

/** The app's configuration from `process.env`, parsed once. Throws `ConfigError`. */
export function getConfig(): AppConfig {
	cached ??= loadAppConfig(process.env);
	return cached;
}

/**
 * Report a configuration failure (V3a). Until jade-alt adds the logger this writes the V3
 * sentence on stderr, rebuilt from the error's names through `formatConfigError`, so a name
 * outside the schemas' key set, or any other text, cannot reach the output.
 */
export function reportConfigError(
	err: ConfigError,
	write: (line: string) => void = (line) => {
		process.stderr.write(line);
	}
): void {
	write(`${formatConfigError(err.missing, err.invalid, err.reasons)}\n`);
}
