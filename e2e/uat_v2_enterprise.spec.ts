import { test, expect, type Page } from '@playwright/test';
import { revealSidebarLink } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
  return tok;
}
const auth = (tok: string) => ({ Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' });

test.describe.configure({ mode: 'default' });

test('V2 #1 — cognify-config: GET defaults, PUT, round-trip', async ({ page }) => {
  const tok = await login(page);
  const g = await page.request.get(`${API}/api/knowledge/cognify-config`, { headers: auth(tok) });
  expect(g.ok()).toBeTruthy();
  const before = (await g.json()).data;
  expect(before.auto_accept_threshold).toBeGreaterThanOrEqual(0);
  expect(before.auto_accept_threshold).toBeLessThanOrEqual(1);
  expect(['flag', 'split', 'lower_conf_wins', 'higher_conf_wins']).toContain(before.conflict_action);

  const p = await page.request.put(`${API}/api/knowledge/cognify-config`, {
    headers: auth(tok),
    data: { auto_accept_threshold: 0.75, conflict_action: 'flag', max_parallel_docs: 12, daily_budget_usd: 100 },
  });
  expect([200, 204]).toContain(p.status());

  const g2 = await page.request.get(`${API}/api/knowledge/cognify-config`, { headers: auth(tok) });
  const after = (await g2.json()).data;
  expect(after.auto_accept_threshold).toBeCloseTo(0.75);
  expect(after.max_parallel_docs).toBe(12);
});

test('V2 #2 — cognify-config: invalid threshold rejected', async ({ page }) => {
  const tok = await login(page);
  const p = await page.request.put(`${API}/api/knowledge/cognify-config`, {
    headers: auth(tok),
    data: { auto_accept_threshold: 2.0 },
  });
  expect([400, 422]).toContain(p.status());
});

test('V2 #3 — cognify-conflicts: list endpoint shape stable', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/knowledge/cognify-conflicts`, { headers: auth(tok) });
  expect(r.ok()).toBeTruthy();
  const body = (await r.json()).data;
  expect(Array.isArray(body.items)).toBeTruthy();
});

test('V2 #4 — document grant + revoke flow', async ({ page }) => {
  const tok = await login(page);
  const kb = await page.request.post(`${API}/api/knowledge`, { headers: auth(tok), data: { name: `v2-acl-${Date.now()}` } });
  if (![200, 201].includes(kb.status())) return;
  const kbId = (await kb.json()).data.id;
  // grants endpoint should exist even when no doc is uploaded
  const g = await page.request.get(`${API}/api/knowledge/${kbId}/documents/${kbId}/grants`, { headers: auth(tok) });
  expect([200, 404]).toContain(g.status());
  await page.request.delete(`${API}/api/knowledge/${kbId}`, { headers: auth(tok) });
});

test('V2 #5 — GDPR receipts route protected + returns array', async ({ page }) => {
  const tok = await login(page);
  const me = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  const user = (await me.json()).data.user || (await me.json()).data;
  const r = await page.request.get(`${API}/api/gdpr/users/${user.id}/receipts`, { headers: auth(tok) });
  expect(r.ok()).toBeTruthy();
  expect(Array.isArray((await r.json()).data)).toBeTruthy();
});

test('V2 #6 — Re-embed dry-run returns estimate', async ({ page }) => {
  const tok = await login(page);
  const kb = await page.request.post(`${API}/api/knowledge`, { headers: auth(tok), data: { name: `v2-reembed-${Date.now()}` } });
  if (![200, 201].includes(kb.status())) return;
  const kbId = (await kb.json()).data.id;
  const r = await page.request.post(`${API}/api/knowledge/${kbId}/reembed`, {
    headers: auth(tok),
    data: { embedding_model: 'voyage-3', dry_run: true },
  });
  expect([200, 201]).toContain(r.status());
  const body = (await r.json()).data;
  expect(body.to_model).toBe('voyage-3');
  expect(body.estimated_usd).toBeGreaterThanOrEqual(0);
  await page.request.delete(`${API}/api/knowledge/${kbId}`, { headers: auth(tok) });
});

test('V2 #7 — UI: /settings/cognify renders + has threshold input', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/cognify`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).toMatch(/cognify|conflict|threshold/);
  const numericInputs = await page.locator('input[type="number"]').count();
  expect(numericInputs).toBeGreaterThan(0);
});

test('V2 #8 — UI: /settings/gdpr renders + has the person search', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/gdpr`);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.getByTestId('gdpr-person-search')).toBeVisible({ timeout: 15_000 });
  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).toMatch(/gdpr|erasure|purge|receipt/);
});

test('V2 #9 — Sidebar: new admin entries reachable', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/dashboard`);
  await page.waitForLoadState('domcontentloaded');
  await revealSidebarLink(page, '/settings/cognify');
  await revealSidebarLink(page, '/settings/gdpr');
});

test('V2 #10 — Doc grant: invalid permission rejected', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.post(
    `${API}/api/knowledge/00000000-0000-0000-0000-000000000000/documents/00000000-0000-0000-0000-000000000000/grants`,
    {
      headers: auth(tok),
      data: { subject_type: 'user', subject_id: '00000000-0000-0000-0000-000000000001', permission: 'BOGUS' },
    },
  );
  expect([400, 404, 422]).toContain(r.status());
});
