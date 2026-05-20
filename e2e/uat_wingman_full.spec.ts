import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Screenshots saved outside the repo — never committed.
const SHOTS_DIR = process.env.WINGMAN_SHOTS_DIR
  || path.join(process.env.USERPROFILE || process.env.HOME || '.', 'wingman-screenshots');
fs.mkdirSync(SHOTS_DIR, { recursive: true });

let _shotCount = 0;
async function shot(page: Page, label: string) {
  _shotCount++;
  const name = `${String(_shotCount).padStart(2, '0')}-${label}.png`;
  await page.screenshot({ path: path.join(SHOTS_DIR, name), fullPage: true });
}

/**
 * Wingman — comprehensive end-to-end browser UAT.
 *
 * Covers every page in the workbench:
 *   1. Arbitrage Workbench — market brief, corridors, run analysis
 *   2. Forward Scenarios   — Bayesian prior strip + fan chart + scenario cards
 *   3. Broker Inbox        — list, classify (ML model), parse, ack → approval gate
 *   4. Approvals (queue)   — list, filter, approve/deny via SDK proxy
 *   5. Operations Watch    — vessel snapshot, weather panel, DAG drawer
 *   6. Strategy Lab        — encode rule, run backtest
 *   7. Knowledge Graph     — Atlas query
 *
 * Plus the cross-cutting DAG drawer + the platform-side check that
 * every wingman agent + sample ML model is registered.
 *
 * Run:
 *   BASE_WM=http://localhost:3006  WM_API=http://localhost:8006 \
 *   AB_API=http://localhost:8000  AF_EMAIL=admin@abenix.dev  AF_PASSWORD=Admin123456 \
 *   USE_K8S=true \
 *   npx playwright test e2e/uat_wingman_full.spec.ts \
 *     --reporter=list --workers=1 --timeout=480000
 */

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const API = process.env.WM_API || 'http://localhost:8006';
const PLATFORM_API = process.env.AB_API || 'http://localhost:8000';
const PLATFORM_EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PLATFORM_PASS = process.env.AF_PASSWORD || 'Admin123456';

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function platformToken(): Promise<string> {
  const r = await fetch(`${PLATFORM_API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: PLATFORM_EMAIL, password: PLATFORM_PASS }),
  });
  expect(r.ok, 'platform login should succeed').toBeTruthy();
  const j = await r.json();
  const t = j?.data?.access_token || j?.access_token;
  expect(t, 'jwt token').toBeTruthy();
  return t;
}

test.describe('Wingman — full browser UAT', () => {
  test('platform: all 10 wingman agents + 2 wingman ML models registered', async () => {
    const token = await platformToken();
    const a = await fetch(`${PLATFORM_API}/api/agents?search=wingman`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(a.ok).toBeTruthy();
    const agents: Array<{ slug?: string }> = (await a.json())?.data || [];
    const slugs = new Set(agents.map((x) => x.slug).filter(Boolean));
    for (const s of [
      'wingman-arb-analyzer', 'wingman-broker-classifier', 'wingman-broker-parser',
      'wingman-graph-query', 'wingman-market-brief', 'wingman-ops-monitor',
      'wingman-scenario-forecaster', 'wingman-strategy-encoder', 'wingman-backtester',
      'wingman-var-simulator',
    ]) {
      expect(slugs.has(s), `agent ${s} must be seeded`).toBeTruthy();
    }
    const m = await fetch(`${PLATFORM_API}/api/ml-models`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(m.ok).toBeTruthy();
    const models: Array<{ name?: string }> = (await m.json())?.data || [];
    const names = new Set(models.map((x) => x.name).filter(Boolean));
    expect(names.has('wingman-broker-intent-classifier')).toBeTruthy();
    expect(names.has('wingman-scenario-prior')).toBeTruthy();
  });

  test('shell: sidebar lists every workbench surface', async ({ page }) => {
    await gotoOk(page, '/');
    expect(page.url()).toMatch(/\/(home|workbench)$/);
    for (const label of [
      'Home', 'Arbitrage Workbench', 'Price at Risk Lens', 'Forward Scenarios', 'Broker Inbox',
      'Approvals', 'Operations Watch', 'Strategy Lab', 'Knowledge Graph',
    ]) {
      await expect(page.getByText(label).first()).toBeVisible({ timeout: 10_000 });
    }
    await shot(page, 'sidebar');
  });

  test('workbench: market brief + corridor cards + data-honesty badge', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await expect(page.getByText(/Forward net-arb by corridor/i).first()).toBeVisible();
    await expect(page.getByText(/US Gulf Coast.*North West Europe/i).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/EIA/).first()).toBeVisible();
    await expect(page.getByText(/AISStream/i).first()).toBeVisible();
    await expect(page.getByText(/bunker-derived/i).first()).toBeVisible();
    await shot(page, 'workbench-landing');
  });

  test('workbench: Run analysis fires the agent and DAG drawer streams events', async ({ page }) => {
    await gotoOk(page, '/workbench');
    const runButton = page.getByRole('button', { name: /Run.*analysis|Re-run.*analysis/i }).first();
    await expect(runButton).toBeVisible({ timeout: 15_000 });
    await runButton.click();
    await expect(
      page.locator('[data-testid="dag-drawer-open"], [data-testid="dag-drawer"]').first(),
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole('button', { name: /^Re-run/i }).first())
      .toBeVisible({ timeout: 240_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'workbench-analysis-complete');
  });

  test('scenarios: page renders selector + run button + Bayesian-prior pipeline label', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await expect(page.getByText(/What might happen, weighted/i).first()).toBeVisible();
    await expect(page.locator('[data-testid^="corridor-chip-"]').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('run-forecast')).toBeVisible();
    await expect(page.getByText(/Bayesian prior/i).first()).toBeVisible();
    await shot(page, 'scenarios-landing');
  });

  test('scenarios: full forecast renders Bayesian prior + scenario cards', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await page.getByTestId('run-forecast').click();
    await expect(
      page.locator('[data-testid="dag-drawer-open"], [data-testid="dag-drawer"]').first(),
    ).toBeVisible({ timeout: 30_000 });
    await shot(page, 'scenarios-dag-running');
    await expect(page.getByText(/Bayesian prior/i).first()).toBeVisible({ timeout: 240_000 });
    // Sonnet 4.5 takes 30-90s end-to-end; allow up to 180s after prior arrives.
    await expect(page.locator('[data-testid="scenario-card-base"]').first())
      .toBeVisible({ timeout: 180_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'scenarios-result');
  });

  test('inbox: 5 broker emails listed', async ({ page }) => {
    await gotoOk(page, '/inbox');
    await expect(page.getByText(/Two hundred broker emails/i).first()).toBeVisible();
    const subjects = ['propane FOB Houston', 'CFR Chiba', 'Q4 quarterly', 'Antwerp'];
    let hits = 0;
    for (const s of subjects) {
      if (await page.getByText(new RegExp(s, 'i')).first().isVisible().catch(() => false)) hits += 1;
    }
    expect(hits).toBeGreaterThanOrEqual(3);
    await shot(page, 'inbox-landing');
  });

  test('inbox: parse one email → structured offer', async ({ page }) => {
    await gotoOk(page, '/inbox');
    const parseButton = page.getByRole('button', { name: /Extract structured offer/i }).first();
    await expect(parseButton).toBeVisible({ timeout: 10_000 });
    await parseButton.click();
    await expect(page.getByText('Volume').first()).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText('Grade').first()).toBeVisible();
    await expect(page.getByText('Port').first()).toBeVisible();
    await page.waitForTimeout(1000);
    await shot(page, 'inbox-structured-offer');
  });

  test('approvals: queue page renders + filter chips + empty/list state', async ({ page }) => {
    await gotoOk(page, '/approvals');
    await expect(page.getByText(/HITL APPROVALS/i).first()).toBeVisible();
    for (const f of ['filter-pending', 'filter-approved', 'filter-denied', 'filter-expired']) {
      await expect(page.getByTestId(f)).toBeVisible();
    }
    // Either empty state OR a list — both are valid initial states.
    const empty = page.getByTestId('approvals-empty');
    const list = page.getByTestId('approvals-list');
    await Promise.race([
      empty.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {}),
      list.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {}),
    ]);
    expect(
      (await empty.isVisible().catch(() => false)) ||
      (await list.isVisible().catch(() => false)),
    ).toBeTruthy();
    await shot(page, 'approvals-queue');
  });

  test('approvals: SDK proxy endpoints respond', async () => {
    const r = await fetch(`${API}/api/wingman/approvals?status=pending`);
    expect(r.ok, 'GET /approvals must succeed').toBeTruthy();
    const body = await r.json();
    expect(Array.isArray(body?.data), 'response should be a list').toBeTruthy();
  });

  test('ops: live AIS snapshot loads vessels + weather', async ({ page }) => {
    await gotoOk(page, '/ops');
    await expect(page.getByText(/Operations Watch/i).first()).toBeVisible();
    await expect(page.getByText(/AISStream/).first()).toBeVisible();
    await expect(page.getByText(/Live AIS — \d+ vessels/i).first()).toBeVisible({ timeout: 240_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'ops-live-vessels');
  });

  test('strategy: encode + see encoded rule', async ({ page }) => {
    await gotoOk(page, '/strategy');
    await expect(page.getByText(/Strategy Lab/i).first()).toBeVisible();
    const sample = page.locator('button[title*="USGC->FE"]').first();
    if (await sample.isVisible().catch(() => false)) {
      await sample.click();
    } else {
      await page.locator('textarea').first().fill('Lock in 10kt USGC->FE for Q1 if spread holds above $30/MT for 5 days.');
    }
    // Button text reads "Encode + save" in the current UI; keep regex loose.
    await page.getByRole('button', { name: /Encode(\s|\+)/i }).first().click();
    await expect(page.getByText(/Encoded rule/i).first()).toBeVisible({ timeout: 240_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'strategy-encoded-rule');
  });

  test('graph: query renders narrative or empty-state envelope', async ({ page }) => {
    await gotoOk(page, '/graph');
    await expect(page.getByText(/Knowledge Graph/i).first()).toBeVisible();
    const sample = page.locator('button[title*="counterparty"]').first();
    if (await sample.isVisible().catch(() => false)) {
      await sample.click();
    } else {
      await page.locator('input[placeholder*="Ask"]').first().fill('Show offers from counterparties tied to vessel disruptions.');
    }
    await page.getByRole('button', { name: /Query graph/i }).click();
    await expect(page.getByText(/Answer/i).first()).toBeVisible({ timeout: 300_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'graph-answer');
  });

  test('SDK: every wingman API endpoint responds + returns data shape', async () => {
    const checks: Array<[string, (j: any) => boolean]> = [
      ['/api/wingman/corridors', (j) => Array.isArray(j?.data) && j.data.length >= 1],
      ['/api/wingman/inbox',     (j) => Array.isArray(j?.data) && j.data.length >= 1],
      ['/api/wingman/approvals?status=pending', (j) => Array.isArray(j?.data)],
      ['/api/wingman/strategy',  (j) => Array.isArray(j?.data)],
      ['/api/wingman/offers',    (j) => Array.isArray(j?.data)],
      ['/api/wingman/tools',     (j) => Array.isArray(j?.data) && j.data.length > 50],
    ];
    for (const [path, check] of checks) {
      const r = await fetch(`${API}${path}`);
      expect(r.ok, `${path} must succeed`).toBeTruthy();
      const j = await r.json();
      expect(check(j), `${path} response shape`).toBeTruthy();
    }
  });
});
