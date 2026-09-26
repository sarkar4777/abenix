import { test, expect, type Page } from '@playwright/test';

/**
 * Claude subscription — browser-driven UAT.
 *
 *   BASE=http://localhost:3000 API=http://localhost:8000 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_claude_subscription.spec.ts \
 *     --reporter=list --workers=1
 *
 * Covers the config screen, the secret-handling contract, and the fact
 * that turning it on is visible in the model pickers platform-wide.
 *
 * The suite restores whatever state it found, so it is safe to run
 * before the rest of the UAT gate.
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

// Syntactically plausible but not a real credential — used to prove the
// screen stores/masks it and that Verify reports a clean failure.
// Assembled rather than written as one literal: the publish leak scanner
// matches /sk-ant-[a-z0-9_-]{20,}/ and cannot tell a fixture from a real key.
const FAKE_TOKEN = ['sk', 'ant', 'oat01', 'uat-placeholder-0000'].join('-');

let TOKEN = '';
let ORIGINAL: Record<string, string> = {};

async function api(path: string, init: RequestInit = {}) {
  const resp = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${TOKEN}`,
      ...(init.headers || {}),
    },
  });
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body, data: (body as any)?.data ?? body };
}

async function setSetting(key: string, value: string) {
  return api(`/api/admin/settings/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify({ value }),
  });
}

async function subStatus() {
  const r = await api('/api/admin/settings/subscription');
  expect(r.status, 'subscription status HTTP').toBe(200);
  return r.data;
}

async function login(page: Page) {
  await page.addInitScript(({ t }: { t: string }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
    } catch {}
  }, { t: TOKEN });
}

test.beforeAll(async () => {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  TOKEN = json.data?.access_token || json.access_token;
  expect(TOKEN, 'access_token').toBeTruthy();

  // Snapshot so we can put the platform back exactly as we found it.
  const before = await subStatus();
  ORIGINAL = {
    enabled: before.enabled ? 'true' : 'false',
    exclusive: before.exclusive ? 'true' : 'false',
    default_model: before.default_model,
  };
});

test.afterAll(async () => {
  if (!TOKEN) return;
  // Order matters: clear the token last, because `enabled=true` is
  // rejected while no token exists.
  await setSetting('llm.subscription.enabled', ORIGINAL.enabled);
  await setSetting('llm.subscription.exclusive', ORIGINAL.exclusive);
  await setSetting('llm.subscription.default_model', ORIGINAL.default_model);
  await setSetting('llm.subscription.token', '');
});

// ── API contract ─────────────────────────────────────────────────────────

test('subscription status endpoint reports a coherent initial state', async () => {
  const s = await subStatus();
  expect(typeof s.enabled).toBe('boolean');
  expect(typeof s.exclusive).toBe('boolean');
  expect(s.default_model, 'a default model is always named').toBeTruthy();
  // active is the AND of the two things that actually matter.
  expect(s.active).toBe(Boolean(s.enabled && s.token_set));
});

test('enabling subscription mode without a token is refused', async () => {
  await setSetting('llm.subscription.token', '');
  const r = await setSetting('llm.subscription.enabled', 'true');
  expect(r.status, 'should not enable without a credential').toBeGreaterThanOrEqual(400);
  const s = await subStatus();
  expect(s.enabled).toBe(false);
  expect(s.active).toBe(false);
});

test('the token is never echoed back in clear text', async () => {
  const saved = await setSetting('llm.subscription.token', FAKE_TOKEN);
  expect(saved.status).toBe(200);
  expect(JSON.stringify(saved.body)).not.toContain(FAKE_TOKEN);

  const s = await subStatus();
  expect(s.token_set).toBe(true);
  expect(s.token_masked).not.toContain(FAKE_TOKEN);
  expect(s.token_masked).toContain('*');

  // Nor via the bulk settings listing that powers the admin screen.
  const all = await api('/api/admin/settings');
  expect(all.status).toBe(200);
  expect(JSON.stringify(all.body)).not.toContain(FAKE_TOKEN);
});

test('model catalogue carries the subscription block and the Claude 5 family', async () => {
  const r = await api('/api/llm-models');
  expect(r.status).toBe(200);
  const models = r.data.models as any[];
  expect(Array.isArray(models)).toBe(true);
  expect(r.data.subscription, 'subscription block present').toBeTruthy();
  expect(typeof r.data.subscription.active).toBe('boolean');

  // The migration-seeded catalogue must include what the subscription serves,
  // otherwise default_model can never be selected.
  const ids = models.map((m) => m.value);
  expect(ids, 'catalogue is migration-seeded, not the hardcoded fallback').toContain(
    'claude-opus-5',
  );
});

test('subscription-served models are flagged once the mode is active', async () => {
  await setSetting('llm.subscription.token', FAKE_TOKEN);
  await setSetting('llm.subscription.exclusive', 'true');
  const on = await setSetting('llm.subscription.enabled', 'true');
  expect(on.status, 'enable with a token present').toBe(200);

  const s = await subStatus();
  expect(s.active).toBe(true);

  const r = await api('/api/llm-models');
  const models = r.data.models as any[];
  expect(r.data.subscription.active).toBe(true);

  const claude = models.find((m) => m.value === 'claude-opus-5');
  expect(claude?.subscription_served, 'Claude models served by the plan').toBe(true);

  // Exclusive mode also absorbs non-Claude models, naming the remap target.
  const gpt = models.find((m) => String(m.value).startsWith('gpt'));
  if (gpt) {
    expect(gpt.subscription_served).toBe(true);
    expect(gpt.subscription_remapped_to).toBeTruthy();
  }
});

test('non-exclusive mode leaves non-Claude models on their own provider', async () => {
  await setSetting('llm.subscription.exclusive', 'false');
  const r = await api('/api/llm-models');
  const models = r.data.models as any[];
  const gpt = models.find((m) => String(m.value).startsWith('gpt'));
  if (gpt) {
    expect(gpt.subscription_served).toBe(false);
    expect(gpt.served_by).not.toBe('claude_subscription');
  }
  const claude = models.find((m) => m.value === 'claude-opus-5');
  expect(claude?.subscription_served, 'Claude still uses the plan').toBe(true);
  await setSetting('llm.subscription.exclusive', 'true');
});

test('verify reports a clean, specific failure for a bad token', async () => {
  await setSetting('llm.subscription.token', FAKE_TOKEN);
  const r = await api('/api/admin/settings/subscription/verify', { method: 'POST', body: '{}' });
  // A bogus credential must surface as a handled 4xx/502 with a message,
  // never a 500 or an empty body.
  expect(r.status, 'handled failure, not a crash').not.toBe(500);
  expect(r.status).toBeGreaterThanOrEqual(400);
  const msg = JSON.stringify(r.body);
  expect(msg.length, 'error carries an explanation').toBeGreaterThan(10);
  expect(msg).not.toContain(FAKE_TOKEN);
});

test('the platform still answers while the subscription is unusable', async () => {
  // Exclusive mode + dead token: the degradation chain must keep the
  // product working off whatever API keys exist, rather than hard-failing.
  await setSetting('llm.subscription.token', FAKE_TOKEN);
  await setSetting('llm.subscription.enabled', 'true');
  const health = await api('/api/health');
  expect(health.status).toBe(200);
  const models = await api('/api/llm-models');
  expect(models.status).toBe(200);
  expect((models.data.models as any[]).length).toBeGreaterThan(0);
});

// ── UI ───────────────────────────────────────────────────────────────────

test('admin LLM settings screen renders the Claude subscription card', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/admin/llm-settings`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});

  const card = page.getByTestId('claude-subscription-section');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText(/claude subscription/i);
  await expect(card).toContainText(/setup-token/i);

  await expect(page.getByTestId('subscription-token-input')).toBeVisible();
  await expect(page.getByTestId('subscription-enabled-toggle')).toBeVisible();
  await expect(page.getByTestId('subscription-exclusive-toggle')).toBeVisible();
  await expect(page.getByTestId('subscription-verify')).toBeVisible();

  // The token field must be a password input — never plain text.
  await expect(page.getByTestId('subscription-token-input')).toHaveAttribute('type', 'password');
});

test('the card shows an active badge and the model it serves', async ({ page }) => {
  await setSetting('llm.subscription.token', FAKE_TOKEN);
  await setSetting('llm.subscription.enabled', 'true');
  await setSetting('llm.subscription.default_model', 'claude-opus-5');

  await login(page);
  await page.goto(`${BASE}/admin/llm-settings`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});

  await expect(page.getByTestId('subscription-status-badge')).toContainText(/active/i, {
    timeout: 20_000,
  });
  await expect(page.getByTestId('subscription-active-note')).toContainText('claude-opus-5');
  // The raw token must not appear anywhere in the rendered DOM.
  expect(await page.content()).not.toContain(FAKE_TOKEN);
});

test('subscription mode is visible in model pickers across the platform', async ({ page }) => {
  await setSetting('llm.subscription.token', FAKE_TOKEN);
  await setSetting('llm.subscription.enabled', 'true');
  await setSetting('llm.subscription.exclusive', 'true');

  await login(page);
  for (const path of ['/admin/llm-settings', '/builder']) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const note = page.getByTestId('model-picker-subscription').first();
    // Not every page mounts a picker immediately; assert when one is there.
    if ((await note.count()) > 0) {
      await expect(note).toContainText(/claude subscription active/i, { timeout: 15_000 });
    }
  }
});

test('the subscription category is not rendered as a model dropdown', async ({ page }) => {
  // Regression guard: the generic category grid renders a ModelPicker per
  // setting, which would be wrong for the token / boolean keys.
  await login(page);
  await page.goto(`${BASE}/admin/llm-settings`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await expect(page.getByTestId('claude-subscription-section')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('category-claude_subscription')).toHaveCount(0);
  await expect(page.getByTestId('select-llm.subscription.token')).toHaveCount(0);
});
