/**
 * The main sidebar pages, walked from the screens as a demanding new user would.
 *
 *   1. Dashboard        every number matches the API and opens the matching list
 *   2. My Agents        search, category filter, open, duplicate, share, delete and restore
 *   3. Knowledge Bases  create, upload, wait for indexing, search, bind to an agent, chat answers from the doc
 *   4. Source Watch     add a source, check it, see a change event
 *   5. SDK Playground   run an agent, copy the generated code
 *   6. Triggers         schedule an agent, run it now, see the execution
 *   7. Evals            suite, case from a real run, run twice, compare
 *   8. Meetings         create one, keys explained
 *   9. Marketplace      list an agent, review it, see it in the store and Creator Hub
 *  10. MCP              add a server, see its tools
 *  11. Edge             what works without hardware
 *  12. Moderation       policies, a test that blocks, the event in the list
 *  13. Phone width      no sideways scroll at 390px
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 USE_K8S=1 npx playwright test e2e/uat_nav_build_run_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const OTHER_USER = process.env.AF_SHARE_EMAIL || 'demo@abenix.dev';
const RUN = Date.now().toString(36);
const AGENT = `Nav walker ${RUN}`;
const TRIGGER = `Morning digest ${RUN}`;
const KB = `Walk handbook ${RUN}`;
const KB_AGENT = `Handbook assistant ${RUN}`;
const CODEWORD = `ORCHID-${RUN.toUpperCase()}`;
// the in-cluster MCP fixture from docs/08-howto/05-testing.md
const MCP_URL = process.env.AF_MCP_URL || 'http://custom-mcp.abenix.svc.cluster.local:8080/mcp';

const DIR = path.join(__dirname, 'uat_nav_build_run_ui');
// files made for the run, kept out of the repo
const FIX = path.join(os.tmpdir(), `uat-nav-${RUN}`);
const SHOTS = path.join(DIR, 'shots');
const LLM_MS = 300_000;

const ids: Record<string, string | undefined> = {};
const extraAgents: string[] = [];

// not serial: a failed page must not hide the others, so tests that need the walker agent make it themselves
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function signIn(page: Page) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(ADMIN.email);
  await page.locator('#auth-password').fill(ADMIN.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const headers: Record<string, string> = { Authorization: `Bearer ${tok}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers,
    data: body === undefined ? undefined : JSON.stringify(body),
  });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function chat(page: Page, message: string, timeoutMs = LLM_MS) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  const err = page.getByTestId('chat-error');
  if (await err.count()) throw new Error(`the run failed in chat: ${await err.innerText()}`);
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 });
  return replies.nth(before).innerText();
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

// a message a person can read, not a stack trace or a JSON dump
function expectPlain(msg: string) {
  expect(msg.trim().length).toBeGreaterThan(0);
  expect(msg.length).toBeLessThan(800);
  expect(msg).not.toMatch(/Traceback|File "[^"]+", line \d+|^\s*[{[]\s*"|Exception:|\bat [\w.$]+ \(|\[object Object\]|\bundefined\b|\bNaN\b/);
}

const num = (s: string) => Number(s.replace(/[^\d.]/g, ''));

// builder: name, description, category, prompt, then save or publish
async function buildAgent(page: Page, route: string, o: { name: string; description: string; prompt?: string; publish?: boolean }) {
  await go(page, route);
  await expect(page.getByTestId('builder-name-button')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(o.name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill(o.description);
  await page.getByTestId('builder-category').selectOption('research');
  if (o.prompt) {
    await page.getByTestId('config-tab-prompt').click();
    await page.getByTestId('builder-system-prompt').fill(o.prompt);
  }
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  const id = new URL(page.url()).searchParams.get('agent') || '';
  expect(id).toBeTruthy();
  if (o.publish) {
    await page.getByTestId('builder-publish').click();
    await page.getByTestId('publish-visibility-org').click();
    await page.getByTestId('publish-submit').click();
    await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
  }
  return id;
}

// the agent the later pages use, built through the builder if this worker has none yet
async function ensureAgent(page: Page) {
  if (ids.agent) return ids.agent;
  ids.agent = await buildAgent(page, '/builder', {
    name: AGENT,
    description: 'Walks the sidebar for the nav UAT.',
    prompt: 'You are a terse helper. Answer in one short sentence.',
    publish: true,
  });
  return ids.agent;
}

// a finished run of the walker agent, made from its chat page
async function ensureRun(page: Page) {
  if (ids.triggerExec || ids.playgroundExec) return (ids.triggerExec || ids.playgroundExec)!;
  await ensureAgent(page);
  await go(page, `/agents/${ids.agent}/chat`);
  await chat(page, 'Reply with the single word pong.');
  const ex = (await api(page, 'GET', `/api/executions?agent_id=${ids.agent}&limit=1`)).json.data[0];
  ids.playgroundExec = ex.id;
  return ex.id as string;
}

test.beforeAll(() => {
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.mkdirSync(FIX, { recursive: true });
  fs.writeFileSync(
    path.join(FIX, 'walk-handbook.md'),
    `# Field handbook\n\nThe vault codeword for the quarter is ${CODEWORD}.\nOnly the duty manager may read it out.\n\nSite visits start at 07:30 and finish by 15:00.\n`,
  );
});

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('Dashboard: every number is real and opens the matching list', async ({ page }) => {
  await go(page, '/dashboard');
  const stats = (await api(page, 'GET', '/api/analytics/live-stats')).json.data;
  const totalCard = page.getByTestId('kpi-total-agents');
  await expect(totalCard).toBeVisible({ timeout: 20_000 });
  // the count-up settles on the API number
  await expect.poll(async () => {
    const fresh = (await api(page, 'GET', '/api/analytics/live-stats')).json.data.total_agents;
    return Math.abs(num(await totalCard.locator('p').first().innerText()) - fresh);
  }, { timeout: 10_000 }).toBeLessThanOrEqual(2);
  const runsCard = page.getByTestId('kpi-executions-today');
  await expect.poll(async () => num(await runsCard.locator('p').first().innerText()), { timeout: 10_000 }).toBeGreaterThanOrEqual(stats.today_executions);
  await expect(runsCard).toContainText(/\d+ failed/);
  const spend = page.getByTestId('kpi-token-spend');
  if (stats.flat_rate_billing) await expect(page.getByTestId('kpi-cost-note')).toContainText('subscription');
  await expect(spend).toContainText('tokens today');
  // own usage, never a fake Unlimited for an admin
  const usage = page.getByTestId('kpi-your-usage');
  await expect(usage).toContainText(/Cost: \$\d/, { timeout: 20_000 });
  await expect(usage).not.toContainText('Unlimited');
  await shot(page, '01-dashboard');

  // Total Agents opens the All tab with the same count
  await totalCard.click();
  await page.waitForURL(/\/agents\?tab=all/, { timeout: 20_000 });
  const allTab = page.getByTestId('agents-tab-all');
  await expect(allTab).toHaveAttribute('aria-pressed', 'true');
  // other runs add agents while this one walks, so compare with a fresh count
  await expect.poll(async () => {
    const fresh = (await api(page, 'GET', '/api/analytics/live-stats')).json.data.total_agents;
    return num(await allTab.innerText()) - fresh;
  }, { timeout: 30_000 }).toBe(0);

  // Executions Today opens today's runs, the failed tile opens today's failures
  await go(page, '/dashboard');
  await page.getByTestId('kpi-executions-today').click();
  await page.waitForURL(/\/executions\?since=today/, { timeout: 20_000 });
  await expect(page.getByTestId('exec-since-chip')).toBeVisible();
  await expect(page.getByTestId('exec-error')).toHaveCount(0);
  const today = (await api(page, 'GET', '/api/executions?since=today&limit=1')).json.meta;
  expect(today.total).toBeGreaterThanOrEqual(stats.today_executions);
  await expect(page.getByText(/^Showing 1.\d+ of \d+$/).or(page.getByText('No executions found'))).toBeVisible({ timeout: 20_000 });

  await go(page, '/dashboard');
  await page.getByTestId('live-failed-today').click();
  await page.waitForURL(/status=failed/, { timeout: 20_000 });
  await expect(page.getByTestId('exec-status-filter')).toHaveValue('failed');
  await expect(page.getByTestId('exec-error')).toHaveCount(0);
  const failed = (await api(page, 'GET', '/api/executions?since=today&status=failed&limit=5')).json;
  expect((failed.data as any[]).every((e) => e.status === 'failed')).toBe(true);
  await shot(page, '02-executions-failed-today');

  // the status filter on the executions page itself works (it used to 500)
  await go(page, '/executions');
  await page.getByTestId('exec-status-filter').selectOption('completed');
  await expect(page.getByTestId('exec-error')).toHaveCount(0);
  await expect(page.getByText(/^Showing 1/).or(page.getByText('No executions found'))).toBeVisible({ timeout: 20_000 });
});

test('My Agents: search, filter, open, duplicate, share, delete and restore', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  ids.agent = await buildAgent(page, '/builder', {
    name: AGENT,
    description: 'Walks the sidebar for the nav UAT.',
    prompt: 'You are a terse helper. Answer in one short sentence.',
    publish: true,
  });

  await go(page, '/agents');
  await page.getByLabel('Search agents').fill(AGENT);
  await expect(page.getByText(AGENT).first()).toBeVisible({ timeout: 20_000 });
  // category filter lists the categories agents really have, and filters
  const cat = page.getByLabel('Filter by category');
  await expect(cat.locator('option[value="research"]')).toHaveCount(1, { timeout: 20_000 });
  await cat.selectOption('research');
  await expect(page.getByText(AGENT).first()).toBeVisible({ timeout: 20_000 });
  await cat.selectOption('other');
  await expect(page.getByText('No agents match')).toBeVisible({ timeout: 20_000 });
  await cat.selectOption('');
  await shot(page, '03-agents-search');

  // open it
  await page.getByText(AGENT).first().click();
  await page.waitForURL(new RegExp(`/agents/${ids.agent}/info`), { timeout: 20_000 });
  await expect(page.getByRole('heading', { level: 1, name: AGENT })).toBeVisible();

  // share with a teammate, a stranger gets a plain error
  await page.getByTestId('agent-share').click();
  const share = page.getByRole('dialog', { name: `Share ${AGENT}` });
  await expect(share.getByTestId('share-empty')).toBeVisible({ timeout: 20_000 });
  await share.getByTestId('share-email').fill('nobody-here@example.com');
  await share.getByTestId('share-submit').click();
  await expect(share.getByTestId('share-error')).toBeVisible();
  expectPlain(await share.getByTestId('share-error').innerText());
  await share.getByTestId('share-email').fill(OTHER_USER);
  await share.getByTestId('share-permission').selectOption('execute');
  await share.getByTestId('share-submit').click();
  await expect(share.getByTestId('share-row').filter({ hasText: OTHER_USER })).toBeVisible({ timeout: 20_000 });
  const shares = await api(page, 'GET', `/api/agents/${ids.agent}/shares`);
  expect((shares.json.data as any[]).some((s) => s.shared_with_email === OTHER_USER && s.permission === 'execute')).toBe(true);
  await shot(page, '04-agent-share');
  await share.getByRole('button', { name: `Revoke access for ${OTHER_USER}` }).click();
  await expect(share.getByTestId('share-row')).toHaveCount(0, { timeout: 20_000 });
  await share.getByRole('button', { name: 'Close' }).click();

  // duplicate lands in the builder on an editable copy
  await page.getByTestId('agent-duplicate').click();
  await page.waitForURL(/\/builder\?agent=/, { timeout: 30_000 });
  const copyId = new URL(page.url()).searchParams.get('agent') || '';
  expect(copyId).not.toBe(ids.agent);
  extraAgents.push(copyId);
  const copy = (await api(page, 'GET', `/api/agents/${copyId}`)).json.data;
  expect(copy.name).toBe(`${AGENT} (Copy)`);
  await expect(page.getByTestId('builder-name-button')).toContainText(`${AGENT} (Copy)`, { timeout: 20_000 });

  // delete the copy from the list, then bring it back
  await go(page, '/agents');
  await page.getByLabel('Search agents').fill(`${AGENT} (Copy)`);
  await page.getByTestId(`agent-delete-${copyId}`).click({ force: true });
  const dlg = page.getByTestId('delete-dialog');
  await expect(dlg).toContainText('Recently deleted');
  await dlg.getByTestId('delete-confirm').click();
  await expect(page.getByTestId(`agent-delete-${copyId}`)).toHaveCount(0, { timeout: 20_000 });
  expect((await api(page, 'GET', `/api/agents/${copyId}`)).status).toBe(404);
  await page.getByTestId('deleted-agents-toggle').click();
  const row = page.getByTestId('deleted-agent-row').filter({ hasText: `${AGENT} (Copy)` });
  await expect(row).toBeVisible({ timeout: 20_000 });
  await shot(page, '05-agents-recently-deleted');
  await page.getByTestId(`agent-restore-${copyId}`).click();
  await expect(row).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId(`agent-delete-${copyId}`)).toHaveCount(1, { timeout: 20_000 });
  expect((await api(page, 'GET', `/api/agents/${copyId}`)).json.data.status).not.toBe('archived');
});

test('Knowledge Bases: create, upload, index, search, bind to an agent, answer in chat', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  await go(page, '/knowledge');
  await expect(page.getByRole('heading', { name: 'Knowledge Bases' })).toBeVisible();
  await page.getByRole('button', { name: 'New Knowledge Base' }).first().click();
  // empty name is refused in words
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Name is required' })).toBeVisible();
  await page.getByLabel('Name', { exact: true }).fill(KB);
  await page.getByLabel('Description').fill('Field handbook for the nav UAT.');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  // straight into the new KB with the upload box
  await page.waitForURL(/\/knowledge\?id=/, { timeout: 20_000 });
  ids.kb = new URL(page.url()).searchParams.get('id') || '';
  await expect(page.getByRole('heading', { level: 1, name: KB })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No documents yet')).toBeVisible();

  // a file type it does not take gets a reason
  fs.writeFileSync(path.join(FIX, 'notes.exe'), 'MZ not really a program');
  await page.getByTestId('kb-dropzone-input').setInputFiles(path.join(FIX, 'notes.exe'));
  const upErr = page.getByTestId('kb-upload-error');
  await expect(upErr).toBeVisible({ timeout: 30_000 });
  await expect(upErr).toContainText('notes.exe (');
  expectPlain(await upErr.innerText());

  await page.getByTestId('kb-dropzone-input').setInputFiles(path.join(FIX, 'walk-handbook.md'));
  const doc = page.getByTestId('kb-doc-row').filter({ hasText: 'walk-handbook.md' });
  await expect(doc).toBeVisible({ timeout: 30_000 });
  await expect(doc).toHaveAttribute('data-status', 'ready', { timeout: 180_000 });
  await expect(doc).toContainText(/\d+ chunks?/);
  await shot(page, '06-kb-indexed');
  const docs = (await api(page, 'GET', `/api/knowledge-bases/${ids.kb}/documents`)).json.data as any[];
  expect(docs[0].status).toBe('ready');
  expect(docs[0].chunk_count).toBeGreaterThan(0);

  // a reload keeps the KB open
  await page.reload();
  await expect(page.getByRole('heading', { level: 1, name: KB })).toBeVisible({ timeout: 20_000 });

  // search finds the line
  await page.getByTestId('kb-open-engine').click();
  await page.waitForURL(new RegExp(`/knowledge/${ids.kb}/engine`), { timeout: 20_000 });
  await page.getByTestId('kb-search-input').fill('What is the vault codeword?');
  await page.getByTestId('kb-search-button').click();
  await expect(page.getByTestId('kb-search-error')).toHaveCount(0);
  await expect(page.getByTestId('kb-search-results')).toContainText(CODEWORD, { timeout: 60_000 });
  await shot(page, '07-kb-search');

  // bind it to a new agent from the KB page
  await go(page, `/knowledge?id=${ids.kb}`);
  await page.getByTestId('kb-use-in-agent').click();
  await page.waitForURL(/\/builder\?kb=/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-knowledge_search"]')).toBeVisible({ timeout: 20_000 });
  ids.kbAgent = await buildAgent(page, page.url().replace(BASE, ''), {
    name: KB_AGENT,
    description: 'Answers from the field handbook.',
    prompt: 'Answer only from the knowledge base using knowledge_search. Quote exact values. If it is not there, say so.',
    publish: true,
  });
  const a = (await api(page, 'GET', `/api/agents/${ids.kbAgent}`)).json.data;
  expect(a.model_config.tools).toContain('knowledge_search');
  expect(a.model_config.knowledge_collection_ids || []).toContain(ids.kb);

  const answer = await chat(page, 'What is the vault codeword for the quarter?');
  console.log(`\n--- kb answer ---\n${answer}\n---`);
  expect(answer).toContain(CODEWORD);
  await shot(page, '08-kb-chat');

  // the KB says which agents use it
  await go(page, `/knowledge/${ids.kb}/engine`);
  await expect(page.getByTestId('kb-agent-grants')).toContainText(KB_AGENT, { timeout: 20_000 });
});

test('Source Watch: add a source, check it, see the change', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  const name = `UUID feed ${RUN}`;
  await go(page, '/sources');
  await expect(page.getByRole('heading', { name: 'Source Watch' })).toBeVisible();
  await page.getByTestId('source-add').click();
  const form = page.getByRole('dialog');
  // a bad address is refused before saving
  await form.getByTestId('source-url').fill('not a url');
  await expect(form.getByTestId('source-url-check')).not.toBeEmpty({ timeout: 10_000 });
  await expect(form.getByTestId('source-save')).toBeDisabled();
  // httpbin returns a fresh uuid each time, so every check is a change
  await form.getByTestId('source-url').fill('https://httpbin.org/uuid');
  await form.getByTestId('source-name').fill(name);
  await form.getByTestId('source-kind-json').click();
  await form.getByTestId('source-test-fetch').click();
  await expect(form.getByTestId('source-preview-text')).toContainText('uuid', { timeout: 60_000 });
  await shot(page, '09-source-preview');
  await form.getByTestId('source-save').click();
  await expect(form).toHaveCount(0, { timeout: 30_000 });

  const list = (await api(page, 'GET', '/api/sources')).json.data as any[];
  const src = list.find((x) => x.name === name);
  expect(src).toBeTruthy();
  ids.source = src.id;

  await go(page, `/sources/${ids.source}`);
  await expect(page.getByTestId('source-title')).toHaveText(name, { timeout: 20_000 });
  // the first check is a baseline, the next one finds a new uuid
  for (let i = 0; i < 2; i++) {
    await page.getByTestId('source-check-now').click();
    await expect(page.getByTestId('source-notice')).toBeVisible({ timeout: 90_000 });
    if (/Changed/.test(await page.getByTestId('source-notice').innerText())) break;
    await page.waitForTimeout(2_500);
  }
  const notice = page.getByTestId('source-notice');
  await expect(notice).toContainText('Changed');
  expectPlain(await notice.innerText());
  await page.getByTestId('source-tab-changes').click();
  await expect(page.getByTestId('change-list')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('change-detail')).toContainText('uuid', { timeout: 20_000 });
  const changes = (await api(page, 'GET', `/api/sources/${ids.source}/changes`)).json.data as any[];
  expect(changes.length).toBeGreaterThan(0);
  await shot(page, '10-source-change');

  // the list shows it changed, and the event is in the recent changes feed
  await go(page, '/sources');
  await page.getByLabel('Search sources').fill(name);
  await expect(page.getByTestId(`source-row-${name}`)).toContainText(/ago|just now/i, { timeout: 20_000 });

  // delete it from its page
  await go(page, `/sources/${ids.source}`);
  await page.getByRole('button', { name: 'Delete source' }).click();
  await page.getByRole('button', { name: 'Delete source' }).last().click();
  await page.waitForURL(/\/sources$/, { timeout: 20_000 });
  expect((await api(page, 'GET', `/api/sources/${ids.source}`)).status).toBe(404);
  ids.source = undefined;
});

test('SDK Playground: run an agent live, generate code and copy it', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await ensureAgent(page);
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
  await go(page, '/sdk-playground');
  await page.getByLabel('Search agents').fill(AGENT);
  // the My Agents test leaves a "(Copy)" whose name also contains AGENT, so pick by id
  const pick = page.getByTestId('playground-agent-list').getByTestId(`playground-agent-${ids.agent}`);
  await expect(pick).toContainText(AGENT, { timeout: 20_000 });
  await pick.click();
  await expect(pick).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('live-inputs-panel')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('live-message-input').first().fill('Reply with the single word pong.');
  await page.getByTestId('run-live-button').click();
  const live = page.getByTestId('live-result-panel');
  await expect(live).toBeVisible({ timeout: LLM_MS });
  await expect(live).toContainText('completed', { timeout: LLM_MS });
  await expect(live).toContainText(/pong/i);
  // the run is a real execution with its own page
  const runLink = live.getByTestId('live-result-run-link');
  const href = await runLink.getAttribute('href');
  const execId = String(href).split('/').pop()!;
  const ex = (await api(page, 'GET', `/api/executions/${execId}`)).json.data;
  expect(ex.agent_id).toBe(ids.agent);
  expect(ex.status).toBe('completed');
  ids.playgroundExec = execId;
  await shot(page, '11-playground-live');

  await page.getByTestId('generate-code').click();
  const code = page.getByTestId('generated-code');
  await expect(code).toContainText('abenix', { timeout: LLM_MS });
  await expect(page.getByTestId('generate-error')).toHaveCount(0);
  const generated = await code.innerText();
  const agentRow = (await api(page, 'GET', `/api/agents/${ids.agent}`)).json.data;
  expect(generated.includes(agentRow.slug) || generated.includes(ids.agent!)).toBe(true);
  await page.getByTestId('copy-code').click();
  await expect(page.getByTestId('copy-code')).toContainText('Copied');
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  // the Windows clipboard stores CRLF, the code itself is the same
  expect(clip.replace(/\r\n/g, '\n').trim()).toBe(generated.trim());
  await shot(page, '12-playground-code');

  await runLink.click();
  await page.waitForURL(new RegExp(`/executions/${execId}`), { timeout: 20_000 });
});

test('Triggers: schedule an agent, run it now, see the execution', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await ensureAgent(page);
  // from the agent page, as a user would
  await go(page, `/agents/${ids.agent}/info`);
  await page.getByRole('link', { name: 'Schedule' }).click();
  await page.waitForURL((u) => u.pathname === '/triggers' && u.searchParams.get('agent') === ids.agent, { timeout: 20_000 });
  await expect(page.getByTestId('trigger-agent-filter')).toContainText(AGENT, { timeout: 20_000 });
  const dlg = page.getByRole('dialog', { name: 'Create Trigger' });
  await expect(dlg).toBeVisible({ timeout: 20_000 });
  await expect(dlg.getByLabel('Agent')).toHaveValue(ids.agent!);
  await dlg.getByRole('button', { name: /Schedule/ }).click();
  // a half cron is refused in words before it reaches the server
  await dlg.getByLabel('Cron Expression').fill('*/5 *');
  await dlg.getByRole('button', { name: 'Create Trigger' }).click();
  await expect(dlg.getByTestId('trigger-form-error')).toContainText('five cron fields');
  // a malformed one the server rejects shows its message, not [object Object]
  await dlg.getByLabel('Cron Expression').fill('99 99 * * *');
  await dlg.getByRole('button', { name: 'Create Trigger' }).click();
  await expect(dlg.getByTestId('trigger-form-error')).toContainText('Invalid cron expression');
  expectPlain(await dlg.getByTestId('trigger-form-error').innerText());
  await dlg.getByRole('button', { name: 'Every 5 minutes' }).click();
  await expect(dlg.getByLabel('Cron Expression')).toHaveValue('*/5 * * * *');
  await dlg.getByLabel('Default Message').fill('Reply with the single word scheduled.');
  await dlg.getByLabel('Name').fill(TRIGGER);
  await dlg.getByRole('button', { name: 'Create Trigger' }).click();
  await expect(dlg).toHaveCount(0, { timeout: 20_000 });

  const list = (await api(page, 'GET', `/api/triggers?agent_id=${ids.agent}`)).json;
  expect(list.meta.total).toBe(1);
  const trig = list.data[0];
  ids.trigger = trig.id;
  expect(trig.cron_expression).toBe('*/5 * * * *');
  expect(trig.name).toBe(TRIGGER);
  expect(new Date(trig.next_run_at).getTime() - Date.now()).toBeLessThan(5 * 60_000 + 30_000);
  const row = page.getByTestId(`trigger-row-${trig.id}`);
  await expect(row).toContainText('*/5 * * * *');
  await expect(row).toContainText('Next:');
  await expect(page.getByTestId(`trigger-name-${trig.id}`)).toHaveText(TRIGGER);
  // a new trigger says it has not run yet
  await expect(page.getByTestId(`trigger-no-runs-${trig.id}`)).toBeVisible();
  await expect(page.getByText(/^Showing 1.1 of 1$/)).toBeVisible();
  await shot(page, '13-trigger-created');

  await page.getByTestId(`trigger-run-${trig.id}`).click();
  const runLink = page.getByTestId(`trigger-run-link-${trig.id}`);
  await expect(runLink).toBeVisible({ timeout: 30_000 });
  const execId = String(await runLink.getAttribute('href')).split('/').pop()!;
  await expect.poll(async () => (await api(page, 'GET', `/api/executions/${execId}`)).json?.data?.status, { timeout: LLM_MS, intervals: [3_000] }).toBe('completed');
  const ex = (await api(page, 'GET', `/api/executions/${execId}`)).json.data;
  expect(ex.agent_id).toBe(ids.agent);
  expect(String(ex.output_message || '').toLowerCase()).toContain('scheduled');
  ids.triggerExec = execId;
  // the run records the trigger that started it
  expect(ex.trigger_id).toBe(trig.id);
  expect(ex.trigger_kind).toBe('manual');
  expect(ex.trigger_name).toBe(TRIGGER);
  expect(ex.started_by).toContain(TRIGGER);
  await page.reload();
  await expect(row).toContainText('1 execution', { timeout: 20_000 });
  await expect(row).toContainText('completed', { timeout: 30_000 });
  // the trigger lists its recent runs with their status
  const recent = row.locator(`[data-testid="trigger-recent-run"][data-execution-id="${execId}"]`);
  await expect(recent).toBeVisible({ timeout: 30_000 });
  await expect(recent).toHaveAttribute('data-status', 'completed', { timeout: 30_000 });
  await expect(recent).toContainText(/completed/i);
  await shot(page, '13b-trigger-recent-runs');
  // and opens the runs list filtered to itself
  await page.getByTestId(`trigger-all-runs-${trig.id}`).click();
  await page.waitForURL((u) => u.pathname === '/executions' && u.searchParams.get('trigger') === trig.id, { timeout: 20_000 });
  await expect(page.getByTestId('exec-trigger-chip')).toContainText(TRIGGER, { timeout: 20_000 });
  await expect(page.getByTestId('execution-list')).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 });
  const listed = page.getByTestId('execution-row');
  await expect(listed).toHaveCount(1, { timeout: 20_000 });
  await expect(listed.first().getByTestId('execution-started-by')).toContainText(`Started by ${TRIGGER} (run now)`);
  // the Started by filter finds it among trigger runs
  await go(page, '/executions');
  await page.getByTestId('exec-origin-filter').selectOption({ label: 'Any trigger' });
  await expect(page.getByTestId('execution-list')).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 });
  await expect(page.locator(`a[href="/executions/${execId}"]`)).toBeVisible({ timeout: 20_000 });
  for (const kind of await page.getByTestId('execution-started-by').evaluateAll((els) => els.map((e) => e.getAttribute('data-kind')))) {
    expect(['schedule', 'webhook', 'manual']).toContain(kind);
  }
  // the run page says the same and links back to the trigger
  await go(page, `/executions/${execId}`);
  const startedBy = page.getByTestId('execution-started-by');
  await expect(startedBy).toContainText(`Started by ${TRIGGER} (run now)`, { timeout: 20_000 });
  await startedBy.getByTestId('execution-started-by-link').click();
  await page.waitForURL((u) => u.pathname === '/triggers' && u.searchParams.get('focus') === trig.id, { timeout: 20_000 });
  await expect(page.getByTestId('trigger-focus-filter')).toContainText(TRIGGER, { timeout: 20_000 });
  await expect(page.getByTestId(`trigger-row-${trig.id}`)).toBeVisible();
  await shot(page, '13c-run-started-by');
  await go(page, '/triggers');
  // the agent's runs are one click away from the row
  await page.getByTestId(`trigger-runs-link-${trig.id}`).click();
  await page.waitForURL((u) => u.pathname === '/executions' && u.searchParams.get('agent') === ids.agent, { timeout: 20_000 });
  await expect(page.getByTestId('exec-agent-chip')).toContainText(AGENT, { timeout: 20_000 });
  await expect(page.locator(`a[href="/executions/${execId}"]`)).toBeVisible({ timeout: 20_000 });
  await page.locator(`a[href="/executions/${execId}"]`).click();
  await page.waitForURL(new RegExp(`/executions/${execId}`), { timeout: 20_000 });
  await expect(page.getByText(/scheduled/i).first()).toBeVisible({ timeout: 20_000 });
  await shot(page, '14-trigger-execution');

  // search by the agent name finds the trigger, then delete it with a confirm
  await go(page, '/triggers');
  await page.getByLabel('Search triggers').fill(AGENT);
  await expect(page.getByTestId(`trigger-row-${trig.id}`)).toBeVisible({ timeout: 20_000 });
  await page.getByTestId(`trigger-row-${trig.id}`).getByRole('button', { name: 'Delete trigger' }).click();
  await expect(page.getByTestId(`trigger-row-${trig.id}`)).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId('triggers-empty')).toContainText('No triggers match');
  ids.trigger = undefined;
  // the run keeps the trigger name after the trigger is gone, and says so
  await go(page, `/executions/${execId}`);
  await expect(page.getByTestId('execution-started-by')).toContainText(TRIGGER, { timeout: 20_000 });
  await expect(page.getByTestId('execution-started-by')).toContainText('The trigger has since been deleted.');
  const after = (await api(page, 'GET', `/api/executions/${execId}`)).json.data;
  expect(after.trigger_id).toBeNull();
  expect(after.trigger_name).toBe(TRIGGER);

  // a chat run says it came from chat
  await go(page, `/agents/${ids.agent}/chat`);
  await chat(page, 'Reply with the single word pong.');
  const chatRun = (await api(page, 'GET', `/api/executions?agent_id=${ids.agent}&trigger_kind=chat&limit=1`)).json.data[0];
  expect(chatRun?.trigger_kind).toBe('chat');
  await go(page, `/executions?agent=${ids.agent}&started_by=chat`);
  await expect(page.getByTestId('execution-list')).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 });
  const chatRow = page.locator(`[data-testid="execution-row"]:has(a[href="/executions/${chatRun.id}"])`);
  await expect(chatRow.getByTestId('execution-started-by')).toHaveText('Started by Chat', { timeout: 20_000 });
  await go(page, `/executions/${chatRun.id}`);
  await expect(page.getByTestId('execution-started-by')).toContainText('Started by Chat', { timeout: 20_000 });
  await shot(page, '14b-chat-started-by');
});

test('Evals: suite for an agent, case from a real run, two runs compared', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  const execId = await ensureRun(page);
  const suiteName = `Walker golden ${RUN}`;

  await go(page, '/evals');
  await expect(page.getByRole('heading', { name: 'Evaluations' })).toBeVisible();
  await page.getByTestId('eval-new-suite').click();
  const dlg = page.getByRole('dialog', { name: 'New evaluation suite' });
  await expect(dlg.getByTestId('eval-suite-agent').locator(`option[value="${ids.agent}"]`)).toHaveCount(1, { timeout: 30_000 });
  await dlg.getByTestId('eval-suite-agent').selectOption(ids.agent!);
  await dlg.getByTestId('eval-suite-name').fill(suiteName);
  await dlg.getByTestId('eval-suite-create').click();
  await page.waitForURL(/\/evals\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  ids.suite = page.url().split('/').pop();
  await expect(page.getByTestId('eval-suite-title')).toHaveText(suiteName);
  await expect(page.getByTestId('eval-run-now')).toBeDisabled();

  // a real run becomes the case
  await go(page, `/executions/${execId}`);
  await page.getByTestId('execution-save-eval-case').click();
  const save = page.getByRole('dialog', { name: 'Save as eval case' });
  await save.getByRole('radio', { name: suiteName }).check();
  await save.getByLabel(/Case name/).fill('Pong reply');
  await save.getByTestId('save-case-confirm').click();
  await expect(save).toContainText(/Saved with \d+ suggested assertion/, { timeout: 30_000 });
  await save.getByTestId('save-case-open-suite').click();
  await page.waitForURL(new RegExp(`/evals/${ids.suite}`), { timeout: 20_000 });
  const suite = (await api(page, 'GET', `/api/evals/suites/${ids.suite}`)).json.data;
  expect(suite.cases.length).toBe(1);
  expect(suite.cases[0].name).toBe('Pong reply');
  await expect(page.getByTestId(`eval-case-${suite.cases[0].id}`)).toBeVisible();
  await shot(page, '15-eval-case');

  // run it twice
  const runIds: string[] = [];
  for (let i = 0; i < 2; i++) {
    await go(page, `/evals/${ids.suite}`);
    await expect(page.getByTestId('eval-run-now')).toBeEnabled({ timeout: 30_000 });
    await page.getByTestId('eval-run-now').click();
    await expect(page.getByTestId('eval-active-run')).toBeVisible({ timeout: 30_000 });
    await expect.poll(async () => {
      const d = (await api(page, 'GET', `/api/evals/suites/${ids.suite}`)).json.data;
      const done = (d.runs as any[]).filter((r) => !['queued', 'running'].includes(r.status));
      return done.length;
    }, { timeout: LLM_MS, intervals: [5_000] }).toBe(i + 1);
  }
  const runs = ((await api(page, 'GET', `/api/evals/suites/${ids.suite}`)).json.data.runs as any[]);
  for (const r of runs) {
    expect(r.total).toBe(1);
    runIds.push(r.id);
  }

  await go(page, `/evals/${ids.suite}`);
  await page.getByTestId('eval-tab-runs').click();
  const table = page.getByTestId('eval-runs-table');
  await expect(table.locator('tbody tr')).toHaveCount(2, { timeout: 30_000 });
  await expect(table).toContainText('1/1');
  await expect(page.getByTestId('eval-compare-runs')).toBeDisabled();
  const boxes = table.getByRole('checkbox', { name: 'Pick for comparison' });
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await shot(page, '16-eval-runs');
  await page.getByTestId('eval-compare-runs').click();
  await page.waitForURL(/\/evals\/compare\?a=.+&b=.+/, { timeout: 20_000 });
  await expect(page.getByTestId('eval-compare-heads')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('eval-compare-table')).toContainText('Pong reply');
  await shot(page, '17-eval-compare');

  // one run's detail links back to the real execution it made
  await go(page, `/evals/runs/${runIds[0]}`);
  await expect(page.getByTestId('eval-run-verdict')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('eval-run-score')).toHaveText(/\d+%/);
  await page.getByTestId('eval-run-results').getByText('Pong reply').click();
  await expect(page.getByTestId('eval-result-execution').first()).toHaveAttribute('href', /\/executions\//);
});

test('Meetings: create one, set its scope, keys explained, connect details, delete', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  const title = `Walker standup ${RUN}`;
  const ready = (await api(page, 'GET', '/api/meetings/readiness')).json.data;
  await go(page, '/meetings');
  await expect(page.getByRole('heading', { name: 'Meeting sessions' })).toBeVisible();
  // plain words, not internal jargon
  await expect(page.getByText('An agent can sit in a call for you')).toBeVisible();
  await expect(page.getByText(/OOB|first-class product|execution surface/)).toHaveCount(0);
  if (ready.livekit_ready) {
    await expect(page.getByTestId('meetings-readiness')).toHaveCount(0);
  } else {
    await expect(page.getByTestId('meetings-readiness')).toContainText('LiveKit');
    await expect(page.getByTestId('meetings-readiness')).toContainText('you can still');
  }
  await page.getByRole('tab', { name: 'history' }).click();
  await expect(page.getByTestId('meetings-empty').or(page.locator('a[href^="/meetings/"]').first())).toBeVisible();
  await page.getByRole('tab', { name: 'upcoming' }).click();

  await page.getByTestId('new-meeting-btn').click();
  await page.getByLabel('Meeting title').fill(title);
  await page.getByTestId('new-meeting-create').click();
  await page.waitForURL(/\/meetings\/[0-9a-f-]{36}$/, { timeout: 20_000 });
  ids.meeting = page.url().split('/').pop();
  await expect(page.getByTestId('meeting-title')).toContainText(title);
  // no topics yet, so the bot has nothing it may answer on
  await expect(page.getByTestId('scope-badge')).toHaveAttribute('data-set', 'false');
  await expect(page.getByTestId('scope-badge')).toHaveText('no topics yet');

  // the bot's scope: what it may answer, what it hands back
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Answers on', { exact: true }).fill('status update');
  await page.getByLabel('Answers on', { exact: true }).press('Enter');
  // typed but not added still saves
  await page.getByLabel('Always hands back', { exact: true }).fill('pricing');
  await page.getByRole('button', { name: /^Save/ }).click();
  await expect(page.getByTestId('scope-badge')).toHaveAttribute('data-set', 'true', { timeout: 20_000 });
  await expect(page.getByTestId('scope-badge')).toHaveText('topics set');
  const m = (await api(page, 'GET', `/api/meetings/${ids.meeting}`)).json.data;
  expect(m.scope_allow).toEqual(['status update']);
  expect(m.scope_defer).toEqual(['pricing']);
  await shot(page, '18-meeting-scope');

  // joining details, or a plain reason they are missing
  await page.getByTestId('connect-from-browser').click();
  if (ready.livekit_ready) {
    const panel = page.getByTestId('connect-panel');
    await expect(panel).toBeVisible({ timeout: 20_000 });
    await expect(panel).toContainText('Join from another LiveKit app');
    await expect(panel).toContainText('Server URL');
    await expect(panel).toContainText(/(wss?|https?):\/\/\S+/);
    await expect(panel).toContainText('Token');
    await expect(panel).toContainText('Joining as');
    await expect(panel).toContainText('The token works for one hour.');
    // joining in this browser is its own page
    await expect(page.getByTestId('join-meeting')).toHaveAttribute('href', `/meetings/${ids.meeting}/join`);
  } else {
    await expect(page.getByTestId('connect-error')).toContainText('Tool configuration');
    // and the bot will not pretend to go live
    await page.getByTestId('start-bot').click();
    await expect(page.getByTestId('meeting-error')).toContainText('LiveKit');
    expect((await api(page, 'GET', `/api/meetings/${ids.meeting}`)).json.data.status).not.toBe('live');
  }
  await shot(page, '19-meeting-connect');

  await page.getByTestId('delete-meeting').click();
  // it asks first, in words
  const ask = page.getByRole('dialog', { name: 'Delete this meeting?' });
  await expect(ask).toContainText('cannot be undone');
  await ask.getByTestId('confirm-action').click();
  await page.waitForURL(/\/meetings$/, { timeout: 20_000 });
  expect((await api(page, 'GET', `/api/meetings/${ids.meeting}`)).status).toBe(404);
  ids.meeting = undefined;
});

test('Marketplace and Creator Hub: list an agent, review it, see it in the store', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await ensureAgent(page);
  await go(page, `/builder?agent=${ids.agent}`);
  await expect(page.getByTestId('builder-publish')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('builder-publish').click();
  await expect(page.getByTestId('publish-visibility-org')).toBeVisible();
  if (!(await page.getByTestId('publish-visibility-public').count())) {
    // this deployment has the marketplace switched off, every surface must say so
    test.info().annotations.push({ type: 'marketplace-off', description: 'NEXT_PUBLIC_ENABLE_MONETIZATION=false on this build, listing is not offered' });
    await page.keyboard.press('Escape');
    for (const route of ['/marketplace', '/creator', '/review-queue']) {
      await go(page, route);
      await expect(page.getByTestId('marketplace-off')).toContainText('switched off', { timeout: 20_000 });
      expectPlain(await page.getByTestId('marketplace-off').innerText());
    }
    await shot(page, '20-marketplace-off');
    await expect(page.getByText('Agents land here when their owner publishes them')).toBeVisible();
    await go(page, '/agents');
    await expect(page.getByTestId('agents-tab-all')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('agents-tab-marketplace')).toHaveCount(0);
    // the store still shows the built-in agents as it would to anyone
    await go(page, '/marketplace');
    await page.getByPlaceholder('Search agents by name or description...').fill('Research Assistant');
    await page.getByText('Research Assistant').first().click();
    await page.waitForURL(/\/marketplace\/[0-9a-f-]{36}/, { timeout: 20_000 });
    await expect(page.getByRole('heading', { level: 1, name: 'Research Assistant' })).toBeVisible({ timeout: 20_000 });
    await shot(page, '21-marketplace-detail');
    return;
  }
  await page.getByTestId('publish-visibility-public').click();
  await expect(page.getByText('submitted for review before going live')).toBeVisible();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
  await expect(page.getByText('Submitted for review')).toBeVisible({ timeout: 10_000 });
  expect((await api(page, 'GET', `/api/agents/${ids.agent}`)).json.data.status).toBe('pending_review');

  // the creator sees it waiting
  await go(page, '/creator');
  await expect(page.getByRole('heading', { name: 'Creator Hub' })).toBeVisible();
  const mine = page.getByTestId('creator-listing').filter({ hasText: AGENT });
  await expect(mine).toHaveAttribute('data-state', 'pending', { timeout: 20_000 });

  // an admin approves it from the queue, however many agents the tenant has
  await go(page, '/review-queue');
  // the inbox opens on held content, submissions have their own tab with a count
  const subTab = page.getByTestId('review-tab-marketplace');
  await expect(subTab).toBeVisible({ timeout: 20_000 });
  await expect(subTab).toContainText(/\d/, { timeout: 20_000 });
  await subTab.click();
  await page.waitForURL(/tab=marketplace/, { timeout: 20_000 });
  const card = page.locator('div', { has: page.getByRole('heading', { name: AGENT, level: 3 }) }).filter({ has: page.getByRole('button', { name: 'Approve' }) }).last();
  await expect(card).toBeVisible({ timeout: 20_000 });
  await shot(page, '20-review-queue');
  await card.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByRole('heading', { name: AGENT, level: 3 })).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId('review-error')).toHaveCount(0);
  const live = (await api(page, 'GET', `/api/agents/${ids.agent}`)).json.data;
  expect(live.is_published).toBe(true);
  expect(live.status).toBe('active');

  // the store shows it
  await go(page, '/marketplace');
  await page.getByPlaceholder('Search agents by name or description...').fill(AGENT);
  const tile = page.getByText(AGENT).first();
  await expect(tile).toBeVisible({ timeout: 30_000 });
  await tile.click();
  await page.waitForURL(new RegExp(`/marketplace/${ids.agent}`), { timeout: 20_000 });
  await expect(page.getByRole('heading', { name: AGENT })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Walks the sidebar for the nav UAT.').first()).toBeVisible();
  await shot(page, '21-marketplace-detail');

  // and Creator Hub counts and links it
  await go(page, '/creator');
  await expect(mine).toHaveAttribute('data-state', 'live', { timeout: 20_000 });
  // listing is free, so the counts come from listings, not the paid dashboard
  const listed = (await api(page, 'GET', '/api/creator/listings')).json.data;
  expect(listed.totals.live).toBeGreaterThanOrEqual(1);
  await expect(page.getByTestId('creator-kpis').getByText('Live listings').locator('..')).toContainText(String(listed.totals.live));
  await mine.getByRole('link', { name: 'View in the store' }).click();
  await page.waitForURL(new RegExp(`/marketplace/${ids.agent}`), { timeout: 20_000 });
  await shot(page, '22-creator-hub');
});

test('MCP: connect the in-cluster server, see its tools, disconnect', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  const name = `Walker MCP ${RUN}`;
  await go(page, '/mcp');
  await expect(page.getByRole('heading', { name: 'MCP Servers' })).toBeVisible();
  await page.getByRole('button', { name: 'Add Server' }).first().click();
  const dlg = page.getByRole('dialog');
  // an address that is not a server gets a reason
  await dlg.getByLabel('Server URL').fill('http://nothing-here.invalid/mcp');
  await dlg.getByLabel('Server Name').click();
  await expect(dlg.getByTestId('mcp-discover-error')).toBeVisible({ timeout: 30_000 });
  expectPlain(await dlg.getByTestId('mcp-discover-error').innerText());
  await dlg.getByLabel('Server Name').fill(name);
  await dlg.getByLabel('Server URL').fill(MCP_URL);
  await dlg.getByLabel('Server Name').click();
  await expect(dlg.getByTestId('mcp-discover-count')).toContainText(/[1-9]\d* tools? discovered/, { timeout: 30_000 });
  await dlg.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(dlg).toHaveCount(0, { timeout: 30_000 });

  const card = page.getByTestId('mcp-server-card').and(page.locator(`[data-name="${name}"]`));
  await expect(card).toBeVisible({ timeout: 20_000 });
  const conns = (await api(page, 'GET', '/api/mcp/connections')).json.data as any[];
  const mine = conns.find((c) => c.server_name === name);
  expect(mine).toBeTruthy();
  ids.mcp = mine.id;
  if (!(mine.discovered_tools || []).length) await card.getByRole('button', { name: /Discover/ }).click();
  await expect(card).toContainText(/[1-9]\d* tools/, { timeout: 30_000 });
  await card.getByRole('button', { name: `Check ${name}` }).click();
  await expect(card).toContainText('Healthy', { timeout: 30_000 });
  await card.getByRole('button', { name: `View tools of ${name}` }).click();
  const drawer = page.getByRole('dialog', { name: `Tools of ${name}` });
  const rows = drawer.getByTestId('mcp-tool-row');
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  const fresh = ((await api(page, 'GET', '/api/mcp/connections')).json.data as any[]).find((c) => c.id === ids.mcp);
  await expect(rows).toHaveCount(fresh.discovered_tools.length);
  await expect(rows.first()).toContainText(fresh.discovered_tools[0].name);
  await shot(page, '23-mcp-tools');
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);

  await card.getByRole('button', { name: `Delete ${name}` }).click();
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(card).toHaveCount(0, { timeout: 20_000 });
  expect(((await api(page, 'GET', '/api/mcp/connections')).json.data as any[]).some((c) => c.id === ids.mcp)).toBe(false);
  ids.mcp = undefined;
});

test('Edge: what works without hardware, a token that can be revoked', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
  await go(page, '/edge');
  await expect(page.getByRole('heading', { name: 'Edge Gateways' })).toBeVisible();
  // the steps read in order
  const step1 = page.getByText(/^Step 1\. What the gateway box needs/);
  const step2 = page.getByText(/^Step 2\. Get a gateway token/);
  await expect(step1).toBeVisible();
  await expect(step2).toBeVisible();
  expect((await step1.boundingBox())!.y).toBeLessThan((await step2.boundingBox())!.y);
  await step1.click();
  await expect(page.getByText('Three tiers. Pick by hardware.')).toBeVisible();

  // runtime choices with copyable install lines
  const variants = page.getByTestId('edge-runtime-variants');
  await expect(variants.locator('[data-testid^="runtime-card-"]').first()).toBeVisible({ timeout: 20_000 });
  const firstCopy = variants.locator('[data-testid^="copy-helm-"]').first();
  await firstCopy.click();
  const helm = await page.evaluate(() => navigator.clipboard.readText());
  expect(helm).toMatch(/helm (install|upgrade)/);

  // registered gateways, or a plain note on how one appears
  const gws = (await api(page, 'GET', '/api/edge/gateways')).json.data.gateways as any[];
  if (!gws.length) await expect(page.getByText('No edge gateways registered yet.')).toBeVisible();
  else await expect(page.getByText(`Registered gateways (${gws.length})`)).toBeVisible();

  // a token and the signing key, once
  await page.getByTestId('edge-mint').click();
  const modal = page.getByRole('dialog', { name: 'Edge token and signing key' });
  await expect(modal).toBeVisible({ timeout: 20_000 });
  await expect(modal.getByTestId('edge-token-value')).toHaveText(/^af_[\w-]{20,}$/);
  await expect(modal.getByTestId('edge-pubkey')).toContainText('BEGIN PUBLIC KEY');
  const keyName = (await modal.getByTestId('edge-token-key-name').locator('strong').innerText()).trim();
  expect(keyName).toMatch(/^edge gateway \d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  await shot(page, '24-edge-token');
  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);

  // retire it where the modal says
  await go(page, '/settings/api-keys');
  const keys = (await api(page, 'GET', '/api/api-keys')).json.data as any[];
  const minted = keys.filter((k) => k.name === keyName);
  expect(minted.length).toBe(1);
  ids.edgeKey = minted[0].id;
  await page.getByTestId(`apikey-revoke-${minted[0].id}`).click();
  await page.getByRole('button', { name: 'Revoke key' }).last().click();
  await expect(page.getByTestId(`apikey-revoke-${minted[0].id}`)).toHaveCount(0, { timeout: 20_000 });
  ids.edgeKey = undefined;
});

test('Moderation: policies, a test that blocks, a chat that blocks, both in the events list', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  const SSN_RE = String.raw`\b\d{3}-\d{2}-\d{4}\b`;
  const policies = (await api(page, 'GET', '/api/moderation/policies')).json.data as any[];
  const active = policies.find((p) => p.is_active);
  await go(page, '/moderation');
  await expect(page.getByRole('heading', { name: 'Content Moderation' })).toBeVisible();
  await expect(page.getByTestId('policies-section')).toContainText(`(${policies.length} total, ${policies.filter((p) => p.is_active).length} active)`, { timeout: 20_000 });
  if (!active || !(active.custom_patterns || []).includes(SSN_RE) || active.default_action !== 'block') {
    test.info().annotations.push({ type: 'skipped-check', description: 'the active policy does not block SSNs, so the blocking checks were skipped' });
    return;
  }
  await expect(page.getByTestId(`policy-row-${active.id}`)).toContainText(active.name);

  // the tester on the page
  const secret = '123-45-6789';
  await page.getByLabel('Content to test').fill(`Payroll note, employee SSN ${secret}.`);
  await page.getByRole('button', { name: 'Test it' }).click();
  await expect(page.getByTestId('vet-result-outcome')).toContainText('blocked', { timeout: 60_000 });
  const cats = page.getByTestId('vet-result-categories');
  await expect(cats).toContainText('custom pattern');
  await expect(cats).not.toContainText('custom:');
  const firstEvent = page.getByTestId('events-list').locator('[data-testid^="event-row-"]').first();
  await expect(firstEvent).toContainText('Test on this page', { timeout: 20_000 });
  await expect(firstEvent).toContainText('Payroll note');
  // the secret the policy caught is not kept in the log
  await expect(firstEvent).not.toContainText(secret);
  await shot(page, '25-moderation-test');

  // a real chat hits the same policy
  await ensureAgent(page);
  await go(page, `/agents/${ids.agent}/chat`);
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(`Please remember my SSN ${secret}`);
  await page.getByTestId('chat-send').click();
  const said = page.getByTestId('chat-error').or(page.locator('[data-testid="chat-message"][data-role="assistant"]').last());
  await expect(said).toContainText('moderation policy', { timeout: LLM_MS });
  const text = await said.innerText();
  expect(text).not.toMatch(/custom:\d/);
  expectPlain(text);
  await shot(page, '26-moderation-chat');

  await expect.poll(async () => {
    const ev = (await api(page, 'GET', '/api/moderation/events?limit=20')).json.data as any[];
    return ev.find((e) => e.source === 'pre_llm' && e.outcome === 'blocked' && String(e.content_preview || '').includes('remember my SSN'))?.id || '';
  }, { timeout: 60_000, intervals: [3_000] }).not.toBe('');
  const ev = ((await api(page, 'GET', '/api/moderation/events?limit=20')).json.data as any[]).find((e) => e.source === 'pre_llm' && String(e.content_preview || '').includes('remember my SSN'));
  expect(ev.content_preview).not.toContain(secret);
  await go(page, '/moderation');
  const row = page.getByTestId(`event-row-${ev.id}`);
  await expect(row).toContainText('Input, before the model', { timeout: 20_000 });
  if (ev.execution_id) {
    await row.getByTestId(`event-run-${ev.id}`).click();
    await page.waitForURL(new RegExp(`/executions/${ev.execution_id}`), { timeout: 20_000 });
  }
});

test('Phone width: no sideways scroll on the pages walked above', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = [
    '/dashboard', '/agents', '/knowledge', '/sources', '/sdk-playground', '/triggers', '/evals', '/meetings',
    '/marketplace', '/creator', '/mcp', '/edge', '/moderation', '/review-queue', '/executions?since=today',
  ];
  if (ids.agent) routes.push(`/agents/${ids.agent}/info`, `/triggers?agent=${ids.agent}`);
  if (ids.kb) routes.push(`/knowledge?id=${ids.kb}`, `/knowledge/${ids.kb}/engine`);
  const wide: string[] = [];
  for (const [i, route] of routes.entries()) {
    await go(page, route);
    await page.waitForTimeout(1_500);
    // a dialog that opens on its own (triggers for a new agent) is part of the check
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    await shot(page, `${30 + i}-phone${route.replace(/[/?=&]/g, '-')}`);
    if (m.sw > m.iw + 1) wide.push(`${route} scrollWidth=${m.sw} innerWidth=${m.iw}`);
  }
  expect(wide, wide.join('\n')).toEqual([]);
});


test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await signIn(page);
  for (const id of [ids.agent, ids.kbAgent, ...extraAgents]) if (id) await api(page, 'DELETE', `/api/agents/${id}?force=true`);
  if (ids.kb) await api(page, 'DELETE', `/api/knowledge-bases/${ids.kb}?force=true`);
  if (ids.source) await api(page, 'DELETE', `/api/sources/${ids.source}`);
  if (ids.trigger) await api(page, 'DELETE', `/api/triggers/${ids.trigger}`);
  if (ids.suite) await api(page, 'DELETE', `/api/evals/suites/${ids.suite}`);
  if (ids.meeting) await api(page, 'DELETE', `/api/meetings/${ids.meeting}`);
  if (ids.mcp) await api(page, 'DELETE', `/api/mcp/connections/${ids.mcp}`);
  if (ids.edgeKey) await api(page, 'DELETE', `/api/api-keys/${ids.edgeKey}`);
  await page.close();
  fs.rmSync(FIX, { recursive: true, force: true });
});
