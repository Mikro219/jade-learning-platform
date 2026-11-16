// Request ids and request logging (plan A2, A4). `handleRequest` gives every request a fresh id
// from crypto.randomUUID(), writes one request line and sets `X-Request-Id` on the response. An
// incoming `X-Request-Id` is ignored: honouring it would let a client write into the logs. The
// route is `event.route.id`, the route pattern, never the path (C2). `handleServerError` returns
// the id in `App.Error` for every kind, writes an error line for kind `unknown` only, and never
// throws.
import { randomUUID } from 'node:crypto';
import type { RequestEvent } from '@sveltejs/kit';
import type { Handle, HandleServerError } from '@sveltejs/kit/hooks';
import { routes } from '$app/manifest';
import { ConfigError, reportConfigError } from '../config/index.ts';
import { log, registerRouteIds, type LogLevel } from '../log/index.ts';

// The logger accepts only route ids SvelteKit can match.
registerRouteIds(routes.map((r) => r.id));

const HEALTH_ROUTES = new Set(['/healthz', '/readyz']);

/** The level of a request line: health probes' 2xx at debug, 5xx at error, the rest at info. */
export function requestLevel(route: string | null, status: number): LogLevel {
	if (status >= 500) return 'error';
	if (status >= 200 && status < 300 && route !== null && HEALTH_ROUTES.has(route)) return 'debug';
	return 'info';
}

function withRequestId(response: Response, requestId: string): Response {
	try {
		response.headers.set('x-request-id', requestId);
		return response;
	} catch {
		// Immutable headers (a Response from fetch or Response.redirect): copy it.
		const copy = new Response(response.body, response);
		copy.headers.set('x-request-id', requestId);
		return copy;
	}
}

export const handleRequest: Handle = async ({ event, resolve }) => {
	const requestId = randomUUID();
	event.locals.requestId = requestId;
	const started = performance.now();
	const route = event.route.id;
	let status = 500;
	try {
		const response = withRequestId(await resolve(event), requestId);
		status = response.status;
		return response;
	} finally {
		log.request(
			{
				requestId,
				method: event.request.method,
				route,
				status,
				durationMs: Math.round((performance.now() - started) * 1000) / 1000
			},
			requestLevel(route, status)
		);
	}
};

/** Fixed phrases for SvelteKit's own errors, by status: nothing from the request. */
function frameworkMessage(status: number): string {
	if (status === 404) return 'Not Found';
	if (status === 405) return 'Method Not Allowed';
	if (status >= 500) return 'Internal Error';
	return 'Bad Request';
}

/** The request id of `event`, set by handleRequest. */
export function requestIdOf(event: Pick<RequestEvent, 'locals'>): string {
	return event.locals.requestId ?? randomUUID();
}

/**
 * SvelteKit 3 calls this for every error kind: `app` (thrown with `error()`), `framework` (its own,
 * such as a 404), `validation` and `unknown`. Every kind gets the request id; only `unknown` is
 * logged, and its message is replaced by a fixed phrase.
 */
export const handleServerError: HandleServerError = (input) => {
	let requestId: string;
	try {
		requestId = requestIdOf(input.event);
	} catch {
		requestId = randomUUID();
	}
	try {
		switch (input.kind) {
			case 'unknown':
				log.error({
					requestId,
					route: input.event.route?.id ?? null,
					kind: 'unknown',
					error: input.error
				});
				return { status: 500, message: 'Internal Error', requestId };
			case 'app':
				return { requestId };
			default:
				return { message: frameworkMessage(input.error.status), requestId };
		}
	} catch {
		return { message: 'Internal Error', requestId };
	}
};

let processHandlersInstalled = false;

/**
 * Handlers for `uncaughtException` and `unhandledRejection` (A4): a closed error line, then exit
 * 1. A ConfigError goes to reportConfigError instead (V3a), as a second line of defence behind
 * the init hook.
 */
export function installProcessHandlers(): void {
	if (processHandlersInstalled) return;
	processHandlersInstalled = true;
	const fatal = (kind: 'uncaught_exception' | 'unhandled_rejection') => (error: unknown) => {
		try {
			if (error instanceof ConfigError) reportConfigError(error);
			else log.error({ requestId: null, route: null, kind, error });
		} finally {
			process.exit(1);
		}
	};
	process.on('uncaughtException', fatal('uncaught_exception'));
	process.on('unhandledRejection', fatal('unhandled_rejection'));
}
