import { test, expect, type Page } from '@playwright/test';

// UX BLOCKER B3 — collapse /commodities IA duplication. The four legacy
// hubs (/gas /power /environmental /lng) now redirect into the
// selector-driven /commodities/forward page so we keep one mental model
// for "commodity". This spec exercises the redirect on every legacy
// path and asserts the rich modules (KPIs, contracts, glossary) render
// on the canonical page.

const BASE = process.env.CIQ_BASE || 'http://localhost:3001';
const API  = process.env.CIQ_API  || 'http://localhost:8001';
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

test.describe('commodities IA collapse — legacy hubs redirect into /forward', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  const legacyRedirects: { from: string; commodity: string }[] = [
    { from: '/commodities/gas',           commodity: 'pipeline_gas' },
    { from: '/commodities/power',         commodity: 'power' },
    { from: '/commodities/lng',           commodity: 'lng' },
    { from: '/commodities/environmental', commodity: 'carbon' },
  ];

  for (const { from, commodity } of legacyRedirects) {
    test(`${from} redirects to /commodities/forward?commodity=${commodity}`, async ({ page }) => {
      await page.goto(`${BASE}${from}`, { waitUntil: 'domcontentloaded' });
      // Next.js redirect() lands the user on the canonical URL.
      await expect.poll(
        () => new URL(page.url()).pathname + new URL(page.url()).search,
        { timeout: 10_000 },
      ).toBe(`/commodities/forward?commodity=${commodity}`);
      // Selector ports the commodity over.
      await expect(page.locator('[data-testid="commodity-selector"]')).toBeVisible();
    });
  }

  test('canonical /commodities/forward renders KPIs, contracts, glossary', async ({ page }) => {
    await page.goto(`${BASE}/commodities/forward?commodity=pipeline_gas`, { waitUntil: 'domcontentloaded' });

    // KPI strip — four cards ported from the retired gas hub.
    const kpis = page.locator('[data-testid="commodity-kpis"]');
    await expect(kpis).toBeVisible({ timeout: 10_000 });
    await expect(kpis.locator('[data-testid^="kpi-card-"]')).toHaveCount(4);

    // Active contracts panel — table renders or empty-state message.
    const contracts = page.locator('[data-testid="active-contracts"]');
    await expect(contracts).toBeVisible();
    // One of: loading row, populated rows, or empty-state copy.
    const anyContractState = page.locator(
      '[data-testid="active-contracts-empty"], [data-testid="active-contracts-loading"], [data-testid^="contract-row-"]',
    );
    await expect(anyContractState.first()).toBeVisible({ timeout: 10_000 });

    // Glossary section with at least one defined term.
    const glossary = page.locator('[data-testid="commodity-glossary"]');
    await expect(glossary).toBeVisible();
    await expect(glossary.locator('dt')).toHaveCount(3); // gas glossary has 3 entries
  });
});
