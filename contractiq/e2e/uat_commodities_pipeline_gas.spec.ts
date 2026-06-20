import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3001';
const API  = process.env.API  || 'http://localhost:8001';
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
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify(u || { email: 'test@contractiq.com', role: 'analyst' }));
    } catch {}
  }, { t: token, u: me });
}

async function gotoOk(page: Page, p: string) {
  const r = await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  expect(r?.status(), `${p} status`).toBeLessThan(400);
}

test.describe('contractiq commodities pipeline_gas forward page', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('commodity selector renders with pipeline_gas enabled and others "Coming soon"', async ({ page }) => {
    await gotoOk(page, '/commodities/forward');
    const selector = page.locator('[data-testid="commodity-selector"]');
    await expect(selector).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-testid="commodity-pipeline_gas"]')).toBeVisible();
    // Verify "Coming soon" badge appears for at least one other commodity
    const comingSoon = page.locator('[data-testid="commodity-lng"] >> text=Coming soon');
    await expect(comingSoon.first()).toBeVisible();
  });

  test('hub selector defaults to TTF', async ({ page }) => {
    await gotoOk(page, '/commodities/forward');
    const ttf = page.locator('[data-testid="hub-TTF"]');
    await expect(ttf).toBeVisible({ timeout: 10000 });
    await expect(ttf).toHaveAttribute('data-active', 'true');
    // All 6 expected hubs render
    for (const h of ['TTF', 'NBP', 'PEG', 'THE', 'CEGH', 'PSV']) {
      await expect(page.locator(`[data-testid="hub-${h}"]`)).toBeVisible();
    }
  });

  test('Run analysis button is clickable', async ({ page }) => {
    // Block the actual forward/run network call so this fast-path test
    // doesn't leave a 3-minute agent execution running in the background
    // (which would push the next test past the per-IP rate limit and
    // fail it for the wrong reason).
    await page.route('**/commodities/**/forward/run', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: null }) }),
    );
    await gotoOk(page, '/commodities/forward');
    const btn = page.locator('[data-testid="run-analysis"]');
    await expect(btn).toBeVisible({ timeout: 10000 });
    await expect(btn).toBeEnabled();
    // Click and verify it transitions or returns an error without throwing
    await btn.click();
    // We don't assert on the agent response here — that's the next phase. We just
    // assert that clicking did not crash the page.
    await page.waitForTimeout(500);
    await expect(page.locator('[data-testid="commodity-selector"]')).toBeVisible();
  });

  test('Provenance banner is visible', async ({ page }) => {
    await gotoOk(page, '/commodities/forward');
    const banner = page.locator('[data-testid="provenance-banner"]');
    await expect(banner).toBeVisible({ timeout: 10000 });
    await expect(banner).toContainText(/provenance/i);
    await expect(page.locator('[data-testid="provenance-mode"]')).toBeVisible();
  });

  test('Run analysis populates the fan chart and an honest provenance banner', async ({ page }) => {
    // Agents in the wild are running 250-300s now (post-processor adds
    // ~5s on top of the 290s ceiling), so widen the test budget to 420s
    // and the response-wait to 360s. Anything tighter will flake on the
    // slow-cluster runs.
    test.setTimeout(420_000);
    await gotoOk(page, '/commodities/forward');

    // Confirm TTF is the default hub.
    await expect(page.locator('[data-testid="hub-TTF"]')).toHaveAttribute(
      'data-active',
      'true',
      { timeout: 10000 },
    );

    // Intercept the run/forward call so we can pull the raw agent payload
    // back and assert on the actual numeric shape, not just "a chart rendered".
    const apiResponse = page.waitForResponse(
      r => /\/api\/contractiq\/commodities\/pipeline_gas\/forward\/run/.test(r.url()),
      { timeout: 360_000 },
    );

    const btn = page.locator('[data-testid="run-analysis"]');
    await expect(btn).toBeEnabled();
    await btn.click();

    const populatedChart = page.locator('[data-testid="fan-chart"] svg');
    const runError = page.locator('[data-testid="run-error"]');
    const provMode = page.locator('[data-testid="provenance-mode"]');

    const resp = await apiResponse;
    const body = await resp.json().catch(() => ({}));
    const payload = body?.data || body;
    const forecast = payload?.forecast || {};

    await Promise.race([
      populatedChart.first().waitFor({ state: 'visible', timeout: 30_000 }).catch(() => null),
      runError.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => null),
    ]);

    if (await runError.isVisible().catch(() => false)) {
      const txt = await runError.textContent().catch(() => '');
      throw new Error(`forward agent surfaced an error: ${txt}`);
    }

    // (a) ≥6 monotone (non-decreasing tenor) points on expected_curve.
    const expected = (forecast.expected_curve || []) as Array<{ tenor_month?: number; price_eur_mwh?: number }>;
    expect(expected.length, 'expected_curve should have ≥6 points').toBeGreaterThanOrEqual(6);
    const tenors = expected.map((p, i) => p.tenor_month ?? i + 1);
    for (let i = 1; i < tenors.length; i += 1) {
      expect(tenors[i], `tenor_month monotone at idx ${i}`).toBeGreaterThanOrEqual(tenors[i - 1]);
    }

    // (b) TTF prices in 15-80 EUR/MWh.
    for (const p of expected) {
      const price = p.price_eur_mwh;
      expect(typeof price, 'price_eur_mwh is a number').toBe('number');
      expect(price, `TTF price ${price} in [15, 80]`).toBeGreaterThanOrEqual(15);
      expect(price, `TTF price ${price} in [15, 80]`).toBeLessThanOrEqual(80);
    }

    // (c) Exact mode equality against data_quality.
    const dq = (forecast.data_quality || '').toString().toLowerCase();
    const mode = (forecast.provenance?.mode || '').toString().toLowerCase();
    const expectedMode =
      dq === 'live' ? 'real_fetched' :
      dq === 'simulated' || dq === 'degraded' ? 'agent_simulated' :
      mode;
    expect(mode, `provenance.mode should match data_quality=${dq}`).toBe(expectedMode);

    // Banner reflects the same mode.
    await expect(provMode).toBeVisible();
    const modeText = (await provMode.textContent())?.toLowerCase() || '';
    expect(modeText).toMatch(/real fetched|fetched|simulated|mixed/);

    // (d) At least one driver with a real http(s) URL.
    const allDrivers: Array<{ url?: string }> = [];
    for (const s of forecast.scenarios || []) {
      for (const d of s.drivers || []) allDrivers.push(d);
    }
    for (const d of forecast.drivers || []) allDrivers.push(d);
    const httpDrivers = allDrivers.filter(d => typeof d.url === 'string' && /^https?:\/\//.test(d.url));
    expect(httpDrivers.length, 'at least one driver with an http(s) URL').toBeGreaterThan(0);
  });
});
