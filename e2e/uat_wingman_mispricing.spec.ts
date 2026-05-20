import { test, expect, type Page } from '@playwright/test';

const BASE_WM = process.env.BASE_WM || 'http://localhost:3006';
const BASE_AF = process.env.BASE || 'http://localhost:3000';
const API     = process.env.API  || 'http://localhost:8000';
const EMAIL   = process.env.AF_EMAIL    || 'admin@abenix.dev';
const PASS    = process.env.AF_PASSWORD || 'Admin123456';

async function gotoOk(page: Page, url: string, settle = 0) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  if (settle) await page.waitForTimeout(settle);
}

async function afLogin(page: Page) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASS }),
  });
  if (!r.ok) throw new Error(`AgentForge login failed: ${r.status}`);
  const json = await r.json();
  const token = json.data?.access_token || json.access_token;
  const me = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
    .then((rr) => rr.json()).then((j) => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {}
  }, { t: token, u: me });
}

test.describe.serial('Wingman Mispricing Lens — end-to-end', () => {
  test('mispricing page renders explainer + sidebar entry', async ({ page }) => {
    await gotoOk(page, `${BASE_WM}/mispricing`, 3000);
    // After the rename, "Price at Risk Lens" appears in sidebar + hero eyebrow
    // + pipeline strip — assert the page-title h1 is the canonical one.
    await expect(page.getByRole('heading', { name: /propane price at risk/i })).toBeVisible();
    await expect(page.getByText(/PRICE AT RISK LENS/i).first()).toBeVisible();
    await expect(page.getByTestId('model-explainer')).toBeVisible();
    await expect(page.getByText(/Bayesian Ridge — fair-value regression/i)).toBeVisible();
    await expect(page.getByText(/Isolation Forest — regime-break detector/i)).toBeVisible();
  });

  test('mispricing — pick corridor, click Score, see verdict + thesis + trade card', async ({ page }) => {
    test.setTimeout(180_000);
    await gotoOk(page, `${BASE_WM}/mispricing`, 3000);
    const chip = page.getByTestId('mispricing-corridor-USGC-NWE').first();
    if (await chip.isVisible().catch(() => false)) await chip.click();
    const run = page.getByTestId('run-mispricing-scan');
    await expect(run).toBeVisible();
    await run.click();
    // Trade card is rendered regardless of which insights tab is active.
    await expect(page.getByTestId('trade-card')).toBeVisible({ timeout: 150_000 });
    // The residual gauge now lives behind the "Residual z-score · feature vector" tab.
    await page.getByTestId('tab-residual').click();
    await expect(page.getByTestId('residual-gauge')).toBeVisible({ timeout: 10_000 });
  });

  test('two mispricing ML models show up in AgentForge /ml-models', async ({ page }) => {
    test.setTimeout(60_000);
    await afLogin(page);
    await gotoOk(page, `${BASE_AF}/ml-models`, 3500);
    const fair = page.getByText('wingman-mispricing-fairvalue').first();
    const anom = page.getByText('wingman-mispricing-anomaly').first();
    await expect(fair).toBeVisible({ timeout: 20_000 });
    await expect(anom).toBeVisible({ timeout: 20_000 });
  });

  test('the new agent shows up in AgentForge /agents', async ({ page }) => {
    test.setTimeout(60_000);
    await afLogin(page);
    await gotoOk(page, `${BASE_AF}/agents`, 3500);
    const text = page.getByText(/Wingman Mispricing Extractor/i).first();
    await expect(text).toBeVisible({ timeout: 20_000 });
  });
});
