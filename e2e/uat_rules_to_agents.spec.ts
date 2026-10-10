/**
 * From a business rule to agents, pipelines and the SDK, through the screens only.
 *
 *   1. sign in on the landing page form
 *   2. Reference sets   create the remote postcode list
 *   3. Decisions        build the surcharge rule and a catch-all in the no-code builder
 *   4. Try, golden tests, Check, propose and publish
 *   5. Agent Builder    an agent with the decision_evaluate tool, saved and published
 *   6. Chat             a shipment that pays the surcharge and one that does not, read on the Flight Recorder
 *   7. Pipeline         typed inputs, a decision step and an explain step, run from chat
 *   8. SDK playground   run the agent and the pipeline live, the generated code carries the inputs
 *   9. Reference sets   a set in use cannot be deleted
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_rules_to_agents.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const SET = `REMOTE_POSTCODES_${RUN.toUpperCase()}`;
const KEY = `uat.r2a.${RUN}`;
const AGENT = `Surcharge Desk ${RUN}`;
const PIPELINE = `Surcharge Pipeline ${RUN}`;
const SURCHARGE = 'REMOTE_AREA_SURCHARGE';

const ids: { agent?: string; pipeline?: string; agentRun?: string; pipelineRun?: string } = {};
const CITATION = 'Carrier tariff 2026, section 4.2';
const VERSION_1_URL = new RegExp(`/decisions/${KEY.replace(/\./g, '\\.')}\\?version=1`);

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
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

async function token(page: Page) {
  return page.evaluate(() => localStorage.getItem('access_token') || '');
}

// read-only lookups for assertions, and cleanup
async function api(page: Page, method: string, p: string) {
  const tok = await token(page);
  const opts = { method, headers: { Authorization: `Bearer ${tok}` } };
  const res = await page.request.fetch(`${API}${p}`, opts).catch(() => page.request.fetch(`${API}${p}`, opts));
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function saved(page: Page) {
  await expect(page.getByTestId('save-state')).toHaveText(/All changes saved/, { timeout: 15_000 });
}

async function addFactCondition(page: Page, prefix: string, idx: string, path: string, type: string) {
  await page.getByTestId(`${prefix}-g-add`).click();
  await page.getByTestId(`${prefix}-c${idx}-fact`).click();
  await page.getByLabel('Search facts').fill(path);
  const existing = page.getByRole('option', { name: new RegExp(`^${path.replace(/\./g, '\\.')}$`) });
  if (await existing.count()) await existing.first().click();
  else {
    await page.getByLabel('Type of the new fact').selectOption(type);
    await page.getByTestId('fact-add-new').click();
  }
}

async function chat(page: Page, message: string, timeoutMs = 240_000) {
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

// open the run behind the latest answer and return the Flight Recorder page text for one tool call
async function openLastRun(page: Page) {
  const viewRun = page.getByTestId('chat-view-run').last();
  await expect(viewRun).toBeVisible({ timeout: 20_000 });
  await viewRun.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
}

function runId(page: Page) {
  return new URL(page.url()).pathname.split('/executions/')[1]?.split(/[/?#]/)[0] || '';
}

// the decision card on a run: outcome, the rule with its source, version link, trace hash and evaluation id
async function checkDecisionCard(scope: ReturnType<Page['locator']>, ruleKey: string) {
  const card = scope.getByTestId('decision-card').first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId('decision-outcome')).toHaveText('Decided');
  await expect(card.getByTestId('decision-outputs')).toContainText(SURCHARGE);
  const rule = card.locator(`[data-testid="decision-rule"][data-rule="${ruleKey}"]`);
  await expect(rule).toBeVisible();
  await expect(rule.getByTestId('decision-citation')).toContainText(CITATION);
  const version = card.getByTestId('decision-version-link');
  await expect(version).toHaveText(/Version 1/);
  await expect(version).toHaveAttribute('href', `/decisions/${encodeURIComponent(KEY)}?version=1`);
  await expect(card.getByTestId('decision-trace-hash')).toHaveText(/^[0-9a-f]{16}$/);
  const evaluation = card.getByTestId('decision-evaluation-id');
  await expect(evaluation).toHaveAttribute('title', /^[0-9a-f-]{36}$/);
  return { card, evaluationId: (await evaluation.getAttribute('title'))! };
}

// the decision's Evaluations tab lists the evaluation with a link back to the run that made it
async function checkEvaluationListed(page: Page, execId: string, evaluationId: string, who: string) {
  await page.getByTestId('tab-evaluations').click();
  const tab = page.getByTestId('evaluations-tab');
  await expect(tab).toBeVisible();
  const row = tab.locator(`[data-testid="evaluation-row"][data-evaluation-id="${evaluationId}"]`);
  await expect(row).toBeVisible({ timeout: 20_000 });
  await expect(row).toHaveAttribute('data-execution-id', execId);
  await expect(row).toContainText('Decided');
  await expect(row).toContainText(who);
  await expect(row.getByTestId('evaluation-run-link')).toHaveAttribute('href', `/executions/${execId}`);
  await row.getByRole('button', { name: /Open the evaluation from/ }).click();
  const detail = page.getByTestId('evaluation-detail');
  await expect(detail).toHaveAttribute('data-evaluation-id', evaluationId);
  await expect(detail.getByTestId('evaluation-detail-outcome')).toHaveText('Decided');
  await expect(detail.getByTestId('evaluation-detail-result')).toContainText(SURCHARGE);
  await expect(detail.getByTestId('evaluation-detail-rules')).toContainText(CITATION);
  await expect(detail.getByTestId('evaluation-detail-trace')).toBeVisible();
  await expect(detail.getByTestId('evaluation-reproduced')).toContainText('trace hash matches');
  await detail.getByTestId('evaluation-detail-run-link').click();
  await page.waitForURL(new RegExp(`/executions/${execId}`), { timeout: 20_000 });
}

async function expand(panelParent: ReturnType<Page['locator']>, title: string) {
  const btn = panelParent.getByRole('button', { name: new RegExp(`^${title}`) }).first();
  if ((await btn.getAttribute('aria-expanded')) !== 'true') await btn.click();
  return btn.locator('xpath=..');
}

async function addTool(page: Page, id: string) {
  const search = page.getByPlaceholder('Search tools, descriptions, params...');
  await search.fill(id);
  await page.getByTestId(`palette-tool-${id}`).first().click();
  await search.fill('');
}

async function publishFromBuilder(page: Page) {
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('a reference set of remote postcodes is created on its page', async ({ page }) => {
  await go(page, '/decisions');
  await page.getByRole('link', { name: /Reference sets/ }).click();
  await page.waitForURL(/\/decisions\/reference-sets/);
  await expect(page.getByRole('heading', { name: 'Reference sets' })).toBeVisible();
  await page.getByTestId('refset-new').click();
  await page.getByTestId('refset-name').fill(`Remote postcodes ${RUN}`);
  await page.getByTestId('refset-key').fill(SET);
  await page.getByTestId('refset-new-values').fill('HS2\nIV27\nZE2\nIV27\n');
  await expect(page.getByTestId('refset-create')).toContainText('3 values');
  await page.getByTestId('refset-create-go').click();
  const row = page.getByTestId(`refset-${SET}`);
  await expect(row).toContainText('3 values · version 1');
  await row.getByRole('button').first().click();
  await expect(page.getByTestId(`refset-values-${SET}`)).toHaveValue('HS2\nIV27\nZE2');
});

test('a decision is authored in the no-code builder with a catch-all outcome', async ({ page }) => {
  await go(page, '/decisions');
  await page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank')).first().click();
  await page.getByTestId('decision-name').fill(`Remote surcharge ${RUN}`);
  await page.getByTestId('decision-key').fill(KEY);
  await expect(page.getByRole('radio', { name: /low/i })).toHaveAttribute('aria-checked', 'true');
  await page.getByTestId('decision-create').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${KEY.replace(/\./g, '\\.')}`));
  // a low tier version publishes without a second person
  await expect(page.getByTestId('decision-tier')).toHaveValue('low');

  await page.getByTestId('rule-add-first').click();
  await page.getByTestId('rule-key').fill('freight.remote.surcharge');
  await page.getByTestId('rule-description').fill('Remote postcodes above 50 kg carry the remote area surcharge');
  await addFactCondition(page, 'rule0', '0', 'shipment.date', 'date');
  await page.getByTestId('rule0-c0-op').selectOption('on_or_after');
  await page.getByTestId('rule0-c0-value').fill('2026-01-01');
  await addFactCondition(page, 'rule0', '1', 'shipment.postcode', 'string');
  await page.getByTestId('rule0-c1-op').selectOption('in_reference_set');
  await page.getByTestId('rule0-c1-value').selectOption(SET);
  await addFactCondition(page, 'rule0', '2', 'shipment.weightKg', 'number');
  await page.getByTestId('rule0-c2-op').selectOption('gt');
  await page.getByTestId('rule0-c2-value').fill('50');
  await page.getByTestId('rule0-new-outcome').fill('surcharge');
  await page.getByTestId('rule0-add-outcome').click();
  await page.getByTestId('rule0-then-surcharge-value').fill(SURCHARGE);
  await page.getByTestId('rule-citation').fill('Carrier tariff 2026, section 4.2');
  await page.getByTestId('rule-citation').press('Enter');
  await expect(page.getByTestId('rule-sentence')).toContainText('shipment.weightKg is more than 50');
  await expect(page.getByTestId('rule-sentence')).toContainText(SURCHARGE);
  await saved(page);

  // first match wins, so a rule with no conditions below it is the default outcome
  await expect(page.getByTestId('hit-policy')).toHaveValue('first');
  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('freight.no.surcharge');
  await page.getByTestId('rule-description').fill('Everything else carries no surcharge');
  await page.getByTestId('rule1-then-surcharge-set').click();
  await page.getByTestId('rule1-then-surcharge-value').fill('NONE');
  await page.getByTestId('rule-citation').fill('Carrier tariff 2026, section 4.1');
  await page.getByTestId('rule-citation').press('Enter');
  await expect(page.getByTestId('rule-sentence')).toContainText(/When always, then surcharge = .NONE./);
  await expect(page.getByTestId('rule-card-1')).toContainText('freight.no.surcharge');

  await page.getByTestId('version-valid-from').fill('2026-01-01');
  await saved(page);
});

test('Try decides hits, misses and missing facts, keeps golden tests, then Check and publish', async ({ page }) => {
  test.setTimeout(120_000);
  await go(page, `/decisions/${KEY}`);
  const panel = page.getByTestId('try-panel');
  await page.getByTestId('try-as-of').fill('2026-03-01');
  await panel.getByTestId('try-fact-shipment.date').fill('2026-03-01');
  await panel.getByTestId('try-fact-shipment.postcode').fill('IV27');
  await panel.getByTestId('try-fact-shipment.weightKg').fill('120');
  await expect(panel.getByTestId('try-result')).toContainText('Decided', { timeout: 15_000 });
  await expect(panel.getByTestId('try-result-value')).toContainText(SURCHARGE);
  await expect(panel.getByTestId('try-result')).toContainText('freight.remote.surcharge');
  await page.getByTestId('try-test-name').fill('Heavy parcel to IV27');
  await page.getByTestId('try-save-test').click();
  await expect(panel).toContainText('Saved as a golden test');

  await panel.getByTestId('try-fact-shipment.postcode').fill('SW1A');
  await expect(panel.getByTestId('try-result-value')).toContainText('NONE', { timeout: 15_000 });
  await expect(panel.getByTestId('try-result')).toContainText('freight.no.surcharge');
  await page.getByTestId('try-test-name').fill('Heavy parcel to London');
  await page.getByTestId('try-save-test').click();
  await expect(panel).toContainText('Saved as a golden test');

  await panel.getByTestId('try-fact-shipment.weightKg').fill('');
  await expect(panel.getByTestId('try-result')).toContainText('Missing facts', { timeout: 15_000 });
  await expect(panel.getByTestId('try-result')).toContainText('Give these before it can decide: shipment.weightKg');

  await page.getByTestId('tab-tests').click();
  await page.getByTestId('tests-run').click();
  await expect(page.getByTestId('tests-summary')).toContainText(/2 of 2 pass|All 2 pass|2 pass/, { timeout: 30_000 });
  await page.getByTestId('tab-rules').click();

  await page.getByTestId('check').click();
  await expect(page.getByTestId('workspace-notice')).toContainText(/Ready\. 2 golden tests pass/);
  await page.getByTestId('propose').click();
  await expect(page.getByTestId('workspace-notice')).toContainText('Approved. You can publish it now.');
  await page.getByTestId('publish').click();
  await expect(page.getByRole('dialog')).toContainText('from 2026-01-01');
  await page.getByRole('button', { name: 'Publish' }).last().click();
  await expect(page.getByTestId('workspace-notice')).toContainText('is now in force');
  await expect(page.getByTestId('version-picker')).toContainText('In force');

  const d = await api(page, 'GET', `/api/decisions/${KEY}`);
  expect(d.json.data.published.length).toBe(1);
});

test('an agent that calls the decision is built, saved and published in the builder', async ({ page }) => {
  await go(page, '/builder');
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Works out the freight surcharge for a shipment from the published remote surcharge decision.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(
    `You price freight surcharges. For every shipment the user describes, call the decision_evaluate tool with ` +
      `decision "${KEY}", facts {"shipment": {"date": "<YYYY-MM-DD>", "postcode": "<postcode>", "weightKg": <number>}} taken ` +
      `from the message, and as_of set to the shipment date. Never decide yourself. Reply with the exact surcharge value ` +
      `the tool returned, the rule that applied, and its source. If the tool reports missing facts, ask for them.`,
  );
  await page.getByTestId('config-tab-model').click();
  const model = page.getByTestId('model-picker-select');
  await expect(model).toBeEnabled({ timeout: 20_000 });
  const sonnet = model.locator('option:not([disabled])', { hasText: /sonnet/i }).first();
  if (await sonnet.count()) await model.selectOption((await sonnet.getAttribute('value'))!);
  await addTool(page, 'decision_evaluate');
  await expect(page.locator('.react-flow__node[data-id="tool-decision_evaluate"]')).toBeVisible();

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.agent = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.agent).toBeTruthy();
  await publishFromBuilder(page);
  const a = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(a.json.data.model_config.tools).toContain('decision_evaluate');
});

test('the agent prices a remote heavy parcel and a London one in chat, and the recorder shows the decision', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, `/agents/${ids.agent}/chat`);
  const hit = await chat(page, 'A 120 kg pallet ships on 2026-03-14 to postcode IV27. Which surcharge applies?');
  expect(hit).toContain(SURCHARGE);
  await openLastRun(page);
  const call = page.locator('[data-testid="tool-call"][data-tool="decision_evaluate"]').first();
  await expect(call).toBeVisible({ timeout: 30_000 });
  await expect(await expand(call, 'Arguments')).toContainText(KEY);
  await expect(await expand(call, 'Result')).toContainText(SURCHARGE);
  await expect(call).toContainText('freight.remote.surcharge');
  ids.agentRun = runId(page);
  const { card, evaluationId } = await checkDecisionCard(call, 'freight.remote.surcharge');

  // Try opens with the run's facts filled in and gives the same answer
  await card.getByTestId('decision-open-try').click();
  await page.waitForURL(VERSION_1_URL, { timeout: 20_000 });
  const tryPanel = page.getByTestId('try-panel');
  await expect(tryPanel.getByTestId('try-preloaded')).toBeVisible();
  await expect(tryPanel.getByTestId('try-fact-shipment.postcode')).toHaveValue('IV27');
  await expect(page.getByTestId('try-as-of')).toHaveValue('2026-03-14');
  await expect(tryPanel.getByTestId('try-result-value')).toContainText(SURCHARGE, { timeout: 15_000 });

  // the version link lands on that version, and the evaluation leads back to the run
  await go(page, `/executions/${ids.agentRun}`);
  const again = page.locator('[data-testid="tool-call"][data-tool="decision_evaluate"]').first();
  await again.getByTestId('decision-version-link').click();
  await page.waitForURL(VERSION_1_URL, { timeout: 20_000 });
  await expect(page.getByTestId('version-picker')).toContainText('Version 1');
  await checkEvaluationListed(page, ids.agentRun, evaluationId, AGENT);
  await expect(page.locator('[data-testid="tool-call"][data-tool="decision_evaluate"]').first()).toBeVisible({ timeout: 30_000 });

  await go(page, `/agents/${ids.agent}/chat`);
  const miss = await chat(page, 'A 120 kg pallet ships on 2026-03-14 to postcode SW1A. Which surcharge applies?');
  expect(miss).toMatch(/NONE/);
  await openLastRun(page);
  const call2 = page.locator('[data-testid="tool-call"][data-tool="decision_evaluate"]').first();
  await expect(call2).toBeVisible({ timeout: 30_000 });
  const res2 = await expand(call2, 'Result');
  await expect(res2).toContainText('NONE');
  await expect(res2).not.toContainText(SURCHARGE);
});

test('a pipeline with typed inputs and a decision step is built, published and run from chat', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, '/builder');
  await page.getByTestId('builder-mode-pipeline').click();
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(PIPELINE);
  await page.getByTestId('builder-name-input').press('Enter');

  // inputs are declared on the pipeline overview, nothing selected
  const inputs: [string, string, string][] = [
    ['ship_date', 'string', 'Shipment date, YYYY-MM-DD'],
    ['postcode', 'string', 'Destination postcode'],
    ['weight_kg', 'number', 'Weight in kg'],
  ];
  for (const [i, [name, type, desc]] of inputs.entries()) {
    await page.getByTestId('input-var-add').click();
    await page.getByTestId(`input-var-name-${i}`).fill(name);
    await page.getByTestId(`input-var-type-${i}`).selectOption(type);
    await page.getByTestId(`input-var-desc-${i}`).fill(desc);
    await page.getByTestId(`input-var-required-${i}`).check();
  }
  await expect(page.getByTestId('input-vars')).toContainText('{{input.ship_date}}');

  const addStep = async (id: string) => {
    const search = page.getByPlaceholder('Search by name, id, or description…');
    await search.fill(id);
    await page.getByTestId(`pipeline-palette-${id}`).first().click();
    await search.fill('');
  };

  await addStep('decision_evaluate');
  await page.getByTestId('step-label-input').fill('decide');
  await page.getByTestId('step-open-arguments').click();
  const decision = page.locator('#arg-decision_evaluate-decision');
  await expect(decision.locator('option', { hasText: KEY })).toHaveCount(1, { timeout: 15_000 });
  await decision.selectOption(KEY);
  await expect(page.getByText('Needs facts:')).toContainText('shipment.weightKg');
  const facts = page.locator('#arg-decision_evaluate-facts');
  await facts.click();
  await facts.pressSequentially('{"shipment": ');
  await expect(page.getByTestId('arg-decision_evaluate-facts-error')).toBeVisible();
  await facts.fill(JSON.stringify({ shipment: { date: '{{input.ship_date}}', postcode: '{{input.postcode}}', weightKg: '{{input.weight_kg}}' } }, null, 2));
  await expect(page.getByTestId('arg-decision_evaluate-facts-error')).toHaveCount(0);
  await page.locator('#arg-decision_evaluate-as_of').fill('{{input.ship_date}}');
  await page.getByRole('button', { name: 'General', exact: true }).click();

  await addStep('llm_call');
  await page.getByTestId('step-label-input').fill('explain');
  await page.getByTestId('step-open-arguments').click();
  await page.getByTestId('step-prompt-input').fill(
    'Tell the shipper in one sentence which surcharge applies and why. Quote the surcharge code exactly as given. Decision: {{decide.result}} Rules applied: {{decide.applied_rules}}',
  );
  await page.getByRole('button', { name: 'General', exact: true }).click();
  await page.locator('[data-testid^="step-dep-"]').first().check();

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.pipeline = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.pipeline).toBeTruthy();
  await expect(page.getByTestId('validation-chip-error')).toHaveCount(0, { timeout: 20_000 });
  await publishFromBuilder(page);

  const p = await api(page, 'GET', `/api/agents/${ids.pipeline}`);
  expect(p.json.data.model_config.input_variables.map((v: any) => v.name)).toEqual(['ship_date', 'postcode', 'weight_kg']);

  await page.getByTestId('chat-param-ship_date').fill('2026-03-14');
  await page.getByTestId('chat-param-postcode').fill('ZE2');
  await page.getByTestId('chat-param-weight_kg').fill('75');
  const answer = await chat(page, 'Price this shipment.', 480_000);
  expect(answer).toContain(SURCHARGE);
  await openLastRun(page);
  const step = page.locator('[data-testid="execution-step"][data-step="decide"]').first();
  await expect(step).toBeVisible({ timeout: 30_000 });
  await expect(await expand(step, 'Output')).toContainText(SURCHARGE);
  await expect(page.locator('main')).toContainText('explain');
  ids.pipelineRun = runId(page);
  const { evaluationId } = await checkDecisionCard(step, 'freight.remote.surcharge');
  await step.getByTestId('decision-card').getByTestId('decision-version-link').click();
  await page.waitForURL(VERSION_1_URL, { timeout: 20_000 });
  await expect(page.getByTestId('version-picker')).toContainText('Version 1');
  await checkEvaluationListed(page, ids.pipelineRun, evaluationId, PIPELINE);
  await expect(page.locator('[data-testid="execution-step"][data-step="decide"]').first()).toBeVisible({ timeout: 30_000 });
});

test('the SDK playground runs the agent and the pipeline live and shows the code', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, '/sdk-playground');
  await expect(page.getByText(/SDK Code Playground/i).first()).toBeVisible();
  const search = page.getByPlaceholder('Search agents...');

  await search.fill(AGENT);
  await page.getByTestId('playground-agent-list').getByRole('button', { name: new RegExp(AGENT) }).click();
  const panel = page.getByTestId('live-inputs-panel');
  await expect(panel).toContainText('agent', { timeout: 20_000 });
  await expect(panel).not.toContainText('Loading input schema', { timeout: 20_000 });
  await page.getByTestId('live-message-input').fill('A 90 kg crate ships on 2026-05-02 to postcode HS2. Which surcharge applies?');
  await page.getByTestId('run-live-button').click();
  const result = page.getByTestId('live-result-panel');
  await expect(result).toContainText('completed', { timeout: 300_000 });
  await expect(result).toContainText(SURCHARGE);

  await page.getByRole('button', { name: 'Python' }).first().click();
  await page.getByRole('button', { name: /Generate Code/ }).click();
  const code = page.locator('pre').filter({ hasText: /abenix|Abenix/ }).first();
  await expect(code).toBeVisible({ timeout: 180_000 });
  const snippet = await code.innerText();
  console.log(`\n--- generated Python snippet (agent) ---\n${snippet.slice(0, 1500)}\n---`);
  expect(snippet).toMatch(new RegExp(`${ids.agent}|surcharge-desk-${RUN}`, 'i'));
  expect(snippet).toContain('postcode HS2');

  await search.fill(PIPELINE);
  await page.getByTestId('playground-agent-list').getByRole('button', { name: new RegExp(PIPELINE) }).click();
  await expect(panel).toContainText('pipeline', { timeout: 20_000 });
  await page.getByTestId('live-input-ship_date').fill('2026-06-10');
  await page.getByTestId('live-input-postcode').fill('IV27');
  await page.getByTestId('live-input-weight_kg').fill('51');
  await page.getByTestId('run-live-button').click();
  await expect(result).toContainText('completed', { timeout: 300_000 });
  await expect(result).toContainText(SURCHARGE);

  await page.getByRole('button', { name: /Generate Code/ }).click();
  const pcode = page.locator('pre').filter({ hasText: /weight_kg/ }).first();
  await expect(pcode).toBeVisible({ timeout: 180_000 });
  const psnippet = await pcode.innerText();
  console.log(`\n--- generated Python snippet (pipeline) ---\n${psnippet.slice(0, 1500)}\n---`);
  expect(psnippet).toMatch(/context=/);
  expect(psnippet).not.toContain('Analyze the latest data');
  expect(psnippet).toContain("'postcode': 'IV27'");
  expect(psnippet).toContain("'weight_kg': 51");
});

test('the reference set cannot be deleted while the decision uses it', async ({ page }) => {
  await go(page, '/decisions/reference-sets');
  const row = page.getByTestId(`refset-${SET}`);
  await row.getByRole('button').first().click();
  await page.getByTestId(`refset-delete-${SET}`).click();
  await page.getByTestId(`refset-delete-confirm-${SET}`).click();
  await expect(page.getByTestId(`refset-msg-${SET}`)).toContainText(`is used by ${KEY}`);
  await expect(row).toBeVisible();
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const tok = (await res.json())?.data?.access_token;
  const call = (method: string, p: string) =>
    page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } }).catch(() => null);
  const list = await call('GET', `/api/agents?search=${encodeURIComponent(RUN)}&limit=100`);
  const mine = ((await list?.json().catch(() => null))?.data || []).filter((a: any) => String(a.name).includes(RUN));
  for (const id of new Set([ids.agent, ids.pipeline, ...mine.map((a: any) => a.id)].filter(Boolean))) await call('DELETE', `/api/agents/${id}`);
  await call('DELETE', `/api/decisions/${KEY}`);
  await call('DELETE', `/api/decision-reference-sets/${SET}`);
  await page.close();
});
