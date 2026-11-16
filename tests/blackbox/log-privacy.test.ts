// INV1, C3: the built server, run once each under APP_ENV development, test and production, is
// sent every registry route (each `[param]` replaced by a kit-code-shaped canary) plus
// `/redeem?code=<canary>`, with canaries in the path, query, cookie, Authorization,
// X-Forwarded-For, X-Request-Id, User-Agent, Referer and a POST body. Every output line is either
// on the adapter's start-up allowlist (RR7) or parses as JSON and matches the line schema; no
// canary appears anywhere, and no value but `ts` looks like an IP address.
import { randomBytes, randomUUID } from 'node:crypto';
import { request as httpRequest } from 'node:http';
import { describe, expect, it } from 'vitest';
import { routes } from '../authz/route-registry.ts';
import '../../src/lib/server/db/index.ts';
import { INVALID, isErrTag } from '../../src/lib/server/log/index.ts';
import { generatedEnv, testEnv, type ServerEnv } from '../support/env.ts';
import { startServer } from '../support/server.ts';

const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const crockford = (n: number) =>
	Array.from(randomBytes(n), (b) => CROCKFORD[b % CROCKFORD.length]).join('');

/** Fresh canaries for one run: values that must never reach the output. */
function canaries() {
	const kitCode = `ARM-${crockford(4)}-${crockford(4)}-${crockford(1)}`;
	return {
		kitCode,
		pathCode: `ARM-${crockford(4)}-${crockford(4)}-${crockford(1)}`,
		redeemCode: `ARM-${crockford(4)}-${crockford(4)}-${crockford(1)}`,
		joinCode: crockford(6),
		email: `canary.${crockford(8).toLowerCase()}@example.org`,
		token: `tok_${randomBytes(12).toString('hex')}`,
		cookie: `ck_${randomBytes(12).toString('hex')}`,
		bearer: `bearer_${randomBytes(12).toString('hex')}`,
		forwardedFor: `203.0.113.${1 + (randomBytes(1)[0]! % 250)}`,
		requestId: randomUUID(),
		userAgent: `ua_${randomBytes(8).toString('hex')}`,
		referer: `ref_${randomBytes(8).toString('hex')}`,
		bodyValue: `body_${randomBytes(12).toString('hex')}`
	};
}
type Canaries = ReturnType<typeof canaries>;

/** A concrete path for a route id: groups removed, every `[param]` replaced by the canary. */
function pathFor(id: string, code: string): string {
	return id.replace(/\/\([^)]+\)/g, '').replace(/\[[^\]]+\]/g, code) || '/';
}

function send(
	url: string,
	method: string,
	headers: Record<string, string>,
	body?: string
): Promise<number> {
	return new Promise((resolve, reject) => {
		const req = httpRequest(url, { method, headers }, (res) => {
			res.resume();
			res.on('end', () => resolve(res.statusCode ?? 0));
		});
		req.on('error', reject);
		if (body !== undefined) req.write(body);
		req.end();
	});
}

async function exercise(base: string, c: Canaries): Promise<number[]> {
	const query =
		`?code=${encodeURIComponent(c.kitCode)}&join=${c.joinCode}` +
		`&email=${encodeURIComponent(c.email)}&token=${c.token}`;
	const headers = {
		cookie: `jade_session=${c.cookie}; kit=${c.kitCode}`,
		authorization: `Bearer ${c.bearer}`,
		'x-forwarded-for': c.forwardedFor,
		'x-request-id': c.requestId,
		'user-agent': c.userAgent,
		referer: `http://127.0.0.1/${c.referer}`
	};
	const json = JSON.stringify({ code: c.kitCode, email: c.email, value: c.bodyValue });
	const paths = [
		...routes.map((r) => `${pathFor(r.id, c.pathCode)}${query}`),
		`/redeem?code=${encodeURIComponent(c.redeemCode)}`,
		`/${c.pathCode}${query}`
	];
	const statuses: number[] = [];
	for (const path of paths) {
		statuses.push(await send(`${base}${path}`, 'GET', headers));
		statuses.push(
			await send(
				`${base}${path}`,
				'POST',
				{ ...headers, 'content-type': 'application/json', accept: 'application/json' },
				json
			)
		);
		statuses.push(
			await send(
				`${base}${path}`,
				'POST',
				{ ...headers, 'content-type': 'text/plain' },
				`code=${c.kitCode}&value=${c.bodyValue}`
			)
		);
	}
	return statuses;
}

// The line schema of A1, written out here independently of the logger's own tables.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ROUTE_IDS = new Set(routes.map((r) => r.id));
const COMMON = ['ts', 'level', 'msg'];
const REQUEST = [...COMMON, 'request_id', 'method', 'route', 'status', 'duration_ms'];
const ERROR = [...COMMON, 'request_id', 'route', 'kind', 'err_type', 'err_tag', 'stack_frames'];
const LIFECYCLE_MSGS = ['boot', 'shutdown', 'migrate', 'config_error'];
const LIFECYCLE_KEYS = [...COMMON, 'migration', 'count', 'missing', 'invalid'];

const isRoute = (v: unknown) => v === null || (typeof v === 'string' && ROUTE_IDS.has(v));
const isId = (v: unknown) => v === null || (typeof v === 'string' && UUID.test(v));

function checkLine(line: Record<string, unknown>): void {
	expect(typeof line.ts === 'string' && !Number.isNaN(Date.parse(line.ts))).toBe(true);
	expect(['debug', 'info', 'warn', 'error']).toContain(line.level);
	if (line.msg === 'request') {
		expect(Object.keys(line)).toEqual(REQUEST);
		expect(isId(line.request_id)).toBe(true);
		expect(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']).toContain(line.method);
		expect(isRoute(line.route)).toBe(true);
		expect(Number.isInteger(line.status)).toBe(true);
		expect(typeof line.duration_ms).toBe('number');
	} else if (line.msg === 'error') {
		expect(Object.keys(line)).toEqual(ERROR);
		expect(isId(line.request_id)).toBe(true);
		expect(isRoute(line.route)).toBe(true);
		expect(['unknown', 'uncaught_exception', 'unhandled_rejection']).toContain(line.kind);
		expect(line.err_type === null || /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(String(line.err_type))).toBe(
			true
		);
		// The logger's own rule (A3): a registered tag, a SQLSTATE, an ERR_ code, a listed errno
		// name, `[invalid]` or null. Importing the db module registers the database tools' tags here,
		// as the server registers them.
		expect(line.err_tag === null || line.err_tag === INVALID || isErrTag(line.err_tag)).toBe(true);
		const frames = line.stack_frames;
		if (frames !== INVALID) {
			expect(Array.isArray(frames)).toBe(true);
			for (const frame of frames as unknown[]) expect(frame).toMatch(/^[\x20-\x7e]+:\d+:\d+\)$/);
		}
	} else {
		expect(LIFECYCLE_MSGS).toContain(line.msg);
		const keys = Object.keys(line);
		expect(keys.slice(0, 3)).toEqual(COMMON);
		for (const key of keys) expect(LIFECYCLE_KEYS).toContain(key);
	}
}

// IPv4, IPv6 (three or more groups, or a `::` form) and IPv4-mapped addresses.
const IP_PATTERNS = [
	/\b(?:\d{1,3}\.){3}\d{1,3}\b/,
	/\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b/i,
	/::(?:[0-9a-f]{1,4}|ffff)/i,
	/\blocalhost\b/i
];

/** Every string or number value in `value`, recursively. */
function leaves(value: unknown): string[] {
	if (value === null || value === undefined) return [];
	if (Array.isArray(value)) return value.flatMap(leaves);
	if (typeof value === 'object') return Object.values(value).flatMap(leaves);
	return [String(value)];
}

const ADAPTER_START = /^Listening on http:\/\/127\.0\.0\.1:\d+$/;

const runs: [string, () => Promise<ServerEnv>][] = [
	['development', async () => ({ ...(await generatedEnv('development')), LOG_LEVEL: 'debug' })],
	['test', async () => ({ ...(await testEnv()), LOG_LEVEL: 'debug' })],
	[
		'production',
		async () => ({
			...(await generatedEnv('production')),
			NODE_ENV: 'production',
			LOG_LEVEL: 'debug'
		})
	]
];

describe.each(runs)('APP_ENV=%s', (appEnv, makeEnv) => {
	it('every line is the adapter start-up line or a schema line, and no canary appears', async () => {
		const c = canaries();
		const server = await startServer(await makeEnv());
		let statuses: number[];
		try {
			statuses = await exercise(server.url, c);
		} finally {
			await server.stop();
		}
		const output = `${server.stdout()}\n${server.stderr()}`;

		for (const value of Object.values(c)) expect(output).not.toContain(value);
		for (const value of Object.values(c)) {
			expect(output).not.toContain(encodeURIComponent(value));
		}

		const lines = output.split('\n').filter((l) => l !== '');
		const parsed: Record<string, unknown>[] = [];
		for (const text of lines) {
			if (ADAPTER_START.test(text)) continue;
			let line: Record<string, unknown>;
			try {
				line = JSON.parse(text) as Record<string, unknown>;
			} catch {
				throw new Error(
					`a line is neither JSON nor on the start-up allowlist (${text.length} chars)`
				);
			}
			checkLine(line);
			const rest = Object.entries(line).filter(([key]) => key !== 'ts');
			for (const value of leaves(rest.map(([, v]) => v))) {
				for (const pattern of IP_PATTERNS) expect(value).not.toMatch(pattern);
			}
			parsed.push(line);
		}

		// The requests were all logged, and the error path was exercised where /dev/ is open.
		const requestLines = parsed.filter((l) => l.msg === 'request');
		expect(requestLines.length).toBeGreaterThan(0);
		const errorLines = parsed.filter((l) => l.msg === 'error');
		const boom = routes.find((r) => r.id === '/dev/boom')!;
		if (appEnv === 'production') {
			expect(errorLines).toEqual([]);
			expect(statuses).not.toContain(500);
			expect(requestLines.some((l) => l.route === boom.id && l.status === 404)).toBe(true);
		} else {
			expect(errorLines.length).toBeGreaterThan(0);
			for (const line of errorLines) expect(Array.isArray(line.stack_frames)).toBe(true);
		}
	});
});

describe('the line check itself (A3)', () => {
	const errorLine = (err_tag: unknown) => ({
		ts: new Date().toISOString(),
		level: 'error',
		msg: 'error',
		request_id: null,
		route: null,
		kind: 'unknown',
		err_type: 'Error',
		err_tag,
		stack_frames: []
	});

	it('accepts the err_tag values the logger writes', () => {
		for (const tag of [
			null,
			INVALID,
			'23505',
			'ERR_SOCKET_CLOSED',
			'EADDRINUSE',
			'MIGRATION_FAILED'
		]) {
			checkLine(errorLine(tag));
		}
	});

	it('refuses an err_tag the logger would never write, a join-code-shaped one included', () => {
		for (const tag of [crockford(6), 'EACCES', 'NOT_REGISTERED_TAG', 'EFOOBAR']) {
			expect(() => checkLine(errorLine(tag))).toThrow();
		}
	});
});
