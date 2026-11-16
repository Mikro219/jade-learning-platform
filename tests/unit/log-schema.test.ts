// INV1, PD6, A1, A1a: the closed logger. Every key is on an allowlist, forbidden key names cannot
// be registered, each value passes its validator or is written as `[invalid]`, an error's message
// and properties are never written, `stack_frames` comes only from recorded call sites, and the
// same input gives the same output under every APP_ENV.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	FORBIDDEN_KEY_PARTS,
	INVALID,
	LINE_KEYS,
	PREVIOUS_HOOK,
	buildAllowlist,
	createLogger,
	isForbiddenKeyName,
	NODE_ERRNO_NAMES,
	registerConfigKeyNames,
	registerErrorTags,
	registerRouteIds,
	stackFramesOf,
	type LogLevel,
	type Logger
} from '../../src/lib/server/log/index.ts';
import { CONFIG_KEYS } from '../../src/lib/server/config/index.ts';

const REQUEST_ID = '0b6f8a3e-6c1d-4f0a-9d47-2f1c3b5a7e90';
const FIXED = new Date('2026-11-15T12:00:00.000Z');

registerRouteIds(['/healthz', '/(student)']);

function capture(options: { level?: LogLevel } = {}) {
	const lines: string[] = [];
	const logger: Logger = createLogger({
		write: (l) => lines.push(l),
		now: () => FIXED,
		...options
	});
	return {
		lines,
		logger,
		parsed: () => lines.map((l) => JSON.parse(l) as Record<string, unknown>)
	};
}

function errorLine(error: unknown): { text: string; line: Record<string, unknown> } {
	const { lines, logger } = capture();
	logger.error({ requestId: REQUEST_ID, route: '/healthz', kind: 'unknown', error });
	expect(lines).toHaveLength(1);
	return { text: lines[0]!, line: JSON.parse(lines[0]!) };
}

/** `stack_frames` is frames built from call sites (this file among them) or `[invalid]`. */
function expectFramesOrInvalid(value: unknown) {
	if (value === INVALID) return;
	expect(Array.isArray(value)).toBe(true);
	for (const frame of value as string[]) expect(frame).toMatch(/^\S.* \(.+:\d+:\d+\)$/);
}

describe('allowlists', () => {
	it('every line kind has exactly its closed key set', () => {
		expect(LINE_KEYS.request).toEqual([
			'ts',
			'level',
			'msg',
			'request_id',
			'method',
			'route',
			'status',
			'duration_ms'
		]);
		expect(LINE_KEYS.error).toEqual([
			'ts',
			'level',
			'msg',
			'request_id',
			'route',
			'kind',
			'err_type',
			'err_tag',
			'stack_frames'
		]);
		expect(LINE_KEYS.lifecycle).toEqual([
			'ts',
			'level',
			'msg',
			'migration',
			'count',
			'missing',
			'invalid'
		]);
	});

	it('no allowlisted key is a forbidden name', () => {
		for (const key of [...LINE_KEYS.request, ...LINE_KEYS.error, ...LINE_KEYS.lifecycle]) {
			expect(isForbiddenKeyName(key)).toBe(false);
		}
	});

	it('forbidden key names, alone or as an underscore-separated part, cannot be registered', () => {
		const names = [
			...FORBIDDEN_KEY_PARTS,
			...FORBIDDEN_KEY_PARTS.map((p) => `client_${p}`),
			...FORBIDDEN_KEY_PARTS.map((p) => `${p}_id`),
			'remote_addr',
			'kit_id',
			'class_id',
			'session_id',
			'step_id',
			'x_user_agent_raw',
			'join_code',
			'IP'
		];
		for (const name of names) {
			expect(isForbiddenKeyName(name)).toBe(true);
			expect(() => buildAllowlist({ [name]: (v) => v })).toThrow(/log key refused/);
		}
		// A substring that is not an underscore-separated part is not forbidden.
		expect(isForbiddenKeyName('description')).toBe(false);
		expect(() => buildAllowlist({ count: (v) => v })).not.toThrow();
	});
});

describe('request lines', () => {
	it('writes the closed key set with valid values', () => {
		const { logger, parsed } = capture();
		logger.request(
			{ requestId: REQUEST_ID, method: 'GET', route: '/healthz', status: 200, durationMs: 1.5 },
			'info'
		);
		expect(parsed()).toEqual([
			{
				ts: FIXED.toISOString(),
				level: 'info',
				msg: 'request',
				request_id: REQUEST_ID,
				method: 'GET',
				route: '/healthz',
				status: 200,
				duration_ms: 1.5
			}
		]);
	});

	it('writes [invalid] for every value that fails its validator', () => {
		const { logger, parsed } = capture();
		logger.request(
			{
				requestId: 'canary-not-a-uuid',
				method: 'CANARY',
				route: '/canary/path?code=canary',
				status: 9999,
				durationMs: Number.NaN
			},
			'info'
		);
		const [line] = parsed();
		expect(line).toMatchObject({
			request_id: INVALID,
			method: INVALID,
			route: INVALID,
			status: INVALID,
			duration_ms: INVALID
		});
		expect(JSON.stringify(line).toLowerCase()).not.toContain('canary');
	});

	it('accepts a null route (nothing matched)', () => {
		const { logger, parsed } = capture();
		logger.request(
			{ requestId: REQUEST_ID, method: 'GET', route: null, status: 404, durationMs: 0 },
			'info'
		);
		expect(parsed()[0]!.route).toBeNull();
	});
});

describe('error lines', () => {
	it('a Postgres-style error: tag only, no message, detail or parameters', () => {
		const err = Object.assign(new Error('duplicate key canary-message'), {
			code: '23505',
			detail: 'Key (code)=(canary-detail) already exists.',
			parameters: ['canary-parameter'],
			hint: 'canary-hint',
			severity: 'ERROR'
		});
		const { text, line } = errorLine(err);
		expect(Object.keys(line)).toEqual(LINE_KEYS.error);
		expect(line).toMatchObject({
			level: 'error',
			msg: 'error',
			request_id: REQUEST_ID,
			route: '/healthz',
			kind: 'unknown',
			err_type: 'Error',
			err_tag: '23505'
		});
		expect(text.toLowerCase()).not.toContain('canary');
		expectFramesOrInvalid(line.stack_frames);
	});

	it('an app error tag is written; a tag that fails its validator is [invalid]', () => {
		registerErrorTags(['MIGRATION_FAILED']);
		const tagged = Object.assign(new Error('x'), { tag: 'MIGRATION_FAILED' });
		expect(errorLine(tagged).line.err_tag).toBe('MIGRATION_FAILED');
		const bad = Object.assign(new Error('x'), { code: 'canary code' });
		expect(errorLine(bad).line.err_tag).toBe(INVALID);
	});

	describe('err_tag is a SQLSTATE, a Node error code or a registered app tag only (jade-zwq)', () => {
		// Shaped like a six-character Crockford join code, and like a kit code without its dashes.
		const JOIN = '7KQ4XM';
		const tagOf = (props: Record<string, unknown>) =>
			errorLine(Object.assign(new Error('x'), props));

		it('a join-code-shaped .code or .tag is [invalid], and the value is not written', () => {
			for (const props of [{ code: JOIN }, { tag: JOIN }, { code: 'ARM7KQ4XM2H9' }]) {
				const { text, line } = tagOf(props);
				expect(line.err_tag).toBe(INVALID);
				expect(text).not.toContain(Object.values(props)[0] as string);
			}
		});

		it('an unregistered app tag is [invalid], a registered one is written', () => {
			expect(tagOf({ tag: 'NOT_A_REGISTERED_TAG' }).line.err_tag).toBe(INVALID);
			registerErrorTags(['SOME_REGISTERED_TAG', 'not upper case']);
			expect(tagOf({ tag: 'SOME_REGISTERED_TAG' }).line.err_tag).toBe('SOME_REGISTERED_TAG');
			expect(tagOf({ tag: 'not upper case' }).line.err_tag).toBe(INVALID);
		});

		it('the app registers its own fixed tags (DbError, db:reset)', async () => {
			await import('../../src/lib/server/db/index.ts');
			await import('../../tools/db/reset.ts');
			for (const tag of [
				'MIGRATION_HISTORY_MISMATCH',
				'MIGRATION_MANIFEST_MISMATCH',
				'MIGRATION_FAILED',
				'MIGRATION_LOCK_TIMEOUT',
				'ROLE_BOOTSTRAP_FAILED',
				'ROLE_LOCK_TIMEOUT',
				'DB_RESET_REFUSED',
				'DB_RESET_FAILED'
			]) {
				expect(tagOf({ tag }).line.err_tag).toBe(tag);
			}
		});

		it('a SQLSTATE, an ERR_ code and a listed errno name in .code are written', () => {
			for (const code of ['23505', '42P01', '57P01', 'ERR_INVALID_ARG_TYPE', 'ERR_SOCKET_CLOSED']) {
				expect(tagOf({ code }).line.err_tag).toBe(code);
			}
			for (const code of NODE_ERRNO_NAMES) expect(tagOf({ code }).line.err_tag).toBe(code);
			expect(NODE_ERRNO_NAMES).toContain('EADDRINUSE');
		});

		it('no listed errno name could be a join code: none is six Crockford characters (A4)', () => {
			const joinCodeShaped = /^[0-9A-HJKMNP-TV-Z]{6}$/;
			expect(NODE_ERRNO_NAMES.filter((name) => joinCodeShaped.test(name))).toEqual([]);
			expect(joinCodeShaped.test('EACCES')).toBe(true);
			expect(tagOf({ code: 'EACCES' }).line.err_tag).toBe(INVALID);
		});

		it('a code that is none of those is [invalid]: not ERR_-prefixed, not listed, too long', () => {
			for (const code of ['EFOOBAR', 'ERR_', 'ERR_lower', 'SQLSTATE', 'A'.repeat(64), '2350']) {
				expect(tagOf({ code }).line.err_tag).toBe(INVALID);
			}
		});

		it('an ERR_ code or errno name in .tag is [invalid] unless registered', () => {
			expect(tagOf({ tag: 'ERR_INVALID_ARG_TYPE' }).line.err_tag).toBe(INVALID);
			expect(tagOf({ tag: 'ECONNRESET' }).line.err_tag).toBe(INVALID);
			expect(tagOf({ tag: '23505' }).line.err_tag).toBe(INVALID);
		});
	});

	it('a tag that fails its validator is [invalid] even when the code is valid (no fallback)', () => {
		const err = Object.assign(new Error('x'), { tag: 'canary tag', code: '23505' });
		const { text, line } = errorLine(err);
		expect(line.err_tag).toBe(INVALID);
		expect(text).not.toContain('23505');
		expect(text.toLowerCase()).not.toContain('canary');
	});

	it('a constructor name that is not an identifier gives err_type [invalid]', () => {
		class Spaced extends Error {}
		Object.defineProperty(Spaced, 'name', { value: 'canary type' });
		class Long extends Error {}
		Object.defineProperty(Long, 'name', { value: `Canary${'x'.repeat(64)}` });
		for (const err of [new Spaced('x'), new Long('x')]) {
			const { text, line } = errorLine(err);
			expect(line.err_type).toBe(INVALID);
			expect(text.toLowerCase()).not.toContain('canary');
		}
	});

	it('a kind off the list is [invalid]', () => {
		const { lines, logger } = capture();
		logger.error({
			requestId: REQUEST_ID,
			route: null,
			kind: 'canary' as 'unknown',
			error: new Error('x')
		});
		const line = JSON.parse(lines[0]!) as Record<string, unknown>;
		expect(line.kind).toBe(INVALID);
		expect(lines[0]!.toLowerCase()).not.toContain('canary');
	});

	it('a Proxy whose getPrototypeOf trap throws: one line, stack_frames [invalid], no throw', () => {
		const hostile = new Proxy(new Error('canary'), {
			getPrototypeOf() {
				throw new Error('canary-trap');
			}
		});
		const { lines, logger } = capture();
		expect(() =>
			logger.error({ requestId: REQUEST_ID, route: null, kind: 'unknown', error: hostile })
		).not.toThrow();
		expect(lines).toHaveLength(1);
		const line = JSON.parse(lines[0]!) as Record<string, unknown>;
		expect(Object.keys(line)).toEqual(LINE_KEYS.error);
		expect(line.stack_frames).toBe(INVALID);
		expect(line.err_type).toBeNull();
		expect(lines[0]!.toLowerCase()).not.toContain('canary');
		expect(stackFramesOf(hostile)).toBe(INVALID);
	});

	it('a Proxy whose property traps throw: one line, no throw', () => {
		const hostile = new Proxy(new Error('canary'), {
			get() {
				throw new Error('canary-get');
			},
			has() {
				throw new Error('canary-has');
			}
		});
		const { lines, logger } = capture();
		expect(() =>
			logger.error({ requestId: REQUEST_ID, route: null, kind: 'unknown', error: hostile })
		).not.toThrow();
		expect(lines).toHaveLength(1);
		const line = JSON.parse(lines[0]!) as Record<string, unknown>;
		expect(line.err_tag).toBeNull();
		expect(line.stack_frames).toBe(INVALID);
		expect(lines[0]!.toLowerCase()).not.toContain('canary');
	});

	it('a multi-line message with a frame-shaped line: no line of the message reaches the frames', () => {
		const err = new Error(
			'canary-one ?code=ARM-7KQ4-XM2H-9\n    at canary (canary:1:1)\ncanary-three@example.org'
		);
		const { text, line } = errorLine(err);
		expect(text.toLowerCase()).not.toContain('canary');
		expect(text).not.toContain('ARM-7KQ4');
		expect(Array.isArray(line.stack_frames)).toBe(true);
		expectFramesOrInvalid(line.stack_frames);
		expect((line.stack_frames as string[])[0]).toContain('log-schema.test.ts');
	});

	it('a message changed after `stack` was first read, to new text', () => {
		const err = new Error('canary-old-1\ncanary-old-2\n    at canary (canary:1:1)');
		void err.stack;
		err.message = 'canary-new';
		const { text, line } = errorLine(err);
		expect(text.toLowerCase()).not.toContain('canary');
		expectFramesOrInvalid(line.stack_frames);
	});

	it('a message changed after `stack` was first read, to the first line of the old message', () => {
		const err = new Error('canary-first\n    at canary (canary:1:1)\ncanary-last');
		void err.stack;
		err.message = 'canary-first';
		const { text, line } = errorLine(err);
		expect(text.toLowerCase()).not.toContain('canary');
		expectFramesOrInvalid(line.stack_frames);
	});

	it('a stack set by hand gives [invalid]', () => {
		const err = new Error('x');
		err.stack = 'Error: canary\n    at canary (canary:1:1)\n    at f (/srv/canary.js:2:3)';
		const { text, line } = errorLine(err);
		expect(line.stack_frames).toBe(INVALID);
		expect(text.toLowerCase()).not.toContain('canary');
	});

	it('a thrown value that is not an Error gives [invalid] frames', () => {
		for (const value of ['canary-string', { message: 'canary', stack: 'canary' }, 42, null]) {
			const { text, line } = errorLine(value);
			expect(line.stack_frames).toBe(INVALID);
			expect(text.toLowerCase()).not.toContain('canary');
		}
		expect(errorLine('canary').line.err_type).toBe('string');
	});

	it('an error whose name is set in its constructor gets real frames', () => {
		class NamedFailure extends Error {
			constructor() {
				super('canary-message');
				this.name = 'Canary\n    at canary (canary:1:1)';
			}
		}
		const { text, line } = errorLine(new NamedFailure());
		expect(line.err_type).toBe('NamedFailure');
		expect(Array.isArray(line.stack_frames)).toBe(true);
		expect((line.stack_frames as string[]).length).toBeGreaterThan(0);
		expect((line.stack_frames as string[])[0]).toContain('log-schema.test.ts');
		expect(text.toLowerCase()).not.toContain('canary');
	});

	it('a frame that is not printable ASCII makes the whole value [invalid]', () => {
		const make = { ['fünf']: () => new Error('x') };
		expect(stackFramesOf(make['fünf']())).toBe(INVALID);
	});

	it('keeps at most 20 frames', () => {
		const limit = Error.stackTraceLimit;
		Error.stackTraceLimit = 50;
		try {
			const deep = (n: number): Error => (n === 0 ? new Error('x') : deep(n - 1));
			const frames = stackFramesOf(deep(30));
			expect(Array.isArray(frames)).toBe(true);
			expect((frames as string[]).length).toBe(20);
		} finally {
			Error.stackTraceLimit = limit;
		}
	});
});

describe('the prepareStackTrace hook', () => {
	const original = Error.prepareStackTrace;
	afterEach(() => {
		Error.prepareStackTrace = original;
	});

	it('err.stack reads the same with the hook as without it', () => {
		const ours = Error.prepareStackTrace as unknown as Record<symbol, unknown>;
		expect(PREVIOUS_HOOK in ours).toBe(true);
		const previous = ours[PREVIOUS_HOOK] as typeof Error.prepareStackTrace;
		const stacks: string[] = [];
		for (const hook of [previous, original]) {
			Error.prepareStackTrace = hook;
			stacks.push(new Error('same\nmessage').stack!);
		}
		expect(stacks[1]).toBe(stacks[0]);
		expect(stacks[0]!.startsWith('Error: same\nmessage\n    at ')).toBe(true);
	});

	it('a hook installed before the log module is still called', async () => {
		const calls: unknown[] = [];
		const before = Error.prepareStackTrace;
		Error.prepareStackTrace = (err, sites) => {
			calls.push(err);
			return before ? before(err, sites) : String(err);
		};
		vi.resetModules();
		const fresh = await import('../../src/lib/server/log/index.ts');
		const err = new Error('x');
		const frames = fresh.stackFramesOf(err);
		expect(calls).toContain(err);
		expect(Array.isArray(frames)).toBe(true);
	});

	it('a hook installed after the log module replaces it: frames are [invalid]', () => {
		Error.prepareStackTrace = (err) => String(err);
		expect(stackFramesOf(new Error('x'))).toBe(INVALID);
	});
});

describe('lifecycle lines', () => {
	it('config_error writes config key names and [invalid] for anything else', () => {
		registerConfigKeyNames(CONFIG_KEYS);
		const { logger, parsed } = capture();
		logger.lifecycle(
			'config_error',
			{
				missing: ['CODE_PEPPER', 'canary-postgres://jade_app:pw@host/db'],
				invalid: ['DATABASE_URL', 42]
			},
			'error'
		);
		expect(parsed()).toEqual([
			{
				ts: FIXED.toISOString(),
				level: 'error',
				msg: 'config_error',
				missing: ['CODE_PEPPER', INVALID],
				invalid: ['DATABASE_URL', INVALID]
			}
		]);
	});

	it('a message off the fixed list and a key off the allowlist are not written', () => {
		const { logger, parsed } = capture();
		logger.lifecycle('canary' as 'boot', { count: 3, ip: '203.0.113.9' } as never);
		expect(parsed()).toEqual([{ ts: FIXED.toISOString(), level: 'info', msg: INVALID, count: 3 }]);
	});

	it('migration and count are validated', () => {
		const { logger, parsed } = capture();
		logger.lifecycle('migrate', { migration: '0000_baseline', count: 1 });
		logger.lifecycle('migrate', { migration: '../canary', count: -1 });
		expect(parsed().map((l) => [l.migration, l.count])).toEqual([
			['0000_baseline', 1],
			[INVALID, INVALID]
		]);
	});
});

describe('levels and environments', () => {
	it('the level only filters lines', () => {
		const all = capture({ level: 'debug' });
		const errorsOnly = capture({ level: 'error' });
		for (const { logger } of [all, errorsOnly]) {
			logger.request(
				{ requestId: REQUEST_ID, method: 'GET', route: '/healthz', status: 200, durationMs: 1 },
				'debug'
			);
			logger.lifecycle('boot');
			logger.request(
				{ requestId: REQUEST_ID, method: 'GET', route: '/healthz', status: 503, durationMs: 1 },
				'error'
			);
		}
		expect(all.lines).toHaveLength(3);
		expect(errorsOnly.lines).toEqual([all.lines[2]]);
	});

	it('a level off the list writes the line at error, never at the bogus level', () => {
		const { lines, logger, parsed } = capture({ level: 'debug' });
		logger.request(
			{ requestId: REQUEST_ID, method: 'GET', route: '/healthz', status: 200, durationMs: 1 },
			'canary' as LogLevel
		);
		logger.lifecycle('boot', {}, 'canary' as LogLevel);
		expect(parsed().map((l) => l.level)).toEqual(['error', 'error']);
		expect(lines.join('').toLowerCase()).not.toContain('canary');
	});

	it('setLevel ignores a level off the list', () => {
		const { lines, logger } = capture({ level: 'error' });
		logger.setLevel('canary' as LogLevel);
		logger.lifecycle('boot');
		expect(lines).toHaveLength(0);
		logger.lifecycle('boot', {}, 'error');
		expect(lines).toHaveLength(1);
	});

	it('the same input gives the same output under every APP_ENV', () => {
		const outputs = new Set<string>();
		for (const appEnv of ['development', 'test', 'staging', 'production']) {
			vi.stubEnv('APP_ENV', appEnv);
			vi.stubEnv('LOG_LEVEL', 'debug');
			const { lines, logger } = capture();
			logger.request(
				{ requestId: REQUEST_ID, method: 'GET', route: '/healthz', status: 200, durationMs: 1 },
				'info'
			);
			logger.error({
				requestId: REQUEST_ID,
				route: null,
				kind: 'unknown',
				error: Object.assign(new Error('canary'), { code: 'XX000' })
			});
			outputs.add(lines.join(''));
			vi.unstubAllEnvs();
		}
		expect(outputs.size).toBe(1);
	});

	it('the log module reads no environment variable', () => {
		const source = readFileSync(
			new URL('../../src/lib/server/log/index.ts', import.meta.url),
			'utf8'
		);
		expect(source).not.toMatch(/process\.env|getConfig|console\./);
	});
});
