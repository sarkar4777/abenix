import { test, expect, type Page } from '@playwright/test';

const BASE_WM = process.env.BASE_WM || 'http://localhost:3006';
// the Abenix web UI, 3100 since the local stack moved off 3000
const BASE_AF = process.env.BASE_AB || process.env.BASE || 'http://localhost:3100';
const API     = process.env.API  || 'http://localhost:8000';
const EMAIL   = process.env.AF_EMAIL    || 'admin@abenix.dev';
const PASS    = process.env.AF_PASSWORD || 'Admin123456';

async function gotoOk(page: Page, url: string, settle = 0) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  // the page keeps a live stream open, so it never goes fully idle
  await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => {});
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
    // the extractor makes ~25 live tool calls, a scan runs about three minutes
    test.setTimeout(420_000);
    await gotoOk(page, `${BASE_WM}/mispricing`, 3000);
    const chip = page.getByTestId('mispricing-corridor-USGC-NWE').first();
    if (await chip.isVisible().catch(() => false)) await chip.click();
    const run = page.getByTestId('run-mispricing-scan');
    await expect(run).toBeVisible();
    await run.click();
    // a cached card may show while the fresh scan runs, wait for the run to land
    await expect(page.getByText(/Scoring price at risk/i)).toBeHidden({ timeout: 330_000 });
    const scanError = page.getByTestId('mispricing-scan-error');
    if (await scanError.isVisible().catch(() => false)) {
      throw new Error(`scan failed: ${await scanError.innerText()}`);
    }
    // Trade card is rendered regardless of which insights tab is active.
    await expect(page.getByTestId('trade-card')).toBeVisible({ timeout: 10_000 });
    // The residual gauge now lives behind the "Residual z-score · feature vector" tab.
    await page.getByTestId('tab-residual').click();
    await expect(page.getByTestId('residual-gauge')).toBeVisible({ timeout: 10_000 });

    // The trader opens the gate, a desk approver signs it in Approvals in
    // another tab, and the trader's card follows the decision.
    // put away the live DAG drawer that floats over the card's right edge
    const drawer = page.getByTestId('dag-drawer');
    if (await drawer.isVisible().catch(() => false)) await drawer.getByTitle('Close').click();
    await page.getByTestId('open-trade-gate').click();
    const gate = page.getByTestId('trade-gate-opened');
    await expect(gate).toHaveAttribute('data-status', 'pending', { timeout: 20_000 });
    const label = (await gate.innerText()).match(/#([0-9a-f]{8})/);
    expect(label, 'gate shows its approval id').toBeTruthy();
    await expect(page.getByTestId('trade-gate-review')).toBeVisible();

    const desk = await page.context().newPage();
    await gotoOk(desk, `${BASE_WM}/approvals`, 1500);
    const card = desk.locator(`[data-testid^="approval-${label![1]}"]`).first();
    await expect(card, 'the trade gate is in the desk queue').toBeVisible({ timeout: 20_000 });
    await expect(card).toContainText('trade.execute');
    await card.locator('[data-testid^="approve-"]').click();
    await expect(card).toBeHidden({ timeout: 20_000 });
    await desk.getByTestId('filter-approved').click();
    await expect(desk.locator(`[data-testid^="approval-${label![1]}"]`).first()).toBeVisible({ timeout: 20_000 });
    await desk.close();

    await expect(gate).toHaveAttribute('data-status', 'approved', { timeout: 20_000 });
    await expect(gate).toContainText('approved by');
  });

  test('approvals queue only shows the gates Wingman opened', async ({ page }) => {
    const r = await fetch(`${BASE_WM.replace(':3006', ':8006')}/api/wingman/approvals?status=pending`);
    expect(r.ok).toBeTruthy();
    const items = (await r.json()).data as any[];
    for (const a of items) {
      expect(['broker.acknowledge', 'strategy.activate', 'trade.execute']).toContain(a.gate_kind);
    }
    await gotoOk(page, `${BASE_WM}/approvals`, 1500);
    await expect(page.getByTestId('approvals-count')).toHaveText(String(items.length));
  });

  test('two mispricing ML models show up in AgentForge /ml-models', async ({ page }) => {
    test.setTimeout(60_000);
    await afLogin(page);
    await gotoOk(page, `${BASE_AF}/ml-models`, 3500);
    // The page is paginated/virtualized; wingman models sit near the end
    // alphabetically. Scroll them into view before asserting visibility.
    const fair = page.getByText('wingman-mispricing-fairvalue').first();
    const anom = page.getByText('wingman-mispricing-anomaly').first();
    await fair.scrollIntoViewIfNeeded({ timeout: 20_000 });
    await expect(fair).toBeVisible({ timeout: 20_000 });
    await anom.scrollIntoViewIfNeeded({ timeout: 20_000 });
    await expect(anom).toBeVisible({ timeout: 20_000 });
  });

  test('the new agent shows up in AgentForge /agents', async ({ page }) => {
    test.setTimeout(60_000);
    await afLogin(page);
    // app agents are seeded as prebuilt, the list opens on My agents
    await gotoOk(page, `${BASE_AF}/agents?tab=prebuilt`, 3500);
    const search = page.getByPlaceholder(/search/i).first();
    if (await search.isVisible().catch(() => false)) {
      await search.fill('mispricing');
      await page.waitForTimeout(900);
    }
    const text = page.getByText(/Wingman Mispricing Extractor/i).first();
    await expect(text).toBeVisible({ timeout: 20_000 });
  });
});
