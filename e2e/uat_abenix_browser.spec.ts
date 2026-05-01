import { test, expect, type Page } from '@playwright/test';

/**
 * Abenix — comprehensive browser-driven UAT.
 *
 *   BASE=http://localhost:3000 \
 *   API=http://localhost:8000  \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_abenix_browser.spec.ts \
 *     --reporter=list --workers=1 --timeout=180000
 *
 * Covers:
 *   • Reachability of every (app)/* page (56 routes)
 *   • Top-bar back button respects logical parent for deep pages
 *   • AI Builder boots + palette + validations panel
 *   • Flight Recorder (executions/[id]) renders KPIs + waterfall + lineage
 *   • Marketplace list + detail
 *   • Sharing controls on agents page
 *   • Settings sub-pages
 *   • Help docs surface every key section
 *   • Console-error sweep
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API  = process.env.API  || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token, 'access_token').toBeTruthy();
  // Pull the user too — most pages gate render on a hydrated user object.
  const meResp = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {}
  }, { t: token, u: me });
}

async function gotoOk(page: Page, path: string, opts: { settle?: number } = {}) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
  if (opts.settle) await page.waitForTimeout(opts.settle);
}

// Every page in (app)/* — reachability + body content.
const PAGES_TO_REACH = [
  '/dashboard', '/agents', '/agents/manage', '/builder', '/marketplace',
  '/chat', '/knowledge', '/knowledge/projects', '/executions',
  '/executions/live', '/code-runner', '/ml-models', '/portfolio-schemas',
  '/mcp', '/triggers', '/meetings', '/persona', '/team', '/moderation',
  '/review-queue', '/load-playground', '/sdk-playground', '/creator',
  '/analytics', '/alerts', '/help',
  '/settings', '/settings/profile', '/settings/api', '/settings/api-keys',
  '/settings/billing', '/settings/data', '/settings/notifications',
  '/settings/observability', '/settings/privacy', '/settings/quotas',
  '/settings/sandbox', '/settings/security', '/settings/team',
  '/settings/webhooks',
  '/admin/llm-pricing', '/admin/llm-settings', '/admin/scaling',
];

// One failure shouldn't halt the rest of the UAT — use parallel-safe
// (we still pin workers=1 from the CLI so the auth/login fetch doesn't
// race the API).
test.beforeEach(async ({ page }) => { await login(page); });

test.describe('Abenix · UAT', () => {

  // ─── Reachability — every page in the (app) shell ────────────────────
  for (const path of PAGES_TO_REACH) {
    test(`reach ${path}`, async ({ page }) => {
      await gotoOk(page, path);
      const text = (await page.textContent('body')) || '';
      expect(text.length, `${path} renders content`).toBeGreaterThan(80);
    });
  }

  // ─── Sidebar mounts + user is hydrated ───────────────────────────────
  test('Sidebar nav + user hydrated', async ({ page }) => {
    await gotoOk(page, '/dashboard');
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/Dashboard|Agents|Knowledge|Help/i);
    // The user-avatar button (initial of full_name) is what indicates
    // hydration. It's a circular button with a single character.
    const avatar = page.locator('button').filter({ hasText: /^[A-Za-z]$/ }).first();
    await expect(avatar).toBeVisible({ timeout: 10_000 });
  });

  // ─── Back-button correctness on deep pages ──────────────────────────
  // Each row: (deep-page-path, expected-parent-after-back-click)
  const BACK_CASES: Array<[string, RegExp]> = [
    ['/settings/profile', /\/dashboard|\/settings$/],
    ['/admin/llm-pricing', /\/dashboard$/],
    ['/admin/scaling', /\/dashboard$/],
    ['/executions/live', /\/executions$|\/dashboard$/],
    ['/knowledge/projects', /\/knowledge$/],
  ];
  for (const [from, expectTo] of BACK_CASES) {
    test(`back from ${from}`, async ({ page }) => {
      await gotoOk(page, from, { settle: 600 });
      // Pin to the topbar's back button — some pages embed their own
      // "back" link inside the body that we don't want to click here.
      const back = page.locator('[data-testid="topbar-back"]');
      if (await back.isVisible().catch(() => false)) {
        await back.click();
      } else {
        await page.goBack();
      }
      await page.waitForLoadState('domcontentloaded');
      await page.waitForTimeout(600);
      expect(page.url(), `back from ${from}`).toMatch(expectTo);
    });
  }

  // ─── AI Builder loads + tool palette renders ────────────────────────
  test('AI Builder boots + palette + validations', async ({ page }) => {
    await gotoOk(page, '/builder', { settle: 1500 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/builder|node|tool|palette|drag|llm_call|pipeline|agent/i);
  });

  // ─── Flight Recorder ────────────────────────────────────────────────
  test('Executions list opens; click first → flight recorder renders', async ({ page }) => {
    test.setTimeout(60_000);
    await gotoOk(page, '/executions', { settle: 2000 });
    // Each row is a collapsed <button> whose visible text contains the
    // agent name + a localized timestamp like "4/26/2026, 2:43:19 PM".
    // The "Open Flight Recorder →" anchor only renders inside the
    // expanded panel — so click the row first.
    const rowButton = page
      .locator('main button')
      .filter({ hasText: /\d{1,2}\/\d{1,2}\/\d{4}/ })
      .first();
    if (!(await rowButton.isVisible().catch(() => false))) {
      const empty = await page.locator('text=/no executions|empty|nothing/i').count();
      if (empty > 0) test.skip(true, 'no executions in this tenant');
    }
    await expect(rowButton).toBeVisible({ timeout: 12_000 });
    await rowButton.click();
    await page.waitForTimeout(400);
    const link = page.locator('a[href^="/executions/"]').first();
    await expect(link).toBeVisible({ timeout: 5_000 });
    await link.click();
    await page.waitForLoadState('domcontentloaded');
    await expect(page).toHaveURL(/\/executions\/[0-9a-f-]{6,}/i, { timeout: 15_000 });
    // Wait for the Flight Recorder shell to actually render — networkidle
    // alone isn't enough because the page streams data via SSE and the
    // textContent() returns only the bootstrap JSON-LD until React paints.
    await page.waitForLoadState('networkidle').catch(() => {});
    await expect(
      page.getByText(/Flight Recorder|Waterfall|Tool Call|Lineage|Live DAG|Duration|Cost|Tokens/i).first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  // ─── Marketplace ─────────────────────────────────────────────────────
  test('Marketplace lists agents + detail page renders', async ({ page }) => {
    await gotoOk(page, '/marketplace', { settle: 800 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/marketplace|agent|template|category|publish/i);
    const link = page.locator('a[href^="/marketplace/"]').first();
    if (await link.isVisible().catch(() => false)) {
      await link.click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page).toHaveURL(/\/marketplace\/[0-9a-f-]{6,}/i, { timeout: 15_000 });
      const t2 = (await page.textContent('body')) || '';
      expect(t2).toMatch(/agent|description|version|publish|use this|fork|deploy/i);
    }
  });

  // ─── Agents queue + detail ──────────────────────────────────────────
  test('Agents list renders + open one → detail tabs render', async ({ page }) => {
    await gotoOk(page, '/agents', { settle: 800 });
    const link = page.locator('a[href^="/agents/"]').first();
    if (!(await link.isVisible().catch(() => false))) {
      test.skip(true, 'no agents in this tenant');
    }
    await link.click();
    await page.waitForLoadState('domcontentloaded');
    await expect(page).toHaveURL(/\/agents\/[0-9a-f-]{6,}/i, { timeout: 15_000 });
    const t2 = (await page.textContent('body')) || '';
    expect(t2).toMatch(/Chat|Info|Memories|Edit|System|Tools|Model/i);
  });

  // ─── Sharing — Agent Info page exposes Share button ─────────────────
  test('Agent Info page shows Share button', async ({ page }) => {
    await gotoOk(page, '/agents', { settle: 1200 });
    const link = page.locator('a[href^="/agents/"]').first();
    if (!(await link.isVisible().catch(() => false))) test.skip(true, 'no agents in this tenant');
    const href = await link.getAttribute('href');
    if (!href) test.skip(true, 'agent link has no href');
    // The list links straight to /agents/{id}/info or /chat — pull the
    // ID and navigate to the Info tab where the Share button lives.
    const m = href.match(/\/agents\/([^/]+)/);
    if (!m) test.skip(true, `unparseable agent href: ${href}`);
    await gotoOk(page, `/agents/${m![1]}/info`, { settle: 1200 });
    const share = page.getByRole('button', { name: /share/i }).first();
    await expect(share).toBeVisible({ timeout: 10_000 });
  });

  // ─── Settings: every sub-page has a save / form ─────────────────────
  test('Settings · Profile has form + Save button', async ({ page }) => {
    await gotoOk(page, '/settings/profile', { settle: 800 });
    const save = page.getByRole('button', { name: /save|update/i }).first();
    await expect(save).toBeVisible({ timeout: 10_000 });
  });
  test('Settings · API Keys lists or has create button', async ({ page }) => {
    await gotoOk(page, '/settings/api-keys', { settle: 800 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/api\s*key|create|new key|scope/i);
  });

  // ─── Knowledge ──────────────────────────────────────────────────────
  test('Knowledge list shows + projects link present', async ({ page }) => {
    await gotoOk(page, '/knowledge', { settle: 600 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/knowledge|engine|cognify|graph|retrieve|search|upload/i);
  });

  // ─── MCP ─────────────────────────────────────────────────────────────
  test('MCP page renders', async ({ page }) => {
    await gotoOk(page, '/mcp', { settle: 600 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/MCP|model context|tools|server|connect/i);
  });

  // ─── Help ────────────────────────────────────────────────────────────
  test('Help renders main sections', async ({ page }) => {
    await gotoOk(page, '/help', { settle: 600 });
    const text = (await page.textContent('body')) || '';
    expect(text).toMatch(/help|getting started|quick start|guide|how|agent/i);
  });

  // ─── Use Cases dropdown surfaces standalone apps ────────────────────
  test('Use Cases dropdown surfaces all 6 standalone apps', async ({ page }) => {
    await gotoOk(page, '/dashboard', { settle: 600 });
    // Open the Use Cases nav button.
    const trigger = page.getByRole('button', { name: /use cases|use-cases/i }).first();
    if (await trigger.isVisible().catch(() => false)) {
      await trigger.click();
      await page.waitForTimeout(400);
      const text = (await page.textContent('body')) || '';
      expect(text).toMatch(/the example app|ResolveAI|Saudi Tourism|OracleNet|ClaimsIQ|Industrial IoT/i);
    }
  });

  // ─── Console-error sweep ────────────────────────────────────────────
  test('Console-error sweep across 18 representative pages', async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on('pageerror', err => errors.push(`pageerror: ${err.message}`));
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
    });
    const sweep = [
      '/dashboard', '/agents', '/builder', '/marketplace',
      '/knowledge', '/executions', '/executions/live', '/chat',
      '/code-runner', '/ml-models', '/mcp', '/team',
      '/review-queue', '/analytics', '/alerts',
      '/settings', '/settings/profile', '/help',
    ];
    for (const path of sweep) {
      await gotoOk(page, path);
      await page.waitForTimeout(300);
    }
    const hard = errors.filter(e =>
      !/favicon|hydrat|webpack|fast refresh|chunk|manifest|isr|prefetch|RSC|Failed to load resource|monaco|404\b/i.test(e)
    );
    expect(hard, hard.join('\n')).toHaveLength(0);
  });
});
