/**
 * AI Builder and pipeline healing, from the screens only, as a new user would use them.
 *
 *   1. Simple agent     describe an invoice checker, build, inspect, save, publish, chat with a CSV
 *   2. Pipeline         describe a fetch, extract, average, summarise pipeline, build, run, read the output
 *   3. Broken pipeline  break a step argument in the builder, run, diagnose on Healing, apply, re-run
 *   4. Broken agent     an agent whose tool config makes it fail, look for a fix path
 *   5. Phone width      builder, healing and chat at 390px
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 USE_K8S=true npx playwright test e2e/uat_ai_build_and_heal_ui.spec.ts --workers=1
 */
import { test, expect, type Page, type Locator } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);

const DIR = path.join(__dirname, 'uat_ai_build_and_heal_ui');
const SHOTS = path.join(DIR, 'shots');
const LLM_MS = 300_000;

const ids: { agent?: string; pipeline?: string; broken?: string; brokenAgent?: string } = {};
const ux: string[] = [];

test.use({ viewport: { width: 1440, height: 900 } });

function note(msg: string) {
  ux.push(msg);
  console.log(`UX: ${msg}`);
}

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
    timeout: 120_000,
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
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

// a message a person can read, not a stack trace or a JSON dump
function expectPlain(msg: string) {
  expect(msg.trim().length).toBeGreaterThan(0);
  expect(msg.length).toBeLessThan(800);
  expect(msg).not.toMatch(/Traceback|File "[^"]+", line \d+|^\s*[{[]\s*"|Exception:|\bat [\w.$]+ \(/);
}

async function noSideScroll(page: Page, where: string) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (over > 2) note(`${where}: page scrolls sideways by ${over}px at 390px`);
  return over;
}

// opens Build with AI, describes the thing and waits for the preview
async function aiBuild(page: Page, description: string, mode: 'agent' | 'pipeline'): Promise<{ dialog: Locator; seconds: number; text: string; raw: any }> {
  await go(page, '/builder');
  await page.getByTestId('ai-builder-button').click();
  const dialog = page.getByRole('dialog').filter({ hasText: 'Build with AI' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId('ai-builder-dialog-model')).toContainText('using');
  await dialog.locator('textarea').fill(description);
  await dialog.getByTestId(`ai-builder-mode-${mode}`).click();
  await shot(page, `${mode}-01-described`);
  const t0 = Date.now();
  await dialog.getByRole('button', { name: /Generate Agent \/ Pipeline/ }).click();
  const apply = dialog.getByRole('button', { name: /Apply to Canvas/ });
  const err = dialog.locator('p.text-red-400');
  await expect(apply.or(err)).toBeVisible({ timeout: LLM_MS });
  const seconds = Math.round((Date.now() - t0) / 1000);
  if (await err.count()) throw new Error(`AI Builder failed: ${await err.innerText()}`);
  if (seconds > 45) note(`AI Builder (${mode}) took ${seconds}s with only a spinner, no step-by-step progress unless Iterative is ticked`);
  await shot(page, `${mode}-02-preview`);
  const text = await dialog.innerText();
  await dialog.getByText('View raw config (JSON)').click();
  const raw = JSON.parse(await dialog.locator('pre').last().innerText());
  return { dialog, seconds, text, raw };
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test.afterAll(async () => {
  console.log('\n===== UX notes =====');
  for (const u of [...new Set(ux)]) console.log(`  - ${u}`);
});

const INVOICES = [
  'invoice_id,vendor,date,amount_eur',
  'INV-1001,Acme GmbH,2026-09-01,4200.00',
  'INV-1002,Nordlicht AG,2026-09-02,12500.00',
  'INV-1003,Acme GmbH,2026-09-03,980.50',
  'INV-1004,Brightway SARL,2026-09-04,7300.00',
  'INV-1002,Nordlicht AG,2026-09-02,12500.00',
  'INV-1005,Kestrel BV,2026-09-05,10000.00',
  'INV-1006,Kestrel BV,2026-09-06,18250.75',
  'INV-1007,Acme GmbH,2026-09-07,640.00',
].join('\n');

test('1. Simple agent: describe, build, inspect, save, publish and use it from chat', async ({ page }) => {
  test.setTimeout(15 * 60_000);
  const { dialog, text, raw } = await aiBuild(
    page,
    'An agent that reads a CSV of invoices I paste into the chat (columns invoice_id, vendor, date, amount_eur) ' +
      'and flags duplicate invoices (same invoice_id, or same vendor, date and amount) and every invoice with an amount ' +
      'over 10,000 EUR. Reply with a short table of flagged rows and the reason for each.',
    'agent',
  );

  // what the preview shows a person
  expect(text).toMatch(/Generated:/);
  expect(text).toContain('Agent');
  expect(text).toMatch(/Tools \(\d+\)/);
  console.log(`agent preview: ${raw.name}, tools=${JSON.stringify(raw.tools)}`);
  expect(raw.mode).toBe('agent');
  expect(String(raw.system_prompt || '').length).toBeGreaterThan(200);
  expect(raw.system_prompt).toMatch(/duplicate/i);
  expect(raw.system_prompt).toMatch(/10[,.]?000/);
  if (!(await dialog.getByTestId('ai-builder-system-prompt').count())) note('AI Builder preview does not show the generated system prompt, only the raw JSON has it');
  else {
    await dialog.getByTestId('ai-builder-system-prompt').locator('summary').click();
    await expect(dialog.getByTestId('ai-builder-system-prompt')).toContainText(/duplicate/i);
  }

  await dialog.getByRole('button', { name: /Apply to Canvas/ }).click();
  await expect(dialog).toBeHidden();

  // the prompt landed in the builder
  await expect.soft(page.getByTestId('builder-category'), 'AI build leaves Category on "Select category"').not.toHaveValue('');
  await page.getByTestId('config-tab-prompt').click();
  const prompt = page.getByTestId('builder-system-prompt');
  await expect(prompt).toBeVisible({ timeout: 15_000 });
  await expect(prompt).toHaveValue(/duplicate/i);
  for (const t of raw.tools || []) {
    await expect.soft(page.locator('.react-flow__node').filter({ hasText: new RegExp(t.replace(/_/g, '[ _]'), 'i') }).first(), `tool ${t} is on screen after Apply`).toBeInViewport({ timeout: 10_000 });
  }
  const name = `Invoice checker ${RUN}`;
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(name);
  await page.getByTestId('builder-name-input').press('Enter');
  await shot(page, 'agent-03-canvas');

  await page.getByTestId('builder-save-draft').click();
  await expect(page).toHaveURL(/\/builder\?agent=/, { timeout: 30_000 });
  ids.agent = new URL(page.url()).searchParams.get('agent') || undefined;
  expect(ids.agent).toBeTruthy();
  await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 });

  const saved = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(saved.json?.data?.name).toBe(name);
  expect(saved.json?.data?.system_prompt).toMatch(/duplicate/i);
  const savedTools: string[] = saved.json?.data?.model_config?.tools || [];
  expect.soft([...savedTools].sort(), 'the saved agent keeps every tool the builder showed').toEqual([...(raw.tools || [])].sort());
  expect.soft(saved.json?.data?.category, 'saved category is one the form offers').not.toBe('engineering');

  await expect(page.getByTestId('builder-publish')).toBeEnabled();
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-submit').click();
  await expect(page).toHaveURL(new RegExp(`/agents/${ids.agent}/chat`), { timeout: 60_000 });
  const pub = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(pub.json?.data?.status).toBe('active');

  if (await page.getByText(/Help me with a task that leverages/).count()) {
    note('agent chat shows the generic "Help me with a task that leverages ..." prompt, the AI-built example prompts were dropped');
  }

  // a person pastes the CSV straight into the chat
  const params = page.locator('[data-testid^="chat-param-"]');
  const required = await page.locator('label').filter({ has: page.locator('span.text-red-400', { hasText: '*' }) }).count();
  const input = page.getByTestId('chat-input');
  const message = `Check these invoices:\n\n${INVOICES}`;
  let answer: string;
  if ((await params.count()) && required) {
    note(`AI-built chat agent has a required input parameter, pasting the CSV in the chat alone is refused`);
    await input.fill(message);
    await page.getByTestId('chat-send').click();
    await expect(page.getByText('Missing required parameters')).toBeVisible({ timeout: 10_000 });
    if (!(await input.inputValue()).includes('INV-1002')) note('chat wipes the pasted message when it refuses to send for a missing parameter');
    await shot(page, 'agent-04-param-wall');
    await params.first().fill(INVOICES);
    answer = await chat(page, message);
  } else {
    answer = await chat(page, message);
  }
  await shot(page, 'agent-04-answer');
  console.log(`agent answer:\n${answer.slice(0, 1500)}`);
  expect(answer).toContain('INV-1002');
  expect(answer).toContain('INV-1006');
  expect(answer).toMatch(/duplicate/i);
  // INV-1005 is exactly 10,000 so it is not over the limit
  const overLines = answer.split('\n').filter((l) => /INV-1005/.test(l));
  for (const l of overLines) {
    // a row of the flagged table means it was flagged
    expect(l, 'INV-1005 is 10,000.00, it must not be in the flagged table').not.toMatch(/\t|\|/);
    // prose may say why it is not flagged, "exactly 10,000 (threshold is >10,000)", but never that it is over
    const negated = /\bnot\b|n't\b|exactly|equal|at the threshold|no flag/i.test(l);
    if (!negated) expect(l, 'INV-1005 is 10,000.00, not over 10,000').not.toMatch(/over|exceed|>\s*10/i);
  }
  for (const clean of ['INV-1001', 'INV-1003', 'INV-1007']) {
    const lines = answer.split('\n').filter((l) => l.includes(clean) && /\|/.test(l));
    if (lines.length) note(`agent table lists ${clean} although it is clean: ${lines[0].slice(0, 120)}`);
  }
});

// a product page the platform ships under /samples, so the run does not depend on the public internet
const SAMPLE_PAGE = '/samples/bookshop-poetry.html';
// the address the cluster fetches it from, the web service inside the cluster
const WEB_IN_CLUSTER = process.env.AF_WEB_INTERNAL || 'http://abenix-web.abenix.svc.cluster.local:3000';
const PRICE_URL = `${WEB_IN_CLUSTER}${SAMPLE_PAGE}`;

// the oracle: average of the prices on the page, read by the test itself through the web app
async function expectedAverage(page: Page): Promise<number | null> {
  try {
    const res = await page.request.get(`${BASE}${SAMPLE_PAGE}`, { timeout: 20_000 });
    const html = await res.text();
    const prices = [...html.matchAll(/class="price_color">[^0-9]*([0-9]+\.[0-9]{2})</g)].map((m) => Number(m[1]));
    if (!prices.length) return null;
    return prices.reduce((a, b) => a + b, 0) / prices.length;
  } catch {
    return null;
  }
}

async function runFromBuilder(page: Page, inputs: Record<string, string> = {}): Promise<{ status: string; text: string }> {
  await page.getByTestId('pipeline-run-button').click();
  const ask = page.getByTestId('run-inputs-dialog');
  await page.waitForTimeout(500);
  if (await ask.count()) {
    for (const [k, v] of Object.entries(inputs)) await ask.getByTestId(`run-input-${k}`).fill(v);
    await ask.getByTestId('run-inputs-submit').click();
  } else if (Object.keys(inputs).length) {
    note('Run Pipeline in the builder never asks for the pipeline inputs, so the first step runs with nothing');
  }
  const label = page.getByText(/^Pipeline (completed|failed)$/);
  await expect(label).toBeVisible({ timeout: LLM_MS });
  const status = (await label.innerText()).includes('failed') ? 'failed' : 'completed';
  // open the details panel to read what each step did
  const panel = page.locator('div.fixed.bottom-0').last();
  if (await page.locator('button[title="Expand details"]').count()) await page.locator('button[title="Expand details"]').click();
  // a failed step only shows its error once you open it
  const rows = panel.locator('div.border.rounded-md > button');
  for (let i = 0; i < (await rows.count()); i++) {
    if (await rows.nth(i).locator('svg.text-red-400').count()) {
      await rows.nth(i).click();
      await page.waitForTimeout(200);
    }
  }
  const text = await panel.innerText();
  return { status, text };
}

test('2. Pipeline: describe, build, inspect the canvas, run it and read the output', async ({ page }) => {
  test.setTimeout(20 * 60_000);
  const avg = await expectedAverage(page);
  console.log(`expected average on the page: ${avg}`);
  expect(avg, `the sample page ${SAMPLE_PAGE} is served and lists prices`).not.toBeNull();
  const { dialog, text, raw } = await aiBuild(
    page,
    'A pipeline that takes a web page URL as input, fetches the page, extracts every product price on it, ' +
      'computes the average price and writes a short two sentence summary that states the number of prices and the average.',
    'pipeline',
  );
  const nodes = raw.pipeline_config?.nodes || [];
  console.log(`pipeline preview: ${raw.name}, nodes=${nodes.map((n: any) => `${n.id}(${n.tool_name || n.type})`).join(' -> ')}`);
  console.log(`inputs: ${JSON.stringify(raw.input_variables)}`);
  expect(raw.mode).toBe('pipeline');
  expect(nodes.length).toBeGreaterThanOrEqual(3);
  expect(text).toMatch(/Pipeline Nodes \(\d+\)/);
  if (raw.validation_issues?.length) note(`AI Builder pipeline came with issues: ${raw.validation_issues.join(' | ').slice(0, 300)}`);

  await dialog.getByRole('button', { name: /Apply to Canvas/ }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('builder-mode-pipeline')).toHaveClass(/emerald/);
  await expect(page.locator('.react-flow__node')).toHaveCount(nodes.length, { timeout: 15_000 });
  for (const n of nodes) await expect.soft(page.locator(`.react-flow__node[data-id="${n.id}"]`), `step ${n.id} on screen`).toBeInViewport();
  const chip = page.locator('[data-testid^="validation-chip-"]').first();
  await expect(chip).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('validation-chip-validating')).toHaveCount(0, { timeout: 30_000 });
  const chipText = await page.locator('[data-testid^="validation-chip-"]').first().innerText();
  console.log(`validation chip: ${chipText}`);
  expect.soft(await page.getByTestId('validation-chip-error').count(), `AI-built pipeline shows validation errors: ${chipText}`).toBe(0);

  const name = `Price summary ${RUN}`;
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('builder-save-draft').click();
  await expect(page).toHaveURL(/\/builder\?agent=/, { timeout: 30_000 });
  ids.pipeline = new URL(page.url()).searchParams.get('agent') || undefined;
  await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 });
  await shot(page, 'pipeline-03-canvas');

  // the builder's Run button, the first thing a person tries
  const urlInput = (raw.input_variables || []).find((v: any) => /url/i.test(v.name))?.name || 'url';
  const first = await runFromBuilder(page, { [urlInput]: PRICE_URL });
  await shot(page, 'pipeline-04-builder-run');
  console.log(`builder run: ${first.status}\n${first.text.slice(0, 1500)}`);
  if (first.status === 'failed') note(`Run Pipeline in the builder failed on the first try: ${first.text.replace(/\s+/g, ' ').slice(0, 300)}`);

  // the Test page, with the URL as the input
  await page.getByRole('button', { name: 'Test', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${ids.pipeline}/chat`));
  const params = page.locator('[data-testid^="chat-param-"]');
  if (await params.count()) await params.first().fill(PRICE_URL);
  else note('the pipeline exposes no input field for the URL on the Test page');
  const answer = await chat(page, `Summarise the prices on ${PRICE_URL}`);
  await shot(page, 'pipeline-05-answer');
  console.log(`pipeline answer:\n${answer.slice(0, 1500)}`);
  expect(answer).toMatch(/average/i);
  const nums = [...answer.matchAll(/([0-9]+\.[0-9]{1,2})/g)].map((m) => Number(m[1]));
  expect(nums.some((n) => Math.abs(n - avg!) < 0.6), `answer states the average ${avg!.toFixed(2)}`).toBeTruthy();
});

test('3. Broken pipeline: a typo in a step argument fails the run, Healing diagnoses it, the fix is applied and the re-run passes', async ({ page }) => {
  test.setTimeout(20 * 60_000);
  const { dialog, raw } = await aiBuild(
    page,
    'A pipeline with exactly two steps and no inputs. Step one, called multiply, uses the calculator tool with the expression 6 * 7. ' +
      'Step two, called announce, depends on multiply and uses llm_call to write one sentence that states the result of step one.',
    'pipeline',
  );
  const nodes = raw.pipeline_config?.nodes || [];
  const calc = nodes.find((n: any) => (n.tool_name || n.tool) === 'calculator');
  console.log(`healing pipeline: ${nodes.map((n: any) => `${n.id}(${n.tool_name})`).join(' -> ')}`);
  expect(calc, 'the builder used the calculator for step one').toBeTruthy();
  await dialog.getByRole('button', { name: /Apply to Canvas/ }).click();

  const name = `Healing check ${RUN}`;
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('builder-save-draft').click();
  await expect(page).toHaveURL(/\/builder\?agent=/, { timeout: 30_000 });
  ids.broken = new URL(page.url()).searchParams.get('agent') || undefined;
  await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 });

  const ok = await runFromBuilder(page);
  console.log(`first run: ${ok.status}`);
  expect(ok.status, `the AI-built pipeline runs before we break it: ${ok.text.slice(0, 400)}`).toBe('completed');
  await page.locator('button:has-text("Clear Results")').click();

  // break it the way people do, a typo in the expression
  await page.locator(`.react-flow__node[data-id="${calc.id}"]`).click();
  await page.getByRole('button', { name: 'Arguments', exact: true }).click();
  const expr = page.locator('#arg-calculator-expression');
  await expect(expr).toBeVisible();
  const autosave = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes(`/api/agents/${ids.broken}`), { timeout: 30_000 });
  await expr.fill('6 x 7');
  await autosave;
  await page.waitForTimeout(1000);
  if (!(await page.getByText('Saved', { exact: true }).count())) note('after a step edit the pipeline autosaves but the top bar never says Saved, Save Draft stays lit');
  expect.soft(await page.getByText('Saved', { exact: true }).count(), 'top bar reads Saved after the autosave').toBe(1);
  const savedBroken = await api(page, 'GET', `/api/agents/${ids.broken}`);
  expect(JSON.stringify(savedBroken.json?.data?.model_config?.pipeline_config)).toContain('6 x 7');

  const bad = await runFromBuilder(page);
  await shot(page, 'heal-01-failed-run');
  console.log(`broken run: ${bad.status}\n${bad.text.slice(0, 600)}`);
  expect(bad.status).toBe('failed');
  expect(bad.text).toMatch(/error|invalid/i);

  // from the failure to the fix
  const heal = page.getByTestId('pipeline-run-heal');
  if (await heal.count()) {
    await heal.click();
  } else {
    note('a failed run in the builder offers no way to the fix, you have to know Healing lives on the agent info page');
    await go(page, `/agents/${ids.broken}/info`);
    await page.getByRole('link', { name: 'Healing' }).click();
  }
  await expect(page).toHaveURL(new RegExp(`/agents/${ids.broken}/healing`));
  await expect(page.getByRole('heading', { name: 'Self-healing' })).toBeVisible();
  const failure = page.locator('section').filter({ hasText: /Recent failures/ });
  await expect(failure).toContainText(calc.id, { timeout: 30_000 });
  await shot(page, 'heal-02-failure-listed');

  const diagnose = page.getByRole('button', { name: /Diagnose latest failure/ });
  await expect(diagnose).toBeEnabled();
  const t0 = Date.now();
  await diagnose.click();
  const pending = page.locator('section').filter({ hasText: /Pending proposals/ });
  await expect(pending.getByRole('button', { name: 'Apply' }).or(page.getByText(/Surgeon failed/))).toBeVisible({ timeout: LLM_MS });
  const secs = Math.round((Date.now() - t0) / 1000);
  if (await page.getByText(/Surgeon failed/).count()) {
    await shot(page, 'heal-03-surgeon-failed');
    throw new Error(`the Surgeon failed: ${(await page.locator('body').innerText()).match(/Surgeon failed[^\n]*\n[^\n]*/)?.[0]}`);
  }
  if (secs > 20) note(`Diagnose took ${secs}s with a spinner on the button only`);
  const card = pending.locator('div.rounded-xl').first();
  const cardText = await card.innerText();
  console.log(`proposal:\n${cardText}`);
  expect(cardText).toMatch(/risk/);
  expect(cardText).toMatch(/conf \d+%/);
  await card.getByRole('button', { name: /Show JSON-Patch/ }).click();
  const patch = await card.locator('pre').innerText();
  console.log(`patch: ${patch}`);
  expect(patch).toMatch(/expression/);
  expect(patch).toMatch(/6\s*\*\s*7/);
  if (!(await card.getByTestId('patch-change').count())) note('the proposal shows a raw JSON-Patch, no before and after of the changed field');
  await shot(page, 'heal-03-proposal');

  await card.getByRole('button', { name: 'Apply' }).click();
  await expect(page.getByText('Patch applied')).toBeVisible({ timeout: 30_000 });
  const applied = page.locator('section').filter({ hasText: /Applied patches/ });
  await expect(applied.getByRole('button', { name: /Roll back/ })).toBeVisible();
  await shot(page, 'heal-04-applied');
  const fixed = await api(page, 'GET', `/api/agents/${ids.broken}`);
  expect(JSON.stringify(fixed.json?.data?.model_config?.pipeline_config)).not.toContain('6 x 7');

  const rerun = page.getByTestId('healing-rerun');
  if (await rerun.count()) await rerun.first().click();
  else {
    note('after Apply there is no way to re-run from Healing, you go back to the builder yourself');
    await go(page, `/builder?agent=${ids.broken}`);
  }
  await expect(page).toHaveURL(new RegExp(`/builder\\?agent=${ids.broken}`));
  await page.locator(`.react-flow__node[data-id="${calc.id}"]`).click();
  await page.getByRole('button', { name: 'Arguments', exact: true }).click();
  await expect(page.locator('#arg-calculator-expression')).not.toHaveValue('6 x 7');
  const again = await runFromBuilder(page);
  await shot(page, 'heal-05-rerun');
  console.log(`re-run: ${again.status}\n${again.text.slice(0, 600)}`);
  expect(again.status).toBe('completed');
});

test('4. Broken agent: a tool pointed at a dead endpoint, what the product offers to fix it', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, '/builder');
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(`Rate quoter ${RUN}`);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('builder-description').fill('Quotes the latest EUR to USD rate from our rates feed for the treasury team.');
  await page.getByTestId('builder-category').selectOption('finance');
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(
    'You quote FX rates. Always call http_client with GET https://rates.invalid/v1/eurusd.json and read the field rate. ' +
      'Never guess a rate. Answer with the rate and the time it was read.',
  );
  await page.getByPlaceholder(/Search tools/).fill('http_client');
  await page.locator('[title*="http_client"], div[role="button"]:has-text("Http Client"), button:has-text("Http Client")').first().click();
  await expect(page.locator('.react-flow__node[data-id="tool-http_client"]')).toBeVisible({ timeout: 10_000 });
  await page.getByTestId('builder-save-draft').click();
  await expect(page).toHaveURL(/\/builder\?agent=/, { timeout: 30_000 });
  ids.brokenAgent = new URL(page.url()).searchParams.get('agent') || undefined;
  await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 });

  await page.getByRole('button', { name: 'Test', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${ids.brokenAgent}/chat`));
  const answer = await chat(page, 'What is EUR/USD right now?');
  await shot(page, 'agent-fix-01-answer');
  console.log(`broken agent answer:\n${answer.slice(0, 800)}`);
  // it must not invent a rate
  expect(answer).not.toMatch(/\b1\.[0-9]{3,4}\b/);

  // where does a person go to fix it
  await go(page, `/agents/${ids.brokenAgent}/info`);
  await shot(page, 'agent-fix-02-info');
  if (!(await page.getByRole('link', { name: 'Healing' }).count())) note('agents get no Healing or diagnose path, only pipelines do. The failed tool call shows in chat but nothing proposes a fix');

  await go(page, `/builder?agent=${ids.brokenAgent}`);
  await page.getByTestId('ai-validate-button').click();
  const v = page.getByRole('dialog').filter({ hasText: 'AI Validate' });
  await v.getByText(/Deep critique/).click();
  await v.getByRole('button', { name: /Run AI Validate/ }).click();
  await expect(v.getByTestId('validate-tier3').or(v.locator('p.text-red-400'))).toBeVisible({ timeout: LLM_MS });
  const verdict = await v.innerText();
  await shot(page, 'agent-fix-03-validate');
  console.log(`AI Validate on the broken agent:\n${verdict.slice(0, 1500)}`);
  if (!/rates\.invalid|unreachable|does not resolve|dead (endpoint|url)/i.test(verdict)) note('AI Validate does not spot the dead endpoint in the agent prompt');
  if (!(await v.getByRole('button', { name: /Apply|Fix/ }).count())) note('AI Validate lists findings for an agent but offers nothing to apply');
});

test('5. Phone width: builder, healing and chat at 390px', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/builder');
  await shot(page, 'phone-01-builder');
  await noSideScroll(page, '/builder');
  const aiBtn = page.getByTestId('ai-builder-button');
  if (await aiBtn.count()) {
    if (!(await aiBtn.isVisible())) note('Build with AI is off screen on a phone');
    await aiBtn.scrollIntoViewIfNeeded();
    const clicked = await aiBtn.click({ timeout: 5_000 }).then(() => true, () => false);
    expect.soft(clicked, 'Build with AI can be tapped on a phone, the top bar does not overlap the form').toBe(true);
    if (!clicked) note('on a phone the builder top bar wraps over the form, Build with AI cannot be tapped');
    else {
      const dialog = page.getByRole('dialog').filter({ hasText: 'Build with AI' });
      await expect(dialog).toBeVisible();
      await shot(page, 'phone-02-ai-builder');
      await noSideScroll(page, 'Build with AI dialog');
      await page.keyboard.press('Escape');
    }
  } else note('Build with AI is not reachable on a phone');

  const agents = await api(page, 'GET', '/api/agents?limit=50');
  const list = agents.json?.data || [];
  const pipe = ids.broken ? { id: ids.broken } : list.find((a: any) => a.model_config?.mode === 'pipeline');
  if (pipe) {
    await go(page, `/agents/${pipe.id}/healing`);
    await expect(page.getByRole('heading', { name: 'Self-healing' })).toBeVisible();
    await shot(page, 'phone-03-healing');
    await noSideScroll(page, 'Healing');
    await go(page, `/builder?agent=${pipe.id}`);
    await shot(page, 'phone-04-builder-pipeline');
    await noSideScroll(page, 'builder with a pipeline');
  }
  const ag = list.find((a: any) => a.model_config?.mode !== 'pipeline');
  if (ag) {
    await go(page, `/agents/${ag.id}/chat`);
    await shot(page, 'phone-05-chat');
    await noSideScroll(page, 'agent chat');
  }
});
