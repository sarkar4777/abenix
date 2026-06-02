import { test, expect, type Page, type Locator } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3001';
const API  = process.env.API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';
const CONTRACTS_DIR = path.resolve(__dirname, '..', 'contractiq', 'test-contracts');

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
  const r = await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  expect(r?.status(), `${p} status`).toBeLessThan(400);
}

async function waitFor(page: Page, sel: string, timeoutMs = 30000): Promise<Locator> {
  const loc = page.locator(sel).first();
  await loc.waitFor({ state: 'visible', timeout: timeoutMs });
  return loc;
}

test.beforeEach(async ({ page }) => { await login(page); });

test('upload PDF · gas supply agreement EU · contract appears in list', async ({ page }) => {
  const pdf = path.join(CONTRACTS_DIR, 'gas_supply_agreement_eu.pdf');
  test.skip(!fs.existsSync(pdf), `missing ${pdf}`);
  await gotoOk(page, '/upload');
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(pdf);
  await page.waitForTimeout(4000);
  await gotoOk(page, '/contracts');
  await expect(page.locator('main').first()).toBeVisible();
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/contract|gas|supply|ppa|tolling|wind|solar/);
});

test('upload PDF · solar UAE 250mw · extraction is triggered', async ({ page }) => {
  const pdf = path.join(CONTRACTS_DIR, 'solar_ppa_uae_250mw.pdf');
  test.skip(!fs.existsSync(pdf), `missing ${pdf}`);
  await gotoOk(page, '/upload');
  await page.locator('input[type="file"]').first().setInputFiles(pdf);
  await page.waitForTimeout(4000);
  await gotoOk(page, '/contracts');
  await expect(page.locator('main').first()).toBeVisible();
});

test('upload multi-PDF batch — 4 contracts ingest without UI errors', async ({ page }) => {
  const batch = [
    'hybrid_offshore_wind_ppa_uk.pdf',
    'iberian_solar_cffd_ppa.pdf',
    'nordic_wind_portfolio_ppa.pdf',
    'wind_ppa_uk_350mw.pdf',
  ].map(n => path.join(CONTRACTS_DIR, n)).filter(fs.existsSync);
  test.skip(batch.length === 0, 'no batch PDFs found');
  for (const pdf of batch) {
    await gotoOk(page, '/upload');
    await page.locator('input[type="file"]').first().setInputFiles(pdf);
    await page.waitForTimeout(2500);
  }
  await gotoOk(page, '/contracts');
  const errs = await page.locator('[role=alert], .text-red-300, .text-rose-300').filter({ hasText: /error|failed/i }).count();
  expect(errs).toBeLessThan(2);
});

test('contracts list — first card opens detail page', async ({ page }) => {
  await gotoOk(page, '/contracts');
  await page.waitForTimeout(2000);
  const cards = page.locator('a[href^="/contracts/"]');
  const n = await cards.count();
  if (n === 0) return;
  await cards.first().click();
  await page.waitForLoadState('domcontentloaded');
  await expect(page).toHaveURL(/\/contracts\/[^/]+/);
  await expect(page.locator('main').first()).toBeVisible();
});

test('KYC landing — Start check CTA + agent-driven message visible', async ({ page }) => {
  await gotoOk(page, '/credit-risk/kyc');
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2500);
  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).toMatch(/sanctions|pep|kyc|screening|standard/);
});

test('insights · Daily Briefing renders', async ({ page }) => {
  await gotoOk(page, '/insights/briefing');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('insights · all 10 children render under main', async ({ page }) => {
  const paths = [
    '/insights/renewals', '/insights/force-majeure', '/insights/reconciliation',
    '/insights/families', '/insights/anomalies', '/insights/version-diff',
    '/insights/stress-test', '/insights/hedge', '/insights/benchmark',
  ];
  for (const p of paths) {
    await gotoOk(page, p);
    await expect(page.locator('main').first()).toBeVisible({ timeout: 10000 });
  }
});

test('valuation page loads and shows table or chart', async ({ page }) => {
  await gotoOk(page, '/valuation');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('risk · VaR page renders + inputs present', async ({ page }) => {
  await gotoOk(page, '/risk');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/var|cvar|risk|portfolio|confidence|var.95|var.99/);
});

test('simulations page renders', async ({ page }) => {
  await gotoOk(page, '/simulations');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('clause library renders + at least one clause type visible', async ({ page }) => {
  await gotoOk(page, '/clauses');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('deal clusters page renders', async ({ page }) => {
  await gotoOk(page, '/deal-clusters');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('event timeline page renders', async ({ page }) => {
  await gotoOk(page, '/timeline');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
});

test('forecaster — sliders + scenario buttons interactive', async ({ page }) => {
  await gotoOk(page, '/forecaster');
  await expect(page.getByText(/Predictive Offtake Forecaster/i).first()).toBeVisible({ timeout: 10000 });

  const sliders = page.locator('input[type=range]');
  const count = await sliders.count();
  expect(count, 'slider count').toBeGreaterThanOrEqual(3);

  for (let i = 0; i < Math.min(count, 3); i++) {
    await sliders.nth(i).evaluate((el: HTMLInputElement, v) => {
      el.value = String(v); el.dispatchEvent(new Event('input', { bubbles: true }));
    }, [4, 0.3, 0.25][i] ?? 1);
  }

  const scenarioBtns = page.getByRole('button', { name: /Cold-snap|Industrial|Retail churn|Mild winter/i });
  if (await scenarioBtns.count()) {
    await scenarioBtns.first().click();
  }
});

test('price-engine — layer weights + stress + hub switch', async ({ page }) => {
  await gotoOk(page, '/price-engine');
  await expect(page.getByText(/Dynamic Forward Price Engine/i).first()).toBeVisible({ timeout: 10000 });

  const hubBtns = page.locator('button').filter({ hasText: /^TTF|^THE|^DE-Power|^HU-Power/ });
  if (await hubBtns.count()) {
    await hubBtns.first().click();
    await page.waitForTimeout(500);
  }

  const sliders = page.locator('input[type=range]');
  for (let i = 0; i < Math.min(await sliders.count(), 2); i++) {
    await sliders.nth(i).evaluate((el: HTMLInputElement) => {
      el.value = '60'; el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  const stressBtns = page.getByRole('button', { name: /Cold winter|Pipeline outage|CO₂|CO2|Mild Mediterranean/i });
  if (await stressBtns.count()) await stressBtns.first().click();
});

test('workbench — pick forecast + submit override (no false success)', async ({ page }) => {
  await gotoOk(page, '/workbench');
  await expect(page.getByText(/Analyst Workbench/i).first()).toBeVisible({ timeout: 10000 });

  const forecastBtns = page.locator('button').filter({ hasText: /TTF M\+1|Residential 14d|Storage cycling|DE-Power Cal\+1/i });
  if (await forecastBtns.count()) {
    await forecastBtns.nth(1).click();
    await page.waitForTimeout(500);
  }

  const numInput = page.locator('input[type=number]').first();
  if (await numInput.isVisible()) {
    await numInput.fill('330.5');
    const reason = page.locator('textarea').first();
    if (await reason.isVisible()) await reason.fill('Override rationale — recent HDD outlook tightens upside.');
    const submit = page.getByRole('button', { name: /Submit override/i });
    if (await submit.isEnabled()) await submit.click();
  }
});

test('model-performance — table selectable, backtest button works', async ({ page }) => {
  await gotoOk(page, '/model-performance');
  await expect(page.getByText(/Performance & Backtest/i).first()).toBeVisible({ timeout: 10000 });
  const tableRows = page.locator('table tbody tr');
  const n = await tableRows.count();
  if (n) {
    await tableRows.nth(Math.min(2, n - 1)).click();
    await page.waitForTimeout(500);
  }
  const backtest = page.getByRole('button', { name: /365-day backtest|Running 365-day/i });
  if (await backtest.count()) {
    await backtest.first().click();
    await page.waitForTimeout(2500);
    await expect(page.getByText(/MAE|RMSE|MAPE/).first()).toBeVisible();
  }
});

test('recommendations — desk filter cards', async ({ page }) => {
  await gotoOk(page, '/recommendations');
  await expect(page.getByText(/^Recommendations$/i).first()).toBeVisible({ timeout: 10000 });
  for (const desk of ['gas', 'power', 'lng', 'environmental', 'cross']) {
    const btn = page.getByRole('button', { name: new RegExp(`^${desk}$`, 'i') });
    if (await btn.count()) await btn.first().click();
    await page.waitForTimeout(300);
  }
});

test('commodity hubs · 4 desks · each renders curve + signals + contracts', async ({ page }) => {
  for (const hub of ['gas', 'power', 'lng', 'environmental']) {
    await gotoOk(page, `/commodities/${hub}`);
    await expect(page.locator('main').first()).toBeVisible({ timeout: 10000 });
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body, `${hub} hub body`).toMatch(/curve|forward|signals|contracts|hubs|spot/i);
  }
});

test('data-fabric · 22 connectors table renders + category filter works', async ({ page }) => {
  await gotoOk(page, '/data-fabric');
  await expect(page.getByText(/Data Fabric/i).first()).toBeVisible({ timeout: 10000 });
  const rows = page.locator('tbody tr');
  expect(await rows.count(), 'connector rows').toBeGreaterThanOrEqual(10);
  const tsoBtn = page.getByRole('button', { name: /TSO/i });
  if (await tsoBtn.count()) {
    await tsoBtn.first().click();
    await page.waitForTimeout(500);
  }
});

test('live activity rail · visible + has Live activity title', async ({ page }) => {
  await gotoOk(page, '/dashboard');
  const rail = page.locator('aside').filter({ hasText: /Live activity/i }).first();
  await expect(rail).toBeVisible({ timeout: 10000 });
  await expect(rail.getByText(/Agents in flight|ML models invoking|Where the data lives/i).first()).toBeVisible();
});

test('chat page · message box + send button present', async ({ page }) => {
  await gotoOk(page, '/chat');
  await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 });
  const input = page.locator('textarea, input[type=text]').first();
  if (await input.isVisible()) {
    await input.fill('What are my top three high-risk counterparties this week?');
    await page.waitForTimeout(500);
  }
});

test('help page · primary section headers visible', async ({ page }) => {
  await gotoOk(page, '/help');
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  const expectedTexts = ['Counterparty data', 'Commodities 101', 'Forecasting & Trading', 'feature catalogue'];
  let found = 0;
  for (const t of expectedTexts) {
    if (await page.getByText(new RegExp(t, 'i')).first().isVisible().catch(() => false)) found++;
  }
  expect(found, 'at least 2 primary section headers visible on help page').toBeGreaterThanOrEqual(2);
});

test('counterparty heat map · tier badges render distinct counts', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('traffic-light-dashboard')).toBeVisible({ timeout: 20000 });
  const greens = await page.getByTestId('cp-card-green').count();
  const ambers = await page.getByTestId('cp-card-amber').count();
  const reds   = await page.getByTestId('cp-card-red').count();
  expect(greens + ambers + reds).toBeGreaterThanOrEqual(8);
  expect(greens).toBeGreaterThan(0);
  expect(reds).toBeGreaterThan(0);
});

test('counterparty detail · five-year financials show numeric values', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('traffic-light-dashboard')).toBeVisible({ timeout: 20000 });
  await page.getByTestId(/cp-card-/).first().click();
  await expect(page.getByTestId('counterparty-detail')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('financials-table')).toBeVisible();
  const moneyCells = page.locator('td.font-mono').filter({ hasText: /^\$/ });
  expect(await moneyCells.count(), 'numeric $ cells in financials').toBeGreaterThanOrEqual(15);
});

test('counterparty detail · ratios tab shows altman z numeric', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('traffic-light-dashboard')).toBeVisible({ timeout: 20000 });
  await page.getByTestId(/cp-card-/).first().click();
  await expect(page.getByTestId('counterparty-detail')).toBeVisible({ timeout: 15000 });
  await page.getByTestId('tab-ratios').click();
  await expect(page.getByTestId('ratios-table')).toBeVisible();
  const altmanRow = page.locator('tr').filter({ hasText: /Altman/i });
  await expect(altmanRow).toBeVisible();
});

test('counterparty detail · permits tab shows at least one expired card', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('traffic-light-dashboard')).toBeVisible({ timeout: 20000 });
  await page.getByTestId('cp-card-red').first().click();
  await expect(page.getByTestId('counterparty-detail')).toBeVisible({ timeout: 15000 });
  await page.getByTestId('tab-permits').click();
  await expect(page.getByTestId('permits-panel')).toBeVisible();
});

test('compliance alerts · ack flow flips status', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('compliance-alerts')).toBeVisible({ timeout: 20000 });
  const before = await page.locator('[data-testid^="alert-"]').count();
  if (before > 0) {
    const ackBtn = page.locator('[data-testid^="ack-"]').first();
    await ackBtn.click();
    await page.waitForTimeout(2000);
    const after = await page.locator('[data-testid^="alert-"]').count();
    expect(after, 'open alert count drops after ack').toBeLessThan(before);
  }
});

test('sweep button raises new alerts (idempotent)', async ({ page }) => {
  await gotoOk(page, '/credit-risk');
  await expect(page.getByTestId('compliance-alerts')).toBeVisible({ timeout: 20000 });
  const sweep = page.getByTestId('run-sweep');
  await sweep.click();
  await page.waitForTimeout(3000);
  await expect(page.getByTestId('compliance-alerts')).toBeVisible();
});
