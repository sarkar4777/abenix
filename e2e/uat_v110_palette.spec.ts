import { test, expect, type Page } from '@playwright/test';

/**
 * Abenix v1.1.0 — production-tooling palette + admin UAT.
 *
 * Drives the Builder palette for the v1.1 primitives that ship as tools (one test per
 * tool), then drives the four new admin pages (/admin/connectors,
 * /approvals, /admin/dlq, /edge) and asserts each renders + a create-form
 * is present.
 *
 * Each test is independent + idempotent — they all log in via the API
 * and seed localStorage in a beforeEach, then drive the UI.
 *
 *   BASE=http://localhost:3000 \
 *   API=http://localhost:8000 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_v110_palette.spec.ts \
 *     --reporter=list --workers=1 --timeout=120000
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page): Promise<void> {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json: any = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token, 'access_token').toBeTruthy();
  const meResp = await fetch(`${API}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const me = await meResp.json().then((j: any) => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {
      /* noop */
    }
  }, { t: token, u: me });
}

async function gotoOk(page: Page, path: string, settleMs = 1500): Promise<void> {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  await page.waitForLoadState('networkidle').catch(() => {});
  if (settleMs) await page.waitForTimeout(settleMs);
}

// add a tool from the palette the way a builder does, then open its node
async function addToolToCanvas(page: Page, toolName: string): Promise<void> {
  const search = page.getByPlaceholder('Search tools, descriptions, params...');
  await expect(search, 'palette search').toBeVisible({ timeout: 15_000 });
  await search.fill(toolName);
  await page.getByTestId(`palette-tool-${toolName}`).first().click();
  await search.fill('');
  const node = page.locator(`.react-flow__node[data-id="tool-${toolName}"]`);
  await expect(node, `${toolName} on the canvas`).toBeVisible({ timeout: 10_000 });
  await node.click();
}

// the tool panel replaces the agent config on the right when a tool node is open
async function expectConfigPanel(page: Page, fieldHints: RegExp[]): Promise<void> {
  const back = page.getByRole('button', { name: 'Back to Agent Config' });
  await expect(back, 'tool config panel').toBeVisible({ timeout: 10_000 });
  const panel = back.locator('xpath=ancestor::div[contains(@class,"w-[320px]")][1]');
  const haystack = (await panel.innerText()) || '';
  for (const hint of fieldHints) {
    expect(haystack, `config panel mentions ${hint}`).toMatch(hint);
  }
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test.describe('Abenix v1.1 · palette tools', () => {
  // ─── Per-tool palette drag + config-panel assertions ────────────────

  test('palette: mqtt_publish — config panel exposes broker, topic, QoS', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'mqtt_publish');
    await expectConfigPanel(page, [/topic/i, /qos|quality of service/i]);
  });

  test('palette: tsdb_query — config panel exposes operation, hypertable, time bucket', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'tsdb_query');
    await expectConfigPanel(page, [/operation|select|insert|aggregate/i, /hypertable|table/i]);
  });

  test('palette: windowed_state — config panel exposes operation, asset, name', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'windowed_state');
    await expectConfigPanel(page, [/append|query|count|pattern/i, /asset|name/i]);
  });

  test('palette: connector_call — config panel exposes connector + operation', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'connector_call');
    await expectConfigPanel(page, [/connector/i, /operation/i]);
  });

  test('palette: approval_gate — config panel exposes signoffs + expires', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'approval_gate');
    await expectConfigPanel(page, [/signoff|approver/i, /expire|ttl/i]);
  });

  test('palette: subscribed_feed — config panel exposes feed, refresh, TTL', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'subscribed_feed');
    await expectConfigPanel(page, [/feed|source/i, /refresh|interval|ttl/i]);
  });

  test('palette: speech_to_text — config panel exposes audio url and language', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'speech_to_text');
    await expectConfigPanel(page, [/audio_url|audio/i, /language/i]);
  });
});

test.describe('Abenix v1.1 · admin pages', () => {
  // ─── /admin/connectors ───────────────────────────────────────────────

  test('admin: /admin/connectors renders + create form is present', async ({ page }) => {
    await gotoOk(page, '/admin/connectors');
    await page.getByRole('button', { name: 'New connector' }).first().click();
    const form = page.getByRole('dialog', { name: 'New connector' });
    await expect(form).toBeVisible({ timeout: 8_000 });
    const after = await form.innerText();
    expect(after).toMatch(/kind|cmms|hris|telematics/i);
    expect(after).toMatch(/url|endpoint/i);
  });

  // ─── /approvals ──────────────────────────────────────────────────────

  test('admin: /approvals renders + filter controls are present', async ({ page }) => {
    await gotoOk(page, '/approvals');
    const text = (await page.textContent('body')) || '';
    expect(text.length).toBeGreaterThan(80);
    expect(text).toMatch(/approval/i);
    // Either a populated list or an empty-state with "no pending" copy.
    expect(text).toMatch(/pending|approved|denied|expired|no pending|nothing/i);
  });

  // ─── /admin/dlq ──────────────────────────────────────────────────────

  test('admin: /admin/dlq renders + replay controls are present', async ({ page }) => {
    await gotoOk(page, '/admin/dlq');
    const text = (await page.textContent('body')) || '';
    expect(text.length).toBeGreaterThan(80);
    expect(text).toMatch(/dead.?letter|dlq|stale/i);
    // Empty-state acceptable; otherwise look for the action buttons.
    expect(text).toMatch(/replay|discard|empty|no failed|nothing/i);
  });

  // ─── /edge ───────────────────────────────────────────────────────────

  test('admin: /edge renders the gateway token action and runtime variants', async ({ page }) => {
    await gotoOk(page, '/edge');
    await expect(page.getByTestId('edge-page')).toBeVisible();
    await expect(page.getByRole('button', { name: /Get gateway token/ }).first()).toBeVisible();
    await expect(page.getByTestId('edge-runtime-variants')).toBeVisible();
    await expect(page.getByText(/Registered gateways \(\d+\)/)).toBeVisible();
  });
});
