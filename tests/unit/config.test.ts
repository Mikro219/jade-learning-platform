// The config module (plan V1 to V3a, INV4). Every case passes its environment explicitly.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
	APP_ENVS,
	CONFIG_KEYS,
	ConfigError,
	SECRET_KEYS,
	configSchema,
	formatConfigError,
	loadAppConfig,
	reportConfigError
} from '../../src/lib/server/config/index.ts';

const REQUIRED = ['APP_ENV', 'DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET'] as const;

// Canary values: if any of these reaches error text, a value leaked.
const PEPPER = 'CanaryPepperAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1';
const SESSION = 'CanarySessionBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2';
const DB_PASSWORD = 'CanaryDbPassword3';

function validEnv(appEnv: string = 'development'): Record<string, string> {
	return {
		APP_ENV: appEnv,
		DATABASE_URL: `postgres://jade_app:${DB_PASSWORD}@127.0.0.1:5432/jade`,
		CODE_PEPPER: PEPPER,
		SESSION_SECRET: SESSION,
		LOG_LEVEL: 'info'
	};
}

function configError(env: Record<string, string | undefined>): ConfigError {
	try {
		loadAppConfig(env);
	} catch (err) {
		expect(err).toBeInstanceOf(ConfigError);
		return err as ConfigError;
	}
	throw new Error('loadAppConfig accepted the environment');
}

function without(env: Record<string, string>, key: string): Record<string, string> {
	const copy = { ...env };
	delete copy[key];
	return copy;
}

describe('loadAppConfig accepts a complete environment', () => {
	it.each(APP_ENVS)('APP_ENV=%s', (appEnv) => {
		const config = loadAppConfig(validEnv(appEnv));
		expect(config).toEqual({
			appEnv,
			databaseUrl: validEnv().DATABASE_URL,
			codePepper: PEPPER,
			sessionSecret: SESSION,
			logLevel: 'info'
		});
		expect(Object.isFrozen(config)).toBe(true);
	});

	it('LOG_LEVEL defaults to info, and postgresql: URLs and hex or base64 secrets are accepted', () => {
		const env = without(validEnv(), 'LOG_LEVEL');
		env.DATABASE_URL = 'postgresql://jade_app:pw@db:5432/jade';
		env.CODE_PEPPER = 'a'.repeat(64);
		env.SESSION_SECRET = 'Zm9vYmFy+/Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9v=';
		expect(loadAppConfig(env).logLevel).toBe('info');
		expect(loadAppConfig({ ...env, LOG_LEVEL: 'debug' }).logLevel).toBe('debug');
	});
});

describe('a missing required variable is named', () => {
	for (const appEnv of APP_ENVS) {
		it.each(REQUIRED)(`APP_ENV=${appEnv}, %s removed`, (key) => {
			// The environment before removal is accepted, so only the removal can refuse it (PD15).
			const env = validEnv(appEnv);
			expect(() => loadAppConfig(env)).not.toThrow();
			const err = configError(without(env, key));
			expect(err.missing).toEqual([key]);
			expect(err.invalid).toEqual([]);
			expect(err.message).toBe(`Configuration error. Missing: ${key}. See .env.example.`);
		});
	}

	it('an empty value counts as missing, and every problem is listed at once', () => {
		const err = configError({ APP_ENV: 'staging', DATABASE_URL: '', LOG_LEVEL: 'loud' });
		expect(err.missing).toEqual(['DATABASE_URL', 'CODE_PEPPER', 'SESSION_SECRET']);
		expect(err.invalid).toEqual(['LOG_LEVEL']);
		expect(err.message).toBe(
			'Configuration error. Missing: DATABASE_URL, CODE_PEPPER, SESSION_SECRET. ' +
				'Invalid: LOG_LEVEL (must be one of debug, info, warn, error). See .env.example.'
		);
	});
});

describe('bad values are refused by name', () => {
	const cases: [string, string, string, string][] = [
		['a short pepper', 'CODE_PEPPER', 'CanaryShort', 'must be at least 43 characters'],
		['a pepper outside the alphabet', 'CODE_PEPPER', `${PEPPER}!`, 'must be at least 43'],
		['a short session secret', 'SESSION_SECRET', 'CanaryShort', 'must be at least 43'],
		[
			'a non-postgres URL',
			'DATABASE_URL',
			`mysql://jade_app:${DB_PASSWORD}@127.0.0.1/jade`,
			'must be a postgres URL for role jade_app'
		],
		[
			'a URL for another role',
			'DATABASE_URL',
			`postgres://jade_owner:${DB_PASSWORD}@127.0.0.1/jade`,
			'must be a postgres URL for role jade_app'
		],
		[
			'a URL that does not parse',
			'DATABASE_URL',
			`not a url ${DB_PASSWORD}`,
			'must be a postgres URL'
		],
		['an unknown APP_ENV', 'APP_ENV', 'CanaryEnv', 'must be one of development, test'],
		['an unknown LOG_LEVEL', 'LOG_LEVEL', 'CanaryLevel', 'must be one of debug, info']
	];
	it.each(cases)('%s', (_label, key, value, phrase) => {
		const err = configError({ ...validEnv(), [key]: value });
		expect(err.missing).toEqual([]);
		expect(err.invalid).toEqual([key]);
		expect(err.message).toContain(`Invalid: ${key} (${phrase}`);
		expect(err.message).not.toContain(value);
		expect(err.message).not.toContain('Canary');
	});
});

describe('test-only values', () => {
	const testOnly = {
		DATABASE_URL: 'postgres://jade_app:test-only-pw@127.0.0.1:5432/jade',
		CODE_PEPPER: 'test-only-pepper-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
		SESSION_SECRET: 'test-only-session-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'
	};

	it('are accepted under APP_ENV=test', () => {
		expect(() => loadAppConfig({ ...validEnv('test'), ...testOnly })).not.toThrow();
	});

	for (const appEnv of ['development', 'staging', 'production'] as const) {
		it.each(Object.keys(testOnly))(`are refused under APP_ENV=${appEnv}: %s`, (key) => {
			const value = testOnly[key as keyof typeof testOnly];
			// The same value passes every format check: under test it is accepted (PD15).
			expect(() => loadAppConfig({ ...validEnv('test'), [key]: value })).not.toThrow();
			const err = configError({ ...validEnv(appEnv), [key]: value });
			expect(err.invalid).toEqual([key]);
			expect(err.message).toBe(
				`Configuration error. Invalid: ${key} (a test-only value is refused unless APP_ENV is test). See .env.example.`
			);
			expect(err.message).not.toContain(value);
		});
	}
});

describe('NODE_ENV=production', () => {
	it.each(['staging', 'production'])('accepts APP_ENV=%s', (appEnv) => {
		expect(loadAppConfig({ ...validEnv(appEnv), NODE_ENV: 'production' }).appEnv).toBe(appEnv);
	});

	it.each(['development', 'test'])('refuses APP_ENV=%s', (appEnv) => {
		expect(() => loadAppConfig(validEnv(appEnv))).not.toThrow();
		const err = configError({ ...validEnv(appEnv), NODE_ENV: 'production' });
		expect(err.invalid).toEqual(['APP_ENV']);
		expect(err.message).toContain(
			'Invalid: APP_ENV (must be staging or production when NODE_ENV is production)'
		);
	});
});

describe('no secret has a default', () => {
	it.each(SECRET_KEYS)('%s: the schema refuses undefined', (key) => {
		expect(configSchema.shape[key].safeParse(undefined).success).toBe(false);
	});

	it('the schema source puts a default or fallback on no secret key', () => {
		const source = readFileSync(
			new URL('../../src/lib/server/config/index.ts', import.meta.url),
			'utf8'
		);
		for (const key of SECRET_KEYS) {
			const lines = source.split('\n').filter((line) => line.includes(`${key}:`));
			expect(lines.length).toBeGreaterThan(0);
			for (const line of lines) expect(line).not.toMatch(/\.default\(|\.catch\(|\?\?|\|\|/);
		}
	});

	it('every secret key is required in every APP_ENV, test included', () => {
		for (const appEnv of APP_ENVS) {
			for (const key of SECRET_KEYS) {
				expect(configError(without(validEnv(appEnv), key)).missing).toEqual([key]);
			}
		}
	});
});

describe('reportConfigError', () => {
	it('writes the V3 sentence', () => {
		const lines: string[] = [];
		reportConfigError(configError(without(validEnv(), 'CODE_PEPPER')), (l) => lines.push(l));
		expect(lines).toEqual(['Configuration error. Missing: CODE_PEPPER. See .env.example.\n']);
	});

	it('writes [invalid] in place of a name outside the schemas, and no canary', () => {
		const canary = 'CanaryValue-postgres://jade_app:secret@host/db';
		const err = new ConfigError(['NOT_A_CONFIG_KEY', canary], ['DATABASE_URL', canary], {
			DATABASE_URL: 'database_url',
			[canary]: 'database_url'
		});
		const lines: string[] = [];
		reportConfigError(err, (l) => lines.push(l));
		const out = lines.join('');
		expect(out).toBe(
			'Configuration error. Missing: [invalid], [invalid]. ' +
				'Invalid: DATABASE_URL (must be a postgres URL for role jade_app), [invalid]. See .env.example.\n'
		);
		expect(out).not.toContain('Canary');
		expect(out).not.toContain('NOT_A_CONFIG_KEY');
		expect(err.message).not.toContain('Canary');
	});

	it('leaves out a reason outside the fixed set', () => {
		expect(formatConfigError([], ['LOG_LEVEL'], { LOG_LEVEL: 'Canary reason' })).toBe(
			'Configuration error. Invalid: LOG_LEVEL. See .env.example.'
		);
	});

	it('the key set is the schema shape', () => {
		expect([...CONFIG_KEYS].sort()).toEqual(Object.keys(configSchema.shape).sort());
	});
});
