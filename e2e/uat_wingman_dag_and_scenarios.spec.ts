import { test, expect, type Page } from '@playwright/test';

/**
 * Wingman — DAG drawer behaviour on Operations Watch + Forward Scenarios
 * (the new GaussianNB-prior + LLM-posterior page).
 *
 *   BASE_WM=http://localhost:3006  WM_API=http://localhost:8006 \
 *   npx playwright test e2e/uat_wingman_dag_and_scenarios.spec.ts \
 *     --reporter=list --workers=1 --timeout=300000
 */

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const API = process.env.WM_API || 'http://localhost:8006';

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.serial('Wingman — DAG drawer + Forward Scenarios', () => {
  test('sidebar exposes the Forward Scenarios entry', async ({ page }) => {
    await gotoOk(page, '/');
    await expect(page.getByText('Forward Scenarios').first()).toBeVisible({ timeout: 10_000 });
  });

  test('Operations Watch: snapshot + DAG drawer renders nodes', async ({ page }) => {
    await gotoOk(page, '/ops');
    await expect(page.getByText('Operations Watch').first()).toBeVisible();
    // ops_snapshot is fired by the page on mount; the platform-side
    // wingman-ops-monitor agent runs (~30-60s) and the DAG drawer chip
    // appears as soon as the execution_id is known.
    await expect(
      page.locator('[data-testid="dag-drawer-open"], [data-testid="dag-drawer"]').first(),
    ).toBeVisible({ timeout: 180_000 });
    // Ensure the drawer panel itself can be opened and shows DAG nodes.
    const collapsed = page.locator('[data-testid="dag-drawer-open"]').first();
    if (await collapsed.isVisible().catch(() => false)) {
      await collapsed.click();
    }
    const drawer = page.locator('[data-testid="dag-drawer"]');
    await expect(drawer).toBeVisible({ timeout: 30_000 });
    // DAG nodes header lands when at least one row is composed (agent
    // node from snapshot or chips from expectedTools).
    await expect(drawer.getByText(/DAG nodes/i).first()).toBeVisible({ timeout: 60_000 });
    // Agent name renders in the snapshot header.
    await expect(drawer.getByText(/Wingman/i).first()).toBeVisible({ timeout: 60_000 });
  });

  test('Forward Scenarios: page renders the corridor selector and run button', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await expect(page.getByText('What might happen, weighted').first()).toBeVisible();
    // Corridor chips are rendered from /api/wingman/corridors.
    await expect(page.locator('[data-testid^="corridor-chip-"]').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('run-forecast')).toBeVisible();
    // Pipeline strip mentions the Bayesian prior so the trader sees the
    // method up front.
    await expect(page.getByText(/Bayesian prior/i).first()).toBeVisible();
  });

  test('Forward Scenarios: Run forecast fires the agent and DAG drawer streams', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    const runBtn = page.getByTestId('run-forecast');
    await expect(runBtn).toBeVisible({ timeout: 10_000 });
    await runBtn.click();
    // DAG drawer chip / panel shows up shortly after submit (the page
    // calls /scenarios/{id}/forecast which uses wait="submitted" so the
    // execution_id is back in well under 5s).
    await expect(
      page.locator('[data-testid="dag-drawer-open"], [data-testid="dag-drawer"]').first(),
    ).toBeVisible({ timeout: 30_000 });
    // Wait for the forecast to land — the Bayesian prior strip is the
    // first piece of structured output we render.
    await expect(page.getByText(/Bayesian prior/i).first()).toBeVisible({ timeout: 240_000 });
    // Probability-weighted expected-curve series renders in the chart.
    await expect(page.getByText(/Expected curve/i).first()).toBeVisible({ timeout: 30_000 });
    // At least the base scenario card lands.
    await expect(page.locator('[data-testid="scenario-card-base"]').first())
      .toBeVisible({ timeout: 30_000 });
  });

  test('platform: wingman-scenario-forecaster + wingman-scenario-prior both registered', async () => {
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

    const agentsRes = await fetch(`${PLATFORM_API}/api/agents?search=wingman`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(agentsRes.ok, 'agents catalog reachable').toBeTruthy();
    const agentsBody = await agentsRes.json();
    const agents: Array<{ slug?: string }> = agentsBody?.data || agentsBody?.items || agentsBody || [];
    const slugs = new Set(agents.map((a) => a.slug).filter(Boolean));
    expect(slugs.has('wingman-scenario-forecaster'), 'forecaster agent should be seeded').toBeTruthy();

    const modelsRes = await fetch(`${PLATFORM_API}/api/ml-models`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(modelsRes.ok, 'ml-models catalog reachable').toBeTruthy();
    const modelsBody = await modelsRes.json();
    const rows: Array<{ name?: string }> = modelsBody?.data || [];
    const names = new Set(rows.map((m) => m.name).filter(Boolean));
    expect(
      names.has('wingman-scenario-prior'),
      'GaussianNB prior must be visible in Abenix Models UI',
    ).toBeTruthy();
    expect(
      names.has('wingman-broker-intent-classifier'),
      'broker intent classifier must be visible too (after seed re-runs with the AIMODELS_DIRS fix)',
    ).toBeTruthy();
  });

  test('wingman API: scenario forecast endpoint accepts a corridor and returns execution_id', async () => {
    const corridors = await (await fetch(`${API}/api/wingman/corridors`)).json();
    const id = corridors?.data?.[0]?.id;
    expect(id, 'at least one corridor should exist').toBeTruthy();
    const r = await fetch(`${API}/api/wingman/scenarios/${id}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenor_months: 12 }),
    });
    expect(r.ok, 'forecast submit should accept').toBeTruthy();
    const j = await r.json();
    expect(j?.data?.execution_id, 'execution_id must be returned').toBeTruthy();
  });
});
