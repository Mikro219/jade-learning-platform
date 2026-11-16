// Dev-only routes (plan PD8, A5): every route under /dev/ calls assertDevRoute(), which answers
// 404 unless APP_ENV is development or test. On staging and production the only page is `/`.
import { error, type RequestEvent } from '@sveltejs/kit';
import { getConfig } from '../config/index.ts';
import { requestIdOf } from './request-context.ts';

export function isDevEnvironment(): boolean {
	const { appEnv } = getConfig();
	return appEnv === 'development' || appEnv === 'test';
}

/** Throws a 404 unless APP_ENV is development or test. */
export function assertDevRoute(event: Pick<RequestEvent, 'locals'>): void {
	if (!isDevEnvironment()) error(404, { message: 'Not Found', requestId: requestIdOf(event) });
}
