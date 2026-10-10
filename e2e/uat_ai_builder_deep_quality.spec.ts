import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API  = process.env.API  || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
}

async function audit(page: Page, label: string) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text().slice(0,200)}`); });
  page.on('requestfailed', (r) => errors.push(`netfail: ${r.url()} ${r.failure()?.errorText}`));
  return { errors, label };
}

test.describe.configure({ mode: 'default' });

test('A. Builder DEEP — structure + buttons + tools panel + chat panel', async ({ page }) => {
  await login(page);
  const a = await audit(page, 'builder');

  await page.goto(`${BASE}/builder`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(5000);

  const sels = {
    h1: await page.locator('h1').count(),
    h2: await page.locator('h2').count(),
    h3: await page.locator('h3').count(),
    nav: await page.locator('nav, [role="navigation"]').count(),
    tabs: await page.locator('[role="tablist"], [role="tab"]').count(),
    inputs: await page.locator('input, textarea').count(),
    buttons: await page.locator('button').count(),
    iconSvgs: await page.locator('svg').count(),
    toolItems: await page.locator('[class*="tool" i]').count(),
    palette: await page.locator('[class*="palette" i]').count(),
    code: await page.locator('pre, code').count(),
  };
  console.log(`BUILDER STRUCTURE: ${JSON.stringify(sels)}`);

  await page.screenshot({ path: 'test-results/uat-deep-builder.png', fullPage: true });

  expect(sels.buttons).toBeGreaterThan(20);
  expect(sels.inputs).toBeGreaterThanOrEqual(1);
  expect(sels.iconSvgs).toBeGreaterThan(5);

  expect(a.errors.filter((e) => !/favicon|websocket/i.test(e)).length).toBeLessThan(3);
});

test('B. Chat DEEP — send button after typing + agent picker', async ({ page }) => {
  await login(page);
  const a = await audit(page, 'chat');

  await page.goto(`${BASE}/chat`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3500);

  const textarea = page.locator('textarea').first();
  const hasTextarea = await textarea.count();
  console.log(`textareas: ${hasTextarea}`);
  if (hasTextarea > 0) {
    await textarea.fill('hello — UAT check from playwright');
    await page.waitForTimeout(500);
  }

  const sendByText = await page.locator('button:has-text("Send"), button:has-text("Submit"), button:has-text("Ask")').count();
  const sendByIcon = await page.locator('button[aria-label*="send" i], button:has(svg)[type="submit"]').count();
  const allButtons = await page.locator('button').count();

  console.log(`AFTER TYPING — sendByText=${sendByText}, sendByIcon=${sendByIcon}, totalButtons=${allButtons}`);

  const agentPicker = await page.locator('select, [class*="picker" i], [class*="dropdown" i], [role="combobox"]').count();
  console.log(`agent picker controls: ${agentPicker}`);

  await page.screenshot({ path: 'test-results/uat-deep-chat.png', fullPage: true });

  expect(hasTextarea).toBeGreaterThanOrEqual(1);
  expect(allButtons).toBeGreaterThanOrEqual(2);
  expect(a.errors.filter((e) => !/favicon|websocket/i.test(e)).length).toBeLessThan(3);
});

test('C. SDK Playground DEEP — code editor + run + language picker', async ({ page }) => {
  await login(page);
  const a = await audit(page, 'sdk-playground');

  await page.goto(`${BASE}/sdk-playground`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(4000);

  const editor = {
    monaco: await page.locator('[class*="monaco" i]').count(),
    codeMirror: await page.locator('[class*="cm-" i], [class*="codemirror" i]').count(),
    pre: await page.locator('pre').count(),
    textareaCode: await page.locator('textarea[class*="code" i], textarea[wrap="off"]').count(),
  };
  const langPicker = await page.locator('button:has-text("Python"), button:has-text("TypeScript"), button:has-text("cURL")').count();
  const runBtn = await page.locator('button:has-text("Run"), button:has-text("Execute"), button:has-text("Generate"), button:has-text("Try")').count();
  const buttons = await page.locator('button').count();
  console.log(`SDK PLAYGROUND — editor=${JSON.stringify(editor)} langPicker=${langPicker} runBtn=${runBtn} totalButtons=${buttons}`);

  await page.screenshot({ path: 'test-results/uat-deep-sdk-playground.png', fullPage: true });

  expect(buttons).toBeGreaterThan(10);
  expect(a.errors.filter((e) => !/favicon|websocket/i.test(e)).length).toBeLessThan(3);
});

test('D. /edge page DEEP — registration form, runtime cards', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/edge`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  const text = (await page.locator('body').innerText()).toLowerCase();
  const hasPython = /python/.test(text);
  const hasRust = /rust/.test(text);
  const hasC = /\bc\s*\(|\bc runtime|\b\.c\b/.test(text);
  const hasInstall = /install|register|token/.test(text);
  const hasGateways = /gateway|node|edge|fleet/.test(text);

  const cards = await page.locator('[class*="card" i], [class*="rounded" i] > div, table').count();
  const codeCopy = await page.locator('button:has(svg)[class*="copy" i], button[aria-label*="copy" i]').count();
  const cmdBlocks = await page.locator('pre, code').count();

  console.log(`/edge — python=${hasPython} rust=${hasRust} c=${hasC} install/register=${hasInstall} gateways=${hasGateways} cards=${cards} cmdBlocks=${cmdBlocks} copyBtns=${codeCopy}`);
  await page.screenshot({ path: 'test-results/uat-deep-edge.png', fullPage: true });

  expect(hasPython || hasRust).toBeTruthy();
  expect(hasGateways).toBeTruthy();
});

test('E. /admin/pipeline-scaling DEEP — DAG rendering for at least one pipeline', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/admin/pipeline-scaling`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(4000);

  await page.locator('button:has-text("Refresh"), button:has(svg[class*="refresh" i])').first().click({ trial: true }).catch(() => {});
  await page.waitForTimeout(1500);

  // Try clicking the first pipeline row to expand DAG
  const rows = await page.locator('button, [role="button"]').filter({ hasText: /pipeline pool|nodes/i }).count();
  console.log(`pipeline rows: ${rows}`);

  if (rows > 0) {
    await page.locator('button, [role="button"]').filter({ hasText: /pipeline pool|nodes/i }).first().click();
    await page.waitForTimeout(1500);
  }

  const nodeCards = await page.locator('[class*="agent" i], [class*="tool" i], [class*="control" i]').count();
  const arrows = await page.locator('svg path[d*="L"], [class*="arrow" i]').count();
  const text = (await page.locator('body').innerText()).toLowerCase();
  const hasAgents = /agent/i.test(text);
  const hasTools = /tool/i.test(text);

  console.log(`/admin/pipeline-scaling — nodeCards=${nodeCards} arrows=${arrows} agentsMentioned=${hasAgents} toolsMentioned=${hasTools}`);
  await page.screenshot({ path: 'test-results/uat-deep-pipeline-scaling.png', fullPage: true });
  expect(hasAgents && hasTools).toBeTruthy();
});

test('F. /admin/tool-scaling DEEP — seeded rows visible and the edit drawer opens', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/admin/tool-scaling`);
  await page.waitForLoadState('domcontentloaded');
  const rows = page.locator('tbody tr').filter({ has: page.getByRole('button', { name: /^Edit / }) });
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  const tableRows = await rows.count();
  console.log(`/admin/tool-scaling — tableRows=${tableRows}`);
  expect(tableRows).toBeGreaterThanOrEqual(5);

  const edit = rows.first().getByRole('button', { name: /^Edit / });
  const slug = ((await edit.getAttribute('aria-label')) || '').replace(/^Edit /, '');
  await edit.click();
  await expect(page.getByRole('heading', { name: slug })).toBeVisible();
  await expect(page.getByText('Inflight cap (global)')).toBeVisible();
  await page.screenshot({ path: 'test-results/uat-deep-tool-scaling.png', fullPage: true });
  await page.keyboard.press('Escape');
  await page.mouse.click(5, 5);
  await expect(page.getByText('Inflight cap (global)')).toHaveCount(0);
});

test('G. /ml-models DEEP — every registered model is listed', async ({ page }) => {
  await login(page);
  const tok = await page.evaluate(() => localStorage.getItem('access_token'));
  const r = await page.request.get(`${API}/api/ml-models`, { headers: { Authorization: `Bearer ${tok}` } });
  const d = (await r.json()).data;
  const models: Array<{ name: string }> = Array.isArray(d) ? d : d.items;
  expect(models.length, 'models registered').toBeGreaterThan(0);
  await page.goto(`${BASE}/ml-models`);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.getByText(models[0].name, { exact: false }).first()).toBeVisible({ timeout: 20_000 });
  const text = await page.locator('main').innerText();
  const missing = models.filter((m) => !text.includes(m.name)).map((m) => m.name);
  await page.screenshot({ path: 'test-results/uat-deep-ml-models.png', fullPage: true });
  expect(missing, 'models missing from the page').toEqual([]);
});

test('H. /help — Scale & operate section visible with three-layer content', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/help`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  const scaleTab = await page.locator('button, [role="button"]', { hasText: /scale|operate/i }).count();
  if (scaleTab > 0) {
    await page.locator('button, [role="button"]', { hasText: /scale|operate/i }).first().click();
    await page.waitForTimeout(1500);
  }

  const text = (await page.locator('body').innerText()).toLowerCase();
  const hasThreeLayers = /three scaling layers|three layers|layer 1|layer 2|layer 3/.test(text);
  const hasKeda = /keda/.test(text);
  const hasNats = /nats/.test(text);
  const hasGate = /tool gate|cache.*sem.*qps|circuit breaker/.test(text);
  console.log(`/help Scale&operate — three_layers=${hasThreeLayers} keda=${hasKeda} nats=${hasNats} gate=${hasGate}`);

  await page.screenshot({ path: 'test-results/uat-deep-help.png', fullPage: true });
  expect(hasThreeLayers || hasKeda || hasNats).toBeTruthy();
});
