/**
 * Risk and Controls, Permissions and the builder's tier picker, as real users.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_governance.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import { openFromSidebar } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };

let token = '';

async function login(page: Page, creds = ADMIN) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: creds });
  expect(res.ok(), `login ${creds.email}`).toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}

async function api(page: Page, method: string, p: string, body?: unknown, tok = token) {
  // one retry, a reused keep-alive socket can be closed under us
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }));
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function clearSwitches(page: Page) {
  const r = await api(page, 'GET', '/api/governance/kill-switches');
  for (const s of r.json?.data?.switches || []) await api(page, 'POST', `/api/governance/kill-switches/${s.id}/clear`);
}

test.describe.configure({ mode: 'serial' });

// a switch left on stops the calculator for every later spec, so clear them however this file ends
test.afterAll(async ({ request }) => {
  const res = await request.post(`${API}/api/auth/login`, { data: ADMIN }).catch(() => null);
  const tok = res && res.ok() ? (await res.json())?.data?.access_token : '';
  if (!tok) return;
  const headers = { Authorization: `Bearer ${tok}` };
  const list = await request.get(`${API}/api/governance/kill-switches`, { headers }).catch(() => null);
  const switches = list && list.ok() ? (await list.json())?.data?.switches || [] : [];
  for (const s of switches) await request.post(`${API}/api/governance/kill-switches/${s.id}/clear`, { headers }).catch(() => null);
});

test('admin sees Risk and Controls in the sidebar and all four tiers', async ({ page }) => {
  await login(page);
  await api(page, 'DELETE', '/api/governance/risk/high');
  await visit(page, '/dashboard');
  await openFromSidebar(page, '/admin/risk');
  await expect(page.getByRole('heading', { name: 'Risk and Controls' })).toBeVisible();
  await expect(page.locator('header').first()).toContainText('Risk & Controls');
  for (const t of ['low', 'medium', 'high', 'critical']) await expect(page.getByTestId(`tier-card-${t}`)).toBeVisible();
  await expect(page.getByTestId('tier-card-high')).toContainText('platform defaults');
});

test('a tier policy is edited, validated at the field, saved and reset', async ({ page }) => {
  await login(page);
  await visit(page, '/admin/risk');
  const card = page.getByTestId('tier-card-high');
  await expect(page.getByTestId('tier-save-high')).toBeDisabled();
  await page.getByTestId('tier-min-approvers-high').fill('11');
  await expect(card.getByRole('alert')).toContainText('0 to 10');
  await expect(page.getByTestId('tier-save-high')).toBeDisabled();
  await page.getByTestId('tier-min-approvers-high').fill('2');
  await page.getByTestId('tier-action-high-block').click();
  await page.getByTestId('tier-models-high').fill('claude-opus-*');
  await page.getByTestId('tier-models-high').press('Enter');
  await page.getByTestId('tier-save-high').click();
  await expect(page.getByTestId('tier-msg-high')).toContainText('Saved');
  await expect(card).toContainText('customised');
  const r = await api(page, 'GET', '/api/governance/risk');
  const high = r.json.data.tiers.find((t: any) => t.tier === 'high');
  expect(high.overrides).toEqual({ publish_approvals: { min_approvers: 2, exclude_author: true, capability: 'approvals.sign', escalate_after_hours: 24 }, tool_call_action: 'block', allowed_models: ['claude-opus-*'] });
  await page.getByTestId('tier-reset-high').click();
  await page.getByRole('button', { name: 'Use defaults' }).last().click();
  await expect(card).toContainText('platform defaults');
});

test('a kill switch is set from the screen, stops the tool in a run, and resumes', async ({ page }) => {
  test.setTimeout(240_000);
  await login(page);
  await clearSwitches(page);
  await visit(page, '/admin/risk#switches');
  await expect(page.getByTestId('kill-switch-empty')).toBeVisible();
  await page.getByTestId('kill-switch-scope-tool').click();
  await page.getByTestId('kill-switch-search').fill('calculator');
  await page.getByRole('option', { name: /^calculator/ }).click();
  await expect(page.getByTestId('kill-switch-submit')).toBeDisabled();
  await page.getByTestId('kill-switch-reason').fill('UAT: wrong rounding');
  await page.getByTestId('kill-switch-submit').click();
  await page.getByRole('button', { name: 'Stop it' }).click();
  await expect(page.getByTestId('kill-switch-msg')).toContainText('Stopped');
  await expect(page.getByTestId('kill-switch-tool-calculator')).toContainText('UAT: wrong rounding');
  await expect(page.getByTestId('risk-tab-switches')).toContainText('1');

  // a one-node pipeline calls the tool every time, no model in the way
  const made = await api(page, 'POST', '/api/agents', {
    name: `UAT kill switch ${Date.now().toString(36)}`,
    system_prompt: '',
    model_config: {
      mode: 'pipeline',
      tools: ['calculator'],
      pipeline_config: { nodes: [{ id: 'multiply', label: 'Multiply', tool_name: 'calculator', arguments: { expression: '17 * 23' }, depends_on: [] }], edges: [] },
    },
  });
  expect(made.status, JSON.stringify(made.json)).toBeLessThan(300);
  const calcId = made.json.data.id;
  try {
    await page.waitForTimeout(6000);
    const run = await api(page, 'POST', `/api/agents/${calcId}/execute`, { message: 'go', stream: false, wait: true });
    const exid = run.json?.data?.execution_id;
    expect(exid, JSON.stringify(run.json)).toBeTruthy();
    const ex = (await api(page, 'GET', `/api/executions/${exid}`)).json.data;
    const call = (ex.tool_calls || []).find((t: any) => t.name === 'calculator');
    expect(call?.is_error, JSON.stringify(ex.tool_calls)).toBeTruthy();
    expect(String(call?.result_preview || call?.result)).toContain('kill switch');

    await page.getByTestId(/kill-switch-resume-/).click();
    await page.getByRole('button', { name: 'Resume' }).last().click();
    await expect(page.getByTestId('kill-switch-empty')).toBeVisible();
  } finally {
    await clearSwitches(page);
    await api(page, 'DELETE', `/api/agents/${calcId}`);
  }
});

test('tool tiers are searchable and audit verification passes', async ({ page }) => {
  await login(page);
  await visit(page, '/admin/risk#tools');
  await page.getByTestId('tool-tiers-search').fill('email');
  await expect(page.getByTestId('tool-tier-email_sender')).toBeVisible();
  await page.getByTestId('risk-tab-audit').click();
  await page.getByTestId('audit-verify').click();
  await expect(page.getByTestId('audit-ok')).toContainText('Intact', { timeout: 60_000 });
});

test('the run records its provenance and tier', async ({ page }) => {
  await login(page);
  const agents = (await api(page, 'GET', '/api/agents?limit=100')).json.data;
  const a = agents.find((x: any) => (x.model_config?.mode || 'agent') !== 'pipeline' && x.status === 'active');
  const run = await api(page, 'POST', `/api/agents/${a.id}/execute`, { message: 'Say hello in one word.', stream: false, wait: true });
  const p = await api(page, 'GET', `/api/governance/runs/${run.json.data.execution_id}/provenance`);
  expect(p.status).toBe(200);
  expect(p.json.data.provenance.config_hash).toHaveLength(64);
  expect(p.json.data.snapshot.model_config).toBeTruthy();
  expect(['low', 'medium', 'high', 'critical']).toContain(p.json.data.risk_tier);
});

test('a plain user cannot reach the screens until a permission set grants it', async ({ page, browser }) => {
  await login(page);
  const email = `gov-${Date.now()}@abenix.dev`;
  const mk = await api(page, 'POST', '/api/team/dev-create-member', { email, password: 'GovPass123!', role: 'user', name: 'Gov Tester' });
  test.skip(mk.status >= 400, `could not create a user (${mk.status})`);

  // admin creates a set through the screen
  await visit(page, '/admin/permissions');
  await expect(page.getByTestId('role-baseline-user')).toBeVisible();
  await page.getByTestId('permset-new').click();
  const setName = `Risk officers ${Date.now()}`;
  await page.getByTestId('permset-name').fill(setName);
  await page.getByTestId('permset-cap-killswitch.manage').check();
  await page.getByTestId('permset-cap-permissions.manage').check();
  await page.getByTestId('permset-save').click();
  await expect(page.getByTestId(`permset-${setName}`)).toBeVisible();

  const userCtx = await browser.newContext();
  const up = await userCtx.newPage();
  await login(up, { email, password: 'GovPass123!' });
  const userToken = token;
  await visit(up, '/admin/permissions');
  await expect(up.getByTestId('permissions-no-access')).toBeVisible();
  expect((await api(up, 'POST', '/api/governance/kill-switches', { scope: 'tool', target: 'web_search', reason: 'nope' }, userToken)).status).toBe(403);

  await page.getByTestId(`permset-add-${setName}`).fill(email.split('@')[0]);
  await page.getByRole('option', { name: new RegExp(email) }).click();
  await expect(page.getByTestId(`permset-${setName}`)).toContainText(email.split('@')[0]);

  await up.waitForTimeout(11_000);
  await visit(up, '/admin/permissions');
  await expect(up.getByRole('heading', { name: 'Permissions' })).toBeVisible();
  const set = await api(up, 'POST', '/api/governance/kill-switches', { scope: 'tool', target: 'web_search', reason: 'granted now' }, userToken);
  expect(set.status).toBe(201);
  await api(page, 'POST', `/api/governance/kill-switches/${set.json.data.id}/clear`);
  await userCtx.close();

  const sets = (await api(page, 'GET', '/api/governance/permission-sets')).json.data;
  const mine = sets.find((s: any) => s.name === setName);
  await api(page, 'DELETE', `/api/governance/permission-sets/${mine.id}`);
});

test('the builder shows the tier and what it requires', async ({ page }) => {
  await login(page);
  const agents = (await api(page, 'GET', '/api/agents?limit=100')).json.data;
  const a = agents.find((x: any) => (x.model_config?.tools || []).includes('email_sender')) || agents[0];
  await visit(page, `/builder?agent=${a.id}`);
  const picker = page.getByTestId('risk-tier-picker');
  await expect(picker).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('risk-tier-critical').click();
  await expect(page.getByTestId('risk-tier-effects')).toContainText('sign-off');
  await page.getByTestId('risk-tier-low').click();
  if ((a.model_config?.tools || []).includes('email_sender')) {
    await expect(page.getByTestId('risk-tier-effects')).toContainText('email_sender is high risk');
  }
});
