/**
 * Wave two of the exploratory pass: the flows a new user reaches once the
 * basics work, and where the moving parts are most numerous.
 *
 *   A. AI Builder: describe an agent in prose, build it, run what came back.
 *   B. Human in the loop: an agent that must stop for sign-off, and whether
 *      the approval actually gates the run.
 *   C. Knowledge: create a KB, upload a document, cognify it, and ask an agent
 *      something only that document can answer.
 *
 * Findings go to test-results/platform-gaps-complex.json. Request bodies are
 * built from the live OpenAPI so a renamed field shows up as a finding rather
 * than a guess.
 *
 *   USE_K8S=true npx playwright test e2e/uat_gaps_complex_flows.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const OUT = path.join('test-results', 'platform-gaps-complex.json');
const SHOTS = path.join('test-results', 'gaps');

type Finding = { area: string; severity: 'blocker' | 'major' | 'minor' | 'note'; what: string; evidence?: unknown; screenshot?: string };
const findings: Finding[] = [];
function note(f: Finding) { findings.push(f); console.log(`  [${f.severity}] ${f.area}: ${f.what}`); }

let token = '';
let openapi: any = null;

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(res.ok(), 'login').toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
  if (!openapi) { try { openapi = await (await page.request.get(`${API}/openapi.json`)).json(); } catch {} }
}

// Playwright's request context gives up after 15 seconds by default. A run
// that asks the server to hold the connection for five minutes needs longer.
async function api(page: Page, method: string, p: string, body?: unknown, timeoutMs = 30_000) {
  const opts = {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
    timeout: timeoutMs,
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

/** Required + optional property names of a route's JSON body, from OpenAPI. */
function bodyShape(method: string, route: string): { required: string[]; props: string[] } {
  const op = openapi?.paths?.[route]?.[method.toLowerCase()];
  let schema = op?.requestBody?.content?.['application/json']?.schema;
  if (schema?.$ref) schema = openapi.components.schemas[schema.$ref.split('/').pop()];
  return { required: schema?.required ?? [], props: Object.keys(schema?.properties ?? {}) };
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const p = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}
async function bodyText(page: Page) { return (await page.locator('body').innerText()).slice(0, 30000); }
async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}
async function runAgent(page: Page, agentId: string, message: string, timeoutS = 240) {
  const r = await api(page, 'POST', `/api/agents/${agentId}/execute`, { message, stream: false, wait: true, wait_timeout_seconds: timeoutS }, (timeoutS + 30) * 1000);
  const d = r.json?.data ?? {};
  const raw = d.output ?? d.final_output ?? d.result ?? '';
  return { http: r.status, status: d.status, failure_code: d.failure_code,
    output: (typeof raw === 'string' ? raw : JSON.stringify(raw)).slice(0, 1500),
    error: String(d.error ?? d.error_message ?? '').slice(0, 600), execution_id: d.id ?? d.execution_id };
}
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

test.describe.serial('platform gaps, complex flows', () => {
  test.setTimeout(25 * 60 * 1000);
  test.afterAll(() => {
    fs.mkdirSync('test-results', { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), findings }, null, 2));
    console.log(`\n  ${findings.length} findings -> ${OUT}`);
  });

  test('A. AI Builder, from a sentence to a running agent', async ({ page }) => {
    await login(page);
    await visit(page, '/builder');
    const shotBefore = await shot(page, '10-builder-landing');
    const t = await bodyText(page);
    note({ area: 'ai builder page', severity: /describe|generate|build with ai|prompt/i.test(t) ? 'note' : 'major',
      what: /describe|generate|build with ai/i.test(t) ? 'page offers a describe-and-build entry' : 'page gives no obvious describe-and-build entry', screenshot: shotBefore });

    const shape = bodyShape('post', '/api/ai/build-agent');
    note({ area: 'ai builder api', severity: 'note', what: `build-agent body: required ${JSON.stringify(shape.required)} props ${JSON.stringify(shape.props)}` });

    // A description that needs two tools and a judgement, the kind of thing a
    // first-time user types.
    const description = 'An agent that takes a company name, looks up recent news about it, calculates the ' +
      'number of days since the most recent article, and returns a one-paragraph summary with that number.';
    const t0 = Date.now();
    // The builder takes a while, it is an LLM call that drafts a whole config.
    const built = await api(page, 'POST', '/api/ai/build-agent', { description, mode: 'agent' }, 300_000);
    const secs = Math.round((Date.now() - t0) / 1000);
    const cfg = built.json?.data ?? built.json ?? {};
    note({ area: 'ai builder build', severity: built.status < 400 ? 'note' : 'major',
      what: `build-agent -> ${built.status} in ${secs}s`, evidence: { keys: Object.keys(cfg), status: built.status, error: built.json?.error } });
    if (built.status >= 400) return;

    const agentCfg = cfg.agent ?? cfg.config ?? cfg;
    const tools: string[] = agentCfg?.model_config?.tools ?? agentCfg?.tools ?? [];
    const reg = await api(page, 'GET', '/api/tools');
    const registered = new Set((Array.isArray(reg.json?.data) ? reg.json.data : reg.json?.data?.tools ?? []).map((x: any) => x.id ?? x.name));
    const unknown = tools.filter(x => !registered.has(x));
    note({ area: 'ai builder output', severity: unknown.length ? 'major' : 'note',
      what: unknown.length ? `builder chose tools that are not registered: ${unknown.join(', ')}` : `builder chose ${tools.length} registered tools: ${tools.join(', ')}`,
      evidence: { name: agentCfg?.name, model: agentCfg?.model_config?.model, tools } });

    // Does the generated config save and run as-is, which is what the UI does?
    const save = await api(page, 'POST', '/api/agents', {
      name: `built-${Date.now()}`, category: 'other',
      description: agentCfg?.description ?? description,
      system_prompt: agentCfg?.system_prompt ?? 'You are helpful.',
      model_config: { mode: 'agent', model: agentCfg?.model_config?.model ?? 'claude-haiku-4-5', tools, max_iterations: 6 },
    });
    const id = (save.json?.data ?? {}).id;
    note({ area: 'ai builder save', severity: id ? 'note' : 'major', what: id ? 'generated config saved' : `generated config did not save (${save.status})`, evidence: save.json?.error });
    if (!id) return;
    const r = await runAgent(page, id, 'Company: Shell plc', 240);
    note({ area: 'ai builder run', severity: r.status === 'completed' ? 'note' : 'major',
      what: `generated agent run ${r.status}${r.failure_code ? ` (${r.failure_code})` : ''}`,
      evidence: { output: r.output.slice(0, 500), error: r.error, execution_id: r.execution_id } });
    await api(page, 'DELETE', `/api/agents/${id}`);
  });

  test('B. human in the loop, does the approval actually gate the run', async ({ page }) => {
    await login(page);
    const shape = bodyShape('post', '/api/approvals');
    const signShape = bodyShape('post', '/api/approvals/{approval_id}/signoff');
    note({ area: 'approvals api', severity: 'note', what: `create props ${JSON.stringify(shape.props)}, signoff props ${JSON.stringify(signShape.props)}` });

    // An agent that must stop before acting.
    const mk = await api(page, 'POST', '/api/agents', {
      name: `hitl-${Date.now()}`, category: 'other', description: 'HITL probe',
      system_prompt: 'Your first and only action is to call the human_approval tool right away with action="approve purchase order" and a one-line summary of the request, then wait for the decision. Never ask the user a question first. If approved, say APPROVED-PATH. If rejected, say REJECTED-PATH.',
      // require_tools turns a run that skipped the gate into a failed run instead of a quiet answer
      model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: ['human_approval'], max_iterations: 6, require_tools: ['human_approval'] },
    });
    const id = (mk.json?.data ?? {}).id;
    expect(id, 'could not create the HITL agent').toBeTruthy();

    // Fire without waiting, then look for the pending approval.
    const fire = await api(page, 'POST', `/api/agents/${id}/execute`, { message: 'Recommend whether to approve a $50k purchase order.', stream: false, wait: false });
    const execId = (fire.json?.data ?? {}).id ?? (fire.json?.data ?? {}).execution_id;
    note({ area: 'hitl fire', severity: execId ? 'note' : 'major', what: `execute -> ${fire.status}, execution ${execId ?? 'none'}` });

    let pending: any = null;
    let hangups = 0;
    for (let i = 0; i < 24 && !pending; i++) {
      await sleep(5000);
      // A dropped connection here is itself a finding, not a reason to stop.
      try {
        const list = await api(page, 'GET', `/api/approvals?status=pending&limit=50`);
        const rows: any[] = list.json?.data?.approvals ?? list.json?.data ?? [];
        pending = rows.find((a: any) => String(a.execution_id ?? a.agent_execution_id ?? '') === String(execId)) ?? rows[0] ?? null;
      } catch (e: any) { hangups++; }
      if (!pending) {
        // The agent-level gate may surface on the executions side instead.
        try {
          const ex = await api(page, 'GET', `/api/executions/approvals`);
          const exRows: any[] = ex.json?.data?.approvals ?? ex.json?.data ?? [];
          pending = exRows.find((a: any) => String(a.execution_id ?? a.id ?? '') === String(execId)) ?? null;
        } catch (e: any) { hangups++; }
      }
    }
    if (hangups) note({ area: 'approvals api', severity: 'major', what: `${hangups} request(s) to the approvals endpoints were dropped without a response (socket hang up)` });
    note({ area: 'hitl pending', severity: pending ? 'note' : 'blocker',
      what: pending ? 'a pending approval appeared for the run' : 'the agent was told to stop for approval and no pending approval ever appeared, so either it skipped the gate or the gate is invisible',
      evidence: pending ? { id: pending.id, keys: Object.keys(pending) } : undefined });

    expect.soft(pending, 'a human_approval gate appears as a pending approval').toBeTruthy();
    // The approvals page, as the approver would see it.
    await visit(page, '/approvals');
    const at = await bodyText(page);
    note({ area: 'approvals page', severity: /approve|reject|pending/i.test(at) ? 'note' : 'major',
      what: /approve|reject|pending/i.test(at) ? 'page shows approve/reject language' : 'page shows nothing to act on', screenshot: await shot(page, '11-approvals') });

    if (pending) {
      const approvalId = pending.id;
      // Two endpoints can close a gate and they do not agree on the words.
      // /api/approvals/{id}/signoff takes decision "approve" | "deny" + reason,
      // /api/executions/{id}/approve takes "approved" | "rejected" + comment.
      // A client has to know which gate it is looking at to pick the right
      // vocabulary, which is a finding in itself.
      let signed = await api(page, 'POST', `/api/approvals/${approvalId}/signoff`, { decision: 'approve', reason: 'uat' });
      let via = 'approvals/signoff';
      if (signed.status >= 400) {
        signed = await api(page, 'POST', `/api/executions/${execId}/approve`, { decision: 'approved', comment: 'uat' });
        via = 'executions/approve';
      }
      note({ area: 'hitl signoff', severity: signed.status < 400 ? 'note' : 'major', what: `signoff via ${via} -> ${signed.status}`, evidence: signed.json?.error });
      note({ area: 'approvals api consistency', severity: 'minor',
        what: 'the two sign-off endpoints use different decision vocabularies (approve/deny + reason versus approved/rejected + comment)' });

      // Did the run resume and take the approved path?
      let final: any = {};
      for (let i = 0; i < 24; i++) {
        await sleep(5000);
        const ex = await api(page, 'GET', `/api/executions/${execId}`);
        final = ex.json?.data ?? {};
        if (['completed', 'failed'].includes(final.status)) break;
      }
      // the execution row calls it output_message
      const out = String(final.output_message ?? final.output ?? final.final_output ?? '');
      expect.soft(/APPROVED-PATH/.test(out), 'approving the gate resumes the run').toBeTruthy();
      note({ area: 'hitl resume', severity: /APPROVED-PATH/.test(out) ? 'note' : 'major',
        what: /APPROVED-PATH/.test(out) ? 'run resumed and took the approved path' : `run ended ${final.status} without the approved path marker`,
        evidence: { status: final.status, output: out.slice(0, 400) } });
    }
    await api(page, 'DELETE', `/api/agents/${id}`);
  });

  test('C. knowledge, from upload to an agent answering from it', async ({ page }) => {
    await login(page);
    const shape = bodyShape('post', '/api/knowledge-bases');
    note({ area: 'knowledge api', severity: 'note', what: `create props ${JSON.stringify(shape.props)}` });

    const marker = `ZX-${Date.now().toString(36).toUpperCase()}`;

    // Agent first, so the KB can be bound to it at creation. The lint says
    // knowledge_search is only registered for an agent that has a collection,
    // so binding is the step that makes the tool exist at all.
    const mk = await api(page, 'POST', '/api/agents', {
      name: `kb-agent-${marker}`, category: 'other', description: 'KB probe',
      system_prompt: 'Answer only from knowledge_search results. If the tool returns nothing, say NOT-FOUND.',
      model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: ['knowledge_search'], max_iterations: 4 },
    });
    const agentId = (mk.json?.data ?? {}).id;
    if (!agentId) { note({ area: 'kb agent', severity: 'major', what: `could not create (${mk.status})`, evidence: mk.json?.error }); return; }

    const kb = await api(page, 'POST', '/api/knowledge-bases', { name: `uat-kb-${marker}`, description: 'exploratory pass', agent_id: agentId });
    const kbId = (kb.json?.data ?? {}).id;
    note({ area: 'kb create', severity: kbId ? 'note' : 'major', what: `create bound to agent -> ${kb.status}`, evidence: kb.json?.error });
    if (!kbId) { await api(page, 'DELETE', `/api/agents/${agentId}`); return; }

    // A fact that exists nowhere else, so an answer can only come from the upload.
    const doc = `Internal memo.\n\nThe maintenance window code for the Rotterdam pump hall is ${marker}. ` +
      `Only this code unlocks the valve cabinet. The previous code was retired on the first of the month.\n`;
    const up = await page.request.post(`${API}/api/knowledge-bases/${kbId}/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: { file: { name: 'memo.txt', mimeType: 'text/plain', buffer: Buffer.from(doc) } },
    });
    note({ area: 'kb upload', severity: up.ok() ? 'note' : 'major', what: `upload -> ${up.status()}` });

    // Wait for it to be processed.
    let ready = false;
    for (let i = 0; i < 36 && !ready; i++) {
      await sleep(5000);
      const docs = await api(page, 'GET', `/api/knowledge-bases/${kbId}/documents`);
      const rows: any[] = docs.json?.data?.documents ?? docs.json?.data ?? [];
      ready = rows.some((d: any) => /ready|completed|indexed/i.test(String(d.status)));
    }
    note({ area: 'kb processing', severity: ready ? 'note' : 'major', what: ready ? 'document reached ready' : 'document never reached ready within 3 minutes' });

    // Direct search first, so a failure later can be placed.
    const s = await api(page, 'POST', `/api/knowledge-engines/${kbId}/search`, { query: 'maintenance window code Rotterdam', top_k: 3 });
    const sText = JSON.stringify(s.json ?? {});
    expect.soft(sText.includes(marker), 'the KB bound at creation is searchable by the agent').toBeTruthy();
    note({ area: 'kb search', severity: sText.includes(marker) ? 'note' : 'major',
      what: sText.includes(marker) ? 'direct search returns the uploaded fact' : `direct search does not return the fact (${s.status})`, evidence: s.json?.error });

    // Now the agent, which is the point. The KB was bound to it at creation.
    const r = await runAgent(page, agentId, 'What is the maintenance window code for the Rotterdam pump hall?', 180);
    const got = r.output.includes(marker);
    note({ area: 'kb agent answer', severity: got ? 'note' : r.status === 'failed' ? 'major' : 'blocker',
      what: got ? 'agent answered with the fact from the upload' : /NOT-FOUND/.test(r.output) ? 'agent reports NOT-FOUND, so knowledge_search found nothing or was not registered' : `agent ${r.status} without the fact`,
      evidence: { status: r.status, failure_code: r.failure_code, output: r.output.slice(0, 500), error: r.error } });

    await visit(page, `/knowledge/${kbId}/engine`).catch(() => {});
    await shot(page, '12-kb-engine');
    await api(page, 'DELETE', `/api/agents/${agentId}`);
    await api(page, 'DELETE', `/api/knowledge-bases/${kbId}`);
  });
});
