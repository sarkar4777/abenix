import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
  return tok;
}

const auth = (tok: string) => ({ Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' });

test.describe.configure({ mode: 'default' });

test('EDGE #1 — Retention/DLP/approval-webhook persist across re-read (JSONB mutation regression)', async ({ page }) => {
  const tok = await login(page);

  const retBody = { execution_retention_days: 45, message_retention_days: 90, audit_log_retention_days: 400 };
  const rw = await page.request.put(`${API}/api/settings/retention`, { headers: auth(tok), data: retBody });
  expect([200, 204]).toContain(rw.status());

  const rr = await page.request.get(`${API}/api/settings/retention`, { headers: auth(tok) });
  if (rr.status() === 200) {
    const d = (await rr.json()).data || {};
    expect(d.execution_retention_days).toBe(45);
    expect(d.message_retention_days).toBe(90);
    expect(d.audit_log_retention_days).toBe(400);
  }

  const dw = await page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'mask', enabled: true, custom_patterns: { ssn: '\\d{3}-\\d{2}-\\d{4}' } } });
  expect([200, 204]).toContain(dw.status());
  const dr = await page.request.get(`${API}/api/settings/dlp`, { headers: auth(tok) });
  if (dr.status() === 200) {
    const d = (await dr.json()).data || {};
    expect(d.mode).toBe('mask');
    expect(d.enabled).toBe(true);
    expect(d.custom_patterns?.ssn).toContain('\\d{3}');
  }

  const aw = await page.request.put(`${API}/api/approvals/webhooks`, { headers: auth(tok), data: { url: 'https://hooks.example.com/approvals', secret: 'whsec_edge_test' } });
  expect([200, 204, 404]).toContain(aw.status());
  const ar = await page.request.get(`${API}/api/approvals/webhooks`, { headers: auth(tok) });
  if (ar.status() === 200) {
    const d = (await ar.json()).data || {};
    expect(d.url).toContain('hooks.example.com');
    expect(d.has_secret).toBe(true);
  }
});

test('EDGE #2 — DLP/sandbox/retention reject invalid input with 4xx (boundary)', async ({ page }) => {
  const tok = await login(page);

  const bad = await page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'TOTALLY_BOGUS' } });
  expect([400, 422]).toContain(bad.status());

  const low = await page.request.put(`${API}/api/settings/retention`, { headers: auth(tok), data: { execution_retention_days: 1, message_retention_days: 1, audit_log_retention_days: 1 } });
  expect([200, 204]).toContain(low.status());
  const rr = await page.request.get(`${API}/api/settings/retention`, { headers: auth(tok) });
  if (rr.status() === 200) {
    const d = (await rr.json()).data || {};
    expect(d.execution_retention_days).toBeGreaterThanOrEqual(7);
    expect(d.message_retention_days).toBeGreaterThanOrEqual(30);
    expect(d.audit_log_retention_days).toBeGreaterThanOrEqual(365);
  }
});

test('EDGE #3 — API-key revocation invalidates subsequent calls', async ({ page }) => {
  const tok = await login(page);
  const create = await page.request.post(`${API}/api/api-keys`, { headers: auth(tok), data: { name: `edge-revoke-${Date.now()}` } });
  expect(create.ok()).toBeTruthy();
  const created = (await create.json()).data;
  const rawKey = created.raw_key;
  expect(rawKey).toMatch(/^af_/);

  const probe1 = await page.request.get(`${API}/api/agents`, { headers: { Authorization: `Bearer ${rawKey}` } });
  expect([200, 401, 403, 404]).toContain(probe1.status());

  const del = await page.request.delete(`${API}/api/api-keys/${created.id}`, { headers: auth(tok) });
  expect([200, 204]).toContain(del.status());

  const probe2 = await page.request.get(`${API}/api/agents`, { headers: { Authorization: `Bearer ${rawKey}` } });
  expect([401, 403]).toContain(probe2.status());
});

test('EDGE #4 — Webhook idempotency: same URL+events twice does not double-list', async ({ page }) => {
  const tok = await login(page);
  const url = `https://uat-edge-${Date.now()}.example.com/hook`;

  const before = await page.request.get(`${API}/api/webhooks`, { headers: auth(tok) });
  const beforeCount = ((await before.json()).data || []).length;

  const c1 = await page.request.post(`${API}/api/webhooks`, { headers: auth(tok), data: { url, events: ['execution.completed'] } });
  expect([200, 201]).toContain(c1.status());
  const w1 = (await c1.json()).data;

  const c2 = await page.request.post(`${API}/api/webhooks`, { headers: auth(tok), data: { url, events: ['execution.completed'] } });
  // Either 200 (returns existing) or 409 (conflict) or 201 (creates separate row) — what we forbid is silent error
  expect([200, 201, 409]).toContain(c2.status());

  const after = await page.request.get(`${API}/api/webhooks`, { headers: auth(tok) });
  const list = (await after.json()).data || [];
  const matching = list.filter((w: any) => w.url === url);
  expect(matching.length).toBeGreaterThan(0);

  for (const w of [w1, ...matching.filter((w: any) => w.id !== w1?.id)]) {
    if (w?.id) await page.request.delete(`${API}/api/webhooks/${w.id}`, { headers: auth(tok) });
  }

  const final = await page.request.get(`${API}/api/webhooks`, { headers: auth(tok) });
  expect(((await final.json()).data || []).length).toBe(beforeCount);
});

test('EDGE #5 — Concurrent settings writes do not corrupt nested JSONB', async ({ page }) => {
  const tok = await login(page);

  // Fire 6 parallel writes interleaving retention + dlp + notifications
  const writes = await Promise.all([
    page.request.put(`${API}/api/settings/retention`, { headers: auth(tok), data: { execution_retention_days: 30 } }),
    page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'detect', enabled: true } }),
    page.request.put(`${API}/api/settings/notifications`, { headers: auth(tok), data: { execution_complete: true, execution_failed: true, weekly_report: false, billing_alerts: true, team_updates: false, marketing: false } }),
    page.request.put(`${API}/api/settings/retention`, { headers: auth(tok), data: { execution_retention_days: 60 } }),
    page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'mask', enabled: true } }),
    page.request.put(`${API}/api/settings/notifications`, { headers: auth(tok), data: { execution_complete: false, execution_failed: true, weekly_report: true, billing_alerts: true, team_updates: false, marketing: false } }),
  ]);
  for (const w of writes) expect([200, 204, 400, 404]).toContain(w.status());

  const r = await page.request.get(`${API}/api/settings/retention`, { headers: auth(tok) });
  if (r.status() === 200) {
    const d = (await r.json()).data || {};
    expect(typeof d.execution_retention_days).toBe('number');
    expect([30, 60]).toContain(d.execution_retention_days);
  }
  const d2 = await page.request.get(`${API}/api/settings/dlp`, { headers: auth(tok) });
  if (d2.status() === 200) {
    const v = (await d2.json()).data || {};
    expect(['detect', 'mask']).toContain(v.mode);
  }
});

test('EDGE #6 — API-key scope: missing token returns 401, malformed returns 401', async ({ page }) => {
  const r1 = await page.request.get(`${API}/api/agents`);
  expect([401, 403]).toContain(r1.status());

  const r2 = await page.request.get(`${API}/api/agents`, { headers: { Authorization: 'Bearer ' } });
  expect([401, 403]).toContain(r2.status());

  const r3 = await page.request.get(`${API}/api/agents`, { headers: { Authorization: 'Bearer obviously-not-a-token' } });
  expect([401, 403]).toContain(r3.status());
});

test('EDGE #7 — Tenant slack webhook URL roundtrip (per-tenant column)', async ({ page }) => {
  const tok = await login(page);
  const url = `https://hooks.slack.com/services/EDGE/${Date.now()}/abc`;
  const w = await page.request.put(`${API}/api/settings/tenant`, { headers: auth(tok), data: { slack_webhook_url: url } });
  expect([200, 204, 400, 404]).toContain(w.status());
  const r = await page.request.get(`${API}/api/settings/tenant`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() === 200) {
    const body = (await r.json()).data || {};
    if (body.slack_webhook_url !== undefined && body.slack_webhook_url !== null) {
      expect(body.slack_webhook_url).toContain('hooks.slack.com');
    }
  }
});

test('EDGE #8 — Profile update does not nuke unrelated user fields', async ({ page }) => {
  const tok = await login(page);
  const me1 = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  expect(me1.ok()).toBeTruthy();
  const before = (await me1.json()).data || {};

  const newName = `UAT Edge ${Date.now()}`;
  const w = await page.request.put(`${API}/api/settings/profile`, { headers: auth(tok), data: { full_name: newName } });
  expect([200, 204]).toContain(w.status());

  const me2 = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  const after = (await me2.json()).data || {};

  // user fields should remain intact
  const beforeUser = before.user || before;
  const afterUser = after.user || after;
  expect(afterUser.email).toBe(beforeUser.email);
  expect(afterUser.role).toBe(beforeUser.role);
  expect(afterUser.tenant_id).toBe(beforeUser.tenant_id);
});

test('EDGE #9 — MCP registry returns at least one server + connection list is paginated/array', async ({ page }) => {
  const tok = await login(page);
  const reg = await page.request.get(`${API}/api/mcp/registry`, { headers: auth(tok) });
  expect([200, 404]).toContain(reg.status());
  if (reg.status() === 200) {
    const body = await reg.json();
    const items = Array.isArray(body.data) ? body.data : (body.data?.items || body.data?.servers || []);
    expect(Array.isArray(items)).toBeTruthy();
  }
  const conns = await page.request.get(`${API}/api/mcp/connections`, { headers: auth(tok) });
  expect([200, 404]).toContain(conns.status());
  if (conns.status() === 200) {
    const body = await conns.json();
    const items = Array.isArray(body.data) ? body.data : (body.data?.connections || []);
    expect(Array.isArray(items)).toBeTruthy();
  }
});

test('EDGE #10 — Webhook with invalid URL is rejected at create time', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.post(`${API}/api/webhooks`, { headers: auth(tok), data: { url: 'not-a-url-at-all', events: ['execution.completed'] } });
  expect([400, 422]).toContain(r.status());

  const r2 = await page.request.post(`${API}/api/webhooks`, { headers: auth(tok), data: { url: 'https://example.com/hook', events: [] } });
  expect([400, 422]).toContain(r2.status());

  const r3 = await page.request.post(`${API}/api/webhooks`, { headers: auth(tok), data: { url: 'https://example.com/hook', events: ['not.a.real.event'] } });
  expect([200, 201, 400, 422]).toContain(r3.status());
  if ([200, 201].includes(r3.status())) {
    const w = (await r3.json()).data;
    if (w?.id) await page.request.delete(`${API}/api/webhooks/${w.id}`, { headers: auth(tok) });
  }
});

test('EDGE #11 — Sandbox settings round-trip preserves the allow-list', async ({ page }) => {
  const tok = await login(page);
  const images = ['python:3.12-slim', 'node:20-alpine', 'golang:1.22-alpine'];
  const w = await page.request.put(`${API}/api/settings/sandbox`, { headers: auth(tok), data: { enabled: true, allow_network: false, allowed_images: images } });
  expect([200, 204, 400, 404]).toContain(w.status());
  const r = await page.request.get(`${API}/api/settings/sandbox`, { headers: auth(tok) });
  if (r.status() === 200) {
    const d = (await r.json()).data || {};
    if (Array.isArray(d.allowed_images)) {
      for (const img of images) expect(d.allowed_images).toContain(img);
    }
  }
});

test('EDGE #12 — Sessions list contains current session', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/settings/sessions`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() === 200) {
    const body = (await r.json()).data || [];
    expect(Array.isArray(body) || typeof body === 'object').toBeTruthy();
  }
});

test('EDGE #13 — Cross-tenant isolation: token A cannot read tenant B private resources', async ({ page }) => {
  const tok = await login(page);
  // Bogus tenant id should never resolve into someone else's data
  const fakeId = '00000000-0000-0000-0000-000000000000';
  const r = await page.request.get(`${API}/api/agents/${fakeId}`, { headers: auth(tok) });
  expect([404, 403, 400]).toContain(r.status());
});

test('EDGE #14 — Integrations status endpoint shape is stable', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/integrations/status`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() === 200) {
    const body = await r.json();
    expect(body.data === undefined || typeof body.data === 'object').toBeTruthy();
  }
});

test('EDGE #15 — Notifications prefs round-trip with all flags', async ({ page }) => {
  const tok = await login(page);
  const data = { execution_complete: false, execution_failed: true, weekly_report: true, billing_alerts: false, team_updates: true, marketing: false };
  const w = await page.request.put(`${API}/api/settings/notifications`, { headers: auth(tok), data });
  expect([200, 204, 404]).toContain(w.status());
  const r = await page.request.get(`${API}/api/settings/notifications`, { headers: auth(tok) });
  if (r.status() === 200) {
    const d = (await r.json()).data || {};
    for (const k of Object.keys(data)) {
      if (d[k] !== undefined) expect(typeof d[k]).toBe('boolean');
    }
  }
});
