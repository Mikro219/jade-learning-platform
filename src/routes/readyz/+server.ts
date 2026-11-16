// Readiness (plan A3): the database answers within 2 seconds and every shipped migration is
// applied with the same hash. Returns no data about anyone, no host name and no error text.
import { json } from '@sveltejs/kit';
import { checkReadiness, requestIdOf } from '#lib/server/http/index.ts';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	const checks = await checkReadiness();
	const headers = { 'cache-control': 'no-store' };
	if (checks.db === 'ok' && checks.migrations === 'ok') {
		return json({ status: 'ready' }, { headers });
	}
	return json(
		{ status: 'not_ready', checks, requestId: requestIdOf(event) },
		{ status: 503, headers }
	);
};
