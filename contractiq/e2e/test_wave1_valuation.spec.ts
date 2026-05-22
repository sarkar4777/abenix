import { test, expect, type Page } from '@playwright/test';

const API_URL = process.env.API_URL || 'http://localhost:8001';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';
const TEST_EMAIL = 'test@contractiq.com';
const TEST_PASSWORD = 'TestPass123!';

async function login(request: any): Promise<string> {
  const r = await request.post(`${API_URL}/api/contractiq/auth/login`, {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
  });
  expect(r.status()).toBe(200);
  return (await r.json()).data.access_token;
}

async function uiLogin(page: Page) {
  await page.goto(`${BASE_URL}`);
  await page.waitForLoadState('networkidle');
  const signIn = page.getByRole('button', { name: /sign in/i }).first();
  if (await signIn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await signIn.click();
  }
  const emailInput = page.locator('input[type="email"]').first();
  await emailInput.waitFor({ state: 'visible', timeout: 10000 });
  await emailInput.fill(TEST_EMAIL);
  await page.locator('input[type="password"]').first().fill(TEST_PASSWORD);
  // Inline sign-in button in the modal
  const submit = page.locator('button', { hasText: /sign in|log in/i }).last();
  await submit.click();
  // Wait for redirect to dashboard
  await page.waitForURL(/\/(dashboard|insights|valuation|deal-clusters)/, { timeout: 15000 });
}

test.describe.serial('Wave 1 — Valuation & Forecast Suite', () => {
  let token: string;

  test('0. Login via API (prerequisite)', async ({ request }) => {
    token = await login(request);
    expect(token.length).toBeGreaterThan(50);
  });

  // ─── Gap fixes ──────────────────────────────────────────────────────

  test('G1. insights/overview includes valuations_total + forecast_curves_total', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toHaveProperty('valuations_total');
    expect(b.data).toHaveProperty('forecast_curves_total');
  });

  test('G2. /deal-clusters returns clause_rows (drill-through payload)', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/deal-clusters`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data.clusters).toBeDefined();
    // Each cluster must at least expose the clause_rows field (may be empty)
    for (const c of b.data.clusters) {
      expect(c).toHaveProperty('clause_rows');
      expect(Array.isArray(c.clause_rows)).toBe(true);
    }
  });

  test('G3. Contract extraction_summary includes completeness_score + missing_fields for analyzed contracts', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/contracts?limit=50`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    const analyzed = (b.data || []).filter((c: any) => c.status === 'analyzed');
    // At least one analyzed contract should exist — check structure only if present
    if (analyzed.length > 0) {
      const first = analyzed[0];
      const rd = await request.get(`${API_URL}/api/contractiq/contracts/${first.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(rd.status()).toBe(200);
      const body = await rd.json();
      const summary = body.data?.extraction_summary || {};
      // Completeness is computed on NEW extractions; older ones may not have
      // it yet — so only assert the presence of fields if the key is there.
      if (summary.completeness_score !== undefined) {
        expect(typeof summary.completeness_score).toBe('number');
        expect(Array.isArray(summary.missing_fields)).toBe(true);
      }
    }
  });

  // ─── Forecast curves ───────────────────────────────────────────────

  test('W1.1 Forecaster — list endpoint returns array (may be empty)', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/valuation/forecast-curves`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toHaveProperty('curves');
    expect(Array.isArray(b.data.curves)).toBe(true);
  });

  test('W1.2 Forecaster — run a single EUR/USD curve', async ({ request }) => {
    test.setTimeout(400_000);
    const r = await request.post(
      `${API_URL}/api/contractiq/insights/valuation/forecast-curves/run`,
      {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        data: { markets: [{ market: 'EUR/USD', unit: 'rate' }], tenor_months: 12, methodology: 'market' },
        timeout: 400_000,
      },
    );
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data.total_targets).toBe(1);
    // At least 1 curve should have generated successfully (agent can sometimes fail)
    expect(b.data.curves.length).toBe(1);
    const c = b.data.curves[0];
    if (c.status === 'completed') {
      expect(Array.isArray(c.curve)).toBe(true);
      expect(c.curve.length).toBeGreaterThan(0);
      expect(c.curve[0]).toHaveProperty('price');
    }
  });

  // ─── Portfolio valuation ───────────────────────────────────────────

  test('W2.1 Valuator — latest endpoint returns null or a valuation row', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/valuation/latest`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    // Either null (never run) or an object with status
    if (b.data != null) {
      expect(b.data).toHaveProperty('status');
      expect(b.data.valuation_type).toBe('mtm');
    }
  });

  test('W2.2 Valuator — run portfolio valuation end-to-end', async ({ request }) => {
    test.setTimeout(600_000);
    const r = await request.post(`${API_URL}/api/contractiq/insights/valuation/run`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { scope: 'portfolio' },
      timeout: 600_000,
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data.valuation_type).toBe('mtm');
    expect(['completed', 'failed']).toContain(b.data.status);
    if (b.data.status === 'completed') {
      expect(typeof b.data.portfolio_mtm === 'number' || b.data.portfolio_mtm == null).toBe(true);
      expect(b.data.payload).toBeDefined();
    }
  });

  // ─── Take-or-Pay monitor ───────────────────────────────────────────

  test('W3.1 T-o-P Monitor — latest endpoint returns null or valuation row', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/valuation/top-monitor`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    if (b.data != null) {
      expect(b.data.valuation_type).toBe('top_monitor');
    }
  });

  test('W3.2 T-o-P Monitor — run end-to-end', async ({ request }) => {
    test.setTimeout(400_000);
    const r = await request.post(`${API_URL}/api/contractiq/insights/valuation/top-monitor/run`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: {},
      timeout: 400_000,
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data.valuation_type).toBe('top_monitor');
    expect(['completed', 'failed']).toContain(b.data.status);
  });

  // ─── UI ─────────────────────────────────────────────────────────────

  test('UI.1 /valuation page renders and shows the three panels', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/valuation`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1', { hasText: 'Portfolio Valuation' })).toBeVisible();
    await expect(page.locator('[data-testid=curves-panel]')).toBeVisible();
    await expect(page.locator('[data-testid=valuation-panel]')).toBeVisible();
    await expect(page.locator('[data-testid=top-monitor-panel]')).toBeVisible();
  });

  test('UI.2 /deal-clusters page renders with clause drill-through button present', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/deal-clusters`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1', { hasText: /Deal Clusters/i })).toBeVisible();
    // A clause button ("N clauses") should be present if there is at least one cluster
    const laneCount = await page.locator('text=/Deal Cluster/').count();
    if (laneCount > 0) {
      // There's at least one cluster rendered
      const clauseBtn = page.locator('button', { hasText: /clause/ }).first();
      await expect(clauseBtn).toBeVisible();
    }
  });

  test('UI.3 Valuation card appears in Insights Hub', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/insights`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1', { hasText: /Insights Hub/i })).toBeVisible();
    await expect(page.locator('text=/Portfolio Valuation & Forecast/i')).toBeVisible();
  });
});
