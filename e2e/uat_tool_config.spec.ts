/**
 * Admin -> Tool Configuration, end to end.
 *
 * The screen is generated from the tools' own config_fields, so the test does
 * not hard-code a tool list. It picks a key off the API, saves a value for it
 * from the browser, sees the source flip to "saved here", sees the badge on
 * /tools follow within the propagation window, clears it, and checks a viewer
 * gets neither the sidebar entry nor the endpoint.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_tool_config.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
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

async function api(page: Page, method: string, p: string, body?: unknown) {
  const opts = {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  };
  let res;
  try {
    res = await page.request.fetch(`${API}${p}`, opts);
  } catch (e: any) {
    // retry once on a dropped connection, a reused keep-alive socket can close under the request
    if (!/socket hang up|ECONNRESET|fetch failed/i.test(String(e?.message))) throw e;
    res = await page.request.fetch(`${API}${p}`, opts);
  }
  let json: any = null; try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.serial('tool configuration', () => {
  test.setTimeout(180_000);
  let key = '';
  let tool = '';
  let group = '';

  test('the catalogue is generated and complete', async ({ page }) => {
    await login(page);
    const cat = await api(page, 'GET', '/api/admin/tool-config');
    expect(cat.status).toBe(200);
    const d = cat.json.data;
    expect(d.key_count).toBeGreaterThan(40);
    expect(d.groups.length).toBeGreaterThan(20);
    expect(typeof d.encrypted_at_rest).toBe('boolean');
    expect(d.propagation_seconds).toBe(30);
    // the provider keys are on the same screen as everything else
    const keys = new Set<string>(d.groups.flatMap((g: any) => g.keys.map((k: any) => k.key)));
    for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY', 'GITHUB_TOKEN']) expect(keys.has(k), k).toBeTruthy();
    // every key names at least one tool, and every tool it names is in the registry
    const reg = await api(page, 'GET', '/api/tools');
    const rows: any[] = Array.isArray(reg.json?.data) ? reg.json.data : reg.json?.data?.tools ?? [];
    const slugs = new Set(rows.map((t) => t.id));
    for (const g of d.groups) for (const k of g.keys) {
      expect(k.tools.length, k.key).toBeGreaterThan(0);
      for (const t of k.tools) expect(slugs.has(t), `${k.key} names ${t}`).toBeTruthy();
    }
    // pick an optional secret that is currently unset, so saving it changes the tool's badge
    const candidate = d.groups.flatMap((g: any) => g.keys.map((k: any) => ({ ...k, group: g.group })))
      .find((k: any) => k.kind === 'secret' && !k.is_set && k.tools.length === 1 && !k.required);
    expect(candidate, 'an unset optional secret to exercise').toBeTruthy();
    key = candidate.key; tool = candidate.tools[0]; group = candidate.group;
    // /api/tools carries the same declaration per tool
    const row = rows.find((t) => t.id === tool);
    expect(row?.config?.status, `${tool} status`).toBe('optional');
    expect(row.config.fields.map((f: any) => f.key)).toContain(key);
  });

  test('save from the screen, see it on the tool, clear it', async ({ page }) => {
    await login(page);
    await visit(page, `/admin/tool-config#${key}`);
    await expect(page.getByTestId('tool-config-counts')).toBeVisible();
    await expect(page.getByTestId(`tool-config-group-${group}`)).toBeVisible();
    const row = page.getByTestId(`tool-config-row-${key}`);
    await expect(row).toBeVisible();
    await expect(row.getByTestId(`tool-config-source-${key}`)).toHaveAttribute('data-source', 'unset');
    await expect(row).toContainText(tool);

    await row.getByTestId(`tool-config-input-${key}`).fill('uat-test-value-1234');
    await row.getByTestId(`tool-config-save-${key}`).click();
    await expect(row.getByTestId(`tool-config-msg-${key}`)).toContainText(/Saved/);
    await expect(row.getByTestId(`tool-config-source-${key}`)).toHaveAttribute('data-source', 'stored');
    // the masked value shows the tail only
    await expect(row.getByTestId(`tool-config-input-${key}`)).toHaveAttribute('placeholder', /\*+1234$/);

    // the admin GET reads the table directly
    const st = await api(page, 'GET', '/api/admin/tool-config');
    const saved = st.json.data.groups.flatMap((g: any) => g.keys).find((k: any) => k.key === key);
    expect(saved.source).toBe('stored');
    expect(saved.is_set).toBe(true);
    expect(saved.value).toMatch(/^\*+1234$/);

    // the badge on /tools follows within the propagation window
    await expect.poll(async () => {
      const reg = await api(page, 'GET', '/api/tools');
      const rows: any[] = Array.isArray(reg.json?.data) ? reg.json.data : reg.json?.data?.tools ?? [];
      return rows.find((t) => t.id === tool)?.config?.status;
    }, { timeout: 45_000, intervals: [2000] }).toBe('configured');
    await visit(page, `/tools#${tool}`);
    const toolRow = page.getByTestId(`tool-row-${tool}`);
    await expect(toolRow).toBeVisible();
    await expect(toolRow.getByTestId('credential-badge-configured')).toBeVisible();
    await expect(toolRow.getByTestId(`tool-configure-${tool}`)).toBeVisible();

    // the integrations page says the same, and sends admins to the screen
    await visit(page, '/settings/integrations');
    await expect(page.getByTestId('integrations-admin-link')).toBeVisible();
    await expect(page.locator('body')).not.toContainText('kubectl create secret');
    await expect(page.locator('body')).not.toContainText('ENTSO_E_TOKEN');

    // clear it and the row is back to the environment or unset
    await visit(page, `/admin/tool-config#${key}`);
    const row2 = page.getByTestId(`tool-config-row-${key}`);
    await row2.getByTestId(`tool-config-clear-${key}`).click();
    await expect(row2.getByTestId(`tool-config-msg-${key}`)).toContainText(/Cleared/);
    await expect(row2.getByTestId(`tool-config-source-${key}`)).not.toHaveAttribute('data-source', 'stored');
  });

  test('validation and the test button', async ({ page }) => {
    await login(page);
    const bad = await api(page, 'PATCH', '/api/admin/tool-config/NOT_A_DECLARED_KEY', { value: 'x' });
    expect(bad.status).toBe(404);
    const cat = await api(page, 'GET', '/api/admin/tool-config');
    const url = cat.json.data.groups.flatMap((g: any) => g.keys).find((k: any) => k.kind === 'url');
    if (url) {
      const r = await api(page, 'PATCH', `/api/admin/tool-config/${url.key}`, { value: 'not a url' });
      expect(r.status).toBe(400);
    }
    // a wrong key is rejected by the provider, and the screen says so instead of saving blindly
    const t = await api(page, 'POST', '/api/admin/tool-config/GITHUB_TOKEN/test', { value: 'ghp_definitely_not_valid' });
    expect(t.status).toBe(200);
    expect(t.json.data.ok).toBe(false);
    expect(t.json.data.message).toMatch(/rejected|HTTP|reach/i);
  });

  test('a missing required key is one sentence the user can act on', async ({ page }) => {
    await login(page);
    const cat = await api(page, 'GET', '/api/admin/tool-config');
    const req = cat.json.data.groups.flatMap((g: any) => g.keys).find((k: any) => k.required && !k.is_set && k.tools.length === 1);
    test.skip(!req, 'every required key is set on this cluster');
    const r = await api(page, 'POST', `/api/tools/${req.tools[0]}/execute`, { arguments: {} });
    const text = JSON.stringify(r.json);
    expect(text).toContain(req.key);
    expect(text).toMatch(/Admin -> Tool Configuration/);
    expect(text).toMatch(/needs_configuration/);
  });

  test('a viewer gets neither the entry nor the endpoint', async ({ page }) => {
    await login(page);
    const email = `viewer-${Date.now()}@abenix.dev`;
    const mk = await api(page, 'POST', '/api/team/dev-create-member', { email, password: 'ViewerPass123!', role: 'user', name: 'Viewer' });
    test.skip(mk.status >= 400, `could not create a viewer (${mk.status})`);
    await login(page, { email, password: 'ViewerPass123!' });
    const denied = await api(page, 'GET', '/api/admin/tool-config');
    expect(denied.status).toBe(403);
    await visit(page, '/tools');
    // the hint text may name the screen, the sidebar must not link to it
    await expect(page.locator('a[href="/admin/tool-config"]')).toHaveCount(0);
    await expect(page.getByTestId('credential-hint').first()).toContainText(/Ask an admin/);
    await visit(page, '/admin/tool-config');
    await expect(page.getByTestId('tool-config-error')).toContainText(/Admin role required/);
  });
});
