// INV8 (first half): every route under src/routes is in tests/authz/route-registry.ts, and every
// registry entry is a route. The route groups of ARCHITECTURE.md section 4 exist.
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { routes } from '../authz/route-registry.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const routesDir = join(root, 'src/routes');
const ROUTE_FILE = /^\+(page\.svelte|server\.(ts|js))$/;

/** The SvelteKit route id of a route file, given its path relative to src/routes. */
export function routeId(relPath: string): string {
	const dir = relPath.split('/').slice(0, -1);
	return '/' + dir.join('/');
}

function routeFiles(dir: string): string[] {
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		if (statSync(path).isDirectory()) return routeFiles(path);
		return ROUTE_FILE.test(name) ? [relative(routesDir, path).split(sep).join('/')] : [];
	});
}

describe('route layout', () => {
	it.each(['(student)', '(adult)', '(staff)', 'api'])('src/routes/%s exists', (dir) => {
		expect(existsSync(join(routesDir, dir))).toBe(true);
	});

	it('derives route ids the way SvelteKit names them', () => {
		expect(routeId('+page.svelte')).toBe('/');
		expect(routeId('(student)/+page.svelte')).toBe('/(student)');
		expect(routeId('(student)/s/[step_id]/+page.svelte')).toBe('/(student)/s/[step_id]');
		expect(routeId('api/healthz/+server.ts')).toBe('/api/healthz');
	});
});

describe('route registry', () => {
	const found = routeFiles(routesDir).map((file) => ({
		id: routeId(file),
		kind: file.endsWith('.svelte') ? 'page' : 'endpoint'
	}));

	it('lists exactly the routes under src/routes', () => {
		const key = (r: { id: string; kind: string }) => `${r.kind} ${r.id}`;
		expect(new Set(routes.map(key))).toEqual(new Set(found.map(key)));
	});

	it('has one entry per route and a path-only sample URL for each', () => {
		const keys = routes.map((r) => `${r.kind} ${r.id}`);
		expect(new Set(keys).size).toBe(keys.length);
		for (const r of routes) expect(r.sample).toMatch(/^\/(?!\/)/);
	});
});
