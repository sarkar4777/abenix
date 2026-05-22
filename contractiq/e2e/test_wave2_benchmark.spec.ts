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
  const submit = page.locator('button', { hasText: /sign in|log in/i }).last();
  await submit.click();
  await page.waitForURL(/\/(dashboard|insights|valuation|deal-clusters)/, { timeout: 15000 });
}

test.describe.serial('Wave 2 — Clause Benchmarking', () => {
  let token: string;
  let contractId: string;
  let clauseId: string;

  test('0. Login via API', async ({ request }) => {
    token = await login(request);
    expect(token.length).toBeGreaterThan(50);
  });

  test('A. Locate an analyzed contract with at least one clause', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/contracts?limit=20`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    const analyzed = (b.data || []).filter((c: any) => c.status === 'analyzed');
    expect(analyzed.length).toBeGreaterThan(0);
    contractId = analyzed[0].id;

    const rd = await request.get(`${API_URL}/api/contractiq/contracts/${contractId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const bd = await rd.json();
    const clauses = bd.data?.clauses || [];
    expect(clauses.length).toBeGreaterThan(0);
    // Prefer a termination/force_majeure clause if present; else first
    const preferred = clauses.find((c: any) => ['termination', 'force_majeure', 'pricing'].includes(c.clause_type));
    clauseId = (preferred || clauses[0]).id;
  });

  test('B. benchmarks list endpoint returns {total, benchmarks[]}', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/benchmarks`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toHaveProperty('total');
    expect(Array.isArray(b.data.benchmarks)).toBe(true);
  });

  test('C. overview includes benchmarks_total', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toHaveProperty('benchmarks_total');
  });

  test('D. Run benchmark on a real clause (runs Gemini 2.5 Pro end-to-end)', async ({ request }) => {
    test.setTimeout(600_000);
    const r = await request.post(`${API_URL}/api/contractiq/insights/benchmarks/run`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { clause_id: clauseId, jurisdiction: 'UK' },
      timeout: 500_000,
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toBeTruthy();
    expect(b.data.clause_id).toBe(clauseId);
    expect(['completed', 'failed']).toContain(b.data.status);
    if (b.data.status === 'completed') {
      // At minimum, the agent should produce one of these useful fields
      const hasUseful = !!(
        b.data.stance ||
        b.data.market_standard_summary ||
        (b.data.peer_comparisons && b.data.peer_comparisons.length) ||
        (b.data.recommendations && b.data.recommendations.length) ||
        b.data.narrative
      );
      expect(hasUseful).toBe(true);
    }
  });

  test('E. GET benchmarks/clause/{id} returns the latest benchmark for the clause', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/insights/benchmarks/clause/${clauseId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(200);
    const b = await r.json();
    expect(b.data).toBeTruthy();
    expect(b.data.clause_id).toBe(clauseId);
  });

  test('F. UI: /insights/benchmark page renders with contract picker + KPI strip', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/insights/benchmark`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1', { hasText: /Clause Benchmarking/i })).toBeVisible();
    await expect(page.locator('[data-testid=benchmark-page]')).toBeVisible();
    await expect(page.locator('[data-testid=contract-picker]')).toBeVisible();
    // At least one clause card should be visible (portfolio has analyzed contracts)
    const cards = page.locator('[data-testid=clause-card]');
    await expect(cards.first()).toBeVisible({ timeout: 10_000 });
  });

  test('G. UI: Insights Hub shows the Clause Benchmarking card', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/insights`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=/Clause Benchmarking/i')).toBeVisible();
  });

  test('H. UI: Help page lists contractiq-clause-benchmarker', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/help`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1', { hasText: /Agent Atlas/i })).toBeVisible();
    // Expand the Insights Hub Agents section so the benchmarker card is rendered
    await page.getByRole('button', { name: /Insights Hub Agents/i }).click();
    await expect(page.locator('text=contractiq-clause-benchmarker').first()).toBeVisible({ timeout: 5000 });
  });

  test('I. UI: Open an existing benchmark in the modal (from step D)', async ({ page }) => {
    await uiLogin(page);
    await page.goto(`${BASE_URL}/insights/benchmark`);
    await page.waitForLoadState('networkidle');

    // Wait for clause cards to load, then find the card whose clause_id matches
    const cards = page.locator('[data-testid=clause-card]');
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);

    // Click the first "View details" button (our step D should have produced
    // at least one benchmark). If none visible, re-benchmark the first card.
    const viewDetails = page.locator('[data-testid=view-benchmark]').first();
    if (await viewDetails.isVisible({ timeout: 2000 }).catch(() => false)) {
      await viewDetails.click();
    } else {
      // No benchmark yet — click the first Run Benchmark
      await page.locator('[data-testid=run-benchmark]').first().click();
      // Wait for modal to appear (agent run inside UI)
      await page.waitForSelector('[data-testid=benchmark-modal]', { timeout: 500_000 });
    }

    await expect(page.locator('[data-testid=benchmark-modal]')).toBeVisible({ timeout: 10_000 });
    // Modal header text
    await expect(page.locator('[data-testid=benchmark-modal]').locator('text=/Clause Benchmark/i')).toBeVisible();
  });
});
