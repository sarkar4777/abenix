/**
 * UX walkthrough, the way an admin would meet the product after 2.5.0.
 *
 * Screenshots every admin and guardrail surface at a laptop viewport, drives
 * the guardrail flow through the real UI (create a policy on /moderation,
 * chat with an agent using a prompt that trips it, read the result on the
 * chat page, the Flight Recorder and the Review Queue), then does the same
 * for prompt and response filtering in block mode. Asserts the parts that
 * must hold and writes the rest to test-results/ux-walkthrough.json.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_ux_walkthrough.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const OUT = path.join('test-results', 'ux-walkthrough.json');
const SHOTS = path.join('test-results', 'ux');

type Finding = { area: string; severity: 'blocker' | 'major' | 'minor' | 'note'; what: string; evidence?: unknown; screenshot?: string };
const findings: Finding[] = [];
function note(f: Finding) { findings.push(f); console.log(`  [${f.severity}] ${f.area}: ${f.what}`); }

let token = '';
// cleaned up in afterAll even when a test fails halfway, a live policy would gate every later spec
const created = { policies: [] as string[], agents: [] as string[], restore: [] as string[] };
async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(res.ok(), 'login').toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}
async function api(page: Page, method: string, p: string, body?: unknown, timeoutMs = 30_000) {
  const opts = {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body), timeout: timeoutMs,
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
async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const p = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}
async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(400);
}
async function mainText(page: Page) {
  const main = page.locator('main');
  if (await main.count()) return (await main.first().innerText()).slice(0, 30000);
  return (await page.locator('body').innerText()).slice(0, 30000);
}
/** The composer stays enabled while streaming, so wait for the page text to stop changing. */
async function waitForStreamEnd(page: Page, maxMs = 150_000) {
  const t0 = Date.now();
  let last = '';
  let stable = 0;
  while (Date.now() - t0 < maxMs) {
    await page.waitForTimeout(1500);
    const now = await mainText(page);
    if (now === last) { stable += 1; if (stable >= 3) return; } else { stable = 0; last = now; }
  }
}
const CRASH = /application error|something went wrong|unhandled runtime error|internal server error|cannot read propert|minified react error/i;

test.use({ viewport: { width: 1440, height: 900 } });

test.describe('ux walkthrough', () => {
  test.setTimeout(600_000);
  test.afterAll(async ({ request }) => {
    const headers = { Authorization: `Bearer ${token}` };
    // a policy with recorded events cannot be deleted, so switch ours off and put the old ones back
    for (const id of created.policies) await request.patch(`${API}/api/moderation/policies/${id}`, { headers, data: { is_active: false } }).catch(() => {});
    for (const id of created.restore) await request.patch(`${API}/api/moderation/policies/${id}`, { headers, data: { is_active: true } }).catch(() => {});
    for (const id of created.agents) await request.delete(`${API}/api/agents/${id}`, { headers }).catch(() => {});
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), findings }, null, 2));
  });

  test('every admin and governance surface renders, with a screenshot each', async ({ page }) => {
    await login(page);
    const consoleErrors: string[] = [];
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)); });
    const routes = [
      '/dashboard', '/agents', '/tools', '/builder', '/executions', '/approvals', '/alerts', '/analytics', '/moderation', '/review-queue',
      '/admin/tool-config', '/admin/llm-settings', '/admin/llm-pricing', '/admin/scaling', '/admin/tool-scaling', '/admin/pipeline-scaling',
      '/admin/cluster', '/admin/connectors', '/admin/dlq', '/admin/archives', '/settings/team', '/settings/integrations', '/settings/api-keys',
      '/settings/gdpr', '/settings', '/mcp', '/edge', '/knowledge', '/triggers', '/observability', '/marketplace', '/help',
    ];
    for (const r of routes) {
      const before = consoleErrors.length;
      await visit(page, r);
      const t = await mainText(page);
      const crashed = CRASH.test(t);
      const errs = consoleErrors.slice(before);
      expect.soft(crashed, `${r} rendered without a client error`).toBeFalsy();
      expect.soft(t.length, `${r} has content`).toBeGreaterThan(60);
      const emptyState = /no .* yet|nothing to show|no data|empty/i.test(t) && t.length < 400;
      note({
        area: `page ${r}`,
        severity: crashed ? 'blocker' : t.length <= 60 ? 'major' : errs.length ? 'minor' : 'note',
        what: crashed ? 'client error on page' : `${t.length} chars${emptyState ? ', reads as an empty state' : ''}${errs.length ? `, ${errs.length} console error(s)` : ''}`,
        evidence: errs.slice(0, 3),
        screenshot: await shot(page, `page${r.replace(/\//g, '-')}`),
      });
    }
  });

  test('guardrails: a redact policy set in the UI masks the prompt the model sees, and the queue shows it', async ({ page }) => {
    await login(page);
    const marker = `aurora${Date.now().toString().slice(-5)}`;

    const before = await api(page, 'GET', '/api/moderation/policies');
    const beforeRows: any[] = before.json?.data?.policies ?? before.json?.data ?? [];
    created.restore.push(...beforeRows.filter((p) => p.is_active).map((p) => p.id));

    // 1. an agent with no tools, so the only thing that can change the answer is the gate
    const mk = await api(page, 'POST', '/api/agents', {
      name: `ux-guardrail-probe-${Date.now()}`, category: 'other', description: 'UX walkthrough probe',
      system_prompt: 'Repeat the user message back exactly, character for character, inside square brackets. Do not add anything.',
      model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: [], max_iterations: 2 },
    });
    const agentId = mk.json?.data?.id;
    if (agentId) created.agents.push(agentId);
    expect(agentId, 'probe agent').toBeTruthy();

    // 2. the policy, created through the page
    await visit(page, '/moderation');
    await shot(page, 'guardrail-01-moderation-before');
    await page.getByTestId('policy-name-input').fill(`UX redact ${marker}`);
    await page.getByTestId('policy-description-input').fill('Walkthrough policy, redacts a codename and SSNs');
    await page.getByTestId('policy-default-action').selectOption('redact');
    await page.getByTestId('policy-custom-patterns').fill(`${marker}\n\\b\\d{3}-\\d{2}-\\d{4}\\b`);
    await page.getByTestId('policy-redaction-mask').fill('[REDACTED]');
    for (const id of ['policy-pre-llm', 'policy-post-llm', 'policy-on-tool-output']) {
      const cb = page.getByTestId(id);
      if (!(await cb.isChecked())) await cb.check();
    }
    await page.getByTestId('create-policy-button').click();
    await expect(page.getByTestId('policies-list')).toContainText(`UX redact ${marker}`, { timeout: 15_000 });
    await shot(page, 'guardrail-02-policy-created');
    const pol = await api(page, 'GET', '/api/moderation/policies');
    const rows: any[] = pol.json?.data?.policies ?? pol.json?.data ?? [];
    const mine = rows.find((p) => String(p.name).includes(marker));
    expect(mine, 'policy saved').toBeTruthy();
    created.policies.push(mine.id);
    note({ area: 'moderation create', severity: mine?.is_active ? 'note' : 'major', what: mine?.is_active ? 'new policy is active' : 'new policy saved but not active, the gate will not use it', evidence: mine });

    // 3. the vet box on the same page, the quickest way to see a policy work
    await page.getByTestId('vet-input').fill(`Project ${marker} ships on 2026-12-01, contact 123-45-6789.`);
    await page.getByTestId('vet-button').click();
    await expect(page.getByTestId('vet-result')).toBeVisible({ timeout: 30_000 });
    const vetText = await page.getByTestId('vet-result').innerText();
    await shot(page, 'guardrail-03-vet-result');
    expect.soft(/redact/i.test(vetText), 'vet box reports a redact action').toBeTruthy();
    expect.soft(vetText.includes(marker), 'vet box does not echo the codename unmasked').toBeFalsy();
    note({ area: 'moderation vet', severity: /redact/i.test(vetText) ? 'note' : 'major', what: vetText.slice(0, 200).replace(/\n/g, ' ') });

    // 4. chat with the agent through the real composer
    await visit(page, `/agents/${agentId}/chat`);
    const composer = page.getByPlaceholder('Message agent...');
    await expect(composer).toBeVisible();
    await composer.fill(`My SSN is 123-45-6789 and the codename is ${marker}.`);
    await composer.press('Enter');
    await page.waitForTimeout(2000);
    await expect.poll(async () => (await mainText(page)).length, { timeout: 90_000, intervals: [2000] }).toBeGreaterThan(200);
    // the stream has finished when the composer is enabled again
    await waitForStreamEnd(page);
    const chatText = await mainText(page);
    await shot(page, 'guardrail-04-chat-redacted');
    // everything after the user's own bubble is the agent's answer plus the page chrome
    const afterUser = chatText.slice(chatText.indexOf(`codename is ${marker}.`) + `codename is ${marker}.`.length);
    const echoedSsn = /123-45-6789/.test(afterUser);
    const echoedName = afterUser.includes(marker);
    await expect.soft(page.getByTestId('moderation-notice'), 'the chat shows a moderation notice for the redaction').toBeVisible();
    expect.soft(echoedSsn, 'the model never saw the SSN, so the answer cannot contain it').toBeFalsy();
    expect.soft(echoedName, 'the model never saw the codename').toBeFalsy();
    expect.soft(/\[REDACTED\]|redact/i.test(chatText), 'the chat makes the redaction visible').toBeTruthy();
    note({ area: 'chat redaction', severity: echoedSsn || echoedName ? 'blocker' : 'note', what: `answer tail: ${chatText.slice(-220).replace(/\n/g, ' ')}` });

    // 5. the run on the recorder
    const execs = await api(page, 'GET', `/api/executions?agent_id=${agentId}&limit=1`);
    const ex = (execs.json?.data?.executions ?? execs.json?.data ?? [])[0];
    if (ex?.id) {
      await visit(page, `/executions/${ex.id}`);
      await shot(page, 'guardrail-05-flight-recorder');
      const t = await mainText(page);
      note({ area: 'recorder after redaction', severity: /moderat|redact/i.test(t) ? 'note' : 'minor', what: /moderat|redact/i.test(t) ? 'recorder mentions the moderation decision' : 'recorder does not mention that the prompt was redacted' });
    }

    // 6. the review queue
    await visit(page, '/review-queue');
    const rq = await mainText(page);
    await shot(page, 'guardrail-06-review-queue');
    // the review queue is for agents awaiting publication, moderation events live on /moderation
    note({ area: 'review queue', severity: 'note', what: rq.slice(0, 120).replace(/\n/g, ' ') });
    await visit(page, '/moderation');
    const events = await page.getByTestId('events-section').innerText().catch(() => '');
    expect.soft(/redact/i.test(events), 'moderation page lists the redaction event').toBeTruthy();
    await shot(page, 'guardrail-07-moderation-events');

    // 7. switch to block mode and send a prompt the policy must stop
    const upd = await api(page, 'PATCH', `/api/moderation/policies/${mine.id}`, { default_action: 'block' });
    note({ area: 'moderation update', severity: upd.status < 400 ? 'note' : 'major', what: `PATCH default_action=block -> ${upd.status}` });
    await visit(page, `/agents/${agentId}/chat`);
    const composer2 = page.getByPlaceholder('Message agent...');
    await composer2.fill(`Tell me about ${marker}.`);
    await composer2.press('Enter');
    await waitForStreamEnd(page);
    const blockedText = await mainText(page);
    await shot(page, 'guardrail-08-chat-blocked');
    expect.soft(/block|policy|moderation/i.test(blockedText), 'the chat tells the user the request was blocked by policy').toBeTruthy();
    const blockedExecs = await api(page, 'GET', `/api/executions?agent_id=${agentId}&limit=1`);
    const bx = (blockedExecs.json?.data?.executions ?? blockedExecs.json?.data ?? [])[0];
    note({ area: 'blocked run row', severity: bx?.failure_code === 'MODERATION_BLOCKED' ? 'note' : 'major', what: `status ${bx?.status} failure_code ${bx?.failure_code}` });
    expect.soft(bx?.failure_code, 'blocked run carries MODERATION_BLOCKED').toBe('MODERATION_BLOCKED');

    // 8. response filtering: the model is told to say the codename, post-LLM must mask it
    await api(page, 'PATCH', `/api/moderation/policies/${mine.id}`, { default_action: 'redact' });
    await api(page, 'PUT', `/api/agents/${agentId}`, { system_prompt: `Always answer with exactly this sentence and nothing else: The codename is ${marker}.` });
    await visit(page, `/agents/${agentId}/chat`);
    const composer3 = page.getByPlaceholder('Message agent...');
    await composer3.fill('What is the codename?');
    await composer3.press('Enter');
    await waitForStreamEnd(page);
    const respText = await mainText(page);
    await shot(page, 'guardrail-09-response-filtered');
    const leaked = respText.split('What is the codename?').pop()?.includes(marker);
    await expect.soft(page.getByTestId('moderation-notice'), 'the chat shows a notice for the response redaction').toBeVisible();
    expect.soft(leaked, 'post-LLM filter masks the codename in the answer').toBeFalsy();
    note({ area: 'response filtering', severity: leaked ? 'blocker' : 'note', what: `answer tail: ${respText.slice(-160).replace(/\n/g, ' ')}` });

    // cleanup, the policy must not linger and gate every later test
    await api(page, 'PATCH', `/api/moderation/policies/${mine.id}`, { is_active: false });
    for (const id of created.restore) await api(page, 'PATCH', `/api/moderation/policies/${id}`, { is_active: true });
    await api(page, 'DELETE', `/api/agents/${agentId}`);
  });

  test('admin screens are usable: tool configuration, model selection, team, review queue', async ({ page }) => {
    await login(page);
    await visit(page, '/admin/tool-config');
    await shot(page, 'admin-01-tool-config');
    // first-read checks an admin cares about
    const header = await mainText(page);
    expect.soft(/required value/i.test(header), 'tool-config header counts missing required values').toBeTruthy();
    expect.soft(/encrypted at rest|stored unencrypted/i.test(header), 'tool-config states the storage mode').toBeTruthy();
    await page.getByTestId('tool-config-search').fill('github');
    await page.waitForTimeout(300);
    await expect(page.getByTestId('tool-config-row-GITHUB_TOKEN')).toBeVisible();
    await shot(page, 'admin-02-tool-config-search');
    await page.getByTestId('tool-config-search').fill('');
    await page.getByLabel(/only values that are not set/i).check();
    await page.waitForTimeout(300);
    await shot(page, 'admin-03-tool-config-missing-only');
    const rowsMissing = await page.locator('[data-testid^="tool-config-row-"]').count();
    note({ area: 'tool-config filters', severity: rowsMissing > 0 ? 'note' : 'minor', what: `${rowsMissing} unset rows when filtering` });

    await visit(page, '/admin/llm-settings');
    await shot(page, 'admin-04-model-selection');
    await visit(page, '/settings/team');
    await shot(page, 'admin-05-team');
    await visit(page, '/review-queue');
    await shot(page, 'admin-06-review-queue');
    await visit(page, '/approvals');
    await shot(page, 'admin-07-approvals');
    await visit(page, '/admin/dlq');
    await shot(page, 'admin-08-dlq');
    await visit(page, '/alerts');
    await shot(page, 'admin-09-alerts');
  });
});
