// INV8 (first half): every route under src/routes is in tests/authz/route-registry.ts, and every
// registry entry is a route. The route groups of ARCHITECTURE.md section 4 exist.
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readdirSync,
	rmSync,
	statSync,
	writeFileSync
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { routes } from '../authz/route-registry.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const routesDir = join(root, 'src/routes');
// `+page@<layout>.svelte` resets to the named layout, whose name may hold dots, as in
// `+page@[...rest].svelte` (A7).
const ROUTE_FILE = /^\+page(@[^/]*)?\.svelte$|^\+server\.(ts|js)$/;

/** The SvelteKit route id of a route file, given its path relative to src/routes. */
export function routeId(relPath: string): string {
	const dir = relPath.split('/').slice(0, -1);
	return '/' + dir.join('/');
}

/** The route files under `dir`, as paths relative to `base` (default: `dir`). */
function routeFiles(dir: string, base: string = dir): string[] {
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		if (statSync(path).isDirectory()) return routeFiles(path, base);
		return ROUTE_FILE.test(name) ? [relative(base, path).split(sep).join('/')] : [];
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

describe('route files', () => {
	it('include page files that reset their layout (+page@.svelte, +page@group.svelte) and +server.js (A6)', () => {
		const dir = mkdtempSync(join(tmpdir(), 'jade-routes-'));
		try {
			const files = [
				'+page.svelte',
				'a/+page@.svelte',
				'(student)/b/+page@(student).svelte',
				'c/+page@c.svelte',
				'r/[...rest]/x/+page@[...rest].svelte',
				'd/+server.ts',
				'e/+server.js',
				// Not route files:
				'+layout.svelte',
				'a/+page.ts',
				'a/+page.server.ts',
				'f/+layout@.svelte',
				'g/+error.svelte',
				'h/page.svelte',
				'i/+page.svelte.orig',
				'j/+page@.svelte.bak',
				'k/+page@x.ts',
				'l/+pages.svelte'
			];
			for (const file of files) {
				mkdirSync(dirname(join(dir, file)), { recursive: true });
				writeFileSync(join(dir, file), '');
			}
			expect(routeFiles(dir).sort()).toEqual(
				[
					'+page.svelte',
					'a/+page@.svelte',
					'(student)/b/+page@(student).svelte',
					'c/+page@c.svelte',
					'r/[...rest]/x/+page@[...rest].svelte',
					'd/+server.ts',
					'e/+server.js'
				].sort()
			);
			expect(routeId('a/+page@.svelte')).toBe('/a');
		} finally {
			rmSync(dir, { recursive: true, force: true });
		}
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
