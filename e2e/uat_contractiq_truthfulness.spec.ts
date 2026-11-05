import { test, expect, Page } from '@playwright/test';

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
  expect(token).toBeTruthy();
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify(u || { email: 'test@contractiq.com', role: 'analyst' }));
    } catch {}
  }, { t: token, u: me });
}

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status()).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.configure({ timeout: 120_000 });

test.describe('contractiq truthfulness wave', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  const explainerPages = ['/dashboard', '/forecaster', '/price-engine', '/workbench', '/recommendations',
                          '/data-fabric', '/model-performance', '/credit-risk', '/contracts', '/upload', '/help'];
  for (const p of explainerPages) {
    test(`explainer mounted on ${p}`, async ({ page }) => {
      await gotoOk(page, p);
      await expect(page.getByTestId('page-explainer').getByRole('button', { name: /What is this page/ }), `explainer mounted on ${p}`).toBeVisible({ timeout: 15_000 });
    });
  }

  test('PageExplainer card opens with its content', async ({ page }) => {
    await gotoOk(page, '/forecaster');
    const trigger = page.getByTestId('page-explainer').getByRole('button', { name: /What is this page/ });
    await trigger.click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const card = page.getByTestId('page-explainer-card');
    await expect(card).toBeVisible({ timeout: 8_000 });
    await card.getByTestId('explainer-tab-sections').click();
    await expect(card.getByTestId('explainer-sections').locator('li').first()).toBeVisible();
    await card.getByTestId('explainer-tab-flow').click();
    await expect(card.getByTestId('explainer-flow').locator('li').first()).toBeVisible();
  });

  test('Model Performance reads from live Abenix registry', async ({ page }) => {
    await gotoOk(page, '/model-performance');
    await expect(page.locator('text=/Registered models/i').first()).toBeVisible({ timeout: 15_000 });
    const count = await page.locator('aside button').count();
    expect(count).toBeGreaterThan(0);
  });

  test('Forecaster: agent returns model name OR honest needs-config banner', async ({ page }) => {
    await gotoOk(page, '/forecaster');
    await page.waitForTimeout(4000);
    const liveModel = page.locator('text=/offtake_residential|offtake_industrial|offtake_storage_cycling/i');
    const needsConfig = page.locator('text=/not yet deployed|needs configuration/i');
    const ok = (await liveModel.count()) > 0 || (await needsConfig.count()) > 0;
    expect(ok).toBeTruthy();
  });

  test('Price Engine: fair-value model name OR honest banner', async ({ page }) => {
    await gotoOk(page, '/price-engine');
    await page.waitForTimeout(4000);
    const liveModel = page.locator('text=/price_fairvalue_gas_hubs|price_fairvalue_power_hubs/i');
    const needsConfig = page.locator('text=/not registered|needs configuration/i');
    const ok = (await liveModel.count()) > 0 || (await needsConfig.count()) > 0;
    expect(ok).toBeTruthy();
  });

  test('Data Fabric renders the market data tools panel', async ({ page }) => {
    await gotoOk(page, '/data-fabric');
    await expect(page.getByRole('heading', { name: 'Market-data tools available to agents' })).toBeVisible({ timeout: 15_000 });
  });

  test('Workbench Run Explain gives feature contributions or an honest error', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await expect(page.getByText('Click Run Explain to score the current feature vector.')).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Run Explain' }).click();
    const outcome = page.getByRole('heading', { name: 'Feature contributions' }).or(page.getByTestId('explain-error'));
    await expect(outcome).toBeVisible({ timeout: 90_000 });
  });

  test('Recommendations renders heading', async ({ page }) => {
    await gotoOk(page, '/recommendations');
    await expect(page.locator('h1:has-text("Recommendations")')).toBeVisible({ timeout: 15_000 });
  });
});
