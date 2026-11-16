// Plan section 13 (L2, L4, AC10). Every page of the route registry, and the error page (the
// fixed missing path that no-offorigin.spec.ts uses), at 360x640 and at 1366x768:
// - no horizontal overflow, one visible `main` landmark and one visible `h1`;
// - the skip link, focused and activated with Enter, moves focus to `main`;
// - `data-shell` names the shell of the page's route group;
// - in the student shell, every text in `main` is at least 18px and every visible target is at
//   least 48 by 48 CSS pixels (there is at least one); in the adult and staff shells every
//   visible target is at least 24 by 24 or meets WCAG 2.5.8's spacing exception. A target is
//   `a[href]`, `button`, `[role=button]` or `summary`; a target whose computed display is
//   `inline` (a link inside running text) is exempt, as WCAG 2.5.8 exempts inline targets, but
//   still counts as a neighbour for the spacing exception.
// Also: with reduced motion the sample button's transition runs in effectively no time, whether
// the preference is set before or after load; the three shells report three different
// `data-shell` values. A page outside the three route groups fails here, so a later page is
// covered or this file is changed with it. No screenshot comparison: the system font stack
// renders differently on each machine.
import { expect, test, type Page } from '@playwright/test';
import { routes, type RouteEntry } from '../authz/route-registry.ts';

const SHELLS = ['student', 'adult', 'staff'] as const;
type Shell = (typeof SHELLS)[number];

/** The shell a page is wrapped in, from its route group, or null outside the three groups. */
function shellOf(route: RouteEntry): Shell | null {
	const group = /^\/\(([^)]+)\)/.exec(route.id)?.[1];
	return SHELLS.find((s) => s === group) ?? null;
}

const pages = routes.filter((r) => r.kind === 'page');
// The same fixed path as no-offorigin.spec.ts. The error page renders in the student shell.
const MISSING = '/no-such-page-jade-e2e';
const checked: { path: string; status: number; shell: Shell | null }[] = [
	...pages.map((r) => ({ path: r.sample, status: 200, shell: shellOf(r) })),
	{ path: MISSING, status: 404, shell: 'student' }
];
const VIEWPORTS = [
	{ width: 360, height: 640 },
	{ width: 1366, height: 768 }
];
const MIN_FONT_PX = 18;
const TAP_MIN_PX = 48;
const TARGET_MIN_PX = 24;
const TARGETS = 'a[href], button, [role=button], summary';

interface Box {
	what: string;
	x: number;
	y: number;
	width: number;
	height: number;
	/** Computed display is `inline`: a target inside running text, exempt under WCAG 2.5.8. */
	inline: boolean;
}

/**
 * Every visible target of the page. Visible means rendered, not `visibility: hidden`, not
 * transparent, and not a visually hidden (clipped, 1px) element. Inline targets are returned
 * too: they are exempt from the size checks but still count as neighbours for the spacing
 * exception.
 */
async function targetsOf(page: Page): Promise<Box[]> {
	return page.locator(TARGETS).evaluateAll((els) =>
		els
			.filter((el) => {
				if (!el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) return false;
				const r = el.getBoundingClientRect();
				const s = getComputedStyle(el);
				const clipped = s.clip !== 'auto' || s.clipPath !== 'none';
				return !(clipped && r.width <= 1 && r.height <= 1);
			})
			.map((el) => {
				const r = el.getBoundingClientRect();
				return {
					what: el.outerHTML.slice(0, 80),
					x: r.x,
					y: r.y,
					width: r.width,
					height: r.height,
					inline: getComputedStyle(el).display === 'inline'
				};
			})
	);
}

/**
 * WCAG 2.5.8's spacing exception: a 24px circle centred on `t` meets no other target, and no
 * other undersized target's circle.
 */
function spacedEnough(t: Box, all: Box[]): boolean {
	const r = TARGET_MIN_PX / 2;
	const cx = t.x + t.width / 2;
	const cy = t.y + t.height / 2;
	const small = (b: Box) => b.width < TARGET_MIN_PX || b.height < TARGET_MIN_PX;
	return all.every((o) => {
		if (o === t) return true;
		const dx = Math.max(o.x - cx, 0, cx - (o.x + o.width));
		const dy = Math.max(o.y - cy, 0, cy - (o.y + o.height));
		if (Math.hypot(dx, dy) < r) return false;
		if (!small(o)) return true;
		return Math.hypot(o.x + o.width / 2 - cx, o.y + o.height / 2 - cy) >= TARGET_MIN_PX;
	});
}

/** The longest transition duration of the element, in seconds. */
async function transitionSeconds(page: Page, selector: string): Promise<number> {
	return page.locator(selector).evaluate((el) => {
		const parse = (d: string) => (d.endsWith('ms') ? parseFloat(d) / 1000 : parseFloat(d));
		return Math.max(...getComputedStyle(el).transitionDuration.split(',').map(parse));
	});
}

test('every registry page is in a route group with a shell', () => {
	for (const route of pages) expect(shellOf(route), route.id).not.toBeNull();
});

for (const { path, status, shell } of checked) {
	for (const viewport of VIEWPORTS) {
		test(`${path} at ${viewport.width}x${viewport.height} holds its layout`, async ({ page }) => {
			await page.setViewportSize(viewport);
			const response = await page.goto(path);
			expect(response?.status()).toBe(status);

			const overflow = await page.evaluate(
				() => document.documentElement.scrollWidth - document.documentElement.clientWidth
			);
			expect(overflow).toBeLessThanOrEqual(0);

			await expect(page.getByRole('main')).toHaveCount(1);
			await expect(page.getByRole('main')).toBeVisible();
			await expect(page.locator('h1')).toHaveCount(1);
			await expect(page.locator('h1')).toBeVisible();
			await expect(page.locator('[data-shell]')).toHaveAttribute('data-shell', shell!);

			// The skip link: focused directly (WebKit does not Tab to links by default), then Enter.
			const skip = page.locator('a.skip-link[href="#main"]');
			await expect(skip).toHaveCount(1);
			await expect(skip).toBeVisible();
			await skip.focus();
			await page.keyboard.press('Enter');
			await expect(page.locator('main#main')).toBeFocused();

			const all = await targetsOf(page);
			const targets = all.filter((t) => !t.inline);
			// Every shell has at least its skip link, so an empty list means the check broke.
			expect(targets.length).toBeGreaterThan(0);
			if (shell === 'student') {
				const bodyPx = await page.evaluate(() =>
					parseFloat(getComputedStyle(document.body).fontSize)
				);
				expect(bodyPx).toBeGreaterThanOrEqual(MIN_FONT_PX);
				const texts = await page.locator('main').evaluate((main) => {
					const out: { text: string; px: number }[] = [];
					const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
					for (let n = walker.nextNode(); n; n = walker.nextNode()) {
						const text = n.textContent?.trim() ?? '';
						if (text === '' || !n.parentElement) continue;
						// Text nobody sees (a closed panel) is not held to the size.
						if (!n.parentElement.checkVisibility({ visibilityProperty: true })) continue;
						out.push({ text, px: parseFloat(getComputedStyle(n.parentElement).fontSize) });
					}
					return out;
				});
				expect(texts.length).toBeGreaterThan(0);
				for (const t of texts) expect(t.px, t.text).toBeGreaterThanOrEqual(MIN_FONT_PX);

				for (const t of targets) {
					expect(t.width, t.what).toBeGreaterThanOrEqual(TAP_MIN_PX);
					expect(t.height, t.what).toBeGreaterThanOrEqual(TAP_MIN_PX);
				}
			} else {
				for (const t of targets) {
					const sized = t.width >= TARGET_MIN_PX && t.height >= TARGET_MIN_PX;
					expect(sized || spacedEnough(t, all), t.what).toBe(true);
				}
			}
		});
	}
}

const samplePages = pages.filter((r) => r.sample.startsWith('/dev/shell/'));

test('the registry holds one sample page per shell', () => {
	expect(samplePages.map(shellOf).sort()).toEqual([...SHELLS].sort());
});

for (const route of samplePages) {
	test(`${route.sample}: the sample button's transition is effectively zero under reduced motion`, async ({
		page
	}) => {
		const button = 'main button';
		await page.emulateMedia({ reducedMotion: 'no-preference' });
		await page.goto(route.sample);
		await expect(page.locator(button)).toHaveCount(1);
		expect(await transitionSeconds(page, button)).toBeGreaterThan(0);

		await page.emulateMedia({ reducedMotion: 'reduce' });
		expect(await transitionSeconds(page, button)).toBeLessThanOrEqual(0.001);
	});

	test(`${route.sample}: the sample button's transition is effectively zero when loaded with reduced motion`, async ({
		page
	}) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await page.goto(route.sample);
		await expect(page.locator('main button')).toHaveCount(1);
		expect(await transitionSeconds(page, 'main button')).toBeLessThanOrEqual(0.001);
	});
}

test('the three shells report three different data-shell values', async ({ page }) => {
	const seen = new Set<string>();
	for (const route of samplePages) {
		await page.goto(route.sample);
		const value = await page.locator('[data-shell]').getAttribute('data-shell');
		expect(value).toBe(shellOf(route));
		seen.add(value!);
	}
	expect(seen.size).toBe(3);
});
