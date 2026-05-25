import { test, expect, type Page, type APIRequestContext } from '@playwright/test';

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

test('1. /settings/api-keys — list + create + revoke', async ({ page }) => {
  const tok = await login(page);
  const list1 = await page.request.get(`${API}/api/api-keys`, { headers: auth(tok) });
  expect(list1.ok()).toBeTruthy();
  const before = ((await list1.json()).data || []).length;

  const create = await page.request.post(`${API}/api/api-keys`, { headers: auth(tok), data: { name: `uat-${Date.now()}` } });
  expect(create.ok()).toBeTruthy();
  const created = (await create.json()).data;
  expect(created.id).toBeTruthy();
  expect(created.raw_key).toMatch(/^af_/);

  const list2 = await page.request.get(`${API}/api/api-keys`, { headers: auth(tok) });
  expect(((await list2.json()).data || []).length).toBe(before + 1);

  const del = await page.request.delete(`${API}/api/api-keys/${created.id}`, { headers: auth(tok) });
  expect(del.ok() || del.status() === 204).toBeTruthy();

  const list3 = await page.request.get(`${API}/api/api-keys`, { headers: auth(tok) });
  expect(((await list3.json()).data || []).length).toBe(before);

  // Verify the UI page renders
  await page.goto(`${BASE}/settings/api-keys`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/api keys?|create|new key/i);
});

test('2. /settings/billing — usage + costs endpoints', async ({ page }) => {
  const tok = await login(page);
  const u = await page.request.get(`${API}/api/billing/usage`, { headers: auth(tok) });
  expect([200, 404, 501]).toContain(u.status());
  const c = await page.request.get(`${API}/api/analytics/costs`, { headers: auth(tok) });
  expect([200, 404, 501]).toContain(c.status());
  await page.goto(`${BASE}/settings/billing`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/billing|usage|plan|cost/i);
});

test('3. /settings/data — read + write DLP and retention', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/settings/dlp`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());

  const w = await page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'detect', enabled: true } });
  expect([200, 204, 404]).toContain(w.status());

  const ret = await page.request.put(`${API}/api/settings/retention`, {
    headers: auth(tok),
    data: { execution_retention_days: 30, message_retention_days: 60, audit_log_retention_days: 365 },
  });
  expect([200, 204, 404]).toContain(ret.status());

  await page.goto(`${BASE}/settings/data`);
  await page.waitForTimeout(2500);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/dlp|retention|days/i);
});

test('4. /settings/notifications — read + write prefs + tenant slack URL', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/settings/notifications`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());

  const w = await page.request.put(`${API}/api/settings/notifications`, {
    headers: auth(tok),
    data: { execution_complete: true, execution_failed: true, weekly_report: false, billing_alerts: true, team_updates: false, marketing: false },
  });
  expect([200, 204, 404]).toContain(w.status());

  const tenant = await page.request.put(`${API}/api/settings/tenant`, {
    headers: auth(tok),
    data: { slack_webhook_url: 'https://hooks.slack.com/services/UAT/TEST/TOKEN' },
  });
  expect([200, 204, 400, 404]).toContain(tenant.status());

  await page.goto(`${BASE}/settings/notifications`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/notifications|slack|webhook|alerts/i);
});

test('5. /settings/observability — health endpoint', async ({ page }) => {
  const tok = await login(page);
  const h = await page.request.get(`${API}/api/health/ready`, { headers: auth(tok) });
  expect([200, 503]).toContain(h.status());
  await page.goto(`${BASE}/settings/observability`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/observability|metrics|health|status/i);
});

test('6. /settings/privacy — privacy endpoints', async ({ page }) => {
  const tok = await login(page);
  const p = await page.request.get(`${API}/api/account/privacy`, { headers: auth(tok) });
  expect([200, 404]).toContain(p.status());
  await page.goto(`${BASE}/settings/privacy`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/privacy|gdpr|delete account|export/i);
});

test('7. /settings/profile — update full_name', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.put(`${API}/api/settings/profile`, {
    headers: auth(tok),
    data: { full_name: 'UAT Admin User', avatar_url: null },
  });
  expect([200, 204]).toContain(r.status());
  await page.goto(`${BASE}/settings/profile`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText());
  expect(txt.toLowerCase()).toMatch(/profile|name|email/i);
});

test('8. /settings/quotas — per-user analytics', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/analytics/per-user`, { headers: auth(tok) });
  expect([200, 403, 404]).toContain(r.status());
  await page.goto(`${BASE}/settings/quotas`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/quota|limit|tokens|cost/i);
});

test('9. /settings/sandbox — read + write config', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/settings/sandbox`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  const w = await page.request.put(`${API}/api/settings/sandbox`, {
    headers: auth(tok),
    data: { enabled: true, allow_network: false, allowed_images: ['python:3.12-slim'] },
  });
  expect([200, 204, 400, 404]).toContain(w.status());
  await page.goto(`${BASE}/settings/sandbox`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/sandbox|isolation|container|image/i);
});

test('10. /settings/security — sessions + activity', async ({ page }) => {
  const tok = await login(page);
  const s = await page.request.get(`${API}/api/settings/sessions`, { headers: auth(tok) });
  expect([200, 404]).toContain(s.status());
  const a = await page.request.get(`${API}/api/settings/activity`, { headers: auth(tok) });
  expect([200, 404]).toContain(a.status());
  await page.goto(`${BASE}/settings/security`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/security|session|activity|login/i);
});

test('11. /settings/team — list members', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/team/members`, { headers: auth(tok) });
  expect([200, 403, 404]).toContain(r.status());
  await page.goto(`${BASE}/settings/team`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/team|members?|invite|role/i);
});

test('12. /settings/webhooks — list + create + delete + load deliveries', async ({ page }) => {
  const tok = await login(page);
  const list1 = await page.request.get(`${API}/api/webhooks`, { headers: auth(tok) });
  expect(list1.ok()).toBeTruthy();
  const before = ((await list1.json()).data || []).length;

  const create = await page.request.post(`${API}/api/webhooks`, {
    headers: auth(tok),
    data: { url: 'https://uat-webhook.example.com/hook', events: ['execution.completed', 'execution.failed'] },
  });
  expect([200, 201]).toContain(create.status());
  const created = (await create.json()).data;
  expect(created.id).toBeTruthy();

  const dlv = await page.request.get(`${API}/api/webhooks/${created.id}/deliveries?limit=20`, { headers: auth(tok) });
  expect([200, 404]).toContain(dlv.status());

  const del = await page.request.delete(`${API}/api/webhooks/${created.id}`, { headers: auth(tok) });
  expect([200, 204]).toContain(del.status());

  const list2 = await page.request.get(`${API}/api/webhooks`, { headers: auth(tok) });
  expect(((await list2.json()).data || []).length).toBe(before);

  await page.goto(`${BASE}/settings/webhooks`);
  await page.waitForTimeout(2000);
  const txt = (await page.locator('body').innerText()).toLowerCase();
  expect(txt).toMatch(/webhook|deliveries|event/i);
});

test('14. /settings/api — redirects to /settings/api-keys (was placeholder)', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/api`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
  expect(page.url()).toContain('/settings/api-keys');
});

test('13. /settings/integrations — MCP link + setup expand drives copyable snippets', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/integrations`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);

  const text = await page.locator('body').innerText();
  expect(text.toLowerCase()).toMatch(/mcp|runtime tool/i);
  expect(text.toLowerCase()).toMatch(/admin/i);

  const setupBtns = page.locator('button', { hasText: /^Setup$/ });
  const n = await setupBtns.count();
  expect(n).toBeGreaterThan(8);

  await setupBtns.first().click();
  await page.waitForTimeout(1000);
  const expanded = (await page.locator('body').innerText()).toLowerCase();
  expect(expanded).toMatch(/local dev|shell|\.env|kubectl|helm/);

  // Click MCP link
  const mcpLink = page.locator('a[href="/mcp"]').first();
  expect(await mcpLink.count()).toBeGreaterThan(0);
});
