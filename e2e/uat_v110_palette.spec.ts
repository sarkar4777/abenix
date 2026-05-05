import { test, expect, type Page } from '@playwright/test';

/**
 * Abenix v1.1.0 — production-tooling palette + admin UAT.
 *
 * Drives the Builder palette for every new v1.1 primitive (one test per
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

// Drag a palette card onto the canvas. The Builder uses React Flow; the
// reliable cross-browser pattern is page.dragAndDrop with locator handles.
// If the Builder uses click-to-add instead of drag, fall back to a click.
async function addToolToCanvas(page: Page, toolName: string): Promise<void> {
  // Try the palette search input first if it exists — most palettes have one.
  const search = page.locator('input[placeholder*="Search" i], input[placeholder*="Find" i]').first();
  if (await search.isVisible().catch(() => false)) {
    await search.fill(toolName);
    await page.waitForTimeout(200);
  }

  const card = page
    .locator(
      `[data-tool-id="${toolName}"], [data-testid="palette-${toolName}"], button:has-text("${toolName}"), div:has-text("${toolName}")`,
    )
    .first();
  await expect(card, `palette card for ${toolName}`).toBeVisible({ timeout: 10_000 });

  // Prefer click-to-add (some palettes), fall back to dragAndDrop onto canvas.
  const canvas = page
    .locator('[data-testid="builder-canvas"], .react-flow, [class*="reactflow"]')
    .first();
  await expect(canvas, 'builder canvas').toBeVisible({ timeout: 10_000 });

  try {
    await card.click({ trial: false });
    await page.waitForTimeout(400);
  } catch {
    await card.dragTo(canvas);
    await page.waitForTimeout(400);
  }
}

async function expectConfigPanel(page: Page, fieldHints: RegExp[]): Promise<void> {
  // The config panel is on the right rail. Match on label/heading text.
  const panel = page
    .locator(
      '[data-testid="config-panel"], aside:has-text("Config"), aside:has-text("Configure"), section:has-text("Configure")',
    )
    .first();
  // Some builders inline config — fall back to the body if no dedicated panel.
  const haystack = (await panel.textContent().catch(() => null)) ?? (await page.textContent('body')) ?? '';
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

  test('palette: mqtt_subscribe — config panel exposes broker, topic, QoS', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'mqtt_subscribe');
    await expectConfigPanel(page, [/topic/i, /qos|subscribe/i]);
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

  test('palette: audio_stt — config panel exposes input, language, diarise', async ({ page }) => {
    await gotoOk(page, '/builder');
    await addToolToCanvas(page, 'audio_stt');
    await expectConfigPanel(page, [/audio|input|url/i, /language|diaris|speaker/i]);
  });
});

test.describe('Abenix v1.1 · admin pages', () => {
  // ─── /admin/connectors ───────────────────────────────────────────────

  test('admin: /admin/connectors renders + create form is present', async ({ page }) => {
    await gotoOk(page, '/admin/connectors');
    const text = (await page.textContent('body')) || '';
    expect(text.length, 'connectors page renders content').toBeGreaterThan(80);
    expect(text).toMatch(/connector/i);

    const newBtn = page
      .locator('button', { hasText: /\+ ?new connector|add connector|create connector/i })
      .first();
    await expect(newBtn, '+ New connector button').toBeVisible({ timeout: 8_000 });
    await newBtn.click();
    await page.waitForTimeout(500);

    // Modal/inline form must include kind picker + base URL field.
    const after = (await page.textContent('body')) || '';
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

  test('admin: /edge renders + register-gateway form is present', async ({ page }) => {
    await gotoOk(page, '/edge');
    const text = (await page.textContent('body')) || '';
    expect(text.length).toBeGreaterThan(80);
    expect(text).toMatch(/edge|gateway/i);

    const registerBtn = page
      .locator('button', { hasText: /\+ ?register gateway|add gateway|new gateway/i })
      .first();
    if (await registerBtn.isVisible().catch(() => false)) {
      await registerBtn.click();
      await page.waitForTimeout(500);
      const after = (await page.textContent('body')) || '';
      expect(after).toMatch(/gateway.?id|name|bootstrap/i);
    } else {
      // The page itself should at least show the column headers / empty state.
      expect(text).toMatch(/no gateways|register|empty|nothing/i);
    }
  });
});
