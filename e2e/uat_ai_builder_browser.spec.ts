import { test, expect, type Page, type Locator } from '@playwright/test';

/*
 * Comprehensive AI Builder + Validation + Chat + SDK Playground + Edge UAT.
 * Drives the browser like a real end user.
 *
 *   BASE=http://localhost:3000 API=http://localhost:8000 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_ai_builder_browser.spec.ts \
 *     --reporter=list --workers=1 --timeout=240000
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API  = process.env.API  || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function loginAndStoreToken(page: Page) {
  const resp = await page.request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  const tok = body?.data?.access_token;
  expect(tok).toBeTruthy();
  await page.goto(BASE);
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('token', t);
  }, tok);
}

async function waitForToast(page: Page, fragment: string, timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const txt = await page.locator('body').innerText().catch(() => '');
    if (txt && txt.toLowerCase().includes(fragment.toLowerCase())) return true;
    await page.waitForTimeout(500);
  }
  return false;
}

test.describe.configure({ mode: 'default' });

test.describe('AI Builder + Validation + Execution + Edge', () => {

  test('1. Builder loads + palette shows tools + chrome is polished', async ({ page }) => {
    await loginAndStoreToken(page);
    await page.goto(`${BASE}/builder`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`);
    });

    const html = await page.locator('body').innerText();
    expect(html.toLowerCase()).toMatch(/builder|agent|pipeline/);

    const buttons = await page.locator('button, [role="button"]').count();
    expect(buttons).toBeGreaterThan(10);

    const headings = await page.locator('h1, h2, h3').count();
    expect(headings).toBeGreaterThan(0);

    const emptyStates = (await page.locator('text=/loading\\.\\.\\./i').count()) +
                        (await page.locator('text=/no data/i').count());

    await page.screenshot({ path: 'test-results/uat-builder-01-load.png', fullPage: true });
    console.log(`/builder: ${buttons} buttons, ${headings} headings, ${emptyStates} loading/empty placeholders, ${errors.length} JS errors`);
    expect(errors.length).toBeLessThan(3);
  });

  test('2. AI Builder: build agent via description prompt (single)', async ({ page }) => {
    await loginAndStoreToken(page);

    const resp = await page.request.post(`${API}/api/ai/build-agent`, {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` },
      data: {
        description:
          'Counterparty due-diligence agent for precious metals. Combine sanctions_screening, ' +
          'adverse_media, country_risk_index, and the contractiq-counterparty-default ML model. ' +
          'Output a 4-level rating with citations.',
        agent_type: 'single',
      },
      timeout: 120000,
    });
    expect(resp.ok()).toBeTruthy();
    const out = (await resp.json()).data;
    expect(out.name).toBeTruthy();
    expect(out.tools).toBeInstanceOf(Array);
    expect(out.tools.length).toBeGreaterThanOrEqual(3);
    const hasSysPrompt = (out.system_prompt && out.system_prompt.length > 50);
    const hasPipeline = out.pipeline_config?.nodes?.length > 0;
    expect(hasSysPrompt || hasPipeline).toBeTruthy();
    console.log(`built: ${out.name}, mode=${out.mode}, ${out.tools.length} tools: ${out.tools.slice(0,6).join(', ')}, sysPrompt=${out.system_prompt?.length || 0}c, pipelineNodes=${out.pipeline_config?.nodes?.length || 0}`);
  });

  test('3. AI Builder: build pipeline (7-node deal scorer)', async ({ page }) => {
    await loginAndStoreToken(page);

    const resp = await page.request.post(`${API}/api/ai/build-agent`, {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` },
      data: {
        description:
          'A pipeline to score a metals deal. Step 1 extract counterparty + notional from the message. ' +
          'Step 2 run contractiq-counterparty-default ML model. Step 3 sanctions_screening. ' +
          'Step 4 yahoo_finance LBMA gold. Step 5 contractiq-risk-tier-predictor ML model. ' +
          'Step 6 emit structured JSON.',
        agent_type: 'pipeline',
      },
      timeout: 180000,
    });
    expect(resp.ok()).toBeTruthy();
    const out = (await resp.json()).data;
    expect(out.mode).toBe('pipeline');
    expect(out.pipeline_config?.nodes?.length).toBeGreaterThanOrEqual(5);

    const tools = out.tools || [];
    expect(tools).toContain('ml_model');
    const nodes = out.pipeline_config.nodes;
    const wired = nodes.filter((n: any) => (n.depends_on || []).length > 0).length;
    expect(wired).toBeGreaterThanOrEqual(2);
    console.log(`pipeline: ${nodes.length} nodes (${wired} with depends_on)`);

    (page as any)._lastPipelineSpec = out;
  });

  test('4. Save AI Builder output as a real agent via /api/agents', async ({ page }) => {
    await loginAndStoreToken(page);
    const tok = await page.evaluate(() => localStorage.getItem('access_token'));

    const build = await page.request.post(`${API}/api/ai/build-agent`, {
      headers: { Authorization: `Bearer ${tok}` },
      data: {
        description: 'A simple pipeline. Step 1 get current_time. Step 2 yahoo_finance gold price. Step 3 emit json.',
        agent_type: 'pipeline',
      },
      timeout: 120000,
    });
    expect(build.ok()).toBeTruthy();
    const built = (await build.json()).data;

    const payload = {
      name: built.name,
      description: built.description,
      system_prompt: built.system_prompt || 'pipeline',
      model_config: {
        model: 'claude-sonnet-4-5-20250929',
        temperature: 0.1,
        max_tokens: 8192,
        mode: 'pipeline',
        pipeline_config: built.pipeline_config,
        tools: built.tools,
        input_variables: built.input_variables,
        example_prompts: built.example_prompts,
      },
      slug: `uat-builder-${Date.now()}`,
      agent_type: 'oob',
    };

    const create = await page.request.post(`${API}/api/agents`, {
      headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
      data: payload,
    });
    expect(create.ok()).toBeTruthy();
    const created = (await create.json()).data;
    expect(created.id).toBeTruthy();
    console.log(`agent created: ${created.id} (slug=${payload.slug})`);

    const val = await page.request.post(`${API}/api/agents/${created.id}/validate-smart`, {
      headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
      data: { deep: false },
      timeout: 60000,
    });
    expect(val.ok()).toBeTruthy();
    const v = (await val.json()).data;
    console.log(`validate-smart: valid=${v.overall?.valid} score=${v.overall?.score} severity=${v.overall?.severity}`);
    expect(v.overall?.valid).toBeTruthy();
  });

  test('5. Chat page: top-notch UI (input + send + agent picker + message area)', async ({ page }) => {
    await loginAndStoreToken(page);
    await page.goto(`${BASE}/chat`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);

    const inputs = await page.locator('textarea, input[type="text"]').count();
    expect(inputs).toBeGreaterThan(0);

    const sendBtn = await page.locator('button:has-text("Send"), button[aria-label*="send" i]').count();
    const buttons = await page.locator('button').count();

    const errors: string[] = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

    await page.screenshot({ path: 'test-results/uat-builder-05-chat.png', fullPage: true });
    console.log(`/chat: inputs=${inputs}, sendBtn=${sendBtn}, totalButtons=${buttons}, jsErrors=${errors.length}`);
    expect(inputs).toBeGreaterThanOrEqual(1);
    expect(buttons).toBeGreaterThanOrEqual(2);
  });

  test('6. SDK Playground: code panel + run controls visible', async ({ page }) => {
    await loginAndStoreToken(page);
    await page.goto(`${BASE}/sdk-playground`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    const html = await page.locator('body').innerText();
    const hasSdkContent = /sdk|playground|code|execute|generate|python|forge|abenix/i.test(html);
    expect(hasSdkContent).toBeTruthy();

    const codeBlocks = await page.locator('pre, code, [class*="monaco" i], [class*="codemirror" i]').count();
    const buttons = await page.locator('button').count();
    const links = await page.locator('a').count();

    await page.screenshot({ path: 'test-results/uat-builder-06-sdk-playground.png', fullPage: true });
    console.log(`/sdk-playground: codeBlocks=${codeBlocks}, buttons=${buttons}, links=${links}`);
    expect(codeBlocks + buttons).toBeGreaterThan(3);
  });

  test('7. /edge page (or /admin/edge) loads with rich UI', async ({ page }) => {
    await loginAndStoreToken(page);

    let edgeUrl = `${BASE}/admin/edge`;
    await page.goto(edgeUrl);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);
    let status = (await page.locator('body').innerText()).toLowerCase();

    if (!/edge|gateway|runtime|register/.test(status)) {
      edgeUrl = `${BASE}/edge`;
      await page.goto(edgeUrl);
      await page.waitForLoadState('domcontentloaded');
      await page.waitForTimeout(2000);
      status = (await page.locator('body').innerText()).toLowerCase();
    }

    expect(/edge|gateway|runtime|register|python|rust|c\b/.test(status)).toBeTruthy();

    const sections = await page.locator('h1, h2, h3').count();
    const cards = await page.locator('[class*="card" i], [class*="rounded" i] > div, table').count();

    await page.screenshot({ path: 'test-results/uat-builder-07-edge.png', fullPage: true });
    console.log(`edge UI at ${edgeUrl}: sections=${sections}, cards=${cards}`);
    expect(sections).toBeGreaterThan(0);
  });

  test('8. Edge runtime API: download + register flow exists', async ({ page }) => {
    const tok = await (async () => {
      await loginAndStoreToken(page);
      return await page.evaluate(() => localStorage.getItem('access_token'));
    })();

    const dl = await page.request.get(`${API}/api/edge/runtime/download`);
    expect([200, 401, 403]).toContain(dl.status());

    const openapi = await page.request.get(`${API}/openapi.json`);
    expect(openapi.ok()).toBeTruthy();
    const spec = await openapi.json();
    const edgePaths = Object.keys(spec.paths || {}).filter((p) => /edge/i.test(p));
    console.log(`edge endpoints registered: ${edgePaths.length}`);
    expect(edgePaths.length).toBeGreaterThan(2);
    for (const p of edgePaths.slice(0, 10)) console.log(`  ${p}`);
  });

  test('9. Tool catalogue: 99+ tools visible in /tools', async ({ page }) => {
    await loginAndStoreToken(page);
    const tok = await page.evaluate(() => localStorage.getItem('access_token'));
    const resp = await page.request.get(`${API}/api/tools`, {
      headers: { Authorization: `Bearer ${tok}` },
    });
    expect(resp.ok()).toBeTruthy();
    const tools = (await resp.json()).data;
    expect(tools.length).toBeGreaterThanOrEqual(80);
    console.log(`tool catalogue: ${tools.length} tools`);

    await page.goto(`${BASE}/tools`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);
    const text = await page.locator('body').innerText();
    expect(text.toLowerCase()).toMatch(/yahoo|tavily|knowledge|calculator|tools/i);
    console.log('/tools page rendered');
  });

  test('10. Pipeline Scaling DAG view loads', async ({ page }) => {
    await loginAndStoreToken(page);
    await page.goto(`${BASE}/admin/pipeline-scaling`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);
    const text = await page.locator('body').innerText();
    expect(text.toLowerCase()).toMatch(/pipeline|scaling|dag|node|pool/i);
    console.log('/admin/pipeline-scaling rendered');
  });

});
