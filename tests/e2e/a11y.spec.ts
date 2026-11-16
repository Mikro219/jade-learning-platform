// Plan section 13 (L4, AC10): axe finds no violation on any page of the route registry (the
// student shell pages `/` and `/dev/shell/student`, and the adult and staff shells alike) nor on
// the error page (the fixed missing path that no-offorigin.spec.ts uses), at 360x640 and at
// 1366x768. Colour contrast is axe's `color-contrast` rule, which must also leave nothing
// `incomplete` (undecided). axe-core is injected from the local package by @axe-core/playwright
// (page.evaluate of its bundled source); each run records requests and asserts none leaves the
// origin (CLAUDE.md rule 5).
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { routes } from '../authz/route-registry.ts';

const pages = routes.filter((r) => r.kind === 'page');
const MISSING = '/no-such-page-jade-e2e';
const checked = [
	...pages.map((r) => ({ path: r.sample, status: 200 })),
	{ path: MISSING, status: 404 }
];
const VIEWPORTS = [
	{ width: 360, height: 640 },
	{ width: 1366, height: 768 }
];

test('the registry gives axe the student shell pages', () => {
	const samples = pages.map((r) => r.sample);
	expect(samples).toContain('/');
	expect(samples).toContain('/dev/shell/student');
});

for (const { path, status } of checked) {
	for (const viewport of VIEWPORTS) {
		test(`${path} at ${viewport.width}x${viewport.height} has no axe violation`, async ({
			context,
			page,
			baseURL
		}) => {
			// axe itself must not reach another origin either.
			const origin = new URL(baseURL!).origin;
			const offOrigin: string[] = [];
			context.on('request', (request) => {
				const url = request.url();
				if (!/^(data|blob|about):/.test(url) && new URL(url).origin !== origin) {
					offOrigin.push(url);
				}
			});
			await page.setViewportSize(viewport);
			const response = await page.goto(path);
			expect(response?.status()).toBe(status);
			const results = await new AxeBuilder({ page }).analyze();
			const summary = results.violations.map(
				(v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`
			);
			expect(summary).toEqual([]);
			const undecided = results.incomplete
				.filter((r) => r.id === 'color-contrast')
				.flatMap((r) => r.nodes.map((n) => n.target.join(' ')));
			expect(undecided).toEqual([]);
			expect(offOrigin).toEqual([]);
		});
	}
}
