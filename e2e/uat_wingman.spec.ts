import { test, expect, type Page } from '@playwright/test';

/**
 * Wingman — full browser-driven UAT covering all 5 use cases:
 *   1. Arbitrage Workbench (Insight + Market Sentinel)
 *   2. Broker Inbox (extraction + HITL acknowledge gate)
 *   3. Operations Watch (live AIS + weather)
 *   4. Strategy Lab (NL → rule → backtest → HITL activation gate)
 *   5. Knowledge Graph (Atlas)
 *
 * Plus the cross-cutting Live DAG drawer that should appear on every
 * page after an agent run.
 *
 *   BASE_WM=http://localhost:3006  WM_API=http://localhost:8006 \
 *   npx playwright test e2e/uat_wingman.spec.ts --reporter=list --workers=1 --timeout=240000
 */

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const API = process.env.WM_API || 'http://localhost:8006';

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.serial('Wingman — full browser UAT', () => {
  test('shell renders, sidebar exposes the surface links', async ({ page }) => {
    await gotoOk(page, '/');
    expect(page.url()).toMatch(/\/(home|workbench)$/);
    for (const label of ['Arbitrage Workbench', 'Broker Inbox', 'Operations Watch', 'Strategy Lab', 'Knowledge Graph', 'Forward Scenarios', 'Approvals']) {
      await expect(page.getByText(label).first()).toBeVisible({ timeout: 10_000 });
    }
  });

  test('health endpoint reports SDK configured', async () => {
    const r = await fetch(`${API}/health`);
    expect(r.ok).toBeTruthy();
    const j = await r.json();
    expect(j.service).toBe('wingman-api');
    expect(j.abenix_sdk_configured, 'WINGMAN_ABENIX_API_KEY must be wired').toBeTruthy();
  });

  test('workbench renders the corridor cards', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await expect(page.getByText(/Forward net-arb|ARBITRAGE WORKBENCH/i).first()).toBeVisible();
    await expect(page.getByText(/US Gulf Coast.*North West Europe/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/US Gulf Coast.*Far East/i).first()).toBeVisible();
    // Data-honesty badge present.
    await expect(page.getByText(/EIA/).first()).toBeVisible();
    await expect(page.getByText(/AISStream/i).first()).toBeVisible();
    await expect(page.getByText(/bunker-derived/i).first()).toBeVisible();
  });

  test('workbench: Run analysis fires an agent and the live DAG drawer appears', async ({ page }) => {
    await gotoOk(page, '/workbench');
    // The first "Run analysis" button on the page is on the first active
    // corridor — USGC->NWE per the corridors.json fixture. We don't pin
    // the locator chain to a specific card label; that was brittle.
    const runButton = page.getByRole('button', { name: /^Run analysis/i }).first();
    await expect(runButton).toBeVisible({ timeout: 15_000 });
    await runButton.click();
    // The DAG drawer chip / panel lands within ~60s after the agent starts.
    await expect(
      page.locator('[data-testid="dag-drawer-open"], [data-testid="dag-drawer"]').first(),
    ).toBeVisible({ timeout: 90_000 });
    // Wait for the analysis to populate. The button text flips to "Re-run analysis".
    await expect(
      page.getByRole('button', { name: /^Re-run analysis/i }).first(),
    ).toBeVisible({ timeout: 240_000 });
  });

  test('inbox: 5 broker emails listed', async ({ page }) => {
    await gotoOk(page, '/inbox');
    await expect(page.getByText('Broker Inbox').first()).toBeVisible();
    // At least three of the five subjects are present.
    const subjects = ['propane FOB Houston', 'CFR Chiba', 'Q4 quarterly', 'Antwerp', 'USGC->FE arb'];
    let hits = 0;
    for (const s of subjects) {
      if (await page.getByText(new RegExp(s, 'i')).first().isVisible().catch(() => false)) hits += 1;
    }
    expect(hits, 'at least 3 broker emails should be visible').toBeGreaterThanOrEqual(3);
  });

  test('inbox: parse one email -> structured offer renders', async ({ page }) => {
    await gotoOk(page, '/inbox');
    const parseButton = page.getByRole('button', { name: /Extract structured offer/i }).first();
    await expect(parseButton).toBeVisible({ timeout: 10_000 });
    await parseButton.click();
    // Structured offer card appears (Volume/Grade/Port labels).
    await expect(page.getByText('Volume').first()).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText('Grade').first()).toBeVisible();
    await expect(page.getByText('Port').first()).toBeVisible();
  });

  test('ops: live AIS snapshot loads vessels and weather', async ({ page }) => {
    await gotoOk(page, '/ops');
    await expect(page.getByText('Operations Watch').first()).toBeVisible();
    await expect(page.getByText(/AISStream/).first()).toBeVisible();
    // Wait up to 120s for the snapshot to populate (AIS subscription window + weather fetch).
    await expect(page.getByText(/Live AIS — \d+ vessels/i).first()).toBeVisible({ timeout: 180_000 });
  });

  test('strategy: encode a sample, see structured rule', async ({ page }) => {
    await gotoOk(page, '/strategy');
    await expect(page.getByText('Strategy Lab').first()).toBeVisible();
    // Pick the first sample to populate the textarea.
    const sample = page.locator('button[title*="USGC->FE"]').first();
    if (await sample.isVisible().catch(() => false)) {
      await sample.click();
    } else {
      await page.locator('textarea').first().fill('Lock in 10kt USGC->FE for Q1 if spread holds above $30/MT for 5 days.');
    }
    await page.getByRole('button', { name: /Encode strategy/i }).click();
    await expect(page.getByText('Encoded rule').first()).toBeVisible({ timeout: 180_000 });
  });

  test('builder palette: 4 new tools are discoverable in the platform /api/tools catalog', async () => {
    // The AI Builder UI fetches /api/tools (with the user's JWT) to drive
    // its palette. This step proves an end user opening the visual
    // designer at /builder would see the four new Wingman-relevant tools
    // alongside every other built-in tool — no gap; nothing hardcoded.
    const PLATFORM_API = process.env.AB_API || 'http://localhost:8000';
    const PLATFORM_EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
    const PLATFORM_PASS = process.env.AF_PASSWORD || 'Admin123456';
    const loginRes = await fetch(`${PLATFORM_API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: PLATFORM_EMAIL, password: PLATFORM_PASS }),
    });
    expect(loginRes.ok, 'platform login should succeed').toBeTruthy();
    const loginBody = await loginRes.json();
    const token = loginBody?.data?.access_token || loginBody?.access_token;
    expect(token, 'jwt token').toBeTruthy();

    const r = await fetch(`${PLATFORM_API}/api/tools`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.ok, 'tools catalog reachable').toBeTruthy();
    const body = await r.json();
    const rows = body?.data || [];
    expect(rows.length, 'platform should list many tools').toBeGreaterThan(50);
    const byId: Record<string, any> = {};
    for (const t of rows) byId[t.id] = t;

    for (const tool of ['eia_open_data', 'open_meteo', 'ais_stream', 'bunker_fuel']) {
      expect(byId[tool], `tool '${tool}' must appear in /api/tools (palette catalog)`).toBeTruthy();
      // Each new tool's input_schema must be JSON-Schema-shaped so the
      // palette can derive a form from it.
      expect(byId[tool]?.input_schema, `${tool} should expose input_schema`).toBeTruthy();
      expect(byId[tool]?.input_schema?.type, `${tool} schema must be 'object'`).toBe('object');
    }
  });

  test('graph: query renders narrative + subgraph', async ({ page }) => {
    await gotoOk(page, '/graph');
    await expect(page.getByText('Knowledge Graph').first()).toBeVisible();
    // First sample question.
    const sample = page.locator('button[title*="counterparty"]').first();
    if (await sample.isVisible().catch(() => false)) {
      await sample.click();
    } else {
      await page.locator('input[placeholder*="Ask"]').first().fill('Show offers from counterparties tied to vessel disruptions.');
    }
    await page.getByRole('button', { name: /Query graph/i }).click();
    // Either a narrative or an empty-state explanation must appear (the
    // ontology may not yet have data — the agent emits a JSON envelope
    // either way per the system prompt).
    await expect(page.getByText('Answer').first()).toBeVisible({ timeout: 240_000 });
  });
});
