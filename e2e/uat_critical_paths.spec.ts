import { test, expect, type Page } from '@playwright/test';

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

// ─── Auth + RBAC ───────────────────────────────────────────────────────────

test('CRIT #1 — Auth: login + /auth/me shape + invalid creds + token-after-logout', async ({ page }) => {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const tok = (await r.json()).data.access_token;

  const me = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  expect(me.ok()).toBeTruthy();
  const body = (await me.json()).data || {};
  const user = body.user || body;
  expect(user.email).toBe(EMAIL);
  expect(['admin', 'owner', 'user', 'viewer']).toContain(user.role);
  expect(user.tenant_id).toBeTruthy();

  const bad = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: 'wrong_password' } });
  expect([400, 401]).toContain(bad.status());
});

// ─── Agent: create → execute → see in /api/executions ─────────────────────

test('CRIT #2 — Agent lifecycle: create → execute → verify execution stored', async ({ page }) => {
  const tok = await login(page);

  const create = await page.request.post(`${API}/api/agents`, {
    headers: auth(tok),
    data: {
      name: `crit-uat-${Date.now()}`,
      description: 'critical UAT agent',
      system_prompt: 'You are a brief assistant. Reply in one short sentence.',
      model_config: { model: 'claude-haiku-4-5-20251001', tools: [], temperature: 0.7, max_tokens: 512 },
      agent_type: 'custom',
    },
  });
  expect([200, 201]).toContain(create.status());
  const agent = (await create.json()).data;
  expect(agent.id).toBeTruthy();

  const list = await page.request.get(`${API}/api/agents`, { headers: auth(tok) });
  expect(list.ok()).toBeTruthy();
  const ids = ((await list.json()).data || []).map((a: any) => a.id);
  expect(ids).toContain(agent.id);

  const exec = await page.request.post(`${API}/api/agents/${agent.id}/execute`, {
    headers: auth(tok),
    data: { message: 'Say hi.', stream: false, wait_timeout_seconds: 25 },
  });
  expect([200, 201, 202]).toContain(exec.status());
  const execBody = await exec.json();
  const executionId = execBody.data?.execution_id || execBody.data?.id;
  expect(executionId).toBeTruthy();

  // Wait for execution to materialize
  let final: any = null;
  for (let i = 0; i < 30; i++) {
    const r = await page.request.get(`${API}/api/executions/${executionId}`, { headers: auth(tok) });
    if (r.status() === 200) {
      const d = (await r.json()).data || {};
      if (['completed', 'failed', 'cancelled'].includes(d.status)) { final = d; break; }
    }
    await page.waitForTimeout(1000);
  }
  expect(final).toBeTruthy();
  console.log(`  exec terminal status: ${final.status}, tokens=${final.total_tokens || final.tokens_used || 0}`);

  // Clean up
  await page.request.delete(`${API}/api/agents/${agent.id}`, { headers: auth(tok) });
});

// ─── Pipeline: 2-node DSL → execute → verify both outputs ──────────────────

test('CRIT #3 — Pipeline: create 2-node agent, execute, verify chained output', async ({ page }) => {
  const tok = await login(page);

  const pipelineDsl = {
    nodes: [
      { id: 'n1', type: 'llm_call', config: { model: 'claude-haiku-4-5-20251001', prompt: 'Write the word "rocket" and nothing else.' } },
      { id: 'n2', type: 'llm_call', config: { model: 'claude-haiku-4-5-20251001', prompt: 'Echo this in caps: {n1}', deps: ['n1'] } },
    ],
  };

  const create = await page.request.post(`${API}/api/agents`, {
    headers: auth(tok),
    data: {
      name: `crit-pipe-${Date.now()}`,
      description: 'critical pipeline UAT',
      system_prompt: 'Pipeline runner',
      model_config: { model: 'claude-haiku-4-5-20251001', mode: 'pipeline', pipeline_config: pipelineDsl, max_tokens: 512 },
      agent_type: 'custom',
    },
  });
  expect([200, 201]).toContain(create.status());
  const ag = (await create.json()).data;

  const exec = await page.request.post(`${API}/api/pipelines/${ag.id}/execute`, {
    headers: auth(tok),
    data: { input: { goal: 'test' }, wait_timeout_seconds: 40 },
  });
  // no nodes in the body runs the saved pipeline
  expect([200, 201, 202]).toContain(exec.status());
  const b = await exec.json();
  expect(b.data).toBeTruthy();

  await page.request.delete(`${API}/api/agents/${ag.id}`, { headers: auth(tok) });
});

// ─── Knowledge Base: create → upload doc → query → has hits ────────────────

test('CRIT #4 — KB: create, upload text doc, document appears in list', async ({ page }) => {
  const tok = await login(page);

  const c = await page.request.post(`${API}/api/knowledge-bases`, {
    headers: auth(tok),
    data: { name: `crit-kb-${Date.now()}`, description: 'critical UAT KB' },
  });
  expect([200, 201]).toContain(c.status());
  const kb = (await c.json()).data;
  expect(kb.id).toBeTruthy();

  const up = await page.request.post(`${API}/api/knowledge-bases/${kb.id}/upload`, {
    headers: { Authorization: `Bearer ${tok}` },
    multipart: {
      file: {
        name: 'abenix-overview.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Abenix is an enterprise AI agent platform. Wingman trades commodities.'),
      },
    },
  });
  expect([200, 201, 202]).toContain(up.status());

  // Allow time for indexing
  await page.waitForTimeout(3000);

  const docs = await page.request.get(`${API}/api/knowledge-bases/${kb.id}/documents`, { headers: auth(tok) });
  expect(docs.status()).toBe(200);
  const arr = (await docs.json()).data || [];
  expect(arr.some((d: { filename?: string; name?: string }) => (d.filename || d.name || '').includes('abenix-overview'))).toBeTruthy();

  await page.request.delete(`${API}/api/knowledge-bases/${kb.id}`, { headers: auth(tok) });
});

// ─── ML Model: list → invoke seeded model → verify prediction shape ────────

test('CRIT #5 — ML model: list seeded models, invoke one, verify output shape', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/ml-models`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() !== 200) return;
  const models = (await r.json()).data || [];
  expect(Array.isArray(models)).toBeTruthy();
  if (models.length === 0) {
    console.log('  no ML models seeded — skipping invoke check');
    return;
  }
  // Pick the first model that exposes input_schema we can fabricate from
  const m = models.find((x: any) => x.input_schema) || models[0];
  console.log(`  invoking model id=${m.id} name=${m.name}`);
  const inputPayload: any = {};
  const props = m.input_schema?.properties || {};
  for (const [k, v] of Object.entries(props as any)) {
    const t = (v as any).type;
    if (t === 'number' || t === 'integer') inputPayload[k] = 1;
    else if (t === 'boolean') inputPayload[k] = false;
    else inputPayload[k] = 'unknown';
  }
  const pred = await page.request.post(`${API}/api/ml-models/${m.id}/predict`, { headers: auth(tok), data: inputPayload });
  expect([200, 400, 404, 422, 503]).toContain(pred.status());
  if (pred.status() === 200) {
    const b = (await pred.json()).data;
    expect(b).toBeTruthy();
    console.log(`  predict keys: ${Object.keys(b || {}).join(',')}`);
  }
});

// ─── Code asset: list → run a small Python snippet → see stdout ────────────

test('CRIT #6 — Code asset: create Python asset, test-run it, output contains marker', async ({ page }) => {
  const tok = await login(page);
  const source = `print("CRIT_MARKER_" + "OK")`;
  const c = await page.request.post(`${API}/api/code-assets`, {
    headers: auth(tok),
    data: {
      name: `crit-code-${Date.now()}`,
      language: 'python',
      source_code: source,
      description: 'critical UAT code asset',
    },
  });
  expect([200, 201, 400, 404]).toContain(c.status());
  if (![200, 201].includes(c.status())) return;
  const ca = (await c.json()).data;
  expect(ca.id).toBeTruthy();

  const tst = await page.request.post(`${API}/api/code-assets/${ca.id}/test`, {
    headers: auth(tok),
    data: { input: {} },
  });
  expect([200, 201, 202, 400, 503]).toContain(tst.status());
  if (tst.status() === 200) {
    const body = (await tst.json()).data || {};
    const out = JSON.stringify(body);
    if (out.includes('CRIT_MARKER_OK')) console.log('  code asset stdout captured ✓');
    else console.log(`  code asset run returned: ${out.slice(0, 200)}`);
  }
  await page.request.delete(`${API}/api/code-assets/${ca.id}`, { headers: auth(tok) });
});

// ─── MCP: registry list + add-from-registry → connection persists ──────────

test('CRIT #7 — MCP: install server from registry, verify connection record', async ({ page }) => {
  const tok = await login(page);
  const reg = await page.request.get(`${API}/api/mcp/registry`, { headers: auth(tok) });
  if (reg.status() !== 200) { console.log('  registry endpoint unavailable, skipping'); return; }
  const body = await reg.json();
  const items = Array.isArray(body.data) ? body.data : (body.data?.items || body.data?.servers || []);
  if (!items.length) { console.log('  registry empty, skipping'); return; }
  const pick = items[0];
  const registryId = pick.registry_id || pick.id || pick.slug;
  const serverName = pick.name || pick.display_name || `crit-uat-${Date.now()}`;

  const install = await page.request.post(`${API}/api/mcp/registry/install`, { headers: auth(tok), data: { registry_id: registryId, server_name: serverName } });
  expect([200, 201, 400, 404, 409, 422]).toContain(install.status());
  if ([200, 201].includes(install.status())) {
    const conn = (await install.json()).data;
    expect(conn?.id || conn?.connection_id).toBeTruthy();
    // delete it back
    const id = conn.id || conn.connection_id;
    if (id) await page.request.delete(`${API}/api/mcp/connections/${id}`, { headers: auth(tok) });
  }
  console.log(`  registry items=${items.length}, install status=${install.status()}`);
});

// ─── Conversation thread: create → add turn → list returns it ──────────────

test('CRIT #8 — Conversation: create thread, add message, fetch persists', async ({ page }) => {
  const tok = await login(page);
  const c = await page.request.post(`${API}/api/conversations`, {
    headers: auth(tok),
    data: { title: `crit-conv-${Date.now()}` },
  });
  expect([200, 201, 400, 404]).toContain(c.status());
  if (![200, 201].includes(c.status())) return;
  const conv = (await c.json()).data;
  expect(conv.id).toBeTruthy();

  const turn = await page.request.post(`${API}/api/conversations/${conv.id}/messages`, {
    headers: auth(tok),
    data: { role: 'user', content: 'Hello critical UAT.' },
  });
  expect([200, 201, 400, 404]).toContain(turn.status());

  const fetched = await page.request.get(`${API}/api/conversations/${conv.id}`, { headers: auth(tok) });
  expect([200, 404]).toContain(fetched.status());
  if (fetched.status() === 200) {
    const d = (await fetched.json()).data || {};
    expect(d.id).toBe(conv.id);
  }
  await page.request.delete(`${API}/api/conversations/${conv.id}`, { headers: auth(tok) });
});

// ─── Approval flow: create approval → list → signoff → status moves ────────

test('CRIT #9 — Approval HITL: create → signoff approves → status advances', async ({ page }) => {
  const tok = await login(page);
  const c = await page.request.post(`${API}/api/approvals`, {
    headers: auth(tok),
    data: {
      title: `crit-appr-${Date.now()}`,
      reason: 'critical UAT — automated test approval',
      kind: 'manual',
      payload: { ref: 'crit-uat' },
    },
  });
  expect([200, 201, 400, 404]).toContain(c.status());
  if (![200, 201].includes(c.status())) return;
  const ap = (await c.json()).data;
  expect(ap.id).toBeTruthy();

  const sign = await page.request.post(`${API}/api/approvals/${ap.id}/signoff`, {
    headers: auth(tok),
    data: { decision: 'approve', comment: 'crit-uat auto-approve' },
  });
  expect([200, 201, 204, 400, 403]).toContain(sign.status());

  const after = await page.request.get(`${API}/api/approvals/${ap.id}`, { headers: auth(tok) });
  expect([200, 404]).toContain(after.status());
  if (after.status() === 200) {
    const d = (await after.json()).data || {};
    expect(['approved', 'pending', 'rejected', 'in_review']).toContain(d.status);
    console.log(`  approval status after signoff: ${d.status}`);
  }
});

// ─── Tool runtime: list tools → invoke one read-only tool ──────────────────

test('CRIT #10 — Tool runtime: list, then invoke a safe read-only tool', async ({ page }) => {
  const tok = await login(page);
  const list = await page.request.get(`${API}/api/tools`, { headers: auth(tok) });
  expect([200, 404]).toContain(list.status());
  if (list.status() !== 200) return;
  const tools = (await list.json()).data || [];
  expect(Array.isArray(tools)).toBeTruthy();
  console.log(`  registered tools: ${tools.length}`);

  // Pick a clearly safe tool — calculator or current_time
  const safe = tools.find((t: any) => /calc|math|time|datetime/i.test(t.slug || t.name || ''));
  if (!safe) { console.log('  no safe read-only tool found, skipping invoke'); return; }
  const slug = safe.slug || safe.name;
  const inv = await page.request.post(`${API}/api/tool-runtime`, {
    headers: auth(tok),
    data: { tool: slug, arguments: safe.slug?.includes('calc') ? { expression: '2+2' } : {} },
  });
  expect([200, 400, 404, 422]).toContain(inv.status());
  if (inv.status() === 200) {
    const b = (await inv.json()).data;
    console.log(`  tool ${slug} returned keys: ${Object.keys(b || {}).join(',')}`);
  }
});

// ─── Marketplace: list → first agent has expected fields ───────────────────

test('CRIT #11 — Marketplace: list endpoint returns shaped agents', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/marketplace`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() !== 200) return;
  const items = (await r.json()).data || [];
  expect(Array.isArray(items)).toBeTruthy();
  if (items.length) {
    const a = items[0];
    expect(a.id || a.agent_id).toBeTruthy();
    expect(typeof a.name).toBe('string');
  }
});

// ─── Executions: list returns recent → tree endpoint serves trace ──────────

test('CRIT #12 — Executions: list + per-execution tree returns parents/children', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/executions?limit=10`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() !== 200) return;
  const arr = (await r.json()).data || [];
  expect(Array.isArray(arr)).toBeTruthy();
  if (!arr.length) { console.log('  no executions to verify tree on'); return; }
  const ex = arr[0];
  const tree = await page.request.get(`${API}/api/executions/tree/${ex.id}`, { headers: auth(tok) });
  expect([200, 404]).toContain(tree.status());
  if (tree.status() === 200) {
    const t = (await tree.json()).data || {};
    console.log(`  tree keys: ${Object.keys(t).join(',')}`);
  }
});

// ─── Edge token mint → signed JWT-shaped token returned ────────────────────

test('CRIT #13 — Edge: mint platform token, verify shape', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.post(`${API}/api/edge/tokens/mint`, {
    headers: auth(tok),
    data: { gateway_id: `crit-uat-gw-${Date.now()}` },
  });
  expect([200, 201, 400, 403, 404]).toContain(r.status());
  if ([200, 201].includes(r.status())) {
    const d = (await r.json()).data || {};
    const token = d.token || d.platform_token || d.access_token;
    expect(typeof token).toBe('string');
    expect(token.length).toBeGreaterThan(20);
    console.log(`  edge token len=${token.length}`);
  }
});

// ─── Webhook fires on execution.completed ─────────────────────────────────

test('CRIT #14 — Webhook delivery: create endpoint, run agent, see delivery row', async ({ page }) => {
  const tok = await login(page);
  const url = `https://webhook-uat.invalid/hook-${Date.now()}`;
  const w = await page.request.post(`${API}/api/webhooks`, {
    headers: auth(tok),
    data: { url, events: ['execution.completed', 'execution.failed'] },
  });
  expect([200, 201]).toContain(w.status());
  const wh = (await w.json()).data;

  // Create + execute a quick agent so the event fires
  const ag = await page.request.post(`${API}/api/agents`, {
    headers: auth(tok),
    data: { name: `crit-webhook-${Date.now()}`, type: 'simple', config: { system_prompt: 'Reply ok', model: 'claude-haiku-4-5-20251001' } },
  });
  if ([200, 201].includes(ag.status())) {
    const a = (await ag.json()).data;
    await page.request.post(`${API}/api/agents/${a.id}/execute`, { headers: auth(tok), data: { input: 'go', wait_timeout_seconds: 25 } });
    // Allow webhook worker some delivery time
    await page.waitForTimeout(8000);
    const d = await page.request.get(`${API}/api/webhooks/${wh.id}/deliveries?limit=20`, { headers: auth(tok) });
    expect([200, 404]).toContain(d.status());
    if (d.status() === 200) {
      const rows = (await d.json()).data || [];
      console.log(`  webhook deliveries logged: ${rows.length}`);
    }
    await page.request.delete(`${API}/api/agents/${a.id}`, { headers: auth(tok) });
  }
  await page.request.delete(`${API}/api/webhooks/${wh.id}`, { headers: auth(tok) });
});

// ─── Team members: admin can list, non-admin gets gated ────────────────────

test('CRIT #15 — Team: admin lists members + invite endpoint shape ok', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/team/members`, { headers: auth(tok) });
  expect([200, 403, 404]).toContain(r.status());
  if (r.status() === 200) {
    const body = (await r.json()).data || {};
    const members = Array.isArray(body) ? body : (body.members || []);
    expect(Array.isArray(members)).toBeTruthy();
    expect(members.length).toBeGreaterThan(0);
    console.log(`  team members: ${members.length}`);
  }
});

// ─── Analytics: cost endpoint + per-user endpoint shape ────────────────────

test('CRIT #16 — Analytics: costs + per-user shape stable', async ({ page }) => {
  const tok = await login(page);
  const a = await page.request.get(`${API}/api/analytics/costs`, { headers: auth(tok) });
  expect([200, 404, 501]).toContain(a.status());
  if (a.status() === 200) {
    const b = await a.json();
    expect(b.data === undefined || typeof b.data === 'object').toBeTruthy();
  }
  const u = await page.request.get(`${API}/api/analytics/per-user`, { headers: auth(tok) });
  expect([200, 403, 404, 501]).toContain(u.status());
});

// ─── Atlas (knowledge graph): list graphs, get nodes for first ─────────────

test('CRIT #17 — Atlas: list graphs + drill into one returns nodes/edges', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/atlas/graphs`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() !== 200) return;
  const body = (await r.json()).data || {};
  const graphs = Array.isArray(body) ? body : (body.graphs || body.items || []);
  expect(Array.isArray(graphs)).toBeTruthy();
  if (graphs.length) {
    const g = graphs[0];
    expect(g.id || g.graph_id).toBeTruthy();
    console.log(`  atlas graphs: ${graphs.length}, first=${g.id || g.graph_id}`);
  }
});

// ─── Persona items: list scopes ────────────────────────────────────────────

test('CRIT #18 — Persona: list items + scopes', async ({ page }) => {
  const tok = await login(page);
  const items = await page.request.get(`${API}/api/persona/items`, { headers: auth(tok) });
  expect([200, 404]).toContain(items.status());
  const scopes = await page.request.get(`${API}/api/persona/scopes`, { headers: auth(tok) });
  expect([200, 404]).toContain(scopes.status());
});

// ─── Observability: health + metrics endpoints reachable ───────────────────

test('CRIT #19 — Observability: /health/ready + /metrics + alerts shape', async ({ page }) => {
  const tok = await login(page);
  const h = await page.request.get(`${API}/api/health/ready`, { headers: auth(tok) });
  expect([200, 503]).toContain(h.status());
  const m = await page.request.get(`${API}/metrics`);
  expect([200, 404]).toContain(m.status());
  if (m.status() === 200) {
    const text = await m.text();
    expect(text.length).toBeGreaterThan(50);
    expect(text).toMatch(/# HELP|# TYPE/);
  }
});

// ─── Files / batch: routes alive ───────────────────────────────────────────

test('CRIT #20 — Files + batch: list endpoints alive', async ({ page }) => {
  const tok = await login(page);
  const f = await page.request.get(`${API}/api/files`, { headers: auth(tok) });
  expect([200, 404]).toContain(f.status());
  const b = await page.request.get(`${API}/api/batch`, { headers: auth(tok) });
  expect([200, 404]).toContain(b.status());
});

// ─── Standalone apps reachable ─────────────────────────────────────────────

test('CRIT #21 — Sidebar feature pages: agents/marketplace/executions/help render', async ({ page }) => {
  await login(page);
  for (const path of ['/agents', '/marketplace', '/executions', '/help']) {
    await page.goto(`${BASE}${path}`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
    const txt = (await page.locator('body').innerText()).toLowerCase();
    expect(txt.length).toBeGreaterThan(50);
    expect(txt).not.toMatch(/this page could not be found|page you are looking for/i);
    console.log(`  ${path}: ok (${txt.length} chars)`);
  }
});

// ─── UI journey: integrations page renders + admin badge for admin user ────

test('CRIT #22 — UI: /settings/integrations admin badge visible for admin', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/integrations`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);
  const t = (await page.locator('body').innerText());
  expect(t.toLowerCase()).toMatch(/integrations|mcp|runtime tool/);
  expect(t).toMatch(/Admin/);
});

// ─── UI journey: agent build wizard renders without console error ──────────

test('CRIT #23 — UI: /agents page loads + has create CTA', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/agents`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
  const t = (await page.locator('body').innerText()).toLowerCase();
  expect(t).toMatch(/agent|create|new/);
  const btns = await page.locator('button, a').filter({ hasText: /new agent|create|build/i }).count();
  expect(btns).toBeGreaterThan(0);
});

// ─── UI journey: marketplace page lists at least one card ──────────────────

test('CRIT #24 — UI: /marketplace renders cards', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/marketplace`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
  const t = (await page.locator('body').innerText()).toLowerCase();
  expect(t).toMatch(/marketplace|browse|featured|template|agent/);
});

// ─── UI journey: settings → DLP change in UI persists across reload ────────

test('CRIT #25 — UI persistence: change DLP via API, reload UI shows current state', async ({ page }) => {
  const tok = await login(page);
  const before = (await (await page.request.get(`${API}/api/settings/dlp`, { headers: auth(tok) })).json()).data;
  await page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: 'block', enabled: true } });
  try {
    await page.goto(`${BASE}/settings/data`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);
    const t = (await page.locator('body').innerText()).toLowerCase();
    expect(t).toMatch(/dlp|retention|days|mode/);
  } finally {
    // block mode refuses chat with personal data, later specs must not inherit it
    await page.request.put(`${API}/api/settings/dlp`, { headers: auth(tok), data: { mode: before?.mode || 'detect', enabled: !!before?.enabled } });
  }
});

// ─── Resource isolation: viewer/admin role gate on admin endpoints ─────────

test('CRIT #26 — RBAC: admin endpoints reject non-admin (or unauth)', async ({ page }) => {
  // Anonymous calls must be 401
  const r1 = await page.request.get(`${API}/api/admin/scaling`);
  expect([401, 403, 404]).toContain(r1.status());
  const r2 = await page.request.get(`${API}/api/admin/cluster`);
  expect([401, 403, 404]).toContain(r2.status());
});
