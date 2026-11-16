// Dev-only (plan PD8, A5): throws an error whose message spans two lines, the request's query
// string and then a line shaped like a stack frame, so the error path can be tested on the built
// server. The logger never reads the message (A1a); the response shows only a fixed phrase.
import { assertDevRoute } from '#lib/server/http/index.ts';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = (event) => {
	assertDevRoute(event);
	const query = event.url.search;
	throw new Error(`${query}\n    at ${query} (x:1:1)`);
};
