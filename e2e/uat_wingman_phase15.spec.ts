import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.WINGMAN_BASE || 'http://localhost:3001';
const ABENIX_BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function loginViaApi(page: Page) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed: HTTP ${r.status}`);
  const j = await r.json();
  const token = j.data?.access_token || j.access_token;
  await page.addInitScript((t: string) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
    } catch {}
  }, token);
}

test.describe.serial('Wingman Phase 1-5 + Home', () => {
  test('home page renders with hero, pillars, ML cards, toolbox', async ({ page }) => {
    await page.goto(`${BASE}/home`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Energy arbitrage you can actually trust')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('link', { name: /Open Arb Workbench/i })).toBeVisible();
    // Pillar cards (in main, not sidebar)
    await expect(page.getByRole('main').getByText('Arbitrage Workbench').first()).toBeVisible();
    await expect(page.getByRole('main').getByText('Mispricing Lens').first()).toBeVisible();
    // ML model + toolbox content
    await expect(page.getByText('wingman-mispricing-fairvalue').first()).toBeVisible();
    await expect(page.getByText('vessel_specs').first()).toBeVisible();
    await expect(page.getByText('freight_baltic_blpg').first()).toBeVisible();
    await expect(page.getByText('freight_worldscale').first()).toBeVisible();
    await expect(page.getByText('port_constraints').first()).toBeVisible();
    await expect(page.getByText('refined_products_forwards').first()).toBeVisible();
  });

  test('sidebar Home link is visible and root path redirects there', async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(/\/home$/, { timeout: 10_000 });
    await expect(page.getByRole('link', { name: /^Home$/ })).toBeVisible();
  });

  test('mispricing explainer mentions the 15-feature v1.2 model', async ({ page }) => {
    await page.goto(`${BASE}/mispricing`, { waitUntil: 'domcontentloaded' });
    const toggle = page.getByTestId('explainer-toggle-mispricing');
    await expect(toggle).toBeVisible({ timeout: 10_000 });
    // ensure panel is open (re-click only if currently hidden)
    if ((await page.getByTestId('explainer-body-mispricing').count()) === 0) {
      await toggle.click();
    }
    const body = page.getByTestId('explainer-body-mispricing');
    await expect(body).toBeVisible({ timeout: 10_000 });
    await expect(body.getByText(/wingman-mispricing-fairvalue v1\.2\.0/i)).toBeVisible();
    await expect(body.getByText(/15 features/i)).toBeVisible();
  });

  test('AgentForge tools API exposes all 5 new tools', async ({ page }) => {
    await loginViaApi(page);
    await page.goto(`${ABENIX_BASE}/builder`, { waitUntil: 'domcontentloaded' });
    const r = await fetch(`${API}/api/tools`, {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` },
    });
    expect(r.ok).toBeTruthy();
    const body = await r.json();
    const tools = body.data?.tools || body.tools || body.data || body;
    const ids = (Array.isArray(tools) ? tools : []).map((t: any) => t.id);
    for (const id of [
      'vessel_specs', 'refined_products_forwards',
      'freight_worldscale', 'freight_baltic_blpg', 'port_constraints',
    ]) {
      expect(ids).toContain(id);
    }
  });
});
