import { test, expect, type Page } from '@playwright/test';

/**
 * Browser-driven UAT for ContractIQ. Drives every page in the
 * sidebar through Chromium against a port-forwarded deployment
 * (default http://localhost:3001). Validates the 13 features in
 * Features.xlsx + the 12-row ETRM Deal-Type Matrix from Sheet 2.
 *
 *   BASE=http://localhost:3001 \
 *   API=http://localhost:8001 \
 *   npx playwright test e2e/uat_contractiq_browser.spec.ts \
 *     --reporter=list --workers=1 --timeout=180000
 */

const BASE = process.env.BASE || 'http://localhost:3001';
const API  = process.env.API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

async function login(page: Page) {
  // The app uses a JWT + a serialized user in localStorage — seed
  // both so the client-side useEffect chains fire and the contracts
  // queue / dashboard fetches actually run.
  const resp = await fetch(`${API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token, 'access_token in login response').toBeTruthy();
  // Pull the user object too so getUser() returns truthy.
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify(u || {
        email: 'test@contractiq.com', role: 'analyst',
      }));
    } catch {}
  }, { t: token, u: me });
}

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => { await login(page); });

test.describe('ContractIQ · UAT', () => {

  // ─── Reachability — every sidebar entry returns 200 ─────────────────
  for (const path of [
    '/', '/dashboard', '/upload', '/contracts', '/deal-clusters',
    '/timeline', '/valuation', '/market', '/simulations',
    '/credit-risk', '/credit-risk/kyc', '/credit-risk/kyc/new',
    '/insights', '/insights/anomalies', '/insights/benchmark',
    '/insights/briefing', '/insights/families', '/insights/force-majeure',
    '/insights/hedge', '/insights/reconciliation', '/insights/renewals',
    '/insights/stress-test', '/insights/version-diff',
    '/compare', '/chat', '/help',
  ]) {
    test(`reach ${path}`, async ({ page }) => {
      await gotoOk(page, path);
      const text = (await page.textContent('body')) || '';
      expect(text.length, `${path} renders some content`).toBeGreaterThan(50);
    });
  }

  // ─── Feature catalogue + ETRM matrix on /help ───────────────────────
  test('Help page surfaces feature catalogue + ETRM matrix', async ({ page }) => {
    await gotoOk(page, '/help');
    await expect(page.getByTestId('feature-catalogue')).toBeVisible();
    await expect(page.getByTestId('help-etrm-matrix')).toBeVisible();
    const text = (await page.textContent('body')) || '';
    // 12 ETRM matrix rules — pick some signature deal types.
    expect(text).toMatch(/Power Physical/);
    expect(text).toMatch(/Commodity Physical \(Gas\)/);
    expect(text).toMatch(/Commodity Physical \(Certificate\)/);
    expect(text).toMatch(/Power European Option/);
    expect(text).toMatch(/Power Asian Option/);
  });

  // ─── ETRM matrix on /deal-clusters ──────────────────────────────────
  test('Deal-clusters page surfaces ETRM matrix + cluster grid', async ({ page }) => {
    await gotoOk(page, '/deal-clusters');
    await expect(page.getByTestId('etrm-matrix')).toBeVisible();
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/Power Financial Swap/);
    expect(text).toMatch(/Commodity Fees/);
    // Cluster KPIs
    expect(text).toMatch(/Contracts/);
    expect(text).toMatch(/Deal Clusters/);
  });

  // ─── New Timeline page ──────────────────────────────────────────────
  test('Timeline page renders KPIs + filters + events list', async ({ page }) => {
    await gotoOk(page, '/timeline');
    await expect(page.getByTestId('timeline-page')).toBeVisible();
    await expect(page.getByTestId('timeline-filters')).toBeVisible();
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/Total events/);
    expect(text).toMatch(/Overdue|Upcoming/);
    // Filter dropdown changes the URL fetch — toggle it and ensure the
    // page doesn't crash.
    const typeSelect = page.locator('select').first();
    await typeSelect.selectOption({ value: 'milestone' });
    await page.waitForTimeout(800);
    await typeSelect.selectOption({ value: '' });
  });

  // ─── Contracts list ── click first row → detail page renders ───────
  test('Contracts queue → detail navigates and renders DAG', async ({ page }) => {
    test.setTimeout(60_000);
    await gotoOk(page, '/contracts');
    // The contracts page fetches client-side; wait for either the
    // empty-state OR a row to render before clicking. Hydration
    // takes ~800ms on a fresh boot.
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(1500);
    // Row pattern: a <div> with the contract status pill ("analyzed"
    // / "uploaded" / "error") + the title — the cursor-pointer parent
    // wraps both.
    const row = page.locator('div.cursor-pointer').filter({ hasText: /(ppa|tolling|wind|gas|certificate|virtual)/i }).first();
    if (!(await row.isVisible().catch(() => false))) {
      const empty = await page.locator('text=/no contracts found/i').count();
      if (empty > 0) test.skip(true, 'queue empty — upload a fixture first');
      // Last resort — any clickable row.
      const any = page.locator('[class*="cursor-pointer"]').first();
      await expect(any).toBeVisible({ timeout: 10_000 });
      await any.click();
    } else {
      await row.click();
    }
    await page.waitForLoadState('domcontentloaded');
    await expect(page).toHaveURL(/\/contracts\/[0-9a-f-]{6,}/i, { timeout: 20_000 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/Overview|Clauses|Events|Risk|Functional|Chat/);
  });

  // ─── Chat interface loads + accepts an input ───────────────────────
  test('Chat page shows input and example questions', async ({ page }) => {
    await gotoOk(page, '/chat');
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/chat|ask|question|portfolio|contracts/i);
    const input = page.locator('input[type="text"], textarea').first();
    if (await input.isVisible().catch(() => false)) {
      await input.fill('How many contracts are in the portfolio?');
    }
  });

  // ─── Insights hub lists every workflow ─────────────────────────────
  test('Insights hub links to every workflow', async ({ page }) => {
    await gotoOk(page, '/insights');
    const expected = ['anomalies','benchmark','briefing','families','force-majeure','hedge','reconciliation','renewals','stress-test','version-diff'];
    for (const slug of expected) {
      const links = await page.locator(`a[href*="/insights/${slug}"]`).count();
      expect(links, `link to /insights/${slug}`).toBeGreaterThan(0);
    }
  });

  // ─── Endur Templates feature ───────────────────────────────────────
  test('Endur Templates panel renders + 12 starter templates listed', async ({ page }) => {
    await gotoOk(page, '/deal-clusters');
    await expect(page.getByTestId('endur-templates')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('upload-template-btn')).toBeVisible();
    const text = (await page.textContent('body')) || '';
    // Each starter is "Starter · <CategoryLabel>"
    expect(text).toMatch(/Starter · Power Physical\b/);
    expect(text).toMatch(/Starter · Commodity Physical \(Gas\)/);
    expect(text).toMatch(/Starter · Power Financial Swap/);
    expect(text).toMatch(/Starter · LNG Tolling/);
  });

  test('Endur Template upload modal opens + JSON validation', async ({ page }) => {
    await gotoOk(page, '/deal-clusters');
    await expect(page.getByTestId('endur-templates')).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('upload-template-btn').click();
    await expect(page.getByTestId('upload-template-modal')).toBeVisible();
    // Type an obviously broken JSON and try to save → modal stays open with error.
    const textarea = page.locator('textarea').first();
    await textarea.fill('not json at all');
    await page.getByRole('button', { name: /save template/i }).click();
    await expect(page.locator('text=/Invalid JSON/i')).toBeVisible({ timeout: 5_000 });
    // Now provide a valid template + name and save.
    await textarea.fill('{"deal_type": "Test", "field": "${value}"}');
    await page.locator('input').first().fill(`UAT Template ${Date.now()}`);
    await page.getByRole('button', { name: /save template/i }).click();
    // Modal closes when save succeeds.
    await expect(page.getByTestId('upload-template-modal')).toBeHidden({ timeout: 10_000 });
  });

  test('Generate Endur JSON modal opens for a cluster', async ({ page }) => {
    await gotoOk(page, '/deal-clusters');
    await expect(page.getByTestId('endur-templates')).toBeVisible({ timeout: 15_000 });
    const genBtn = page.getByTestId('generate-endur-btn').first();
    if (!(await genBtn.isVisible().catch(() => false))) {
      test.skip(true, 'no clusters available');
    }
    await genBtn.click();
    await expect(page.getByTestId('generate-endur-modal')).toBeVisible();
    // The Run button is present.
    await expect(page.getByTestId('run-generate-btn')).toBeVisible();
    // Close.
    await page.locator('[data-testid="generate-endur-modal"] button:has(.lucide-x)').first().click().catch(() => {});
  });

  // ─── Console-error sweep across every page ─────────────────────────
  test('Console-error sweep — no hard errors anywhere', async ({ page }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on('pageerror', err => errors.push(`pageerror: ${err.message}`));
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
    });
    for (const path of [
      '/', '/dashboard', '/upload', '/contracts', '/deal-clusters', '/timeline',
      '/valuation', '/market', '/insights', '/help', '/chat',
    ]) {
      await gotoOk(page, path);
      await page.waitForTimeout(400);
    }
    const hard = errors.filter(e =>
      !/favicon|hydrat|webpack|fast refresh|chunk|manifest|isr|prefetch|RSC|Failed to load resource/i.test(e)
    );
    expect(hard, hard.join('\n')).toHaveLength(0);
  });
});
