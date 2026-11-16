// Dev-only (plan PD8, L3): the student shell with neutral sample elements. 404 unless APP_ENV is
// development or test.
import { assertDevRoute } from '#lib/server/http/index.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = (event) => {
	assertDevRoute(event);
};
