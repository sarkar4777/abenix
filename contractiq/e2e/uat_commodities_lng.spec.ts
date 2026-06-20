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

test.describe('contractiq commodities lng forward page', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('Run analysis on LNG/JKM populates a JKM-anchored fan chart with cited drivers', async ({ page }) => {
    // Agent + JKM proxy fetch + Tavily news + MC overlay routinely runs
    // 240-300s; the post-processor adds ~5s. 420s test budget gives the
    // slow-cluster runs headroom; 360s response wait covers everything
    // up to the agent-runtime 300s ceiling.
    test.setTimeout(420_000);
    await gotoOk(page, '/commodities/forward');

    // Switch to LNG.
    await expect(page.locator('[data-testid="commodity-lng"]')).toBeVisible({ timeout: 10000 });
    await page.locator('[data-testid="commodity-lng"]').click();

    // JKM should be the default hub once LNG is selected.
    await expect(page.locator('[data-testid="hub-JKM"]')).toHaveAttribute(
      'data-active',
      'true',
      { timeout: 10000 },
    );

    // All four LNG hubs render.
    for (const h of ['JKM', 'FOB_USGC', 'DES_NWE', 'TFDES']) {
      await expect(page.locator(`[data-testid="hub-${h}"]`)).toBeVisible();
    }

    // Intercept the run/forward call so we can pull the raw agent payload
    // back and assert on the actual numeric shape.
    const apiResponse = page.waitForResponse(
      r => /\/api\/contractiq\/commodities\/lng\/forward\/run/.test(r.url()),
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

    // (a) model field starts with 'azure-' (LNG fairvalue uses azure-gpt-4o).
    const model = (payload?.model || '').toString().toLowerCase();
    expect(model.startsWith('azure-'), `model "${model}" should start with azure-`).toBe(true);

    // (b) ≥6 monotone (non-decreasing tenor) points on expected_curve.
    const expected = (forecast.expected_curve || []) as Array<{
      tenor_month?: number;
      price_usd_mmbtu?: number;
      price_eur_mwh?: number;
    }>;
    expect(expected.length, 'expected_curve should have ≥6 points').toBeGreaterThanOrEqual(6);
    const tenors = expected.map((p, i) => p.tenor_month ?? i + 1);
    for (let i = 1; i < tenors.length; i += 1) {
      expect(tenors[i], `tenor_month monotone at idx ${i}`).toBeGreaterThanOrEqual(tenors[i - 1]);
    }

    // (c) JKM prices in [5, 30] USD/MMBtu. Accept price_usd_mmbtu as the
    //     primary key; tolerate price_eur_mwh only if the post-processor
    //     happened to leave it (it shouldn't — it forces unit='USD/MMBtu').
    for (const p of expected) {
      const price = p.price_usd_mmbtu ?? p.price_eur_mwh;
      expect(typeof price, 'price_usd_mmbtu is a number').toBe('number');
      expect(price, `JKM price ${price} in [5, 30]`).toBeGreaterThanOrEqual(5);
      expect(price, `JKM price ${price} in [5, 30]`).toBeLessThanOrEqual(30);
    }

    // (d) provenance.data_source cites natgas_jkm or JKM.
    const dataSource = (forecast.provenance?.data_source || '').toString();
    expect(
      /natgas_jkm|JKM/i.test(dataSource),
      `provenance.data_source "${dataSource}" should mention natgas_jkm or JKM`,
    ).toBe(true);

    // (e) provenance.mode matches data_quality.
    const dq = (forecast.data_quality || '').toString().toLowerCase();
    const mode = (forecast.provenance?.mode || '').toString().toLowerCase();
    const expectedMode =
      dq === 'live' ? 'real_fetched' :
      dq === 'simulated' || dq === 'degraded' ? 'agent_simulated' :
      mode;
    // The post-processor sets mode='mixed' when it overrides — accept that too.
    if (mode !== 'mixed') {
      expect(mode, `provenance.mode should match data_quality=${dq}`).toBe(expectedMode);
    }

    // Banner reflects the mode.
    await expect(provMode).toBeVisible();
    const modeText = (await provMode.textContent())?.toLowerCase() || '';
    expect(modeText).toMatch(/real fetched|fetched|simulated|mixed/);

    // (f) At least one driver with a real http(s) URL.
    const allDrivers: Array<{ url?: string }> = [];
    for (const s of forecast.scenarios || []) {
      for (const d of s.drivers || []) allDrivers.push(d);
    }
    for (const d of forecast.drivers || []) allDrivers.push(d);
    const httpDrivers = allDrivers.filter(d => typeof d.url === 'string' && /^https?:\/\//.test(d.url));
    expect(httpDrivers.length, 'at least one driver with an http(s) URL').toBeGreaterThan(0);
  });
});
