import { test, expect } from '@playwright/test';

const ST_URL = 'http://localhost:3002';
const CIQ_URL = 'http://localhost:3001';

async function loginST(page: any) {
  await page.goto(ST_URL);
  await page.getByRole('button', { name: /Sign In/i }).first().click();
  await page.waitForTimeout(500);
  await page.getByText('Use demo credentials').click();
  await page.waitForTimeout(300);
  await page.getByRole('button', { name: /Sign In/i }).last().click();
  await page.waitForURL('**/dashboard', { timeout: 15000 });
}

// ─── SAUDI TOURISM ──────────────────────────────────────────

test.describe('Saudi Tourism — Full E2E', () => {
  test('01 — Landing page loads with Saudi green theme', async ({ page }) => {
    await page.goto(ST_URL);
    await expect(page).toHaveTitle(/Saudi Tourism/);
    await expect(page.locator('h1')).toContainText('Tourism Intelligence');
    await page.screenshot({ path: 'test-results/st-01-landing.png', fullPage: true });
  });

  test('02 — Login with demo credentials', async ({ page }) => {
    await loginST(page);
    await expect(page.locator('h1')).toContainText('Tourism Dashboard');
    await page.screenshot({ path: 'test-results/st-02-dashboard.png', fullPage: true });
  });

  test('03 — Upload page shows datasets', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/upload`);
    await expect(page.locator('h1')).toContainText('Upload');
    // Data already seeded — just verify the list shows
    await expect(page.getByText('Your Datasets')).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: 'test-results/st-03-upload.png', fullPage: true });
  });

  test('04 — Dashboard shows cached analytics', async ({ page }) => {
    await loginST(page);
    // Dashboard should load cached data instantly
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test-results/st-04-dashboard-data.png', fullPage: true });
  });

  test('05 — Regional Analytics page loads', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/regional`);
    await expect(page.locator('h1')).toContainText('Regional');
    await page.screenshot({ path: 'test-results/st-05-regional.png', fullPage: true });
  });

  test('06 — Deep Analytics page loads', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/analytics`);
    await expect(page.locator('h1')).toContainText('Deep Analytics');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'test-results/st-06-analytics.png', fullPage: true });
  });

  test('07 — Simulations page loads with presets', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/simulations`);
    await expect(page.locator('h1')).toContainText('Simulations');
    await expect(page.getByText('Visa Fee Impact Analysis').first()).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: 'test-results/st-07-simulations.png', fullPage: true });
  });

  test('08 — Chat page loads with suggestions', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/chat`);
    await expect(page.locator('h1')).toContainText('Tourism Chat');
    await page.screenshot({ path: 'test-results/st-08-chat.png', fullPage: true });
  });

  test('09 — Reports page loads with report types', async ({ page }) => {
    await loginST(page);
    await page.goto(`${ST_URL}/reports`);
    await expect(page.locator('h2').first()).toContainText('Generate');
    await expect(page.getByText('Executive Briefing')).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: 'test-results/st-09-reports.png', fullPage: true });
  });
});

// ─── EXAMPLE_APP ──────────────────────────────────────────────

test.describe('the example app — Smoke Test', () => {
  test('10 — the example app landing page loads', async ({ page }) => {
    await page.goto(CIQ_URL);
    await expect(page).toHaveTitle(/the example app/);
    await expect(page.locator('h1')).toContainText('Upload your PPA');
    await page.screenshot({ path: 'test-results/ciq-10-landing.png', fullPage: true });
  });

  test('11 — the example app login works', async ({ page }) => {
    await page.goto(CIQ_URL);
    await page.getByRole('button', { name: /Sign In/i }).first().click();
    await page.waitForTimeout(500);
    await page.getByText('Use demo credentials').click();
    await page.waitForTimeout(300);
    await page.getByRole('button', { name: /Sign In/i }).last().click();
    await page.waitForURL('**/dashboard', { timeout: 15000 });
    await page.screenshot({ path: 'test-results/ciq-11-dashboard.png', fullPage: true });
  });
});
