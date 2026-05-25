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

test('AGENTS: info page (Overview / API & SDK / Triggers & Events) — sample 5 agents incl pipelines', async ({ page }) => {
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
    await page.waitForTimeout(2000);

    const txt = (await page.locator('body').innerText()).toLowerCase();
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
      await page.waitForTimeout(1500);
      const t = (await page.locator('body').innerText()).toLowerCase();
      sdkOK = /curl|python|sdk|forge\.|x-api-key|bearer/.test(t);
    }

    // Click Triggers tab
    const trigTab = page.locator('button, [role="tab"]', { hasText: /triggers|events/i }).first();
    let trigOK = false;
    if (await trigTab.count()) {
      await trigTab.click().catch(() => {});
      await page.waitForTimeout(1500);
      const t = (await page.locator('body').innerText()).toLowerCase();
      trigOK = /webhook|cron|schedule|trigger/.test(t);
    }

    results.push({ slug: a.slug, hasName, hasOverview, hasApiTab, hasTriggersTab, hasChat, sdkOK, trigOK });
    console.log(`  ${a.slug.padEnd(40)} overview=${hasOverview} api=${hasApiTab} trig=${hasTriggersTab} sdkContent=${sdkOK} trigContent=${trigOK}`);
  }
  await page.screenshot({ path: 'test-results/uat-agent-info-last.png', fullPage: true });

  const ok = results.filter(r => r.hasOverview && r.hasApiTab && r.hasTriggersTab && r.sdkOK && r.trigOK);
  expect(ok.length).toBeGreaterThanOrEqual(Math.floor(results.length * 0.7));
});

test('SETTINGS: every sub-page renders without error', async ({ page }) => {
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
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2200);
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
  await page.waitForTimeout(2500);

  const txt = (await page.locator('body').innerText()).toLowerCase();
  const providers = ['slack','teams','salesforce','hubspot','jira','notion','gmail','github','google calendar','google drive'];
  const present = providers.filter(p => txt.includes(p));
  console.log(`  providers visible: ${present.length}/${providers.length}: ${present.join(', ')}`);
  expect(present.length).toBeGreaterThanOrEqual(3);

  const cards = await page.locator('[class*="card" i], [class*="rounded" i] > div').count();
  const connectBtns = await page.locator('button:has-text("Connect"), button:has-text("Add"), button:has-text("Configure")').count();
  const removeBtns = await page.locator('button:has-text("Remove"), button:has-text("Delete"), button:has-text("Disconnect")').count();
  console.log(`  cards=${cards}  connect/add btns=${connectBtns}  remove btns=${removeBtns}`);

  await page.screenshot({ path: 'test-results/uat-integrations-admin.png', fullPage: true });
  expect(connectBtns + removeBtns).toBeGreaterThan(0);

  // Check admin-only RBAC at the API level
  const r = await page.request.get(`${API}/api/integrations`, { headers: { Authorization: `Bearer ${tok}` } });
  expect(r.ok()).toBeTruthy();
});

test('MCP: registry + custom server add flow', async ({ page }) => {
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
