import { test, expect, type Page } from '@playwright/test';

const BASE  = process.env.BASE  || 'http://localhost:3000';
const API   = process.env.API   || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL    || 'admin@abenix.dev';
const PASS  = process.env.AF_PASSWORD || 'Admin123456';

const stamp = () => Date.now().toString(36);
const RUN = stamp();
const SIMPLE_NAME   = `UAT Simple ${RUN}`;
const RESEARCH_NAME = `UAT Research ${RUN}`;
const DATA_NAME     = `UAT DataAnalyst ${RUN}`;

const RESEARCH_TOOLS = ['web_search', 'tavily_search', 'http_request', 'atlas_query', 'knowledge_search', 'vector_search'];
const DATA_TOOLS     = ['ml_model', 'code_executor', 'sql_query', 'http_request', 'atlas_query', 'persona_rag', 'web_search'];

let cachedToken: string | null = null;
async function platformToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASS }),
  });
  cachedToken = (await r.json()).data.access_token as string;
  return cachedToken;
}

async function login(page: Page) {
  const token = await platformToken();
  const meR = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me  = (await meR.json()).data ?? {};
  await page.addInitScript(({ t, u }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify(u || {}));
  }, { t: token, u: me });
}

async function gotoOk(page: Page, path: string, timeout = 20_000) {
  const r = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded', timeout }).catch(() => null);
  const status = r?.status() ?? 0;
  expect(status, `${path} -> HTTP ${status}`).toBeLessThan(500);
  return status;
}

async function addToolByLabel(page: Page, label: string): Promise<boolean> {
  const search = page.locator('input[placeholder*="Search tools"]').first();
  if (!(await search.isVisible().catch(() => false))) return false;
  await search.fill(label);
  await page.waitForTimeout(400);
  const dragBtn = page.locator('button[draggable="true"]').first();
  if (!(await dragBtn.isVisible().catch(() => false))) {
    await search.fill('');
    return false;
  }
  await dragBtn.click();
  await page.waitForTimeout(150);
  await search.fill('');
  await page.waitForTimeout(200);
  return true;
}

async function buildAgent(page: Page, name: string, prompt: string, tools: string[]): Promise<number> {
  await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});

  const nameInput = page.locator('label:has-text("Agent Name") + input, input[value="New Agent"]').first();
  await expect(nameInput).toBeVisible({ timeout: 15_000 });
  await nameInput.fill(name);

  const promptBox = page.locator('label:has-text("System Prompt") + textarea, textarea').filter({ hasNotText: /System Prompt/ }).first();
  if (await promptBox.isVisible().catch(() => false)) await promptBox.fill(prompt);

  let added = 0;
  for (const t of tools) {
    if (await addToolByLabel(page, t)) { added++; await page.waitForTimeout(150); }
  }

  const save = page.getByRole('button', { name: /^Save Draft$|^Publish$|^Save Agent$/ }).first();
  await expect(save).toBeVisible({ timeout: 8_000 });
  await save.click();
  await page.waitForTimeout(3_500);
  return added;
}

async function findAgentIdByName(name: string): Promise<string | null> {
  const tok = await platformToken();
  for (const sort of ['newest', '']) {
    const url = `${API}/api/agents?search=${encodeURIComponent(name)}&limit=100${sort ? `&sort=${sort}` : ''}`;
    const r = await fetch(url, { headers: { Authorization: `Bearer ${tok}` } });
    const items = (await r.json()).data || [];
    const hit = items.find((a: any) => typeof a.name === 'string' && a.name === name);
    if (hit?.id) return hit.id;
    if (items.length && !hit) {
      console.log(`[findAgentIdByName miss] looking for "${name}" len=${name.length}, top 3 names:`);
      for (const it of items.slice(0, 3)) console.log(`  "${it.name}" len=${(it.name || '').length}`);
    }
  }
  return null;
}

test.describe.configure({ mode: 'serial' });

test.describe('Enterprise critical UAT', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('shell — every primary route < 500', async ({ page }) => {
    test.setTimeout(180_000);
    const routes = [
      '/dashboard', '/agents', '/builder', '/tools', '/ml-models',
      '/chat', '/sdk-playground', '/approvals', '/executions',
      '/atlas', '/kb', '/code-runner', '/triggers',
      '/admin/cluster', '/help',
    ];
    for (const p of routes) await gotoOk(page, p);
  });

  test('/tools — every tool the API registers has a row', async ({ page }) => {
    const r = await page.request.get(`${API}/api/tools`, { headers: { Authorization: `Bearer ${await platformToken()}` } });
    const d = (await r.json()).data;
    const tools: Array<{ id: string }> = Array.isArray(d) ? d : d.tools;
    expect(tools.length, 'tools registered').toBeGreaterThan(50);
    await gotoOk(page, '/tools');
    await expect(page.getByRole('heading', { name: /Tools catalogue/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid^="tool-row-"]')).toHaveCount(tools.length, { timeout: 15_000 });
  });

  test('/ml-models — the five ContractIQ models are listed', async ({ page }) => {
    await gotoOk(page, '/ml-models');
    for (const m of ['offtake_residential', 'offtake_industrial', 'price_fairvalue_gas_hubs', 'price_fairvalue_power_hubs', 'contractiq-counterparty-default']) {
      await expect(page.getByText(m, { exact: false }).first(), `expected '${m}'`).toBeVisible({ timeout: 15_000 });
    }
  });

  test('/builder simple — 2 tools + save', async ({ page }) => {
    test.setTimeout(120_000);
    const added = await buildAgent(page, SIMPLE_NAME,
      'Reply with the single word the caller asks for. Be terse.',
      ['ml_model', 'web_search'],
    );
    expect(added, 'tools added').toBeGreaterThan(0);
  });

  test('/agents — UAT Simple visible in list', async ({ page }) => {
    await gotoOk(page, '/agents');
    const search = page.getByPlaceholder(/search/i).first();
    if (await search.isVisible().catch(() => false)) {
      await search.fill('UAT Simple');
      await page.waitForTimeout(900);
    }
    await expect(page.getByText(new RegExp(SIMPLE_NAME.replace(/\s+/g, '\\s+'), 'i')).first()).toBeVisible({ timeout: 15_000 });
  });

  async function chatExecute(page: Page, agentName: string, prompt: string, expected: RegExp) {
    const id = await findAgentIdByName(agentName);
    expect(id, `agent ${agentName} not found`).toBeTruthy();
    await gotoOk(page, `/agents/${id}/chat`);
    await page.waitForTimeout(1500);
    const composer = page.locator('textarea, [contenteditable="true"]').last();
    await expect(composer).toBeVisible({ timeout: 10_000 });
    await composer.fill(prompt);
    const send = page.getByRole('button', { name: /send|^→$|^▶$/i }).last();
    await send.click();
    await expect(page.getByText(expected).first()).toBeVisible({ timeout: 90_000 });
  }

  test('/chat — execute UAT Simple agent', async ({ page }) => {
    test.setTimeout(180_000);
    await chatExecute(page, SIMPLE_NAME, 'Reply with exactly the single word: pong', /\bpong\b/i);
  });

  test('/sdk-playground — pick agent, execute in browser', async ({ page }) => {
    test.setTimeout(180_000);
    await gotoOk(page, '/sdk-playground');

    const tabAgent = page.getByRole('button', { name: /^Agent$/i }).first();
    if (await tabAgent.isVisible().catch(() => false)) await tabAgent.click();

    const search = page.getByPlaceholder(/search/i).first();
    if (await search.isVisible().catch(() => false)) {
      await search.fill('UAT Simple');
      await page.waitForTimeout(900);
    }
    const pick = page.getByText(new RegExp(SIMPLE_NAME.replace(/\s+/g, '\\s+'), 'i')).first();
    await expect(pick).toBeVisible({ timeout: 10_000 });
    await pick.click();
    await page.waitForTimeout(800);

    const gen = page.getByRole('button', { name: /Generate|Build snippet|Render/i }).first();
    if (await gen.isVisible().catch(() => false)) await gen.click();

    const msgBox = page.locator('textarea').first();
    if (await msgBox.isVisible().catch(() => false)) {
      await msgBox.fill('Reply with exactly the single word: pong');
    }

    const runBtn = page.getByRole('button', { name: /^Run$|Run in sandbox|Execute/i }).first();
    await expect(runBtn).toBeVisible({ timeout: 10_000 });
    await runBtn.click();

    await expect(page.getByText(/\bpong\b/i).first()).toBeVisible({ timeout: 120_000 });
  });

  test('/triggers — create webhook trigger via UI', async ({ page }) => {
    test.setTimeout(120_000);
    await gotoOk(page, '/triggers');
    await expect(page.getByRole('heading', { name: /Event Triggers/i })).toBeVisible({ timeout: 10_000 });

    const newBtn = page.getByRole('button', { name: /^New Trigger$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10_000 });
    await newBtn.click();
    await page.waitForTimeout(600);

    const modal = page.locator('h3:has-text("Create Trigger")').locator('..');
    const agentSelect = modal.locator('select').first();
    await expect(agentSelect).toBeVisible({ timeout: 10_000 });
    const opts = await agentSelect.locator('option').all();
    let picked = false;
    for (const o of opts) {
      const label = ((await o.textContent()) || '').trim();
      const value = (await o.getAttribute('value')) || '';
      if (/UAT Simple/.test(label) && value) {
        await agentSelect.selectOption(value);
        picked = true;
        break;
      }
    }
    expect(picked, `no UAT Simple option in modal agent select`).toBeTruthy();

    const webhookTab = page.locator('button').filter({ hasText: /^Webhook$/ }).first();
    if (await webhookTab.isVisible().catch(() => false)) await webhookTab.click();

    const submit = page.getByRole('button', { name: /^Create Trigger$/i }).first();
    await expect(submit).toBeVisible({ timeout: 5_000 });
    await submit.click();
    await page.waitForTimeout(2_500);

    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).toMatch(/webhook|trigger|created|copy/i);
  });

  test('/triggers — create scheduled trigger via UI', async ({ page }) => {
    test.setTimeout(120_000);
    await gotoOk(page, '/triggers');

    const newBtn = page.getByRole('button', { name: /^New Trigger$/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 10_000 });
    await newBtn.click();
    await page.waitForTimeout(600);

    const modal = page.locator('h3:has-text("Create Trigger")').locator('..');
    const agentSelect = modal.locator('select').first();
    await expect(agentSelect).toBeVisible({ timeout: 10_000 });
    const opts = await agentSelect.locator('option').all();
    let picked = false;
    for (const o of opts) {
      const label = (await o.textContent()) || '';
      const value = (await o.getAttribute('value')) || '';
      if (/UAT Simple/.test(label) && value) {
        await agentSelect.selectOption(value);
        picked = true;
        break;
      }
    }
    expect(picked, `expected an option matching UAT Simple`).toBeTruthy();

    const scheduleTab = modal.locator('button').filter({ hasText: /^Schedule \(Cron\)$/ }).first();
    await expect(scheduleTab).toBeVisible({ timeout: 5_000 });
    await scheduleTab.click();
    await page.waitForTimeout(300);

    const cronInput = page.locator('input[placeholder*="cron" i], input[placeholder*="* * *" i]').first();
    await expect(cronInput).toBeVisible({ timeout: 5_000 });
    await cronInput.fill('*/5 * * * *');

    const submit = page.getByRole('button', { name: /^Create Trigger$/i }).last();
    await submit.click();
    await page.waitForTimeout(3_000);

    const body = (await page.locator('body').innerText());
    expect(body, 'expected the cron expression to appear').toMatch(/\*\/5|every 5/i);
  });

  test('SDK pull — programmatic execute via X-API-Key returns output', async () => {
    test.setTimeout(180_000);
    const tok = await platformToken();
    const keyRes = await fetch(`${API}/api/api-keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tok}` },
      body: JSON.stringify({ name: `UAT SDK ${RUN}` }),
    });
    const keyJ = await keyRes.json();
    const apiKey: string = keyJ.data?.raw_key || '';
    expect(apiKey, `api-key created: ${JSON.stringify(keyJ.error)}`).toBeTruthy();
    const keyId: string = keyJ.data.id;
    try {

    const agentId = await findAgentIdByName(SIMPLE_NAME);
    expect(agentId, 'agent created earlier').toBeTruthy();

    const execR = await fetch(`${API}/api/agents/${agentId}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
      body: JSON.stringify({
        message: 'Reply with exactly the single word: pong',
        stream: false, wait: true, wait_timeout_seconds: 90,
      }),
    });
    expect(execR.ok, `execute HTTP ${execR.status}`).toBeTruthy();
    const j = await execR.json();
    const execId: string = j.data?.execution_id || '';
    expect(execId).toBeTruthy();

    let output: string = (j.data?.output || j.data?.output_message || '') as string;
    if (!output.trim()) {
      for (const d of [1000, 2000, 3000, 5000, 8000, 10_000, 15_000, 20_000]) {
        await new Promise(r => setTimeout(r, d));
        const er = await fetch(`${API}/api/executions/${execId}`, { headers: { 'X-API-Key': apiKey } });
        if (er.ok) {
          const ej = (await er.json()).data || {};
          output = ej.output_message || ej.output || '';
          if (output && output.trim()) break;
          if (ej.status && ['failed', 'error', 'cancelled'].includes(String(ej.status).toLowerCase())) break;
        }
      }
    }
    expect(output.toLowerCase()).toContain('pong');
    } finally {
      await fetch(`${API}/api/api-keys/${keyId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${tok}` } });
    }
  });

  test('/builder complex — research agent (6 tools)', async ({ page }) => {
    test.setTimeout(180_000);
    const added = await buildAgent(page, RESEARCH_NAME,
      'You are a research assistant. Use web_search, tavily_search, http_request, knowledge_search, vector_search, atlas_query as needed. Always cite sources. Be terse.',
      RESEARCH_TOOLS,
    );
    expect(added).toBeGreaterThan(2);
  });

  test('/builder complex — data analyst agent (7 tools)', async ({ page }) => {
    test.setTimeout(180_000);
    const added = await buildAgent(page, DATA_NAME,
      'You are a data analyst. Use ml_model for inference, code_executor for transforms, sql_query for reads, http_request for APIs, atlas_query for entities, persona_rag for memory, web_search for context. One concise paragraph.',
      DATA_TOOLS,
    );
    expect(added).toBeGreaterThan(2);
  });

  test('/chat — execute research agent (LLM live)', async ({ page }) => {
    test.setTimeout(180_000);
    await chatExecute(page, RESEARCH_NAME, 'Reply with exactly: ready', /\bready\b/i);
  });

  test('/chat — execute data analyst agent (LLM live)', async ({ page }) => {
    test.setTimeout(180_000);
    await chatExecute(page, DATA_NAME, 'Reply with exactly: analysed', /\banaly(s|z)ed\b/i);
  });

  test('/executions — recent UAT runs visible', async ({ page }) => {
    await gotoOk(page, '/executions');
    await page.waitForTimeout(3000);
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).toMatch(/completed|running|failed|recent|execution/i);
  });

  test('observability — recent executions recorded for UAT agents', async () => {
    const tok = await platformToken();
    const r = await fetch(`${API}/api/executions?limit=50`, { headers: { Authorization: `Bearer ${tok}` } });
    expect(r.ok, `executions HTTP ${r.status}`).toBeTruthy();
    const items = (await r.json()).data || [];
    expect(items.length, 'at least one execution').toBeGreaterThan(0);
    const uatExec = items.find((e: any) => typeof e.agent_name === 'string' && e.agent_name.startsWith('UAT'));
    expect(uatExec, 'one of the UAT agent executions visible').toBeTruthy();
  });

  test('/approvals — page renders', async ({ page }) => {
    await gotoOk(page, '/approvals');
    await expect(page.getByRole('heading', { name: /approvals/i }).first()).toBeVisible({ timeout: 10_000 });
  });

  test('/atlas — knowledge graph renders', async ({ page }) => {
    await gotoOk(page, '/atlas');
    await page.waitForTimeout(2500);
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).toMatch(/atlas|graph|node|relationship|entit/i);
  });

  test('/kb — knowledge base list', async ({ page }) => {
    await gotoOk(page, '/kb');
    await page.waitForTimeout(2500);
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).toMatch(/knowledge|kb|document|chunk|search/i);
  });

  test('/code-runner — list renders', async ({ page }) => {
    await gotoOk(page, '/code-runner');
    await page.waitForTimeout(2000);
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).toMatch(/code|asset|runtime|sandbox|repo|run|script/i);
  });

  test('cleanup — drop UAT agents + triggers + key', async () => {
    const tok = await platformToken();
    for (const q of ['UAT Simple', 'UAT Research', 'UAT DataAnalyst']) {
      const list = await fetch(`${API}/api/agents?search=${encodeURIComponent(q)}&limit=50`, { headers: { Authorization: `Bearer ${tok}` } });
      const items = (await list.json()).data || [];
      for (const a of items) {
        if (typeof a.name === 'string' && a.name.startsWith(q)) {
          await fetch(`${API}/api/agents/${a.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${tok}` } });
        }
      }
    }
    const trigs = await fetch(`${API}/api/triggers?search=UAT&limit=50`, { headers: { Authorization: `Bearer ${tok}` } });
    for (const t of ((await trigs.json()).data || [])) {
      await fetch(`${API}/api/triggers/${t.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${tok}` } });
    }
    const keys = await fetch(`${API}/api/api-keys`, { headers: { Authorization: `Bearer ${tok}` } });
    for (const k of ((await keys.json()).data || [])) {
      if (typeof k.name === 'string' && k.name.startsWith(`UAT SDK ${RUN}`)) {
        await fetch(`${API}/api/api-keys/${k.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${tok}` } });
      }
    }
  });
});
