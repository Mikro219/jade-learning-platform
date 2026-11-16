// THROWAWAY (plan X5, OB12): fails on purpose to prove the e2e job uploads the Playwright report.
// This branch is never merged; its PR is closed and the branch deleted once the artifact is seen.
import { expect, test } from '@playwright/test';

test('deliberate failure for the upload proof', async ({ page }) => {
	await page.goto('/');
	expect(1, 'deliberate failure: upload proof').toBe(2);
});
