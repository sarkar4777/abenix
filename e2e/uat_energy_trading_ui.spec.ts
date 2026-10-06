/**
 * An energy trader builds a spark spread desk from the screens only.
 *
 *   1. sign in on the landing page form
 *   2. Code Runner      upload the spark desk zip, wait for analysis, test run it
 *   3. Decisions        the desk hedge policy as three cited rules, golden tests, Check and publish
 *   4. Agent Builder    a trading desk agent with the code asset, the policy and four built-in tools, published
 *   5. Chat             vol from price history, simulated gas curve, spread pricing, VaR and the policy's hedge call
 *   6. Pipeline         raw closes in, every number wired step to step, the policy decides, an LLM writes the brief
 *   7. SDK playground   run the agent and the pipeline live and generate the code
 *
 * The hedge call is checked against the desk's own numbers on each run, so the
 * checks hold whatever wording the model picks.
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_energy_trading_ui.spec.ts --workers=1
 *   SHOTS=<folder> saves the showcase screenshots there
 */
import path from 'path';
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const ASSET = `spark-desk-${RUN}`;
const KEY = `energy.hedge.${RUN}`;
const AGENT = `Gas Power Desk ${RUN}`;
const PIPELINE = `Spark Hedge Run ${RUN}`;
const MARKER = 'SPARK_DESK_V1';
const ZIP = path.join(__dirname, 'fixtures', 'spark_desk', 'spark_desk.zip');
const TTF_CLOSES = [33.8, 34.6, 35.9, 35.1, 36.4, 37.8, 36.9, 38.2, 37.1, 35.6, 36.8, 38.9, 37.4, 36.2, 36.0];
const POLICY = 'Desk risk policy 2026';
const SHOTS = process.env.SHOTS || '';

const ids: { asset?: string; agent?: string; pipeline?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

// the policy as the desk wrote it, first match wins
function expectedHedge(stressMarginEur: number, monthsNegative: number) {
  if (stressMarginEur < 0 && monthsNegative >= 4) return { signal: 'HEDGE_75', rule: 'energy.hedge.heavy' };
  if (monthsNegative >= 1) return { signal: 'HEDGE_50', rule: 'energy.hedge.partial' };
  return { signal: 'HEDGE_25', rule: 'energy.hedge.base' };
}

// the note quotes the call as the code, the rule or the ratio, the card checks the exact output
function saysHedge(text: string, want: { signal: string; rule: string }) {
  const pct = want.signal.split('_')[1];
  const rule = want.rule.replace(/\./g, '\\.');
  expect(text, `the answer gives the ${want.signal} call`).toMatch(new RegExp(`${want.signal}|${rule}|HEDGE[ _]${pct}|${pct}\\s*%`));
}

function deskFacts(text: string) {
  const stress = Number(text.match(/"stress_margin_eur":\s*(-?[\d.]+)/)?.[1]);
  const negative = Number(text.match(/"months_negative_count":\s*(\d+)/)?.[1]);
  expect(Number.isFinite(stress), 'stress margin in the desk output').toBe(true);
  expect(Number.isFinite(negative), 'months negative in the desk output').toBe(true);
  return expectedHedge(stress, negative);
}

async function shot(page: Page, name: string, target?: ReturnType<Page['locator']>) {
  if (!SHOTS) return;
  await page.waitForTimeout(700);
  if (target) await target.scrollIntoViewIfNeeded().catch(() => {});
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

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

// read-only lookups for assertions, and cleanup
async function api(page: Page, method: string, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
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

async function chat(page: Page, message: string, timeoutMs = 420_000) {
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

async function openLastRun(page: Page) {
  const viewRun = page.getByTestId('chat-view-run').last();
  await expect(viewRun).toBeVisible({ timeout: 20_000 });
  await viewRun.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
}

async function expand(panelParent: ReturnType<Page['locator']>, title: string) {
  const btn = panelParent.getByRole('button', { name: new RegExp(`^${title}`) }).first();
  if ((await btn.getAttribute('aria-expanded')) !== 'true') await btn.click();
  return btn.locator('xpath=..');
}

// the decision card on a tool call or step names the rule, its source and a trace hash
async function checkDecisionCard(scope: ReturnType<Page['locator']>, want: { signal: string; rule: string }) {
  const card = scope.getByTestId('decision-card').first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId('decision-outcome')).toHaveText('Decided');
  await expect(card.getByTestId('decision-outputs')).toContainText(want.signal);
  const rule = card.locator(`[data-testid="decision-rule"][data-rule="${want.rule}"]`);
  await expect(rule).toBeVisible();
  await expect(rule.getByTestId('decision-citation')).toContainText(POLICY);
  await expect(card.getByTestId('decision-trace-hash')).toHaveText(/^[0-9a-f]{16}$/);
  return card;
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

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('the spark desk code is uploaded, analysed and test run on the Code Runner page', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await go(page, '/code-runner');
  await page.getByPlaceholder('Name (e.g. sentiment-scorer)').fill(ASSET);
  await page.getByPlaceholder('Description (optional)').fill('Clean spark spread, P90 gas stress and Kirk spread option value per delivery month');
  await page.locator('input[type=file][accept=".zip"]').setInputFiles(ZIP);
  await expect(page.getByTestId('code-source-zip')).toContainText('spark_desk.zip');
  await expect(page.getByTestId('code-source-git-url')).toBeDisabled();
  await page.getByRole('button', { name: /Create & analyze/ }).click();

  const item = page.locator(`[data-testid="code-asset-item"][data-name="${ASSET}"]`);
  await expect(item).toBeVisible({ timeout: 60_000 });
  await expect(item).toHaveAttribute('data-status', /ready|failed/, { timeout: 240_000 });
  await item.click();
  await expect(page.getByTestId('code-asset-error')).toHaveCount(0);
  await expect(item).toHaveAttribute('data-status', 'ready');
  await expect(page.locator('main')).toContainText('main.py');

  await page.getByTestId('code-test-input').fill(JSON.stringify({
    power_price: 112, gas_price: 36, carbon_price: 68, heat_rate: 2.0, volume_mw: 200, gas_vol: 0.55, months: 3,
  }));
  await page.getByTestId('code-test-run').click();
  const out = page.getByTestId('code-test-output');
  await expect(out).toContainText(MARKER, { timeout: 240_000 });
  await expect(out).toContainText('"clean_spark_spread": 15.18');
  await expect(out).toContainText('"months_negative_count": 3');
  await shot(page, '01-code-runner-test-run', out);

  // bad input is reported, not hidden
  await page.getByTestId('code-test-input').fill('{"gas_price": 36}');
  await page.getByTestId('code-test-run').click();
  await expect(out).toContainText(/power_price is required|failed/i, { timeout: 240_000 });

  const list = await api(page, 'GET', '/api/code-assets');
  const asset = (list.json?.data || []).find((a: any) => a.name === ASSET);
  expect(asset?.status).toBe('ready');
  ids.asset = asset.id;
});

test('the desk hedge policy is written as cited rules, tested and published', async ({ page }) => {
  await go(page, '/decisions');
  await page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank')).first().click();
  await page.getByTestId('decision-name').fill(`Desk hedge policy ${RUN}`);
  await page.getByTestId('decision-key').fill(KEY);
  await page.getByTestId('decision-create').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${KEY.replace(/\./g, '\\.')}`));

  await page.getByTestId('rule-add-first').click();
  await page.getByTestId('rule-key').fill('energy.hedge.heavy');
  await page.getByTestId('rule-description').fill('Stress margin below zero with four or more months under water: hedge 75%');
  await addFactCondition(page, 'rule0', '0', 'position.stressMarginEur', 'number');
  await page.getByTestId('rule0-c0-op').selectOption('lt');
  await page.getByTestId('rule0-c0-value').fill('0');
  await addFactCondition(page, 'rule0', '1', 'position.monthsNegative', 'number');
  await page.getByTestId('rule0-c1-op').selectOption('gte');
  await page.getByTestId('rule0-c1-value').fill('4');
  await page.getByTestId('rule0-new-outcome').fill('hedge');
  await page.getByTestId('rule0-add-outcome').click();
  await page.getByTestId('rule0-then-hedge-value').fill('HEDGE_75');
  await page.getByTestId('rule-citation').fill(`${POLICY}, section 3.1`);
  await page.getByTestId('rule-citation').press('Enter');
  await expect(page.getByTestId('rule-sentence')).toContainText('HEDGE_75');
  await saved(page);

  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('energy.hedge.partial');
  await page.getByTestId('rule-description').fill('Any month under water in the stress case: hedge 50%');
  await addFactCondition(page, 'rule1', '0', 'position.monthsNegative', 'number');
  await page.getByTestId('rule1-c0-op').selectOption('gte');
  await page.getByTestId('rule1-c0-value').fill('1');
  await page.getByTestId('rule1-then-hedge-set').click();
  await page.getByTestId('rule1-then-hedge-value').fill('HEDGE_50');
  await page.getByTestId('rule-citation').fill(`${POLICY}, section 3.2`);
  await page.getByTestId('rule-citation').press('Enter');
  await saved(page);

  await page.getByTestId('rule-add').click();
  await page.getByTestId('rule-key').fill('energy.hedge.base');
  await page.getByTestId('rule-description').fill('Every month survives the stress case: keep the 25% base hedge');
  await page.getByTestId('rule2-then-hedge-set').click();
  await page.getByTestId('rule2-then-hedge-value').fill('HEDGE_25');
  await page.getByTestId('rule-citation').fill(`${POLICY}, section 3.3`);
  await page.getByTestId('rule-citation').press('Enter');
  await expect(page.getByTestId('rule-sentence')).toContainText(/When always, then hedge = .HEDGE_25./);
  await page.getByTestId('version-valid-from').fill('2026-01-01');
  await saved(page);

  // Try each branch and keep it as a golden test
  const panel = page.getByTestId('try-panel');
  const tryCase = async (stress: string, negative: string, want: string, rule: string, name: string) => {
    await panel.getByTestId('try-fact-position.stressMarginEur').fill(stress);
    await panel.getByTestId('try-fact-position.monthsNegative').fill(negative);
    await expect(panel.getByTestId('try-result-value')).toContainText(want, { timeout: 15_000 });
    await expect(panel.getByTestId('try-result')).toContainText(rule);
    await page.getByTestId('try-test-name').fill(name);
    await page.getByTestId('try-save-test').click();
    await expect(panel).toContainText('Saved as a golden test');
  };
  await tryCase('-11870000', '6', 'HEDGE_75', 'energy.hedge.heavy', 'Deep stress loss, six months under');
  await tryCase('-200000', '2', 'HEDGE_50', 'energy.hedge.partial', 'Small stress loss, two months under');
  await tryCase('4200000', '0', 'HEDGE_25', 'energy.hedge.base', 'Every month survives stress');
  await shot(page, '02-hedge-policy-rules');

  await page.getByTestId('tab-tests').click();
  await page.getByTestId('tests-run').click();
  await expect(page.getByTestId('tests-summary')).toContainText(/3 of 3 pass|All 3 pass|3 pass/);
  await page.getByTestId('tab-rules').click();
  await page.getByTestId('check').click();
  await expect(page.getByTestId('workspace-notice')).toContainText(/Ready\. 3 golden tests pass/);
  await page.getByTestId('propose').click();
  await expect(page.getByTestId('workspace-notice')).toContainText('Approved. You can publish it now.');
  await page.getByTestId('publish').click();
  const confirm = page.getByRole('dialog');
  await expect(confirm).toContainText('from 2026-01-01');
  await confirm.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByTestId('workspace-notice')).toContainText('is now in force');
  const d = await api(page, 'GET', `/api/decisions/${KEY}`);
  expect(d.json.data.published.length).toBe(1);
});

test('a trading desk agent is built from the asset with the policy and four built-in tools', async ({ page }) => {
  await go(page, '/code-runner');
  await page.locator(`[data-testid="code-asset-item"][data-name="${ASSET}"]`).click();
  await page.getByTestId('code-use-in-agent').click();
  await page.waitForURL(/\/builder\?.*tool=code_asset/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-code_asset"]')).toBeVisible({ timeout: 20_000 });

  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Gas and power desk: realised vol, simulated TTF curve, spark spread pricing, VaR, and the hedge call from the desk policy.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(
    'You support a gas and power trading desk that runs a gas-fired plant. Work only from tool results and never make the hedge call yourself.\n' +
      'For a hedging question:\n' +
      '1. realized_vol_calc on the gas closes the user gives.\n' +
      '2. monte_carlo_curve with spot = last_price and vol = vol_annual from step 1, the tenor the user asks for, seasonality_amplitude 0.25, seasonality_peak_month 1, seed 7.\n' +
      '3. code_asset with input {"gas_curve": <the points list from step 2>, "power_price", "carbon_price", "heat_rate", "volume_mw", "gas_vol": vol_annual}.\n' +
      '4. risk_analyzer with analysis_type "var" and params {"portfolio_value": position_notional_eur, "mean_return": 0, "std_return": daily_return_vol, "confidence_levels": [0.95, 0.99], "holding_period_days": 1} from step 3.\n' +
      `5. decision_evaluate with decision "${KEY}" and facts {"position": {"stressMarginEur": stress_margin_eur, "monthsNegative": months_negative_count}} copied exactly from step 3.\n` +
      '6. For the monthly volume, calculator with the expression "<volume_mw> * <hours> / 1000", which is GWh.\n' +
      'Answer with a short desk note: realised vol, expected and stress margin, the hedge value the decision returned exactly as written with the rule and its source, the 99% one-day VaR and the monthly volume.',
  );
  await page.getByTestId('config-tab-model').click();
  const model = page.getByTestId('model-picker-select');
  await expect(model).toBeEnabled({ timeout: 20_000 });
  // the newest Sonnet on offer, as a trader would pick
  const values = await model.locator('option:not([disabled])').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  const best = [/sonnet-5/, /sonnet-4-6/, /sonnet-4-5/, /sonnet/].map((re) => values.find((v) => re.test(v))).find(Boolean);
  if (best) await model.selectOption(best);

  for (const t of ['realized_vol_calc', 'monte_carlo_curve', 'risk_analyzer', 'decision_evaluate', 'calculator']) await addTool(page, t);
  // the agent card counts every tool on the canvas
  await expect(page.locator('.react-flow__node[data-id="agent"]')).toContainText('6 tools');

  await page.locator('.react-flow__node[data-id="tool-code_asset"]').click();
  const pick = page.getByTestId('code-asset-select');
  await expect(pick).toBeVisible({ timeout: 20_000 });
  await expect(pick).toHaveValue(ids.asset!);
  await shot(page, '03-agent-builder');

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.agent = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.agent).toBeTruthy();
  await publishFromBuilder(page);
  const a = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(a.json.data.model_config.tools).toEqual(expect.arrayContaining(['code_asset', 'realized_vol_calc', 'monte_carlo_curve', 'risk_analyzer', 'decision_evaluate', 'calculator']));
});

test('the desk agent prices a six month hedge in chat and the policy makes the call', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  await go(page, `/agents/${ids.agent}/chat`);
  const answer = await chat(
    page,
    `TTF day-ahead closes for the last 15 sessions, oldest first: ${TTF_CLOSES.join(', ')} EUR/MWh. ` +
      'Power baseload forward is 112 EUR/MWh, EUA carbon 68 EUR/t. Our CCGT runs at heat rate 2.0 and we sell 200 MW. ' +
      'Price the next 6 months, tell me how much to hedge and our one-day VaR, and give the monthly volume for 730 hours.',
  );
  console.log(`\n--- desk note ---\n${answer}\n---`);
  await shot(page, '04-agent-chat-desk-note', page.locator('[data-testid="chat-message"][data-role="assistant"]').last());

  await openLastRun(page);
  const calls = (tool: string) => page.locator(`[data-testid="tool-call"][data-tool="${tool}"]`).first();
  for (const t of ['realized_vol_calc', 'monte_carlo_curve', 'code_asset', 'risk_analyzer', 'decision_evaluate', 'calculator']) {
    await expect(calls(t), `${t} was called`).toBeVisible({ timeout: 30_000 });
  }
  await expect(await expand(calls('monte_carlo_curve'), 'Result')).toContainText('M+6');
  await expect(await expand(calls('risk_analyzer'), 'Result')).toContainText('var_dollar');
  await expect(await expand(calls('calculator'), 'Result')).toContainText('146');

  // the desk's own numbers decide which rule must fire, and the agent quotes it
  const desk = await (await expand(calls('code_asset'), 'Result')).innerText();
  expect(desk).toContain(MARKER);
  const want = deskFacts(desk);
  await checkDecisionCard(calls('decision_evaluate'), want);
  saysHedge(answer, want);
  expect(answer).toMatch(/146\s*GWh/);
  await shot(page, '05-agent-flight-recorder', calls('decision_evaluate'));
});

test('a pipeline takes raw closes, wires every number step to step and the policy decides', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  await go(page, '/builder');
  await page.getByTestId('builder-mode-pipeline').click();
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(PIPELINE);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('pipeline-description').fill(
    'From raw TTF closes to a hedge brief: realised vol, simulated curve, spark desk pricing, VaR, the desk hedge policy and a power sensitivity.',
  );

  const inputs: [string, string, string][] = [
    ['gas_closes', 'string', 'Daily TTF closes in EUR/MWh, oldest first, separated by commas'],
    ['tenor_months', 'number', 'Months to price'],
    ['power_price', 'number', 'Baseload power forward, EUR/MWh'],
    ['carbon_price', 'number', 'EUA, EUR/t'],
    ['volume_mw', 'number', 'Plant output sold, MW'],
  ];
  for (const [i, [name, type, desc]] of inputs.entries()) {
    await page.getByTestId('input-var-add').click();
    await page.getByTestId(`input-var-name-${i}`).fill(name);
    await page.getByTestId(`input-var-type-${i}`).selectOption(type);
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

  await addStep('realized_vol_calc', 'vol');
  await args();
  // a list field takes one reference to the whole list
  await page.locator('#arg-realized_vol_calc-prices').fill('{{input.gas_closes}}');
  await expect(page.getByTestId('arg-realized_vol_calc-prices-error')).toHaveCount(0);
  await general();

  await addStep('monte_carlo_curve', 'curve');
  await args();
  // a number field says what it needs, then takes a reference to a step
  await page.locator('#arg-monte_carlo_curve-spot').fill('front month');
  await expect(page.getByTestId('arg-monte_carlo_curve-spot-error')).toContainText('Enter a number, or a reference');
  await page.locator('#arg-monte_carlo_curve-spot').fill('{{vol.last_price}}');
  await expect(page.getByTestId('arg-monte_carlo_curve-spot-error')).toHaveCount(0);
  await page.locator('#arg-monte_carlo_curve-vol').fill('{{vol.vol_annual}}');
  await page.locator('#arg-monte_carlo_curve-tenor_months').fill('{{input.tenor_months}}');
  await page.locator('#arg-monte_carlo_curve-mean_reversion').fill('0.2');
  await page.locator('#arg-monte_carlo_curve-seasonality_amplitude').fill('0.25');
  await page.locator('#arg-monte_carlo_curve-paths').fill('2000');
  await page.locator('#arg-monte_carlo_curve-seed').fill('7.5');
  await expect(page.getByTestId('arg-monte_carlo_curve-seed-error')).toContainText('whole number');
  await page.locator('#arg-monte_carlo_curve-seed').fill('7');
  await page.locator('#arg-monte_carlo_curve-commodity').fill('TTF');
  await general();
  await dependOn('vol');

  await addStep('code_asset', 'desk');
  await args();
  // the asset is picked by name, and the picker lists what the code reads
  const assetPick = page.getByTestId('step-code-asset-select');
  await expect(assetPick.locator('option', { hasText: ASSET })).toHaveCount(1, { timeout: 15_000 });
  await assetPick.selectOption((await assetPick.locator('option', { hasText: ASSET }).getAttribute('value'))!);
  await expect(assetPick).toHaveValue(ids.asset!);
  await expect(page.getByTestId('step-code-asset-fields')).toContainText('power_price*');
  await page.locator('#arg-code_asset-input').fill(JSON.stringify({
    gas_curve: '{{curve.points}}',
    power_price: '{{input.power_price}}',
    carbon_price: '{{input.carbon_price}}',
    volume_mw: '{{input.volume_mw}}',
    gas_vol: '{{vol.vol_annual}}',
    heat_rate: 2.0,
  }, null, 2));
  await expect(page.getByTestId('arg-code_asset-input-error')).toHaveCount(0);
  await general();
  await dependOn('curve', 'vol');
  await args();
  await shot(page, '06-pipeline-builder-desk-step');
  await general();

  await addStep('risk_analyzer', 'var');
  await args();
  await page.locator('#arg-risk_analyzer-analysis_type').selectOption('var');
  await page.locator('#arg-risk_analyzer-params').fill(JSON.stringify({
    portfolio_value: '{{desk.result.position_notional_eur}}',
    mean_return: 0,
    std_return: '{{desk.result.daily_return_vol}}',
    confidence_levels: [0.95, 0.99],
    holding_period_days: 1,
  }, null, 2));
  await general();
  await dependOn('desk');

  await addStep('decision_evaluate', 'policy');
  await args();
  const decision = page.locator('#arg-decision_evaluate-decision');
  await expect(decision.locator('option', { hasText: KEY })).toHaveCount(1, { timeout: 15_000 });
  await decision.selectOption(KEY);
  await expect(page.getByText('Needs facts:')).toContainText('position.monthsNegative');
  await page.locator('#arg-decision_evaluate-facts').fill(JSON.stringify({
    position: { stressMarginEur: '{{desk.result.stress_margin_eur}}', monthsNegative: '{{desk.result.months_negative_count}}' },
  }, null, 2));
  await expect(page.getByTestId('arg-decision_evaluate-facts-error')).toHaveCount(0);
  await general();
  await dependOn('desk');
  await args();
  // every step so far is wired, so nothing is flagged
  await expect(page.getByTestId('validation-chip-error')).toHaveCount(0, { timeout: 20_000 });
  await shot(page, '07-pipeline-builder-policy-step');
  await general();

  await addStep('scenario_planner', 'sensitivity');
  await args();
  await page.locator('#arg-scenario_planner-parameters').fill(JSON.stringify({
    power: { base: '{{input.power_price}}', range: [80, 140], steps: 7, unit: 'EUR/MWh' },
    gas: { base: '{{vol.last_price}}' },
    carbon: { base: '{{input.carbon_price}}' },
  }, null, 2));
  await page.locator('#arg-scenario_planner-formula').fill('power - 2.0*gas - 0.365*carbon');
  await page.locator('#arg-scenario_planner-output_name').fill('clean_spark_spread');
  await general();
  await dependOn('vol');

  await addStep('llm_call', 'brief');
  await args();
  await page.getByTestId('step-prompt-input').fill(
    'Write a five line hedge brief for the gas and power desk. Quote the hedge value from the policy decision exactly and name the rule and its source. ' +
      'State the realised vol, the expected and stress margin in EUR, the 99% one-day VaR in EUR, and the power price below which the spark spread turns negative.\n' +
      'Realised vol, annualised as a decimal (0.55 means 55%): {{vol.vol_annual}}\nDesk: {{desk.result}}\nPolicy decision: {{policy.result}}\nRules applied: {{policy.applied_rules}}\nVaR: {{var.var}}\nPower sensitivity: {{sensitivity}}',
  );
  await general();
  await dependOn('policy', 'var', 'sensitivity');

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.pipeline = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.pipeline).toBeTruthy();
  await expect(page.getByTestId('validation-chip-error')).toHaveCount(0, { timeout: 20_000 });

  // references were saved as references, literals as numbers, the asset by id
  const stored = await api(page, 'GET', `/api/agents/${ids.pipeline}`);
  expect(stored.json.data.description).toContain('desk hedge policy');
  const nodes = stored.json.data.model_config.pipeline_config.nodes as any[];
  const byTool = (t: string) => nodes.find((n) => (n.tool_name || n.tool) === t);
  expect(byTool('realized_vol_calc').arguments.prices).toBe('{{input.gas_closes}}');
  expect(byTool('monte_carlo_curve').arguments.spot).toBe('{{vol.last_price}}');
  expect(byTool('monte_carlo_curve').arguments.seed).toBe(7);
  expect(byTool('code_asset').arguments.code_asset_id).toBe(ids.asset);

  await publishFromBuilder(page);
  await page.getByTestId('chat-param-gas_closes').fill(TTF_CLOSES.join(', '));
  await page.getByTestId('chat-param-tenor_months').fill('6');
  await page.getByTestId('chat-param-power_price').fill('112');
  await page.getByTestId('chat-param-carbon_price').fill('68');
  await page.getByTestId('chat-param-volume_mw').fill('200');
  const brief = await chat(page, 'Run the hedge for the next six months.', 600_000);
  console.log(`\n--- hedge brief ---\n${brief}\n---`);
  await shot(page, '08-pipeline-hedge-brief', page.locator('[data-testid="chat-message"][data-role="assistant"]').last());

  await openLastRun(page);
  const step = (s: string) => page.locator(`[data-testid="execution-step"][data-step="${s}"]`).first();
  await expect(step('vol')).toBeVisible({ timeout: 30_000 });
  const volOut = await (await expand(step('vol'), 'Output')).innerText();
  const volAnnual = Number(volOut.match(/"vol_annual":\s*([\d.]+)/)?.[1]);
  expect(volAnnual).toBeGreaterThan(0.3);
  // the curve was simulated with exactly the vol the first step measured
  const curveIn = await (await expand(step('curve'), 'Input')).innerText();
  expect(Number(curveIn.match(/"vol":\s*([\d.]+)/)?.[1])).toBe(volAnnual);
  await expect(await expand(step('curve'), 'Output')).toContainText('M+6');
  const deskOut = await (await expand(step('desk'), 'Output')).innerText();
  expect(deskOut).toContain(MARKER);
  const want = deskFacts(deskOut);
  await expect(await expand(step('var'), 'Output')).toContainText('var_dollar');
  await expect(await expand(step('sensitivity'), 'Output')).toContainText('clean_spark_spread');
  await checkDecisionCard(step('policy'), want);
  saysHedge(brief, want);
  await shot(page, '09-pipeline-flight-recorder', step('policy'));
});

test('the SDK playground runs the desk agent and the hedge pipeline live and shows the code', async ({ page }) => {
  test.setTimeout(14 * 60_000);
  await go(page, '/sdk-playground');
  await expect(page.getByText(/SDK Code Playground/i).first()).toBeVisible();
  const search = page.getByPlaceholder('Search agents...');
  const panel = page.getByTestId('live-inputs-panel');
  const result = page.getByTestId('live-result-panel');

  await search.fill(AGENT);
  await page.getByTestId('playground-agent-list').getByRole('button', { name: new RegExp(AGENT) }).click();
  await expect(panel).not.toContainText('Loading input schema', { timeout: 20_000 });
  await page.getByTestId('live-message-input').fill(
    `Gas closes oldest first: ${TTF_CLOSES.slice(5).join(', ')}. Power 105, carbon 70, heat rate 2.0, 150 MW. ` +
      'Price the next 3 months and give the hedge call and the 99% one-day VaR.',
  );
  await page.getByTestId('run-live-button').click();
  await expect(result).toContainText('completed', { timeout: 420_000 });
  await expect(result).toContainText(/HEDGE[ _](25|50|75)|energy\.hedge\.(heavy|partial|base)/);

  await page.getByRole('button', { name: 'Python' }).first().click();
  await page.getByRole('button', { name: /Generate Code/ }).click();
  const code = page.locator('pre').filter({ hasText: /abenix|Abenix/ }).first();
  await expect(code).toBeVisible({ timeout: 180_000 });
  expect(await code.innerText()).toMatch(new RegExp(`${ids.agent}|gas-power-desk-${RUN}`, 'i'));

  await search.fill(PIPELINE);
  await page.getByTestId('playground-agent-list').getByRole('button', { name: new RegExp(PIPELINE) }).click();
  await expect(panel).toContainText('pipeline', { timeout: 20_000 });
  await page.getByTestId('live-input-gas_closes').fill('41.2, 42.0, 43.5, 42.8, 44.1, 45.0, 43.9, 44.6, 46.2, 45.1, 44.0, 42.9');
  await page.getByTestId('live-input-tenor_months').fill('4');
  await page.getByTestId('live-input-power_price').fill('118');
  await page.getByTestId('live-input-carbon_price').fill('72');
  await page.getByTestId('live-input-volume_mw').fill('250');
  await page.getByTestId('run-live-button').click();
  await expect(result).toContainText('completed', { timeout: 600_000 });
  await expect(result).toContainText(/HEDGE[ _](25|50|75)|energy\.hedge\.(heavy|partial|base)/);

  await page.getByRole('button', { name: /Generate Code/ }).click();
  const pcode = page.locator('pre').filter({ hasText: /volume_mw/ }).first();
  await expect(pcode).toBeVisible({ timeout: 180_000 });
  const psnippet = await pcode.innerText();
  console.log(`\n--- generated Python snippet (pipeline) ---\n${psnippet.slice(0, 1200)}\n---`);
  expect(psnippet).toMatch(/context=/);
  expect(psnippet).toContain("'volume_mw': 250");
  expect(psnippet).toContain('gas_closes');
  await shot(page, '10-sdk-playground', result);
});

test.afterAll(async ({ browser }) => {
  if (process.env.KEEP) return;
  const page = await browser.newPage();
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const tok = (await res.json())?.data?.access_token;
  const call = (method: string, p: string) =>
    page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } }).catch(() => null);
  const list = await call('GET', `/api/agents?search=${encodeURIComponent(RUN)}&limit=100`);
  const mine = ((await list?.json().catch(() => null))?.data || []).filter((a: any) => String(a.name).includes(RUN));
  for (const id of new Set([ids.agent, ids.pipeline, ...mine.map((a: any) => a.id)].filter(Boolean))) await call('DELETE', `/api/agents/${id}`);
  if (ids.asset) await call('DELETE', `/api/code-assets/${ids.asset}`);
  await call('DELETE', `/api/decisions/${KEY}`);
  await page.close();
});
