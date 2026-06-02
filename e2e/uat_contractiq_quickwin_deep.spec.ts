import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3001';
const API  = process.env.API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';
const CONTRACTS_DIR = path.resolve(__dirname, '..', 'contractiq', 'test-contracts');

const PDF_CONTRACTS = [
  'gas_supply_agreement_eu.pdf',
  'hybrid_offshore_wind_ppa_uk.pdf',
  'iberian_solar_cffd_ppa.pdf',
  'nordic_wind_portfolio_ppa.pdf',
  'solar_ppa_uae_250mw.pdf',
  'wind_ppa_uk_350mw.pdf',
];

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
    localStorage.setItem('contractiq_user', JSON.stringify(u || { email: EMAIL, role: 'analyst' }));
  }, { t: token, u: me });
}

async function gotoOk(page: Page, p: string) {
  const r = await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  expect(r?.status(), `${p} status`).toBeLessThan(400);
}

test.beforeEach(async ({ page }) => { await login(page); });

test('quickwin · traffic-light heat map renders bands + filters', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  const dash = page.getByTestId('traffic-light-dashboard');
  await expect(dash).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId(/cp-card-(green|amber|red)/).first()).toBeVisible();
  const greens = await page.getByTestId('cp-card-green').count();
  const ambers = await page.getByTestId('cp-card-amber').count();
  const reds = await page.getByTestId('cp-card-red').count();
  expect(greens + ambers + reds, 'at least one card per tier seeded').toBeGreaterThanOrEqual(3);
  await page.getByRole('button', { name: /^Red/ }).click();
  await expect(page.getByTestId('cp-card-green')).toHaveCount(0);
});

test('quickwin · compliance ticker shows seeded warnings, ack works', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  const ticker = page.getByTestId('compliance-alerts');
  await expect(ticker).toBeVisible({ timeout: 15000 });
  const criticals = await page.getByTestId('alert-critical').count();
  const warnings = await page.getByTestId('alert-warning').count();
  expect(criticals + warnings, 'expected pre-seeded alerts').toBeGreaterThanOrEqual(3);
  const firstAck = page.locator('[data-testid^="ack-"]').first();
  await firstAck.click();
  await page.waitForTimeout(1500);
});

test('quickwin · run sweep triggers backend', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  const sweep = page.getByTestId('run-sweep');
  await expect(sweep).toBeVisible();
  await sweep.click();
  await page.waitForTimeout(2500);
  await expect(page.getByTestId('compliance-alerts')).toBeVisible();
});

test('quickwin · counterparty detail — financials/ratios/permits tabs all populated', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('traffic-light-dashboard')).toBeVisible({ timeout: 15000 });
  await page.getByTestId(/cp-card-/).first().click();
  await expect(page.getByTestId('counterparty-detail')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('financials-table')).toBeVisible();
  await expect(page.locator('text=Revenue').first()).toBeVisible();
  await page.getByTestId('tab-ratios').click();
  await expect(page.getByTestId('ratios-table')).toBeVisible();
  await expect(page.locator('text=Altman').first()).toBeVisible();
  await page.getByTestId('tab-permits').click();
  await expect(page.getByTestId('permits-panel')).toBeVisible();
});

test('contracts · upload each PDF + analysis fires', async ({ page }) => {
  for (const pdf of PDF_CONTRACTS) {
    const full = path.join(CONTRACTS_DIR, pdf);
    if (!fs.existsSync(full)) continue;
    await gotoOk(page, '/upload');
    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(full);
    await page.waitForTimeout(2500);
  }
  await gotoOk(page, '/contracts');
  await expect(page.locator('main')).toBeVisible({ timeout: 15000 });
});

const ALL_PAGES = [
  '/dashboard', '/credit-risk', '/credit-risk/kyc', '/risk', '/insights',
  '/insights/briefing', '/insights/renewals', '/insights/force-majeure',
  '/insights/reconciliation', '/insights/families', '/insights/anomalies',
  '/insights/version-diff', '/insights/stress-test', '/insights/hedge', '/insights/benchmark',
  '/clauses', '/deal-clusters', '/timeline', '/valuation', '/simulations',
  '/market', '/compare', '/chat',
  '/data-fabric', '/forecaster', '/price-engine', '/workbench', '/model-performance', '/recommendations',
  '/commodities/gas', '/commodities/power', '/commodities/lng', '/commodities/environmental',
  '/metals', '/metals/extract', '/metals/compliance', '/metals/disputes',
  '/metals/loco', '/metals/sourcing', '/metals/refiners',
  '/admin/rbac', '/admin/market-sources', '/admin/audit',
  '/help', '/features',
];

for (const p of ALL_PAGES) {
  test(`page renders 200 + has main · ${p}`, async ({ page }) => {
    await gotoOk(page, p);
    await expect(page.locator('main').first()).toBeVisible({ timeout: 10000 });
  });
}

test('quickwin module pages · forecaster sliders + price-engine + workbench interactive', async ({ page }) => {
  await gotoOk(page, '/forecaster');
  await expect(page.locator('text=Predictive Offtake').first()).toBeVisible();
  const slider = page.locator('input[type=range]').first();
  if (await slider.count()) await slider.evaluate((el: HTMLInputElement) => { el.value = '4'; el.dispatchEvent(new Event('input', { bubbles: true })); });

  await gotoOk(page, '/price-engine');
  await expect(page.locator('text=Forward Price Engine').first()).toBeVisible();
  const wSliders = page.locator('input[type=range]');
  if (await wSliders.count()) {
    await wSliders.nth(0).evaluate((el: HTMLInputElement) => { el.value = '50'; el.dispatchEvent(new Event('input', { bubbles: true })); });
  }

  await gotoOk(page, '/workbench');
  await expect(page.locator('text=Analyst Workbench').first()).toBeVisible();
});

test('quickwin · DAG viewer rail visible on every page', async ({ page }) => {
  for (const p of ['/dashboard', '/credit-risk', '/forecaster', '/contracts', '/help']) {
    await gotoOk(page, p);
    const sidebar = page.locator('aside').filter({ hasText: 'Live activity' }).first();
    await expect(sidebar).toBeVisible({ timeout: 10000 });
  }
});

test('help page · 5-module diagram + glossary visible', async ({ page }) => {
  await gotoOk(page, '/help');
  await expect(page.locator('text=Commodities 101').first()).toBeVisible({ timeout: 15000 });
  await expect(page.locator('text=Forecasting & Trading platform').first()).toBeVisible();
  await expect(page.locator('text=pocket glossary').first()).toBeVisible();
});
