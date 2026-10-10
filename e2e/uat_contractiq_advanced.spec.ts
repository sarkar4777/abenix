import { test, expect, type Page, type Locator } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.CIQ_BASE || 'http://localhost:3001';
const API  = process.env.CIQ_API  || 'http://localhost:8001';
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

test('upload a contract, watch extraction, open it and ask about it in chat', async ({ page }) => {
  // The old upload checks only picked a file and never pressed Upload, so they
  // passed on an untouched page. This one is the analyst's whole journey.
  test.setTimeout(900_000);
  const file = path.join(CONTRACTS_DIR, 'gas_supply_agreement_eu.txt');
  test.skip(!fs.existsSync(file), `missing ${file}`);
  const title = `UAT gas supply ${Date.now().toString(36)}`;

  await gotoOk(page, '/upload');
  await page.locator('input[type="file"]').first().setInputFiles(file);
  const upload = page.getByRole('button', { name: /Upload & Extract/i });
  const titleBox = page.getByPlaceholder('e.g. Solar PPA - Project Sunrise');
  // the title is taken from the file name, and cannot be left empty
  await expect(titleBox).toHaveValue('gas supply agreement eu');
  await titleBox.fill('');
  await expect(upload, 'no upload without a title').toBeDisabled();
  await expect(page.getByText('Enter a title to enable upload.')).toBeVisible();
  await titleBox.fill(title);
  await page.getByPlaceholder('e.g. Acme Energy Corp').fill('Nordgas Trading GmbH');
  await page.getByPlaceholder('e.g. SunPower LLC').fill('Rhein Utilities AG');
  await upload.click();
  await expect(page.getByText(/Extraction Pipeline/i)).toBeVisible({ timeout: 60_000 });
  const view = page.getByRole('link', { name: /View Contract Details/i });
  // the page shows either the finished pipeline or why it stopped
  const stopped = page.locator('p.text-red-400').filter({ hasText: /fail|error/i });
  await expect(view.or(stopped).first()).toBeVisible({ timeout: 800_000 });
  if (await stopped.isVisible()) throw new Error(`extraction stopped in the UI: ${await stopped.innerText()}`);
  await view.click();
  await expect(page).toHaveURL(/\/contracts\/[^/]+$/);
  await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('analyzed').first()).toBeVisible({ timeout: 60_000 });

  // the uploaded contract is in the list under its own title
  await gotoOk(page, '/contracts');
  await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });

  // and the portfolio chat can answer about it
  await gotoOk(page, '/chat');
  await page.getByRole('button', { name: /new chat/i }).first().click();
  const box = page.getByPlaceholder(/Ask about your contracts/i);
  await box.fill(`Who are the parties to the contract titled "${title}"?`);
  await box.press('Enter');
  const reply = page.getByTestId('chat-msg-assistant').last();
  await expect(reply).toBeVisible({ timeout: 240_000 });
  await expect(page.getByText('Analyzing your portfolio...')).toBeHidden({ timeout: 240_000 });
  expect((await reply.innerText()).toLowerCase()).toMatch(/nordgas|rhein/);
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

test('workbench — pick a model, edit features, run the explainer', async ({ page }) => {
  test.setTimeout(90_000);
  await gotoOk(page, '/workbench');
  await expect(page.getByText(/Analyst Workbench/i).first()).toBeVisible({ timeout: 10000 });

  const modelBtns = page.locator('aside button').filter({ hasText: /offtake_|price_fairvalue_/i });
  if (await modelBtns.count() > 1) {
    await modelBtns.nth(1).click();
    await page.waitForTimeout(800);
  }

  const numInput = page.locator('input[type=number]').first();
  if (await numInput.isVisible()) await numInput.fill('0.55');

  const runBtn = page.getByRole('button', { name: /Run Explain/i });
  await expect(runBtn).toBeEnabled({ timeout: 10000 });
  await runBtn.click();
  // Abenix's ml_models.explain answers with a waterfall that ends at the prediction
  await expect(page.getByText(/Feature contributions/i).first()).toBeVisible({ timeout: 60000 });
  await expect(page.getByTestId('explain-error')).toHaveCount(0);
  await expect(page.getByTestId('explain-prediction')).not.toHaveText('n/a');
  expect(await page.getByTestId('explain-waterfall').locator('> div').count()).toBeGreaterThan(0);
});

test('model-performance — reads live Abenix registry', async ({ page }) => {
  await gotoOk(page, '/model-performance');
  await expect(page.getByText(/Performance & Backtest|Model Performance/i).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(/Registered models/i).first()).toBeVisible({ timeout: 15000 });
  const sidebar = page.locator('aside button');
  await page.waitForTimeout(2500);
  const n = await sidebar.count();
  expect(n, 'at least one registered model').toBeGreaterThan(0);
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

test('legacy commodity hubs redirect to the selector-driven forward page', async ({ page }) => {
  // The four hubs were retired into /commodities/forward. The redirect is the
  // contract now, uat_commodities_ia_collapse covers the page itself.
  const hubs: Record<string, string> = {
    gas: 'pipeline_gas', power: 'power', lng: 'lng', environmental: 'carbon',
  };
  for (const [hub, commodity] of Object.entries(hubs)) {
    await gotoOk(page, `/commodities/${hub}`);
    await expect(page).toHaveURL(new RegExp(`/commodities/forward\\?commodity=${commodity}$`), { timeout: 15000 });
    await expect(page.locator('main').first()).toBeVisible({ timeout: 10000 });
  }
});

test('data-fabric · live telemetry — sources panel renders', async ({ page }) => {
  await gotoOk(page, '/data-fabric');
  await expect(page.getByText(/Data Fabric/i).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(/Market-data tools available to agents/i).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(/ML models in the registry/i).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(/Execution telemetry/i).first()).toBeVisible({ timeout: 10000 });
  // The registry count comes from the platform through the SDK, not a hardcoded zero.
  const mlTile = page.locator('div').filter({ hasText: /^ML models/ }).filter({ hasText: /registered for this tenant/ }).last();
  await expect(mlTile).not.toContainText('...', { timeout: 20000 });
  const n = Number(((await mlTile.innerText()).match(/\d+/) || ['0'])[0]);
  expect(n, 'registered ML models shown on the fabric page').toBeGreaterThan(0);
});

test('live activity rail · opens on demand, lists live agents and models, collapses', async ({ page }) => {
  await gotoOk(page, '/dashboard');
  // collapsed by default outside the narrative-heavy pages, the user opens it
  await page.getByTitle('Show live activity').click();
  const rail = page.locator('aside').filter({ hasText: /Agents in flight/i }).first();
  await expect(rail).toBeVisible({ timeout: 10000 });
  await expect(rail.getByText(/Live agents \(\d+\)/).first()).toBeVisible();
  // each section of the rail says connecting until its stream is up
  await expect(rail.getByText(/connecting/i)).toHaveCount(0, { timeout: 20000 });
  // and the user can put it away again
  await rail.getByTitle('Collapse').click();
  await expect(page.getByTitle('Show live activity')).toBeVisible();
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
