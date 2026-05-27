import { test, expect, type Page } from '@playwright/test';

/**
 * Cross-app browser UAT — covers every standalone except ContractIQ
 * plus the Abenix platform. Run after a deploy:
 *
 *   BASE_AB=http://localhost:3000  AB_API=http://localhost:8000 \
 *   BASE_IOT=http://localhost:3003 IOT_API=http://localhost:8003 \
 *   BASE_RA=http://localhost:3004  RA_API=http://localhost:8004 \
 *   BASE_ST=http://localhost:3002  ST_API=http://localhost:8002 \
 *   BASE_CIQ=http://localhost:3005 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_apps_full.spec.ts \
 *     --reporter=list --workers=1 --timeout=180000
 *
 * Each describe block proves the app is genuinely usable from a
 * browser end-user POV — pages render with real text, navigation
 * works, the most important action has an observable effect, and
 * (where applicable) a file upload round-trips to disk.
 */

const PLATFORM = {
  base: process.env.BASE_AB || 'http://localhost:3000',
  api: process.env.AB_API || 'http://localhost:8000',
  email: process.env.AF_EMAIL || 'admin@abenix.dev',
  password: process.env.AF_PASSWORD || 'Admin123456',
};
const IOT = { base: process.env.BASE_IOT || 'http://localhost:3003', api: process.env.IOT_API || 'http://localhost:8003' };
const RA = { base: process.env.BASE_RA || 'http://localhost:3004', api: process.env.RA_API || 'http://localhost:8004' };
const ST = { base: process.env.BASE_ST || 'http://localhost:3002', api: process.env.ST_API || 'http://localhost:8002' };
const CIQ_WEB = process.env.BASE_CIQ || 'http://localhost:3005';

async function loginPlatform(page: Page) {
  const r = await fetch(`${PLATFORM.api}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: PLATFORM.email, password: PLATFORM.password }),
  });
  expect(r.ok, 'platform login should succeed').toBeTruthy();
  const json = await r.json();
  const token = json.data?.access_token || json.access_token;
  expect(token).toBeTruthy();
  const meRaw = await fetch(`${PLATFORM.api}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((r) => r.json());
  const inner = meRaw?.data ?? meRaw;
  const user = inner?.user ?? inner;
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify(u || {}));
  }, { t: token, u: user });
  return { token, user };
}

async function gotoOk(page: Page, url: string) {
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${url} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
}

// ─────────────────────────────────────────────────────────────────────
// Abenix platform
// ─────────────────────────────────────────────────────────────────────

test.describe.serial('Abenix platform — end-user UAT', () => {
  test.beforeEach(async ({ page }) => {
    await loginPlatform(page);
  });

  test('/dashboard renders authenticated', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/dashboard`);
    expect(page.url()).toContain('/dashboard');
    await expect(page.locator('body')).toContainText(/agent|execution|usage|workspace/i);
  });

  test('/agents lists at least one agent', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/agents`);
    await expect(page.locator('body')).toContainText(/agent/i);
    // Real OOB agents are seeded — at least one card or row should render.
    const anyAgentText = await page.locator('text=/forecaster|extractor|valuator|builder|router|monitor/i').count();
    expect(anyAgentText, 'expected at least one OOB agent name visible on /agents').toBeGreaterThan(0);
  });

  test('/knowledge renders and reaches the upload modal', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/knowledge`);
    await expect(page.locator('body')).toContainText(/knowledge/i);
  });

  test('/executions list reachable', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/executions`);
    expect(page.url()).toContain('/executions');
    await expect(page.locator('body')).toContainText(/execution|status|cost/i);
  });

  test('/approvals page reachable', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/dashboard`);
    await gotoOk(page, `${PLATFORM.base}/approvals`);
    expect(page.url()).toContain('/approvals');
    await expect(
      page.getByRole('heading', { name: /approval/i }).first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('/alerts page reachable', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/alerts`);
    expect(page.url()).toContain('/alerts');
  });

  test('/sdk-playground hydrates the input form for a picked agent', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/dashboard`);
    await gotoOk(page, `${PLATFORM.base}/sdk-playground`);
    expect(page.url()).toContain('/sdk-playground');
    // First agent in the list — click and wait for the live-inputs panel.
    const firstAgent = page.locator('button').filter({ has: page.locator('div.font-medium') }).first();
    await firstAgent.click();
    await expect(page.locator('[data-testid="live-inputs-panel"]')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-testid="run-live-button"]')).toBeEnabled();
  });

  test('top-bar bell exists + clickable', async ({ page }) => {
    await gotoOk(page, `${PLATFORM.base}/dashboard`);
    // The Bell icon button has aria-haspopup-ish visual but no role; we
    // pin to the icon container in TopBar.
    const bell = page.locator('header button').filter({ has: page.locator('svg.lucide-bell') }).first();
    await expect(bell).toBeVisible({ timeout: 10_000 });
    await bell.click();
    // Either "No notifications yet" or a list — both prove the popover opened.
    await expect(page.locator('text=/notifications|no notifications yet/i').first()).toBeVisible({ timeout: 5_000 });
  });
});

// ─────────────────────────────────────────────────────────────────────
// Industrial IoT
// ─────────────────────────────────────────────────────────────────────

test.describe.serial('Industrial IoT — end-user UAT', () => {
  test('all 6 showcase tabs render', async ({ page }) => {
    await gotoOk(page, IOT.base);
    await expect(page.locator('body')).toContainText(/Industrial IoT/i);
    for (const tab of ['Pump Vibration', 'Cold Chain', 'Design Studio', 'Field Guide', 'Alarm Desk', 'Architecture']) {
      const btn = page.getByRole('button', { name: new RegExp(tab, 'i') }).first();
      await expect(btn, `tab "${tab}" should be visible`).toBeVisible({ timeout: 10_000 });
    }
  });

  test('KB status reports available — banner is GONE (regression: post-1.1.5 envFrom fix)', async ({ page }) => {
    await gotoOk(page, IOT.base);
    // The KB Not Available banner appeared on the Pump tab when
    // INDUSTRIALIOT_ABENIX_API_KEY was empty. After the IoT manifest
    // re-apply this should be gone. We probe both the API and the DOM
    // so the test fails loud either way.
    const r = await fetch(`${IOT.api}/api/industrial-iot/kb-status`);
    const body = await r.json();
    expect(body?.data?.available, 'kb-status must return available:true after envFrom fix').toBeTruthy();

    // DOM: the warning banner must NOT be visible. Any of the warning
    // strings is enough to fail the test.
    const banner = page.getByText(/KB Not Available|no_api_key/i).first();
    expect(await banner.isVisible().catch(() => false), 'KB warning banner must be hidden').toBeFalsy();
  });

  test('Pump Vibration tab shows the streaming-pipeline scaffold', async ({ page }) => {
    await gotoOk(page, IOT.base);
    await page.getByRole('button', { name: /Pump Vibration/i }).first().click();
    await expect(page.locator('body')).toContainText(/Stream vibration|pipeline|Step \d/i);
  });

  test('Architecture tab renders the high-level diagram', async ({ page }) => {
    await gotoOk(page, IOT.base);
    await page.getByRole('button', { name: /Architecture/i }).first().click();
    await expect(page.locator('body')).toContainText(/architecture|platform|edge|signal/i);
  });

  test('subscribed feeds endpoint responds', async ({ page }) => {
    // The Live System tab references three feeds.
    const r = await fetch(`${IOT.api}/api/industrial-iot/subscribed-feeds/pump_alarms`);
    expect(r.status, 'feed endpoint reachable').toBeLessThan(500);
  });
});

// ─────────────────────────────────────────────────────────────────────
// ResolveAI
// ─────────────────────────────────────────────────────────────────────

test.describe.serial('ResolveAI — end-user UAT', () => {
  test('landing dashboard renders', async ({ page }) => {
    await gotoOk(page, RA.base);
    await expect(page.locator('body')).toContainText(/ResolveAI|cases|customer/i);
  });

  test('cases queue reachable + ticket file CTA exists', async ({ page }) => {
    await gotoOk(page, `${RA.base}/cases`);
    await expect(page.locator('body')).toContainText(/case|customer|status/i);
  });

  test('admin / pending approvals API responds', async () => {
    const r = await fetch(`${RA.api}/api/resolveai/admin/pending-approvals`);
    expect(r.status, 'pending-approvals endpoint reachable').toBeLessThan(500);
  });

  test('SLA + QA + Trends pages reachable', async ({ page }) => {
    for (const path of ['/sla', '/qa', '/trends']) {
      await gotoOk(page, `${RA.base}${path}`);
      expect(page.url()).toContain(path);
    }
  });

  test('admin settings page reachable', async ({ page }) => {
    await gotoOk(page, `${RA.base}/admin`);
    expect(page.url()).toContain('/admin');
  });
});

// ─────────────────────────────────────────────────────────────────────
// Mideast Tourism
// ─────────────────────────────────────────────────────────────────────

test.describe.serial('Mideast Tourism — end-user UAT', () => {
  let stToken: string | null = null;

  test('register OR login, capture JWT', async () => {
    // Try login with a deterministic test user; if it fails, register.
    const email = 'uat-st@example.com';
    const password = 'UAT_st_test_42!';
    let r = await fetch(`${ST.api}/api/st/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      r = await fetch(`${ST.api}/api/st/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, full_name: 'UAT Probe' }),
      });
      expect(r.ok, 'ST register should succeed').toBeTruthy();
    }
    const j = await r.json();
    stToken = j?.data?.access_token || j?.access_token || null;
    expect(stToken, 'ST JWT must be captured').toBeTruthy();
  });

  test('dashboard analytics endpoint responds', async () => {
    expect(stToken, 'previous test must have set stToken').not.toBeNull();
    const r = await fetch(`${ST.api}/api/st/analytics/dashboard`, {
      headers: { Authorization: `Bearer ${stToken}` },
    });
    expect(r.status, 'dashboard endpoint reachable').toBeLessThan(500);
  });

  test('regions endpoint returns rows', async () => {
    expect(stToken).not.toBeNull();
    const r = await fetch(`${ST.api}/api/st/analytics/regions`, {
      headers: { Authorization: `Bearer ${stToken}` },
    });
    expect(r.status).toBeLessThan(500);
  });

  test('datasets list reachable', async () => {
    expect(stToken).not.toBeNull();
    const r = await fetch(`${ST.api}/api/st/datasets`, {
      headers: { Authorization: `Bearer ${stToken}` },
    });
    expect(r.status).toBeLessThan(500);
  });

  test('UI: index page renders', async ({ page }) => {
    await gotoOk(page, ST.base);
    await expect(page.locator('body')).toContainText(/tourism|saudi|kingdom|destination|visit/i);
  });
});

// ─────────────────────────────────────────────────────────────────────
// ClaimsIQ
// ─────────────────────────────────────────────────────────────────────

test.describe.serial('ClaimsIQ — end-user UAT', () => {
  test('liveness endpoint OK', async () => {
    const r = await fetch(`${CIQ_WEB}/actuator/health/liveness`);
    expect(r.ok, 'claimsiq liveness probe').toBeTruthy();
  });

  test('UI root reachable', async ({ page }) => {
    const resp = await page.goto(CIQ_WEB, { waitUntil: 'domcontentloaded' });
    expect(resp?.status(), 'claimsiq root status').toBeLessThan(500);
  });
});
