// The closed logger (plan PD6, A1, A1a, INV1). One JSON object per line on stdout, in three line
// kinds, each with a closed key set:
//   - request:   ts, level, msg (`request`), request_id, method, route, status, duration_ms
//   - error:     ts, level, msg (`error`), request_id, route, kind, err_type, err_tag, stack_frames
//   - lifecycle: ts, level, msg (a fixed list) and keys from the lifecycle allowlist
// Every key has a value validator; a value that fails is written as `[invalid]`. There is no call
// that logs an arbitrary object, an error's message or its other properties. The same input gives
// the same output in every APP_ENV; the level only filters lines. A change to the forbidden-key
// list or the line schema touches CLAUDE.md rule 4 and goes to Mike.
//
// This module imports nothing from SvelteKit and nothing from the config module (which imports
// it), so the tools can use it outside the app (PD10).

export const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;
export type LogLevel = (typeof LOG_LEVELS)[number];

export const INVALID = '[invalid]';

/**
 * Key names that could carry forbidden data. None of them, and no key that has one of them as an
 * underscore-separated part (`client_ip`, `kit_id`, `x_user_agent`), can be put on an allowlist.
 */
export const FORBIDDEN_KEY_PARTS = [
	'ip',
	'addr',
	'cookie',
	'code',
	'token',
	'email',
	'body',
	'authorization',
	'password',
	'secret',
	'pepper',
	'url',
	'path',
	'query',
	'headers',
	'user_agent',
	'referer',
	'kit',
	'class',
	'session',
	'step'
] as const;

/** Whether `name` is, or has as an underscore-separated part, a forbidden key name. */
export function isForbiddenKeyName(name: string): boolean {
	const parts = name.toLowerCase().split('_');
	return FORBIDDEN_KEY_PARTS.some((forbidden) => {
		const f = forbidden.split('_');
		for (let i = 0; i + f.length <= parts.length; i++) {
			if (f.every((p, j) => parts[i + j] === p)) return true;
		}
		return false;
	});
}

/** A value validator: returns the value to write, or INVALID. */
export type Validator = (value: unknown) => unknown;

/** Build an allowlist, refusing any forbidden key name. Used for every allowlist below. */
export function buildAllowlist(
	spec: Readonly<Record<string, Validator>>
): Readonly<Record<string, Validator>> {
	for (const name of Object.keys(spec)) {
		if (isForbiddenKeyName(name)) throw new Error(`log key refused: ${name}`);
		if (!/^[a-z][a-z0-9_]*$/.test(name)) throw new Error('log key refused: not snake_case');
	}
	return Object.freeze({ ...spec });
}

// ---------------------------------------------------------------------------------------------
// Validators

const ok =
	(test: (value: unknown) => boolean): Validator =>
	(value) =>
		test(value) ? value : INVALID;
const nullable =
	(validator: Validator): Validator =>
	(value) =>
		value === null ? null : validator(value);
const oneOf = (values: readonly string[]): Validator =>
	ok((v) => typeof v === 'string' && values.includes(v));

export const HTTP_METHODS = [
	'GET',
	'HEAD',
	'POST',
	'PUT',
	'PATCH',
	'DELETE',
	'OPTIONS',
	'CONNECT',
	'TRACE'
] as const;

/** `unknown`: an unexpected error while answering a request (SvelteKit's kind); the others: the
 * process handlers (A4). SvelteKit's `app`, `framework` and `validation` errors are not logged. */
export const ERROR_KINDS = ['unknown', 'uncaught_exception', 'unhandled_rejection'] as const;
export type ErrorKind = (typeof ERROR_KINDS)[number];

export const LIFECYCLE_MESSAGES = ['boot', 'shutdown', 'migrate', 'config_error'] as const;
export type LifecycleMessage = (typeof LIFECYCLE_MESSAGES)[number];

const MAX_FRAMES = 20;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]{0,63}$/;
const TAG = /^[A-Z0-9_]{1,64}$/;
const MIGRATION_NAME = /^[0-9]{4}_[a-z0-9_]{1,59}$/;

// The route ids SvelteKit can match, registered once by the app (src/lib/server/http). Until then
// every route but `null` is invalid.
let knownRoutes: ReadonlySet<string> = new Set();
let routesRegistered = false;

/** Register the app's route ids (once; later calls are ignored). */
export function registerRouteIds(ids: Iterable<string>): void {
	if (routesRegistered) return;
	routesRegistered = true;
	knownRoutes = new Set([...ids].filter((id) => typeof id === 'string' && id.startsWith('/')));
}

// The config schemas' key set, registered once by the config module (which imports this one).
let configKeys: ReadonlySet<string> = new Set();
let configKeysRegistered = false;

/** Register the config schemas' key names (once; later calls are ignored). */
export function registerConfigKeyNames(keys: Iterable<string>): void {
	if (configKeysRegistered) return;
	configKeysRegistered = true;
	configKeys = new Set(
		[...keys].filter((k) => typeof k === 'string' && /^[A-Z][A-Z0-9_]*$/.test(k))
	);
}

const configKeyList: Validator = (value) => {
	if (!Array.isArray(value) || value.length > 32) return INVALID;
	return value.map((name) => (typeof name === 'string' && configKeys.has(name) ? name : INVALID));
};

const V = {
	request_id: nullable(ok((v) => typeof v === 'string' && UUID.test(v))),
	method: oneOf(HTTP_METHODS),
	route: nullable(ok((v) => typeof v === 'string' && knownRoutes.has(v))),
	status: ok((v) => Number.isInteger(v) && (v as number) >= 100 && (v as number) <= 599),
	duration_ms: ok((v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v < 1e9),
	kind: oneOf(ERROR_KINDS),
	err_type: nullable(ok((v) => typeof v === 'string' && IDENTIFIER.test(v))),
	err_tag: nullable(ok((v) => typeof v === 'string' && TAG.test(v))),
	stack_frames: ok(
		(v) => Array.isArray(v) && v.length <= MAX_FRAMES && v.every((f) => typeof f === 'string')
	),
	migration: ok((v) => typeof v === 'string' && MIGRATION_NAME.test(v)),
	count: ok((v) => Number.isInteger(v) && (v as number) >= 0 && (v as number) < 1e9),
	missing: configKeyList,
	invalid: configKeyList
} satisfies Record<string, Validator>;

const REQUEST_KEYS = buildAllowlist({
	request_id: V.request_id,
	method: V.method,
	route: V.route,
	status: V.status,
	duration_ms: V.duration_ms
});

const ERROR_KEYS = buildAllowlist({
	request_id: V.request_id,
	route: V.route,
	kind: V.kind,
	err_type: V.err_type,
	err_tag: V.err_tag,
	stack_frames: V.stack_frames
});

const LIFECYCLE_KEYS = buildAllowlist({
	migration: V.migration,
	count: V.count,
	missing: V.missing,
	invalid: V.invalid
});

/** The closed key sets, for tests and the black-box schema check. */
export const LINE_KEYS = Object.freeze({
	request: Object.freeze(['ts', 'level', 'msg', ...Object.keys(REQUEST_KEYS)]),
	error: Object.freeze(['ts', 'level', 'msg', ...Object.keys(ERROR_KEYS)]),
	lifecycle: Object.freeze(['ts', 'level', 'msg', ...Object.keys(LIFECYCLE_KEYS)])
});

// ---------------------------------------------------------------------------------------------
// Stack frames (A1a). The text of `err.stack` is never parsed: an `Error.prepareStackTrace` hook,
// which V8 calls with the error and its structured call sites when `err.stack` is first read,
// records each site's function name, file name, line and column in a WeakMap keyed by the error,
// and returns the stack text unchanged (by calling the hook installed before it, or by building
// V8's default text).

interface RecordedSite {
	readonly fn: string | null;
	readonly file: string | null;
	readonly line: number | null;
	readonly column: number | null;
}

interface CallSiteLike {
	getFunctionName(): string | null;
	getFileName(): string | null | undefined;
	getLineNumber(): number | null;
	getColumnNumber(): number | null;
	toString(): string;
}

type PrepareStackTrace = (err: Error, sites: CallSiteLike[]) => unknown;

const MAX_FRAME_LENGTH = 300;
/** Where the hook keeps the hook it chains to (read by tests/unit/log-schema.test.ts). */
export const PREVIOUS_HOOK = Symbol.for('jade.log.previousStackHook');

type MarkedHook = PrepareStackTrace & { [PREVIOUS_HOOK]?: PrepareStackTrace | undefined };

function installStackHook(): WeakMap<object, readonly RecordedSite[]> {
	const sitesByError = new WeakMap<object, readonly RecordedSite[]>();
	const ErrorCtor = Error as unknown as { prepareStackTrace?: MarkedHook };
	const current = ErrorCtor.prepareStackTrace;
	// When this module is evaluated again (the dev server), chain to what the old hook chained to.
	const previous =
		current !== undefined && PREVIOUS_HOOK in current ? current[PREVIOUS_HOOK] : current;
	const jadeRecordCallSites: MarkedHook = (err, sites) => {
		try {
			sitesByError.set(
				err,
				sites.map((s) => ({
					fn: s.getFunctionName(),
					file: s.getFileName() ?? null,
					line: s.getLineNumber(),
					column: s.getColumnNumber()
				}))
			);
		} catch {
			// Not an object, or a site that cannot be read: nothing is recorded.
		}
		if (typeof previous === 'function') return previous(err, sites);
		let text = String(err);
		for (const site of sites) text += `\n    at ${String(site)}`;
		return text;
	};
	jadeRecordCallSites[PREVIOUS_HOOK] = previous;
	ErrorCtor.prepareStackTrace = jadeRecordCallSites;
	return sitesByError;
}

const recordedSites = installStackHook();

function formatSite(site: RecordedSite): string | null {
	const file = (site.file ?? '<anonymous>').replace(/\?.*$/s, '');
	const frame = `${site.fn ?? '<anonymous>'} (${file}:${site.line ?? 0}:${site.column ?? 0})`;
	return /^[\x20-\x7e]{1,300}$/.test(frame) && frame.length <= MAX_FRAME_LENGTH ? frame : null;
}

/**
 * The frames of `err` from its recorded call sites, or INVALID: when the value is not an Error,
 * when its `stack` was set by hand, when a later hook replaced this one, or when any frame is not
 * printable ASCII of at most 300 characters. The message is never read.
 */
export function stackFramesOf(err: unknown): readonly string[] | typeof INVALID {
	let sites: readonly RecordedSite[] | undefined;
	try {
		// `instanceof` runs a Proxy's getPrototypeOf trap, which can throw: inside the try.
		if (!(err instanceof Error)) return INVALID;
		// Reading `stack` runs the hook if V8 has not formatted it yet. Its text is not used.
		void err.stack;
		sites = recordedSites.get(err);
	} catch {
		return INVALID;
	}
	if (sites === undefined) return INVALID;
	const frames: string[] = [];
	for (const site of sites.slice(0, MAX_FRAMES)) {
		const frame = formatSite(site);
		if (frame === null) return INVALID;
		frames.push(frame);
	}
	return frames;
}

/** The error's type: its constructor's name for an object, `typeof` for anything else. */
function errorType(err: unknown): unknown {
	if (err === null) return 'null';
	if (typeof err !== 'object' && typeof err !== 'function') return typeof err;
	try {
		const ctor = (Object.getPrototypeOf(err) as { constructor?: { name?: unknown } } | null)
			?.constructor;
		// Read once: a getter could answer differently the second time.
		const name = ctor?.name;
		return typeof name === 'string' ? name : null;
	} catch {
		return null;
	}
}

/** The error's tag: the app's own `tag`, else a driver's `code` (a SQLSTATE), else null. */
function errorTag(err: unknown): unknown {
	if (err === null || (typeof err !== 'object' && typeof err !== 'function')) return null;
	try {
		const { tag, code } = err as { tag?: unknown; code?: unknown };
		if (typeof tag === 'string') return tag;
		if (typeof code === 'string') return code;
		return null;
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------------------------
// The logger

export interface RequestFields {
	readonly requestId: string;
	readonly method: string;
	readonly route: string | null;
	readonly status: number;
	readonly durationMs: number;
}

export interface ErrorFields {
	readonly requestId: string | null;
	readonly route: string | null;
	readonly kind: ErrorKind;
	/** The thrown value. Only its type, its tag and its recorded call sites are written. */
	readonly error: unknown;
}

export interface LifecycleFields {
	readonly migration?: string;
	readonly count?: number;
	readonly missing?: readonly unknown[];
	readonly invalid?: readonly unknown[];
}

export interface Logger {
	request(fields: RequestFields, level: LogLevel): void;
	error(fields: ErrorFields): void;
	lifecycle(msg: LifecycleMessage, fields?: LifecycleFields, level?: LogLevel): void;
	setLevel(level: LogLevel): void;
}

export interface LoggerOptions {
	/** Where each line goes, newline included. Defaults to stdout. */
	readonly write?: (line: string) => void;
	readonly level?: LogLevel;
	readonly now?: () => Date;
}

const stdout = (line: string) => {
	process.stdout.write(line);
};

function rank(level: LogLevel): number {
	return LOG_LEVELS.indexOf(level);
}

function validated(
	allowlist: Readonly<Record<string, Validator>>,
	values: Readonly<Record<string, unknown>>
): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const [key, validator] of Object.entries(allowlist)) {
		if (!(key in values)) continue;
		let value: unknown;
		try {
			value = validator(values[key]);
		} catch {
			value = INVALID;
		}
		out[key] = value;
	}
	return out;
}

/** A logger writing to `options.write`. The app uses the shared instance, `log`. */
export function createLogger(options: LoggerOptions = {}): Logger {
	const write = options.write ?? stdout;
	const now = options.now ?? (() => new Date());
	let threshold: LogLevel = options.level ?? 'info';

	const emit = (level: LogLevel, msg: string, fields: Record<string, unknown>) => {
		if (rank(level) < rank(threshold)) return;
		try {
			write(`${JSON.stringify({ ts: now().toISOString(), level, msg, ...fields })}\n`);
		} catch {
			// Logging never throws into the caller.
		}
	};

	return {
		request(fields, level) {
			emit(
				oneOf(LOG_LEVELS)(level) === INVALID ? 'error' : level,
				'request',
				validated(REQUEST_KEYS, {
					request_id: fields.requestId,
					method: fields.method,
					route: fields.route,
					status: fields.status,
					duration_ms: fields.durationMs
				})
			);
		},
		error(fields) {
			emit(
				'error',
				'error',
				validated(ERROR_KEYS, {
					request_id: fields.requestId,
					route: fields.route,
					kind: fields.kind,
					err_type: errorType(fields.error),
					err_tag: errorTag(fields.error),
					stack_frames: stackFramesOf(fields.error)
				})
			);
		},
		lifecycle(msg, fields = {}, level = 'info') {
			const values: Record<string, unknown> = {};
			for (const key of Object.keys(LIFECYCLE_KEYS)) {
				if (Object.hasOwn(fields, key)) values[key] = (fields as Record<string, unknown>)[key];
			}
			emit(
				oneOf(LOG_LEVELS)(level) === INVALID ? 'error' : level,
				oneOf(LIFECYCLE_MESSAGES)(msg) === INVALID ? INVALID : msg,
				validated(LIFECYCLE_KEYS, values)
			);
		},
		setLevel(level) {
			if (oneOf(LOG_LEVELS)(level) !== INVALID) threshold = level;
		}
	};
}

/** The app's logger: stdout, level `info` until the app sets LOG_LEVEL. */
export const log: Logger = createLogger();
