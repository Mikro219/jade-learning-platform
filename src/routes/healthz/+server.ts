// Liveness (plan A3): the process is up. Touches nothing else; returns no data about anyone.
import { json } from '@sveltejs/kit';
import { version } from '$app/env';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = () =>
	json({ status: 'ok', version }, { headers: { 'cache-control': 'no-store' } });
