import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.CIQ_BASE || 'http://localhost:3001';
const API  = process.env.CIQ_API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

async function login(page: Page) {
  const resp = await fetch(`${API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    localStorage.setItem('contractiq_token', t);
    localStorage.setItem('contractiq_user', JSON.stringify(u || { email: 'test@contractiq.com', role: 'analyst' }));
  }, { t: token, u: me });
}

test.beforeEach(async ({ page }) => { await login(page); });

test('valuation page · h1 + subhead + explainer render synchronously within 2s', async ({ page }) => {
  const started = Date.now();
  await page.goto(`${BASE}/valuation`, { waitUntil: 'domcontentloaded', timeout: 30000 });

  // h1 must be visible within 2s of the route loading — NOT gated behind a spinner
  const h1 = page.locator('h1', { hasText: 'Valuation' });
  await expect(h1).toBeVisible({ timeout: 2000 });

  // subhead is the literal copy from the brief
  await expect(
    page.getByText('Mark-to-market and forward P&L across active positions.', { exact: false }),
  ).toBeVisible({ timeout: 2000 });

  // "What is this page?" pill (same pattern as Dashboard / Model Performance)
  await expect(page.getByTestId('page-explainer-trigger').first()).toBeVisible({ timeout: 2000 });

  const elapsed = Date.now() - started;
  expect(elapsed, 'shell should mount fast').toBeLessThan(8000);
});

test('valuation page · skeleton or data renders below shell while loading', async ({ page }) => {
  await page.goto(`${BASE}/valuation`, { waitUntil: 'domcontentloaded' });
  // shell stays visible the whole time
  await expect(page.locator('h1', { hasText: 'Valuation' })).toBeVisible();
  // either skeleton (still loading), empty state, or one of the data panels
  const skeleton = page.getByTestId('valuation-skeletons');
  const empty = page.getByTestId('valuation-empty');
  const curves = page.getByTestId('curves-panel');
  await expect.poll(async () => {
    return (await skeleton.count()) + (await empty.count()) + (await curves.count()) > 0;
  }, { timeout: 15000 }).toBeTruthy();
});
