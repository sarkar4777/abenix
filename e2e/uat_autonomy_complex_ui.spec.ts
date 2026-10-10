/**
 * A battery storage desk earns autonomy on agents it builds itself, from the screens only.
 *
 *   1. ML Models       upload a next-hour price model with its features, predict once
 *   2. Code Runner     upload the battery dispatch code, wait for analysis, test run it
 *   3. Decisions       hard limits as rules: at most 50 MW, state of charge 10 to 90, golden tests, publish
 *   4. Agent Builder   a dispatcher agent with the model, the code and mqtt_publish
 *   5. Pipeline        forecast, dispatch wired from the forecast, publish with a templated payload
 *   6. Enrol           the agent from its Actions panel, the pipeline from Autonomy, limits on both
 *   7. Watching        runs record and publish nothing, reviews answered under Approvals
 *   8. Promote         the author is refused, a teammate invited from Settings approves in Approvals
 *   9. Asks first      approve, edit and reject, the approved one really published
 *  10. Limits          a 200 MW command is blocked at any level, with the reason on the card and in the run
 *  11. Outcomes        entered on the card, the record and the chart move
 *  12. Harm            at Acts within limits a harm flag drops it back to Asks first
 *  13. Flight recorder the run page shows the autonomy badge
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_autonomy_complex_ui.spec.ts --workers=1
 *   KEEP=1 keeps what it built, RESUME=1 picks up the last run's state
 */
import fs from 'node:fs';
import path from 'node:path';
import { test, expect, type Browser, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const FIX = path.join(__dirname, 'fixtures', 'battery_desk');
const SHOTS = path.join(__dirname, 'uat_autonomy_complex_ui', 'shots');
// kept beside the screenshots, the test-results folder is wiped on each run
const STATE_FILE = path.join(SHOTS, 'state.json');
const LLM_WAIT = 8 * 60_000;

interface State {
  run: string;
  model?: string;
  asset?: string;
  agent?: string;
  pipeline?: string;
  agentGrant?: string;
  pipeGrant?: string;
  mate?: { email: string; password: string; name: string; id?: string };
  approvedId?: string;
  editedId?: string;
  rejectedId?: string;
  blockedRun?: string;
  autoRun?: string;
}

const resumed: State | null = process.env.RESUME && fs.existsSync(STATE_FILE) ? JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')) : null;
const state: State = resumed || { run: Date.now().toString(36) };
const RUN = state.run;
const MODEL = `battery-price-${RUN}`;
const ASSET = `battery-dispatch-${RUN}`;
const LIMITS = `battery.dispatch.limits.${RUN}`;
const AGENT = `Battery dispatcher ${RUN}`;
const PIPELINE = `Battery dispatch flow ${RUN}`;
const TOPIC = `controls.battery.${RUN}`;
const ACTION_LABEL = `Publish a battery dispatch command ${RUN}`;
const MARKER = 'BATTERY_DISPATCH_V1';

function save() {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

async function signIn(page: Page, who: { email: string; password: string } = ADMIN) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

// read-only lookups for assertions, and cleanup
async function api(page: Page, method: string, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), data: json?.data ?? json, json };
}

async function grantOf(page: Page, id: string) {
  return (await api(page, 'GET', `/api/autonomy/grants/${id}`)).data;
}

async function actionsOf(page: Page, id: string, status = ''): Promise<any[]> {
  const q = status ? `?status=${status}&limit=100` : '?limit=100';
  return (await api(page, 'GET', `/api/autonomy/grants/${id}/actions${q}`)).data?.items || [];
}

async function openGrant(page: Page, id: string) {
  await go(page, `/autonomy/${id}`);
  await expect(page.getByTestId('autonomy-grant-page')).toBeVisible({ timeout: 30_000 });
}

async function saved(page: Page) {
  await expect(page.getByTestId('save-state')).toHaveText(/All changes saved/, { timeout: 15_000 });
}

async function addFactCondition(page: Page, prefix: string, idx: string, factPath: string, type: string) {
  await page.getByTestId(`${prefix}-g-add`).click();
  await page.getByTestId(`${prefix}-c${idx}-fact`).click();
  await page.getByLabel('Search facts').fill(factPath);
  const existing = page.getByRole('option', { name: new RegExp(`^${factPath.replace(/\./g, '\\.')}$`) });
  if (await existing.count()) await existing.first().click();
  else {
    await page.getByLabel('Type of the new fact').selectOption(type);
    await page.getByTestId('fact-add-new').click();
  }
}

async function addTool(page: Page, id: string) {
  const search = page.getByPlaceholder('Search tools, descriptions, params...');
  await search.fill(id);
  await page.getByTestId(`palette-tool-${id}`).first().click();
  await search.fill('');
  await expect(page.locator(`.react-flow__node[data-id="tool-${id}"]`)).toBeVisible();
}

async function publishFromBuilder(page: Page) {
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
}

// sends a chat message and returns once the reply is in
async function sendChat(page: Page, message: string) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  return before;
}

async function chatDone(page: Page, before: number, opts: { allowError?: boolean } = {}) {
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: LLM_WAIT });
  const err = page.getByTestId('chat-error');
  if (!opts.allowError && (await err.count())) throw new Error(`the run failed in chat: ${await err.innerText()}`);
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 }).catch(() => {});
  return (await replies.count()) > before ? replies.nth(before).innerText() : '';
}

async function chat(page: Page, message: string, opts: { allowError?: boolean } = {}) {
  const before = await sendChat(page, message);
  return chatDone(page, before, opts);
}

async function lastRunId(page: Page) {
  const viewRun = page.getByTestId('chat-view-run').last();
  await expect(viewRun).toBeVisible({ timeout: 30_000 });
  const href = await viewRun.getAttribute('href');
  if (href) return href.split('/executions/')[1].split(/[?#/]/)[0];
  await viewRun.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
  return page.url().split('/executions/')[1].split(/[?#/]/)[0];
}

async function expand(scope: ReturnType<Page['locator']>, title: string) {
  const btn = scope.getByRole('button', { name: new RegExp(`^${title}`) }).first();
  if ((await btn.getAttribute('aria-expanded')) !== 'true') await btn.click();
  return btn.locator('xpath=..');
}

function pipelineInputs(page: Page, v: { hour: number; demand: number; wind: number; soc: number; capacity: number; maxMw: number }) {
  return (async () => {
    // after the first run the inputs fold away behind a link
    const reopen = page.getByTestId('chat-params-open');
    if (await reopen.count()) await reopen.click();
    await page.getByTestId('chat-param-hour').fill(String(v.hour));
    await page.getByTestId('chat-param-demand_gw').fill(String(v.demand));
    await page.getByTestId('chat-param-wind_gw').fill(String(v.wind));
    await page.getByTestId('chat-param-soc_pct').fill(String(v.soc));
    await page.getByTestId('chat-param-capacity_mwh').fill(String(v.capacity));
    await page.getByTestId('chat-param-max_mw').fill(String(v.maxMw));
  })();
}

async function teammate(browser: Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.accept());
  await signIn(page, state.mate!);
  return { ctx, page };
}

// a promotion card in Approvals for this grant
function promotionCard(page: Page, agentName: string) {
  return page.locator('[data-testid="approval-card"][data-status="pending"]').filter({ has: page.getByTestId('approval-promotion') }).filter({ hasText: agentName });
}

const DISPATCH_PROMPT =
  'You run the dispatch desk for a grid battery. For each hour the user gives, in order:\n' +
  `1. ml_model with operation "predict", model_name "${MODEL}" and input_data {"features": [hour, demand_gw, wind_gw]}. Its "prediction" is the next-hour price in EUR/MWh.\n` +
  '2. code_asset with input {"price_forecast": <that prediction>, "soc_pct", "capacity_mwh", "max_mw"} from the user. Copy every number exactly.\n' +
  `3. mqtt_publish with topic "${TOPIC}", qos 1 and payload {"hour", "action", "mw", "soc_pct", "price_forecast", "expected_revenue_eur"} copied exactly from step 2. ` +
  'Pass _intent with the reason from step 2, and _prediction {"metric": "expected_revenue_eur", "value": expected_revenue_eur, "low": revenue_low_eur, "high": revenue_high_eur} from step 2.\n' +
  'Handle the hours one after another and publish a command for every hour. Never change the numbers the code returned.\n' +
  'Never say a command was sent unless mqtt_publish answered with "published": true. If it says the command was recorded in watching mode, rejected, blocked or not done, say that plainly for that hour and go on.\n' +
  'End with one line per hour: hour, action, MW, forecast price and what happened to the command.';

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test.afterEach(() => save());

test('ML Models: the price model is uploaded with its features and predicts', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  if (state.model) test.skip();
  await go(page, '/ml-models');
  await expect(page.getByTestId('ml-howto')).toBeVisible();
  await page.getByTestId('ml-file-input').setInputFiles(path.join(FIX, 'price_model.joblib'));
  await page.locator('#ml-name').fill(MODEL);
  await page.locator('#ml-desc').fill('Next-hour power price in EUR/MWh from hour, demand and wind');
  await page.getByText('Inputs and outputs (optional, recommended)').click();
  await page.locator('#ml-in-schema').fill(JSON.stringify({ features: ['hour', 'demand_gw', 'wind_gw'], example: [19, 55, 5] }));
  await page.locator('#ml-out-schema').fill(JSON.stringify({ type: 'regression', target: 'price_eur_mwh' }));
  await page.getByTestId('ml-upload-submit').click();
  await expect(page.getByTestId('ml-upload-error')).toHaveCount(0, { timeout: 60_000 });
  const detail = page.getByTestId('ml-detail');
  await expect(detail).toContainText(MODEL, { timeout: 60_000 });
  await expect(page.getByTestId('ml-status')).toHaveText('Ready', { timeout: 60_000 });
  await expect(detail).toContainText('3 features');

  await page.getByRole('button', { name: 'Reset to example' }).click();
  await expect(page.getByTestId('ml-predict-input')).toHaveValue(/19/);
  await page.getByTestId('ml-predict').click();
  const result = page.getByTestId('ml-predict-result');
  await expect(result).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('ml-predict-error')).toHaveCount(0);
  const price = Number((await result.innerText()).match(/(\d{2,3}\.\d+)/)?.[1]);
  expect(price, 'an evening peak with little wind is dear').toBeGreaterThan(100);
  await shot(page, '01-ml-model-predict');

  const m = ((await api(page, 'GET', '/api/ml-models')).data || []).find((x: any) => x.name === MODEL);
  expect(m?.status).toBe('ready');
  state.model = m.id;
});

test('Code Runner: the dispatch code is uploaded, analysed and test run', async ({ page }) => {
  test.setTimeout(8 * 60_000);
  if (!state.asset && process.env.RESUME) {
    const found = ((await api(page, 'GET', '/api/code-assets')).data || []).find((a: any) => a.name === ASSET && a.status === 'ready');
    if (found) state.asset = found.id;
  }
  if (state.asset) test.skip();
  await go(page, '/code-runner');
  await page.getByPlaceholder('Name (e.g. sentiment-scorer)').fill(ASSET);
  await page.getByPlaceholder('Description (optional)').fill('One hour of battery dispatch from a price forecast');
  await page.locator('input[type=file][accept=".zip"]').setInputFiles(path.join(FIX, 'battery_dispatch.zip'));
  await expect(page.getByTestId('code-source-zip')).toContainText('battery_dispatch.zip');
  await page.getByRole('button', { name: /Create & analyze/ }).click();

  const item = page.locator(`[data-testid="code-asset-item"][data-name="${ASSET}"]`);
  await expect(item).toBeVisible({ timeout: 60_000 });
  await expect(item).toHaveAttribute('data-status', /ready|failed/, { timeout: 300_000 });
  await item.click();
  await expect(page.getByTestId('code-asset-error')).toHaveCount(0);
  await expect(item).toHaveAttribute('data-status', 'ready');

  await page.getByTestId('code-test-input').fill(JSON.stringify({ price_forecast: 125.8, soc_pct: 60, capacity_mwh: 100, max_mw: 40 }));
  await page.getByTestId('code-test-run').click();
  const out = page.getByTestId('code-test-output');
  await expect(out).toContainText(MARKER, { timeout: 240_000 });
  await expect(out).toContainText('"action": "discharge"');
  await expect(out).toContainText(/"mw": 40[,.\s]/);
  await expect(out).toContainText(/"expected_revenue_eur": 5032[,.\s]/);
  await shot(page, '02-code-runner-test-run');

  await page.getByTestId('code-test-input').fill('{"soc_pct": 60}');
  await page.getByTestId('code-test-run').click();
  await expect(out).toContainText(/price_forecast is required|failed/i, { timeout: 240_000 });

  const asset = ((await api(page, 'GET', '/api/code-assets')).data || []).find((a: any) => a.name === ASSET);
  expect(asset?.status).toBe('ready');
  state.asset = asset.id;
});

test('Decisions: the hard limits are written as rules, tested and published', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  const existing = await api(page, 'GET', `/api/decisions/${LIMITS}`);
  if (existing.status === 200 && existing.data?.published?.length) test.skip();
  await go(page, '/decisions');
  await page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank')).first().click();
  await page.getByTestId('decision-name').fill(`Battery dispatch limits ${RUN}`);
  await page.getByTestId('decision-key').fill(LIMITS);
  await page.getByTestId('decision-create').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${LIMITS.replace(/\./g, '\\.')}`));

  await page.getByTestId('rule-add-first').click();
  await page.getByTestId('rule-key').fill('battery.mw.max');
  await page.getByTestId('rule-description').fill('Never more than 50 MW in or out of the battery');
  await addFactCondition(page, 'rule0', '0', 'payload.mw', 'number');
  await page.getByTestId('rule0-c0-op').selectOption('gt');
  await page.getByTestId('rule0-c0-value').fill('50');
  await page.getByTestId('rule0-new-outcome').fill('ok');
  await page.getByTestId('rule0-add-outcome').click();
  await page.getByTestId('rule0-then-ok-value').fill('false');
  await page.getByTestId('rule0-new-outcome').fill('reason');
  await page.getByTestId('rule0-add-outcome').click();
  await page.getByTestId('rule0-then-reason-value').fill('The command is over the 50 MW inverter limit');
  await saved(page);

  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('battery.soc.low');
  await page.getByTestId('rule-description').fill('State of charge below 10 percent');
  await addFactCondition(page, 'rule1', '0', 'payload.soc_pct', 'number');
  await page.getByTestId('rule1-c0-op').selectOption('lt');
  await page.getByTestId('rule1-c0-value').fill('10');
  await page.getByTestId('rule1-then-ok-set').click();
  await page.getByTestId('rule1-then-ok-value').selectOption('false');
  await page.getByTestId('rule1-then-reason-set').click();
  await page.getByTestId('rule1-then-reason-value').fill('State of charge is below the 10% floor');
  await saved(page);

  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('battery.soc.high');
  await page.getByTestId('rule-description').fill('State of charge above 90 percent');
  await addFactCondition(page, 'rule2', '0', 'payload.soc_pct', 'number');
  await page.getByTestId('rule2-c0-op').selectOption('gt');
  await page.getByTestId('rule2-c0-value').fill('90');
  await page.getByTestId('rule2-then-ok-set').click();
  await page.getByTestId('rule2-then-ok-value').selectOption('false');
  await page.getByTestId('rule2-then-reason-set').click();
  await page.getByTestId('rule2-then-reason-value').fill('State of charge is above the 90% ceiling');
  await saved(page);

  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('battery.inside');
  await page.getByTestId('rule-description').fill('Inside every limit');
  await page.getByTestId('rule3-then-ok-set').click();
  await page.getByTestId('rule3-then-ok-value').selectOption('true');
  await page.getByTestId('rule3-then-reason-set').click();
  await page.getByTestId('rule3-then-reason-value').fill('Inside the limits');
  await saved(page);

  const panel = page.getByTestId('try-panel');
  const tryCase = async (mw: string, soc: string, ok: boolean, rule: string, name: string) => {
    await panel.getByTestId('try-fact-payload.mw').fill(mw);
    await panel.getByTestId('try-fact-payload.soc_pct').fill(soc);
    await expect(panel.getByTestId('try-result-value')).toContainText(`"ok": ${ok}`, { timeout: 15_000 });
    await expect(panel.getByTestId('try-result')).toContainText(rule);
    await page.getByTestId('try-test-name').fill(name);
    await page.getByTestId('try-save-test').click();
    await expect(panel).toContainText('Saved as a golden test');
  };
  await tryCase('40', '60', true, 'battery.inside', 'A 40 MW discharge at 60% is fine');
  await tryCase('200', '70', false, 'battery.mw.max', '200 MW is over the inverter limit');
  await tryCase('20', '5', false, 'battery.soc.low', 'Charge below the floor is refused');
  await tryCase('20', '95', false, 'battery.soc.high', 'Above the ceiling is refused');
  await shot(page, '03-limits-rules');

  await page.getByTestId('tab-tests').click();
  await page.getByTestId('tests-run').click();
  await expect(page.getByTestId('tests-summary')).toContainText(/4 of 4 pass|All 4 pass|4 pass/);
  await page.getByTestId('tab-rules').click();
  await page.getByTestId('check').click();
  await expect(page.getByTestId('workspace-notice')).toContainText(/Ready\. 4 golden tests pass/);
  await page.getByTestId('propose').click();
  await expect(page.getByTestId('workspace-notice')).toContainText('Approved. You can publish it now.');
  await page.getByTestId('publish').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByTestId('workspace-notice')).toContainText('is now in force');
  const d = await api(page, 'GET', `/api/decisions/${LIMITS}`);
  expect(d.data.published.length).toBe(1);
});

test('Agent Builder: the dispatcher gets the model, the code and mqtt_publish', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  if (state.agent) test.skip();
  await go(page, '/ml-models');
  await page.getByTestId('ml-model-row').filter({ hasText: MODEL }).first().click();
  await page.getByTestId('ml-use-in-agent').click();
  await page.waitForURL(/\/builder\?.*tool=ml_model/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-ml_model"]')).toBeVisible({ timeout: 20_000 });

  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Forecasts the next-hour price, decides battery dispatch with the desk code and publishes the command.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(DISPATCH_PROMPT);
  await page.getByTestId('config-tab-model').click();
  const model = page.getByTestId('model-picker-select');
  await expect(model).toBeEnabled({ timeout: 20_000 });
  const values = await model.locator('option:not([disabled])').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  const best = [/sonnet-5/, /sonnet-4-6/, /sonnet-4-5/, /sonnet/].map((re) => values.find((v) => re.test(v))).find(Boolean);
  if (best) await model.selectOption(best);

  await addTool(page, 'code_asset');
  await addTool(page, 'mqtt_publish');
  await expect(page.locator('.react-flow__node[data-id="agent"]')).toContainText('3 tools');
  await page.locator('.react-flow__node[data-id="tool-code_asset"]').click();
  const pick = page.getByTestId('code-asset-select');
  await expect(pick).toBeVisible({ timeout: 20_000 });
  await expect(pick.locator('option', { hasText: ASSET })).toHaveCount(1, { timeout: 15_000 });
  await pick.selectOption(state.asset!);
  await shot(page, '04-agent-builder');

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  state.agent = new URL(page.url()).searchParams.get('agent') || '';
  expect(state.agent).toBeTruthy();
  await publishFromBuilder(page);
  const a = await api(page, 'GET', `/api/agents/${state.agent}`);
  expect(a.data.model_config.tools).toEqual(expect.arrayContaining(['ml_model', 'code_asset', 'mqtt_publish']));
});

test('Pipeline: forecast, dispatch from the forecast, publish a templated command', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  if (state.pipeline) test.skip();
  await go(page, '/builder');
  await page.getByTestId('builder-mode-pipeline').click();
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(PIPELINE);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('pipeline-description').fill('Price forecast from the ML model, dispatch from the desk code, the command published to the battery.');

  const inputs: [string, string][] = [
    ['hour', 'Hour of the day, 0 to 23'],
    ['demand_gw', 'Expected demand, GW'],
    ['wind_gw', 'Expected wind output, GW'],
    ['soc_pct', 'State of charge now, percent'],
    ['capacity_mwh', 'Battery capacity, MWh'],
    ['max_mw', 'Inverter limit, MW'],
  ];
  for (const [i, [name, desc]] of inputs.entries()) {
    await page.getByTestId('input-var-add').click();
    await page.getByTestId(`input-var-name-${i}`).fill(name);
    await page.getByTestId(`input-var-type-${i}`).selectOption('number');
    await page.getByTestId(`input-var-desc-${i}`).fill(desc);
    await page.getByTestId(`input-var-required-${i}`).check();
  }

  const addStep = async (id: string, label: string) => {
    const search = page.getByPlaceholder('Search by name, id, or description…');
    await search.fill(id);
    await page.getByTestId(`pipeline-palette-${id}`).first().click();
    await search.fill('');
    await page.getByTestId('step-label-input').fill(label);
  };
  const args = () => page.getByTestId('step-open-arguments').click();
  const general = () => page.getByRole('button', { name: 'General', exact: true }).click();
  const dependOn = async (...labels: string[]) => {
    for (const l of labels) await page.getByLabel(l, { exact: true }).check();
  };

  await addStep('ml_model', 'forecast');
  await args();
  await page.locator('#arg-ml_model-operation').selectOption('predict');
  await page.locator('#arg-ml_model-model_name').fill(MODEL);
  await page.locator('#arg-ml_model-input_data').fill(JSON.stringify({ features: ['{{input.hour}}', '{{input.demand_gw}}', '{{input.wind_gw}}'] }));
  await expect(page.getByTestId('arg-ml_model-input_data-error')).toHaveCount(0);
  await general();

  await addStep('code_asset', 'dispatch');
  await args();
  const assetPick = page.getByTestId('step-code-asset-select');
  await expect(assetPick.locator('option', { hasText: ASSET })).toHaveCount(1, { timeout: 15_000 });
  await assetPick.selectOption(state.asset!);
  await expect(page.getByTestId('step-code-asset-fields')).toContainText('price_forecast*');
  await page.locator('#arg-code_asset-input').fill(JSON.stringify({
    price_forecast: '{{forecast.prediction}}',
    soc_pct: '{{input.soc_pct}}',
    capacity_mwh: '{{input.capacity_mwh}}',
    max_mw: '{{input.max_mw}}',
  }, null, 2));
  await expect(page.getByTestId('arg-code_asset-input-error')).toHaveCount(0);
  await general();
  await dependOn('forecast');

  await addStep('mqtt_publish', 'publish');
  await args();
  await page.locator('#arg-mqtt_publish-topic').fill(TOPIC);
  await page.locator('#arg-mqtt_publish-payload').fill(JSON.stringify({
    source: 'pipeline',
    hour: '{{input.hour}}',
    action: '{{dispatch.result.action}}',
    mw: '{{dispatch.result.mw}}',
    soc_pct: '{{dispatch.result.soc_pct}}',
    price_forecast: '{{dispatch.result.price_forecast}}',
    expected_revenue_eur: '{{dispatch.result.expected_revenue_eur}}',
  }, null, 2));
  await expect(page.getByTestId('arg-mqtt_publish-payload-hint')).toContainText('JSON object');
  await shot(page, '05-pipeline-publish-step');
  await general();
  await dependOn('dispatch');

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  state.pipeline = new URL(page.url()).searchParams.get('agent') || '';
  expect(state.pipeline).toBeTruthy();
  await expect(page.getByTestId('validation-chip-error')).toHaveCount(0, { timeout: 20_000 });

  const stored = await api(page, 'GET', `/api/agents/${state.pipeline}`);
  const nodes = stored.data.model_config.pipeline_config.nodes as any[];
  const byTool = (t: string) => nodes.find((n) => (n.tool_name || n.tool) === t);
  expect(byTool('code_asset').arguments.code_asset_id).toBe(state.asset);
  expect(byTool('mqtt_publish').arguments.payload.mw).toBe('{{dispatch.result.mw}}');
  expect(stored.data.model_config.tools).toEqual(expect.arrayContaining(['ml_model', 'code_asset', 'mqtt_publish']));
  await publishFromBuilder(page);
});

test('Enrol: the agent from its Actions panel and the pipeline from Autonomy, with the limits', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  if (!state.agentGrant) {
    await go(page, `/agents/${state.agent}/info`);
    const panel = page.getByTestId('autonomy-agent-actions');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    const row = panel.getByTestId('autonomy-agent-action-mqtt_publish');
    await expect(row).toContainText('Not enrolled');
    await row.getByTestId('autonomy-agent-enrol').click();

    const wiz = page.getByTestId('autonomy-enrol-wizard');
    await expect(wiz).toBeVisible();
    // the tool was picked from the panel, so the wizard starts at the settings
    await page.getByTestId('autonomy-enrol-label').fill(ACTION_LABEL);
    await expect(page.getByTestId('autonomy-enrol-match-param')).toHaveValue('topic');
    await page.getByTestId('autonomy-enrol-match-glob').fill(TOPIC);
    await expect(wiz).toContainText(`Calls where topic is ${TOPIC}`);
    await wiz.getByText('A person enters it').click();
    await page.locator('#en-after').fill('60');
    await page.locator('#en-pmetric').fill('expected_revenue_eur');
    await shot(page, '06-enrol-which-calls');
    await page.getByTestId('autonomy-enrol-next').click();
    await page.locator('#en-wmmetric').fill('expected_revenue_eur');
    await page.locator('#en-band').fill('50');
    await page.getByTestId('autonomy-enrol-next').click();
    await page.getByTestId('autonomy-enrol-limits').selectOption(LIMITS);
    await page.getByTestId('autonomy-enrol-start').click();
    await page.waitForURL(/\/autonomy\/[0-9a-f-]{36}/, { timeout: 30_000 });
    state.agentGrant = page.url().split('/autonomy/')[1].split(/[?#]/)[0];
    save();
  }
  await openGrant(page, state.agentGrant!);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Watching');
  await expect(page.getByTestId('autonomy-setting-limits')).toContainText(LIMITS);
  await expect(page.getByTestId('autonomy-limits-problem')).toHaveCount(0);

  // the desk sets how much evidence it wants before each step up
  await page.getByTestId('autonomy-thresholds-edit').click();
  const thr = async (k: string, v: string) => page.getByTestId(`autonomy-threshold-${k}`).fill(v);
  await thr('to_asks_first.min_reviews', '0');
  await page.getByTestId('autonomy-thresholds-save').click();
  await expect(page.getByTestId('autonomy-thresholds')).toContainText('A whole number from 1');
  await thr('to_asks_first.min_reviews', '5');
  await thr('to_asks_first.min_agreement_lb', '50');
  await thr('to_within_limits.min_executed', '2');
  await thr('to_within_limits.min_accuracy_lb', '30');
  await thr('to_within_limits.min_no_edit_rate', '50');
  await thr('to_within_limits.max_reject_rate', '50');
  await thr('to_within_limits.harm_free_days', '0');
  await thr('to_within_limits.min_days_at_level', '0');
  await page.getByTestId('autonomy-thresholds-save').click();
  await expect(page.getByTestId('autonomy-thresholds-summary')).toContainText('5');
  await expect(page.getByTestId('autonomy-history')).toContainText('Thresholds changed');
  await expect(page.getByTestId('autonomy-next-step')).toContainText('of 5 reviews');
  await shot(page, '07-agent-grant-thresholds');

  if (!state.pipeGrant) {
    await go(page, '/autonomy');
    await page.getByTestId('autonomy-enrol-open').click();
    const wiz = page.getByTestId('autonomy-enrol-wizard');
    await page.getByTestId('autonomy-enrol-agent-search').fill(PIPELINE);
    await wiz.getByTestId('autonomy-enrol-agent').filter({ hasText: PIPELINE }).click();
    const tool = wiz.getByTestId('autonomy-enrol-tool-mqtt_publish');
    await expect(tool).toBeVisible({ timeout: 30_000 });
    // the same desk command, so the pipeline joins the action the agent already has
    const existing = tool.locator(`[data-testid="autonomy-enrol-existing"][data-key="mqtt_publish:${TOPIC}"]`);
    await expect(existing).toContainText(ACTION_LABEL);
    await existing.getByTestId('autonomy-enrol-use-existing').click();
    await expect(page.getByTestId('autonomy-enrol-reuse-note')).toBeVisible();
    await page.getByTestId('autonomy-enrol-next').click();
    await page.getByTestId('autonomy-enrol-next').click();
    await expect(page.getByTestId('autonomy-enrol-limits')).toHaveValue(LIMITS);
    await page.getByTestId('autonomy-enrol-start').click();
    await page.waitForURL(/\/autonomy\/[0-9a-f-]{36}/, { timeout: 30_000 });
    state.pipeGrant = page.url().split('/autonomy/')[1].split(/[?#]/)[0];
    save();
  }
  await openGrant(page, state.pipeGrant!);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Watching');
  await expect(page.getByTestId('autonomy-next-step')).toContainText('of 5 reviews');
  const g1 = await grantOf(page, state.agentGrant!);
  const g2 = await grantOf(page, state.pipeGrant!);
  expect(g1.action_type.key).toBe(`mqtt_publish:${TOPIC}`);
  expect(g2.action_type.id).toBe(g1.action_type.id);
});

test('Watching: the agent and the pipeline record commands and publish nothing', async ({ page }) => {
  test.setTimeout(30 * 60_000);
  const agentBefore = (await actionsOf(page, state.agentGrant!, 'watching')).length;
  await go(page, `/agents/${state.agent}/chat`);
  const hours =
    'Battery: 100 MWh, 40 MW inverter, state of charge 60% for every hour. ' +
    'Hours: 19 with demand 55 GW and wind 5 GW; 3 with demand 32 GW and wind 25 GW; 20 with demand 52 GW and wind 6 GW.';
  for (let i = 0; i < 3 && (await actionsOf(page, state.agentGrant!, 'watching')).length - agentBefore < 5; i++) {
    const answer = await chat(page, `Dispatch the battery. ${hours}`);
    console.log(`\n--- watching answer ---\n${answer}\n---`);
    expect(answer.toLowerCase()).toMatch(/watching|not (been )?(sent|executed|published)|recorded/);
  }
  const agentWatching = await actionsOf(page, state.agentGrant!, 'watching');
  expect(agentWatching.length - agentBefore).toBeGreaterThanOrEqual(5);
  const w = agentWatching[0];
  expect(w.intent).toBeTruthy();
  expect(w.prediction?.metric).toBe('expected_revenue_eur');
  expect(w.arguments.topic).toBe(TOPIC);
  expect((await actionsOf(page, state.agentGrant!)).filter((a) => a.status === 'executed')).toHaveLength(0);
  await shot(page, '08-agent-watching-chat');

  const runId = await lastRunId(page);
  await go(page, `/executions/${runId}`);
  await expect(page.getByTestId('autonomy-step-badge').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-step-badge').first()).toContainText(/Watching/);

  // the pipeline, five runs from its run page
  const pipeBefore = (await actionsOf(page, state.pipeGrant!, 'watching')).length;
  await go(page, `/agents/${state.pipeline}/chat`);
  const rows = [
    { hour: 19, demand: 55, wind: 5 }, { hour: 3, demand: 32, wind: 25 }, { hour: 20, demand: 52, wind: 6 },
    { hour: 18, demand: 50, wind: 4 }, { hour: 2, demand: 30, wind: 22 },
  ];
  for (const r of rows) {
    if ((await actionsOf(page, state.pipeGrant!, 'watching')).length - pipeBefore >= 5) break;
    await pipelineInputs(page, { ...r, soc: 60, capacity: 100, maxMw: 40 });
    await chat(page, `Dispatch hour ${r.hour}.`);
  }
  expect((await actionsOf(page, state.pipeGrant!, 'watching')).length - pipeBefore).toBeGreaterThanOrEqual(5);

  const pipeRun = await lastRunId(page);
  await go(page, `/executions/${pipeRun}`);
  const step = page.locator('[data-testid="execution-step"][data-step="publish"]').first();
  await expect(step).toBeVisible({ timeout: 30_000 });
  const outText = await (await expand(step, 'Output')).innerText();
  expect(outText).toMatch(/"status":\s*"watching"/);
  expect(outText).toContain(TOPIC);
  await expect(step.getByTestId('autonomy-step-badge')).toContainText(/Watching/);
  // the dispatch step was wired from the forecast
  const dispatchIn = await (await expand(page.locator('[data-testid="execution-step"][data-step="dispatch"]').first(), 'Input')).innerText();
  expect(dispatchIn).toMatch(/"price_forecast":\s*\d/);
  await shot(page, '09-pipeline-watching-run');
  expect((await actionsOf(page, state.pipeGrant!)).filter((a) => a.status === 'executed')).toHaveLength(0);
});

test('Limits: a 200 MW command from the pipeline is blocked even while watching', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, `/agents/${state.pipeline}/chat`);
  await pipelineInputs(page, { hour: 19, demand: 55, wind: 5, soc: 70, capacity: 400, maxMw: 200 });
  await chat(page, 'Dispatch hour 19 on the big site.', { allowError: true });
  const blocked = (await actionsOf(page, state.pipeGrant!, 'blocked'))[0];
  expect(blocked, 'the over-limit command is on the ledger as blocked').toBeTruthy();
  expect(blocked.card.limits.ok).toBe(false);
  expect(blocked.card.limits.reasons.join(' ')).toContain('50 MW');
  state.blockedRun = blocked.execution_id;

  await openGrant(page, state.pipeGrant!);
  await page.getByTestId('autonomy-filter-blocked').click().catch(() => {});
  const card = page.locator(`[data-testid="action-card"][data-action-id="${blocked.id}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId('action-card-limits-breach')).toContainText('over the 50 MW inverter limit');
  await shot(page, '10-limits-blocked-card');

  await go(page, `/executions/${blocked.execution_id}`);
  await expect(page.locator('body')).toContainText('over the 50 MW inverter limit', { timeout: 30_000 });
  await shot(page, '11-limits-blocked-run');
});

test('Reviews: the desk answers them under Approvals, Watching reviews', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, '/approvals?tab=watching');
  await expect(page.getByTestId('autonomy-reviews')).toBeVisible({ timeout: 30_000 });
  await shot(page, '12-watching-reviews');
  const need = async () => {
    const a = await grantOf(page, state.agentGrant!);
    const p = await grantOf(page, state.pipeGrant!);
    return Number(a.stats?.reviews ?? 0) < 5 || Number(p.stats?.reviews ?? 0) < 5;
  };
  for (let i = 0; i < 80 && (await need()); i++) {
    if (await page.getByTestId('autonomy-reviews-empty').count()) break;
    const agree = page.getByTestId('autonomy-review-agree').first();
    await expect(agree).toBeVisible({ timeout: 20_000 });
    await page.keyboard.press('a');
    await page.waitForTimeout(700);
  }
  for (const id of [state.agentGrant!, state.pipeGrant!]) {
    const g = await grantOf(page, id);
    expect(Number(g.stats?.reviews ?? 0)).toBeGreaterThanOrEqual(5);
    expect(g.next?.ready, `${g.agent.name} is ready for Asks first`).toBe(true);
  }
});

test('Promote: the author is refused, a teammate invited from Settings approves in Approvals', async ({ page, browser }) => {
  test.setTimeout(10 * 60_000);
  // the builder of the agent cannot promote it
  await openGrant(page, state.agentGrant!);
  await expect(page.getByTestId('autonomy-promote')).toBeEnabled({ timeout: 30_000 });
  await page.getByTestId('autonomy-promote').click();
  const msg = page.getByTestId('autonomy-promote-message');
  await expect(msg).toContainText('You built this agent, so someone else has to approve its promotion.');
  await expect(msg).not.toContainText('AUTHOR_CANNOT_GRANT');
  await shot(page, '13-author-cannot-promote');

  if (!state.mate) {
    // the message links to the team page, where the desk lead is invited
    await msg.getByRole('link', { name: /invite a teammate/ }).click();
    await page.waitForURL(/\/settings\/team/, { timeout: 20_000 });
    const mate = { email: `desk-lead-${RUN}@example.com`, password: `DeskLead-${RUN}-9`, name: `Desk Lead ${RUN}` };
    await page.getByRole('button', { name: 'Invite Member' }).click();
    await page.getByPlaceholder('email@example.com').fill(mate.email);
    await page.locator('select').filter({ has: page.locator('option[value="admin"]') }).first().selectOption('admin');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    const link = page.getByTestId('invite-link');
    await expect(link).toBeVisible({ timeout: 20_000 });
    const url = (await link.innerText()).trim();
    await shot(page, '14-team-invite');

    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const p2 = await ctx.newPage();
    await p2.goto(url, { waitUntil: 'domcontentloaded' });
    await expect(p2.getByTestId('accept-title')).toBeVisible({ timeout: 30_000 });
    await p2.locator('#accept-full-name').fill(mate.name);
    await p2.locator('#accept-password').fill(mate.password);
    await p2.getByTestId('accept-submit').click();
    await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
    await ctx.close();
    state.mate = mate;
    const members = (await api(page, 'GET', '/api/team/members')).data?.members || [];
    state.mate.id = members.find((m: any) => m.email === mate.email)?.id;
    save();
  }

  const { ctx, page: lead } = await teammate(browser);
  try {
    // the lead asks for both promotions from the grant pages
    for (const id of [state.agentGrant!, state.pipeGrant!]) {
      await openGrant(lead, id);
      await expect(lead.getByTestId('autonomy-promote')).toBeEnabled({ timeout: 30_000 });
      await lead.getByTestId('autonomy-promote').click();
      await expect(lead.getByTestId('autonomy-promote-message')).toContainText('Sent for approval', { timeout: 20_000 });
    }
    await shot(lead, '15-lead-sent-for-approval');

    // the author still cannot sign it in Approvals, and is told why in plain words
    await go(page, '/approvals');
    const mine = promotionCard(page, AGENT);
    await expect(mine).toBeVisible({ timeout: 30_000 });
    await expect(mine.getByTestId('approval-promotion')).toContainText('Watching to Asks first');
    await mine.getByTestId('approval-approve').click();
    await expect(mine.getByTestId('approval-error')).toContainText('You built this agent, so someone else has to approve its promotion.');
    await expect(mine.getByTestId('approval-error')).not.toContainText('AUTHOR_CANNOT_GRANT');
    await shot(page, '16-author-refused-in-approvals');
    expect((await grantOf(page, state.agentGrant!)).level).toBe(1);

    await go(lead, '/approvals');
    for (const name of [AGENT, PIPELINE]) {
      const card = promotionCard(lead, name);
      await expect(card).toBeVisible({ timeout: 30_000 });
      await card.getByTestId('approval-approve').click();
      await expect(card).toHaveCount(0, { timeout: 30_000 });
    }
  } finally {
    await ctx.close();
  }
  for (const id of [state.agentGrant!, state.pipeGrant!]) {
    await expect.poll(async () => (await grantOf(page, id)).level, { timeout: 30_000 }).toBe(2);
  }
  await openGrant(page, state.agentGrant!);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Asks first');
  await expect(page.getByTestId('autonomy-history')).toContainText(`Promotion approved by ${state.mate!.name}`);
  await shot(page, '17-asks-first');
});

test('Asks first: approve, edit and reject, the approved command really published', async ({ page }) => {
  test.setTimeout(30 * 60_000);
  const before = new Set((await actionsOf(page, state.agentGrant!)).map((a) => a.id));
  await go(page, `/agents/${state.agent}/chat`);
  const sent = await sendChat(
    page,
    'Dispatch the battery. Battery: 100 MWh, 40 MW inverter, state of charge 60% for every hour. ' +
      'Hours: 19 with demand 55 GW and wind 5 GW; 3 with demand 32 GW and wind 25 GW; 20 with demand 52 GW and wind 6 GW.',
  );
  const desk = await page.context().newPage();
  const fresh = async () => (await actionsOf(desk, state.agentGrant!, 'pending')).filter((a) => !before.has(a.id));
  await go(desk, '/dashboard');

  // the first one is approved from Approvals, where it shows as an action card
  await expect.poll(async () => (await fresh()).length, { timeout: LLM_WAIT, intervals: [5_000] }).toBeGreaterThan(0);
  const first = (await fresh())[0];
  await go(desk, '/approvals');
  const row = desk.locator(`[data-testid="approval-action-row"]`).filter({ has: desk.locator(`[data-action-id="${first.id}"]`) });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row.getByTestId('action-card-prediction')).toContainText(/\d/);
  await expect(row.getByTestId('action-card-limits-ok')).toBeVisible();
  await shot(desk, '18-action-card-in-approvals');
  // it is on the grant timeline too
  await openGrant(desk, state.agentGrant!);
  await expect(desk.locator(`[data-testid="action-card"][data-action-id="${first.id}"]`)).toHaveAttribute('data-status', 'pending');
  await go(desk, '/approvals');
  await row.getByTestId('action-card-approve').click();
  state.approvedId = first.id;
  save();

  // the second is edited on the timeline: less power than the agent asked for
  await expect.poll(async () => (await fresh()).filter((a) => a.id !== first.id).length, { timeout: LLM_WAIT, intervals: [5_000] }).toBeGreaterThan(0);
  const second = (await fresh()).find((a) => a.id !== first.id)!;
  await openGrant(desk, state.agentGrant!);
  const card2 = desk.locator(`[data-testid="action-card"][data-action-id="${second.id}"]`);
  await expect(card2).toHaveAttribute('data-status', 'pending', { timeout: 30_000 });
  await card2.getByTestId('action-card-edit').click();
  const payload = card2.getByTestId('action-card-arg-payload');
  const p = JSON.parse(await payload.inputValue());
  const editedMw = Math.max(5, Math.round(Number(p.mw) / 2));
  p.mw = editedMw;
  await payload.fill(JSON.stringify(p, null, 2));
  await shot(desk, '19-edit-before-approve');
  await card2.getByTestId('action-card-edit-submit').click();
  await expect(card2).not.toHaveAttribute('data-status', 'pending', { timeout: 60_000 });
  state.editedId = second.id;
  save();

  // the third is rejected with a reason
  await expect.poll(async () => (await fresh()).filter((a) => ![first.id, second.id].includes(a.id)).length, { timeout: LLM_WAIT, intervals: [5_000] }).toBeGreaterThan(0);
  const third = (await fresh()).find((a) => ![first.id, second.id].includes(a.id))!;
  await openGrant(desk, state.agentGrant!);
  const card3 = desk.locator(`[data-testid="action-card"][data-action-id="${third.id}"]`);
  await expect(card3).toHaveAttribute('data-status', 'pending', { timeout: 30_000 });
  await card3.getByTestId('action-card-reject').click();
  await card3.getByTestId('action-card-reject-note').fill('Keep the energy for the morning peak');
  await card3.getByTestId('action-card-reject-submit').click();
  await expect(card3).toHaveAttribute('data-status', 'rejected', { timeout: 60_000 });
  state.rejectedId = third.id;
  save();

  const answer = await chatDone(page, sent);
  console.log(`\n--- asks first answer ---\n${answer}\n---`);
  await shot(page, '20-asks-first-chat');

  const rows = await actionsOf(page, state.agentGrant!);
  const byId = Object.fromEntries(rows.map((a) => [a.id, a]));
  expect(byId[first.id].status).toBe('executed');
  expect(byId[first.id].result_preview).toMatch(/"published":\s*true/);
  expect(byId[second.id].status).toBe('executed');
  expect(byId[second.id].arguments.payload.mw).toBe(editedMw);
  expect(byId[second.id].result_preview).toMatch(/"published":\s*true/);
  expect(byId[third.id].status).toBe('rejected');

  await openGrant(page, state.agentGrant!);
  const done = page.locator(`[data-testid="action-card"][data-action-id="${first.id}"]`);
  await expect(done).toHaveAttribute('data-status', 'executed');
  await expect(done.getByTestId('action-card-result')).toContainText('"published": true');
  await expect(done.getByTestId('action-card-result')).toContainText(TOPIC);
  await done.getByTestId('action-card-result').scrollIntoViewIfNeeded();
  await shot(page, '21-executed-with-result');
  await desk.close();
});

test('Asks first on the pipeline: the run waits, is approved and publishes', async ({ page }) => {
  test.setTimeout(15 * 60_000);
  const before = new Set((await actionsOf(page, state.pipeGrant!)).map((a) => a.id));
  await go(page, `/agents/${state.pipeline}/chat`);
  await pipelineInputs(page, { hour: 19, demand: 55, wind: 5, soc: 60, capacity: 100, maxMw: 40 });
  const sent = await sendChat(page, 'Dispatch hour 19.');
  const desk = await page.context().newPage();
  await go(desk, '/dashboard');
  await expect.poll(async () => (await actionsOf(desk, state.pipeGrant!, 'pending')).filter((a) => !before.has(a.id)).length, { timeout: 5 * 60_000, intervals: [5_000] }).toBeGreaterThan(0);
  const pending = (await actionsOf(desk, state.pipeGrant!, 'pending')).find((a) => !before.has(a.id))!;
  await go(desk, '/approvals');
  const row = desk.locator('[data-testid="approval-action-row"]').filter({ has: desk.locator(`[data-action-id="${pending.id}"]`) });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row).toContainText(PIPELINE);
  await row.getByTestId('action-card-approve').click();
  await chatDone(page, sent);
  await desk.close();
  await expect.poll(async () => (await actionsOf(page, state.pipeGrant!)).find((a) => a.id === pending.id)?.status, { timeout: 60_000 }).toBe('executed');
  const done = (await actionsOf(page, state.pipeGrant!)).find((a) => a.id === pending.id);
  expect(done.result_preview).toMatch(/"published":\s*true/);
  await openGrant(page, state.pipeGrant!);
  await expect(page.locator(`[data-testid="action-card"][data-action-id="${pending.id}"]`).getByTestId('action-card-result')).toContainText('"published": true');
  await shot(page, '22-pipeline-executed');
});

test('Limits: the agent asking for 200 MW is blocked at Asks first, before anyone is asked', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  const before = new Set((await actionsOf(page, state.agentGrant!)).map((a) => a.id));
  await go(page, `/agents/${state.agent}/chat`);
  const answer = await chat(page, 'Dispatch the big site. Battery: 400 MWh, 200 MW inverter, state of charge 70%. Hour 19 with demand 55 GW and wind 5 GW.');
  console.log(`\n--- limits answer ---\n${answer}\n---`);
  const blocked = (await actionsOf(page, state.agentGrant!, 'blocked')).find((a) => !before.has(a.id));
  expect(blocked, 'the 200 MW command was blocked').toBeTruthy();
  expect(blocked.arguments.payload.mw).toBeGreaterThan(50);
  expect(blocked.approval_id).toBeFalsy();
  expect((await actionsOf(page, state.agentGrant!, 'pending')).filter((a) => !before.has(a.id))).toHaveLength(0);

  await openGrant(page, state.agentGrant!);
  const card = page.locator(`[data-testid="action-card"][data-action-id="${blocked.id}"]`);
  await expect(card.getByTestId('action-card-limits-breach')).toContainText('over the 50 MW inverter limit');
  await go(page, `/executions/${blocked.execution_id}`);
  const call = page.locator('[data-testid="tool-call"][data-tool="mqtt_publish"]').first();
  await expect(call).toBeVisible({ timeout: 30_000 });
  await expect(await expand(call, 'Result')).toContainText('over the 50 MW inverter limit');
  await shot(page, '23-agent-limits-in-run');
});

test('Outcomes: entered on the executed cards, the record and the chart move', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await openGrant(page, state.agentGrant!);
  for (const id of [state.approvedId!, state.editedId!]) {
    const a = (await actionsOf(page, state.agentGrant!)).find((x) => x.id === id);
    if (a.outcome_status === 'manual' || a.outcome_status === 'observed') continue;
    // the actual revenue landed inside the band the agent stated
    const actual = Math.round((Number(a.prediction.low) + Number(a.prediction.high)) / 2);
    const card = page.locator(`[data-testid="action-card"][data-action-id="${id}"]`);
    await card.getByTestId('action-card-enter-outcome').click();
    await card.getByTestId('action-card-outcome-value').fill(String(actual));
    await card.getByTestId('action-card-outcome-submit').click();
    await expect(card.getByTestId('action-card-outcome')).toContainText('Inside the predicted band', { timeout: 30_000 });
  }
  await openGrant(page, state.agentGrant!);
  await expect(page.locator('[data-testid="autonomy-chart-dot"]').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-grant-page')).toContainText('Held 2 of 2 scored actions');
  const g = await grantOf(page, state.agentGrant!);
  expect(g.stats.scored).toBe(2);
  expect(g.next.ready, (g.next.requirements || []).filter((r: any) => !r.met).map((r: any) => r.label).join(' | ')).toBe(true);
  await shot(page, '24-outcomes-and-chart');
});

test('Harm: at Acts within limits it acts alone, a harm flag drops it to Asks first', async ({ page, browser }) => {
  test.setTimeout(20 * 60_000);
  if ((await grantOf(page, state.agentGrant!)).level < 3) {
    const { ctx, page: lead } = await teammate(browser);
    try {
      await openGrant(lead, state.agentGrant!);
      await lead.getByTestId('autonomy-promote').click();
      await expect(lead.getByTestId('autonomy-promote-message')).toContainText('Sent for approval', { timeout: 20_000 });
      await go(lead, '/approvals');
      const card = promotionCard(lead, AGENT);
      await expect(card.getByTestId('approval-promotion')).toContainText('Asks first to Acts within limits');
      await card.getByTestId('approval-approve').click();
      await expect(card).toHaveCount(0, { timeout: 30_000 });
    } finally {
      await ctx.close();
    }
  }
  await expect.poll(async () => (await grantOf(page, state.agentGrant!)).level, { timeout: 30_000 }).toBe(3);

  const before = new Set((await actionsOf(page, state.agentGrant!)).map((a) => a.id));
  await go(page, `/agents/${state.agent}/chat`);
  const answer = await chat(page, 'Dispatch the battery. Battery: 100 MWh, 40 MW inverter, state of charge 60%. Hour 19 with demand 55 GW and wind 5 GW.');
  console.log(`\n--- acts within limits answer ---\n${answer}\n---`);
  const auto = (await actionsOf(page, state.agentGrant!)).find((a) => !before.has(a.id) && a.mode === 'auto');
  expect(auto, 'inside the limits with a confident prediction it acted without asking').toBeTruthy();
  expect(auto.status).toBe('executed');
  expect(auto.result_preview).toMatch(/"published":\s*true/);
  state.autoRun = auto.execution_id;

  await openGrant(page, state.agentGrant!);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Acts within limits');
  const card = page.locator(`[data-testid="action-card"][data-action-id="${auto.id}"]`);
  await expect(card).toHaveAttribute('data-status', 'executed', { timeout: 30_000 });
  await shot(page, '25-acted-alone');
  await card.getByTestId('action-card-flag-harm').click();
  await page.getByTestId('action-card-harm-note').fill('Discharged into a negative imbalance price, the desk lost money');
  await page.getByTestId('action-card-harm-confirm').click();
  await expect.poll(async () => (await grantOf(page, state.agentGrant!)).level, { timeout: 30_000 }).toBe(2);
  await openGrant(page, state.agentGrant!);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Asks first');
  await expect(page.getByTestId('autonomy-history')).toContainText(/Harm flagged/);
  await go(page, '/autonomy');
  await expect(page.getByTestId('autonomy-demoted')).toContainText(AGENT, { timeout: 30_000 });
  await shot(page, '26-demoted-after-harm');
});

test('Flight recorder: the run that acted alone carries its autonomy badge', async ({ page }) => {
  await go(page, `/executions/${state.autoRun}`);
  const badge = page.getByTestId('autonomy-step-badge').first();
  await expect(badge).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('execution-autonomy-actions')).toContainText('mqtt_publish');
  await shot(page, '27-flight-recorder');
});

test.afterAll(async ({ browser }) => {
  save();
  if (process.env.KEEP) return;
  const page = await browser.newPage();
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const tok = (await res.json())?.data?.access_token;
  const call = (method: string, p: string) =>
    page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } }).catch(() => null);
  for (const g of [state.agentGrant, state.pipeGrant]) if (g) await call('DELETE', `/api/autonomy/grants/${g}`);
  for (const id of [state.agent, state.pipeline]) if (id) await call('DELETE', `/api/agents/${id}`);
  if (state.asset) await call('DELETE', `/api/code-assets/${state.asset}`);
  if (state.model) await call('DELETE', `/api/ml-models/${state.model}`);
  await call('DELETE', `/api/decisions/${LIMITS}`);
  if (state.mate?.id) await call('DELETE', `/api/team/members/${state.mate.id}`);
  await page.close();
  if (fs.existsSync(STATE_FILE)) fs.unlinkSync(STATE_FILE);
});
