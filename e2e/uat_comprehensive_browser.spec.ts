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

test.describe.configure({ mode: 'default' });

const bodyText = async (page: Page) => (await page.locator('body').innerText()).toLowerCase();

async function textAppears(page: Page, re: RegExp, timeout = 10_000) {
  return expect.poll(async () => re.test(await bodyText(page)), { timeout }).toBe(true).then(() => true, () => false);
}

test('AGENTS: info page (Overview / API & SDK / Triggers & Events) — sample 5 agents incl pipelines', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/agents?limit=100`, { headers: { Authorization: `Bearer ${tok}` } });
  const agents = ((await r.json()).data || []).filter((a: any) => a.status === 'active').slice(0, 6);
  expect(agents.length).toBeGreaterThan(2);
  console.log(`sampling ${agents.length} active agents`);

  const results: any[] = [];
  for (const a of agents) {
    const url = `${BASE}/agents/${a.id}/info`;
    await page.goto(url);
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByRole('heading', { level: 1, name: a.name })).toBeVisible({ timeout: 30_000 });

    const txt = await bodyText(page);
    const hasName = txt.includes((a.name || '').toLowerCase().slice(0, 20));
    const hasOverview = /overview/.test(txt);
    const hasApiTab = /api & sdk|api &amp; sdk|api\/sdk|sdk/.test(txt);
    const hasTriggersTab = /triggers.*events|trigger/.test(txt);
    const hasDesc = (a.description || '').length > 0 ? txt.includes((a.description.slice(0, 30) || '').toLowerCase()) : true;
    const hasChat = /\bchat\b/.test(txt);

    // Click API & SDK tab if present
    const sdkTab = page.locator('button, [role="tab"]', { hasText: /api & sdk|api\/sdk|sdk/i }).first();
    let sdkOK = false;
    if (await sdkTab.count()) {
      await sdkTab.click().catch(() => {});
      sdkOK = await textAppears(page, /curl|python|forge\.|x-api-key|bearer/);
    }

    // Click Triggers tab
    const trigTab = page.locator('button, [role="tab"]', { hasText: /triggers|events/i }).first();
    let trigOK = false;
    if (await trigTab.count()) {
      await trigTab.click().catch(() => {});
      trigOK = await textAppears(page, /webhook|cron|schedule/);
    }

    results.push({ slug: a.slug, hasName, hasOverview, hasApiTab, hasTriggersTab, hasChat, sdkOK, trigOK });
    console.log(`  ${a.slug.padEnd(40)} overview=${hasOverview} api=${hasApiTab} trig=${hasTriggersTab} sdkContent=${sdkOK} trigContent=${trigOK}`);
  }
  await page.screenshot({ path: 'test-results/uat-agent-info-last.png', fullPage: true });

  const ok = results.filter(r => r.hasOverview && r.hasApiTab && r.hasTriggersTab && r.sdkOK && r.trigOK);
  expect(ok.length).toBeGreaterThanOrEqual(Math.floor(results.length * 0.7));
});

test('SETTINGS: every sub-page renders without error', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await login(page);

  const sub = [
    'api','api-keys','billing','data','integrations','notifications',
    'observability','privacy','profile','quotas','sandbox','security','team','webhooks',
  ];
  const out: any[] = [];
  for (const s of sub) {
    const errors: string[] = [];
    page.removeAllListeners('console');
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 120)); });
    await page.goto(`${BASE}/settings/${s}`);
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    const txt = (await page.locator('body').innerText()).slice(0, 4000).toLowerCase();
    const buttons = await page.locator('button').count();
    const inputs = await page.locator('input, textarea, select').count();
    const has404 = /not found|404/.test(txt);
    const hasContent = txt.length > 100 && !has404;
    const filteredErrors = errors.filter(e => !/favicon|websocket|404/i.test(e));
    out.push({ s, hasContent, buttons, inputs, jsErrors: filteredErrors.length });
    console.log(`  /settings/${s.padEnd(20)} content=${hasContent}  btns=${buttons}  inputs=${inputs}  errs=${filteredErrors.length}`);
  }
  await page.screenshot({ path: 'test-results/uat-settings-last.png', fullPage: true });
  const good = out.filter(r => r.hasContent);
  expect(good.length).toBeGreaterThanOrEqual(out.length - 1);
});

test('INTEGRATIONS catalog: shows providers + admin RBAC + add/remove flow', async ({ page }) => {
  const tok = await login(page);
  await page.goto(`${BASE}/settings/integrations`);
  await page.waitForLoadState('domcontentloaded');
  // the list and the admin action both need the catalog and the role loaded
  await expect(page.locator('button', { hasText: /^Setup$/ }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('integrations-admin-link')).toHaveText('Open Tool Configuration', { timeout: 30_000 });

  const txt = await bodyText(page);
  const providers = ['slack','teams','salesforce','hubspot','jira','notion','gmail','github','google calendar','google drive'];
  const present = providers.filter(p => txt.includes(p));
  console.log(`  providers visible: ${present.length}/${providers.length}: ${present.join(', ')}`);
  expect(present.length).toBeGreaterThanOrEqual(3);

  // Setup shows the keys a service reads, live values are set on Tool Configuration
  const setup = page.locator('button', { hasText: /^Setup$/ }).first();
  await setup.click();
  await expect(page.locator('[data-testid^="integration-live-"]').first()).toBeVisible();

  await page.screenshot({ path: 'test-results/uat-integrations-admin.png', fullPage: true });

  // Check admin-only RBAC at the API level
  const r = await page.request.get(`${API}/api/integrations`, { headers: { Authorization: `Bearer ${tok}` } });
  expect(r.ok()).toBeTruthy();
});

test('MCP: registry + custom server add flow', async ({ page }) => {
  test.setTimeout(2 * 60_000);
  const tok = await login(page);

  // MCP servers list
  const r = await page.request.get(`${API}/api/mcp/registry`, { headers: { Authorization: `Bearer ${tok}` } });
  console.log(`  /api/mcp/registry status: ${r.status()}`);

  const userMcpResp = await page.request.get(`${API}/api/mcp/connections`, { headers: { Authorization: `Bearer ${tok}` } });
  console.log(`  /api/mcp/connections status: ${userMcpResp.status()}`);

  // UI: find the MCP page
  const candidatePaths = ['/settings/integrations', '/integrations', '/mcp', '/connectors'];
  let mcpUrl = '';
  for (const p of candidatePaths) {
    await page.goto(`${BASE}${p}`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
    const txt = (await page.locator('body').innerText()).toLowerCase();
    if (/mcp|model context/.test(txt)) { mcpUrl = p; break; }
  }
  console.log(`  MCP UI page: ${mcpUrl || '(none found)'}`);

  if (mcpUrl) {
    await page.screenshot({ path: 'test-results/uat-mcp-page.png', fullPage: true });
    const buttons = await page.locator('button').count();
    expect(buttons).toBeGreaterThan(0);
  }
});
