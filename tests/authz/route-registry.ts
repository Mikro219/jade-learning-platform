// Every route of the app, with its access class and a sample URL (plan PD7).
// tests/unit/route-registry.test.ts fails when a route under src/routes is missing here or an
// entry here has no route. jade-aq5 widens each entry to its five actors.

/** `public`: anyone may request it. `dev-only`: 404 unless APP_ENV is development or test. */
export type AccessClass = 'public' | 'dev-only';

export interface RouteEntry {
	/** The SvelteKit route id, for example `/(student)` or `/api/healthz`. */
	readonly id: string;
	/** `page` for a `+page.svelte`, `endpoint` for a `+server.ts`. */
	readonly kind: 'page' | 'endpoint';
	readonly access: AccessClass;
	/** A concrete URL path that reaches the route. */
	readonly sample: string;
}

export const routes: readonly RouteEntry[] = [
	{ id: '/(student)', kind: 'page', access: 'public', sample: '/' }
];
