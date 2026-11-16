// INV3 (runtime half): no page causes a request, WebSocket or prefetch to another origin.
// Requests are recorded at context level, so a worker's or service worker's count too.
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { routes } from '../authz/route-registry.ts';

const INERT = /^(data|blob|about):/;

/** Starts recording; returns the list that every off-origin URL is appended to. */
function record(context: BrowserContext, page: Page, origin: string): string[] {
	const offOrigin: string[] = [];
	const check = (url: string) => {
		if (INERT.test(url)) return;
		const httpUrl = url.replace(/^ws(s?):/, 'http$1:');
		if (new URL(httpUrl).origin !== origin) offOrigin.push(url);
	};
	context.on('request', (request) => check(request.url()));
	const watch = (p: Page) => p.on('websocket', (ws) => check(ws.url()));
	watch(page);
	context.on('page', watch);
	return offOrigin;
}

const pages = routes.filter((r) => r.kind === 'page').map((r) => r.sample);
// A fixed path: test titles must be the same in every Playwright process.
const missing = '/no-such-page-jade-e2e';

for (const path of [...pages, missing]) {
	test(`${path} requests only its own origin`, async ({ context, page, baseURL }) => {
		const origin = new URL(baseURL!).origin;
		const offOrigin = record(context, page, origin);
		const response = await page.goto(path, { waitUntil: 'networkidle' });
		expect(response).not.toBeNull();
		if (path === missing) expect(response!.status()).toBe(404);
		// Hover every link, so a preload on hover is requested and recorded too.
		for (const link of await page.locator('a[href]').all()) await link.hover();
		await page.waitForLoadState('networkidle');
		expect(offOrigin).toEqual([]);
	});
}
