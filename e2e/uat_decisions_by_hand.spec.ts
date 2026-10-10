/**
 * A person signs up for a one-person workspace and rebuilds the Groundwork exclusion zone rules by hand, through the screens only:
 * a new decision with a key check, five rules typed key by key with decimals, number outcomes, sources,
 * a paste from Excel into an empty decision, Try it and Keep as test, Check, a risk tier lowering that waits for sign-off,
 * the tier lock while proposed, Propose, approving as the only approver, Publish, the same answers as gw.safety.exclusion,
 * Retire, Archive and Restore, and Export and Import. Then, in the main workspace, a reviewer invited through Team signs what the
 * author can't: the publish, a tier lowering and the review a tier raise asks for.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_decisions_by_hand.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { openFromSidebar } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
// a workspace with one person in it, so nobody else can sign; made through the sign-up page
const SOLO = { email: `solo-${RUN}@example.com`, password: 'SoloPass123!', name: `Sam Solo ${RUN}` };
const REVIEWER = { email: `reviewer-${RUN}@example.com`, name: `Rita Reviewer ${RUN}`, password: 'Reviewer123!' };
const TWO_KEY = `uat.twoperson.${RUN}`;
const KEY = `uat.byhand.${RUN}`;
const NAME = `Exclusion zones by hand ${RUN}`;
const PASTE_KEY = `uat.paste.${RUN}`;
const COPY_KEY = `uat.copy.${RUN}`;
// a fresh workspace each run, so Groundwork's own key is free there
const GW_KEY = 'gw.safety.exclusion';
const GW_FILE = process.env.GW_FILE || 'C:/Users/sarka/projects/groundwork/abenix/decisions/gw.safety.exclusion.json';
const SHOTS = path.join(__dirname, 'uat_decisions_by_hand', 'shots');

const TIP = 'machine.tip_speed_ms';
const CLEAR = 'worker.clearance_m';
const SOURCE = 'Northgate Yard site safety plan, section 3.2 Exclusion zones';

// the rules and cases from groundwork/abenix/decisions/gw.safety.exclusion.json
const RULES = [
  { key: 'stop.fast_swing', desc: 'Tip moving faster than 2 m/s, a worker within 4 m of the swing radius', tip: '2', clear: ['lt', '4'], action: 'stop', margin: '4', reason: 'Worker inside the swing radius plus 4 m while the tip moves over 2 m/s', source: SOURCE },
  { key: 'stop.medium_swing', desc: 'Tip moving 0.5 to 2 m/s, a worker within 3 m of the swing radius', tip: '0.5', clear: ['lt', '3'], action: 'stop', margin: '3', reason: 'Worker inside the swing radius plus 3 m while the tip moves', source: SOURCE },
  { key: 'stop.any', desc: 'Any worker within 2 m of the swing radius, moving or not', tip: null, clear: ['lt', '2'], action: 'stop', margin: '2', reason: 'Worker inside the swing radius plus 2 m', source: SOURCE },
  { key: 'warn.approach', desc: 'A worker within 7 m of the swing radius', tip: null, clear: ['lt', '7'], action: 'warn', margin: '7', reason: 'Worker approaching the exclusion zone', source: 'Northgate Yard site safety plan, section 3.3 Warning zone' },
  { key: 'ok.clear', desc: 'Everyone clear', tip: null, clear: ['gte', '7'], action: 'ok', margin: '7', reason: '', source: null },
] as const;

const CASES = [
  { name: 'fast swing, worker 3 m out', tip: '4.5', clear: '3', expected: { action: 'stop', margin_m: 4, reason: 'Worker inside the swing radius plus 4 m while the tip moves over 2 m/s' } },
  { name: 'slow swing, worker 2.5 m out', tip: '0.2', clear: '2.5', expected: { action: 'warn', margin_m: 7, reason: 'Worker approaching the exclusion zone' } },
  { name: 'parked, worker inside', tip: '0', clear: '1', expected: { action: 'stop', margin_m: 2, reason: 'Worker inside the swing radius plus 2 m' } },
  { name: 'clear', tip: '6', clear: '20', expected: { action: 'ok', margin_m: 7, reason: '' } },
];

const PASTE = [
  ['rule', TIP, CLEAR, 'action', 'margin_m', 'reason', 'sources'],
  ['stop.fast_swing', '>= 2', '< 4', 'stop', '4', RULES[0].reason, SOURCE],
  ['stop.medium_swing', '>= 0.5', '< 3', 'stop', '3', RULES[1].reason, SOURCE],
  ['stop.any', '', '< 2', 'stop', '2', RULES[2].reason, SOURCE],
  ['warn.approach', '', '< 7', 'warn', '7', RULES[3].reason, RULES[3].source],
  ['ok.clear', '', '>= 7', 'ok', '7', '""', ''],
].map((r) => r.join('\t')).join('\n');

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });
test.setTimeout(6 * 60_000);

let tok = '';

async function tokenFor(page: Page, creds: { email: string; password: string } = SOLO) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: { email: creds.email, password: creds.password } });
  expect(res.ok(), `login ${creds.email}`).toBeTruthy();
  return (await res.json()).data.access_token as string;
}

async function login(page: Page, creds: { email: string; password: string } = SOLO) {
  const t = await tokenFor(page, creds);
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, t);
  return t;
}

async function api(page: Page, t: string, method: string, p: string, body?: unknown) {
  const opts = { method, headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' }, data: body === undefined ? undefined : JSON.stringify(body) };
  const res = await page.request.fetch(`${API}${p}`, opts).catch(() => page.request.fetch(`${API}${p}`, opts));
  let json: any = null;
  try { json = await res.json(); } catch { /* not json */ }
  return { status: res.status(), json };
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
}

// the what-now guide in its current state, checked and kept as a picture
async function guideIs(page: Page, step: string, text: RegExp, name: string) {
  const g = page.getByTestId('decision-guide');
  await expect(g).toHaveAttribute('data-step', step, { timeout: 20_000 });
  await expect(page.getByTestId('guide-text')).toContainText(text, { timeout: 20_000 });
  fs.mkdirSync(SHOTS, { recursive: true });
  await g.screenshot({ path: path.join(SHOTS, `guide-${name}.png`) });
}

async function saved(page: Page) {
  await expect(page.getByTestId('save-state')).toHaveText(/All changes saved/, { timeout: 20_000 });
}

async function pickFact(page: Page, prefix: string, idx: string, factPath: string, expectGuess: string) {
  await page.getByTestId(`${prefix}-c${idx}-fact`).click();
  await page.getByLabel('Search facts').fill(factPath);
  const existing = page.getByRole('option', { name: new RegExp(`^${factPath.replace(/\./g, '\\.')}$`) });
  if (await existing.count()) { await existing.first().click(); return; }
  // a new fact: the type is guessed from the name, not left on Text
  await expect(page.getByTestId('fact-new-type')).toHaveValue(expectGuess);
  await page.getByTestId('fact-add-new').click();
}

async function addCondition(page: Page, prefix: string, idx: string, factPath: string, op: string, typed: string) {
  await page.getByTestId(`${prefix}-g-add`).click();
  await pickFact(page, prefix, idx, factPath, 'number');
  await page.getByTestId(`${prefix}-c${idx}-op`).selectOption(op);
  const value = page.getByTestId(`${prefix}-c${idx}-value`);
  await value.fill('');
  await value.pressSequentially(typed, { delay: 40 });
  await expect(value).toHaveValue(typed);
}

async function setOutcome(page: Page, prefix: string, field: string, typed: string, first: boolean) {
  if (first) {
    await page.getByTestId(`${prefix}-new-outcome`).pressSequentially(field, { delay: 20 });
    await page.getByTestId(`${prefix}-add-outcome`).click();
  } else {
    await page.getByTestId(`${prefix}-then-${field}-set`).click();
  }
  const input = page.getByTestId(`${prefix}-then-${field}-value`);
  if (typed) {
    await input.pressSequentially(typed, { delay: 15 });
    await expect(input).toHaveValue(typed);
  }
  await input.press('Tab');
}

test('a new person signs up for their own workspace', async ({ page }) => {
  await visit(page, '/');
  // the tab only switches once the page has hydrated, so press it until the form changes
  await expect(async () => {
    await page.getByRole('button', { name: 'Switch to register' }).click();
    await expect(page.locator('#auth-full-name')).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await page.locator('#auth-full-name').fill(SOLO.name);
  await page.locator('#auth-email').fill(SOLO.email);
  await page.locator('#auth-password').fill(SOLO.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  tok = await tokenFor(page);
  const me = await api(page, tok, 'GET', '/api/me/permissions');
  expect(me.json.data.is_admin).toBe(true);
});

test('a new decision checks its key as it is typed and says why Create waits', async ({ page }) => {
  await login(page);
  await visit(page, '/dashboard');
  await openFromSidebar(page, '/decisions');
  const start = page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank'));
  await start.first().click();
  await expect(page.getByTestId('decision-create')).toBeDisabled();
  await expect(page.getByTestId('decision-create-why')).toHaveText('Give it a name to continue.');
  await expect(page.getByTestId('decision-name')).toHaveValue('');
  await shot(page, '01-new-decision-empty');
  await page.getByTestId('decision-name').pressSequentially(NAME, { delay: 10 });
  await page.getByTestId('decision-key').fill('Bad Key');
  await expect(page.getByTestId('decision-key-help')).toContainText('Use lowercase letters');
  await page.getByTestId('decision-key').fill(KEY);
  await expect(page.getByTestId('decision-key-help')).toContainText('Free to use', { timeout: 10_000 });
  await page.getByTestId('decision-tier-high').click();
  await shot(page, '02-new-decision-key-free');
  await page.getByTestId('decision-create').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${KEY.replace(/\./g, '\\.')}`));
  await expect(page.getByTestId('lifecycle-bar')).toContainText('Propose');
  await guideIs(page, 'rules', /Paste them from Excel/, '1-rules');

  // the same key again is caught at the field, with a free one offered
  await visit(page, '/decisions');
  await page.getByTestId('decision-new').click();
  await page.getByTestId('decision-name').fill('Another one');
  await page.getByTestId('decision-key').fill(KEY);
  await expect(page.getByTestId('decision-key-help')).toContainText('already used', { timeout: 10_000 });
  await expect(page.getByTestId('decision-create')).toBeDisabled();
  await expect(page.getByTestId('decision-create-why')).toHaveText('Pick a key that is free.');
  await shot(page, '03-new-decision-key-taken');
  await page.getByTestId('decision-key-suggestion').click();
  await expect(page.getByTestId('decision-key')).toHaveValue(`${KEY}.2`);
  await expect(page.getByTestId('decision-key-help')).toContainText('Free to use', { timeout: 10_000 });
  await page.getByRole('button', { name: 'Cancel' }).click();
});

test('five rules typed key by key, with decimals, number outcomes and sources', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  for (let i = 0; i < RULES.length; i++) {
    const r = RULES[i];
    const prefix = `rule${i}`;
    await page.getByTestId(i === 0 ? 'rule-add-first' : 'rule-add').click();
    await page.getByTestId('rule-key').pressSequentially(r.key, { delay: 10 });
    await page.getByTestId('rule-description').fill(r.desc);
    let c = 0;
    if (r.tip) await addCondition(page, prefix, String(c++), TIP, 'gte', r.tip);
    await addCondition(page, prefix, String(c++), CLEAR, r.clear[0], r.clear[1]);
    await setOutcome(page, prefix, 'action', r.action, i === 0);
    await setOutcome(page, prefix, 'margin_m', r.margin, i === 0);
    await setOutcome(page, prefix, 'reason', r.reason, i === 0);
    if (r.tip) await page.getByTestId(`rule-requires-${TIP}`).click();
    await page.getByTestId(`rule-requires-${CLEAR}`).click();
    if (r.source) {
      await page.getByTestId('rule-citation').pressSequentially(r.source, { delay: 5 });
      // the source is kept when the person just moves on, and the field is empty for the next rule
      if (i === 3) await page.getByTestId('rule-citation-add').click();
      else await page.getByTestId('rule-description').click();
      await expect(page.getByTestId('rule-citation-chip')).toHaveText(r.source);
      await expect(page.getByTestId('rule-citation')).toHaveValue('');
    }
    if (i === 1) {
      await expect(page.getByTestId('rule-sentence')).toContainText('is at least 0.5');
      await shot(page, '04-rule-typed-0.5');
    }
    await saved(page);
  }
  await expect(page.getByTestId('rule-sentence')).toContainText('reason = “”');
  await guideIs(page, 'try', /Add a golden test/, '2-try');

  // margin_m was guessed a number from its name, action and reason took text from their first values
  await page.getByTestId('tab-facts').click();
  await expect(page.getByTestId('outcome-type-margin_m')).toHaveValue('number');
  await expect(page.getByTestId('outcome-type-action')).toHaveValue('string');
  await expect(page.getByTestId('outcomes-table')).toContainText('Type');
  await expect(page.getByTestId(`fact-type-${TIP}`)).toHaveValue('number');
  await shot(page, '05-facts-and-outcomes');

  await page.getByTestId('tab-table').click();
  await expect(page.getByTestId(`table-1-${TIP}`)).toHaveValue('>= 0.5');
  await expect(page.getByTestId('table-4-out-reason')).toHaveValue('""');
  await page.getByTestId('table-columns').click();
  await page.getByTestId('table-col-sources').check();
  await page.getByTestId('table-columns').click();
  await expect(page.getByTestId('table-0-sources')).toHaveValue(SOURCE);
  await expect(page.getByTestId('table-4-sources')).toHaveValue('');
  await shot(page, '06-table-typed');

  const v = await api(page, tok, 'GET', `/api/decisions/${KEY}/versions/1`);
  const rules = v.json.data.authoring.rules;
  expect(rules.map((x: any) => x.key)).toEqual(RULES.map((x) => x.key));
  expect(rules[1].when.all[0]).toMatchObject({ fact: TIP, op: 'gte', value: 0.5 });
  expect(rules[0].then.margin_m).toEqual({ value: 4 });
  expect(rules[4].then.reason).toEqual({ value: '' });
  expect(rules[0].provenance.citations).toEqual([SOURCE]);
  expect(rules[3].provenance.citations).toEqual([RULES[3].source]);
  expect(rules[4].provenance?.citations ?? []).toEqual([]);
});

test('Try it takes 4.5 as typed and keeps cases as tests as of when they run', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  const panel = page.getByTestId('try-panel');
  await expect(panel.getByTestId(`try-fact-${TIP}`)).toHaveAttribute('placeholder', 'type a number');
  await expect(panel.getByTestId('try-result')).toContainText('Missing facts', { timeout: 15_000 });
  await expect(panel.getByTestId(`try-fact-${TIP}-flag`)).toHaveText('needed');
  await shot(page, '07-try-needed');
  for (const c of CASES) {
    for (const [fact, typed] of [[TIP, c.tip], [CLEAR, c.clear]] as const) {
      const f = panel.getByTestId(`try-fact-${fact}`);
      await f.fill('');
      await f.pressSequentially(typed, { delay: 40 });
      await expect(f).toHaveValue(typed);
    }
    await expect(panel.getByTestId('try-result')).toContainText('Decided', { timeout: 15_000 });
    await expect(panel.getByTestId('try-result-value')).toContainText(`"margin_m": ${c.expected.margin_m}`);
    await expect(panel.getByTestId('try-result-value')).toContainText(`"action": "${c.expected.action}"`);
    if (c.tip === '4.5') await shot(page, '08-try-4.5');
    await page.getByTestId('try-test-name').fill(c.name);
    await page.getByTestId('try-save-test').click();
    await expect(page.getByTestId('try-test-saved')).toContainText('as of the day the tests run');
  }
  await guideIs(page, 'check', /Run Check/, '3-check');
  const tests = await api(page, tok, 'GET', `/api/decisions/${KEY}/tests`);
  expect(tests.json.data).toHaveLength(4);
  for (const t of tests.json.data) expect(t.as_of).toBeNull();
  const fast = tests.json.data.find((t: any) => t.name === CASES[0].name);
  expect(fast.facts).toEqual({ machine: { tip_speed_ms: 4.5 }, worker: { clearance_m: 3 } });
});

test('Check shows its result once', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  await page.getByTestId('check').click();
  await expect(page.getByTestId('workspace-notice')).toContainText(/4 golden tests pass/, { timeout: 20_000 });
  await expect(page.getByTestId('validation-summary')).toHaveCount(0);
  await expect(page.getByText(/4 golden tests pass/)).toHaveCount(1);
  // one sentence says what the tier needs and that the only approver signs it
  await expect(page.getByTestId('signoff-summary')).toContainText('High risk needs one approver who did not write it. Nobody else here can approve, so you sign it yourself');
  await expect(page.getByTestId('signoff-summary')).not.toContainText("can't approve it");
  await shot(page, '09-check-once');
  await guideIs(page, 'signoff', /Ready\. Propose it for sign-off/, '4-propose');
});

test('lowering the risk tier waits for sign-off under the current tier', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  await page.getByTestId('decision-tier').selectOption('low');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Lower the risk tier from High to Low?');
  await expect(dialog).toContainText('needs the sign-off the High tier asks for');
  await expect(page.getByTestId('tier-confirm')).toBeDisabled();
  await page.getByTestId('tier-reason').fill('The zone sensors now stop the machine on their own.');
  await expect(page.getByTestId('tier-confirm')).toBeEnabled();
  await page.waitForTimeout(300);
  await shot(page, '10-tier-lower-dialog');
  await page.getByTestId('tier-confirm').click();
  await expect(page.getByTestId('pending-tier-change')).toContainText('from High to Low is waiting for sign-off');
  await expect(page.getByTestId('decision-tier')).toHaveValue('high');
  await expect(page.getByTestId('workspace-notice')).toContainText('Sent for sign-off');
  await shot(page, '11-tier-pending');
  const m = await api(page, tok, 'GET', `/api/decisions/${KEY}`);
  expect(m.json.data.risk_tier).toBe('high');
  expect(m.json.data.pending_tier_change).toMatchObject({ from_tier: 'high', to_tier: 'low' });
  await page.getByTestId('tier-change-withdraw').click();
  await expect(page.getByTestId('pending-tier-change')).toHaveCount(0);
});

test('propose locks the risk tier and the only approver signs it with a reason', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  await page.getByTestId('propose').click();
  await expect(page.getByTestId('workspace-notice')).toContainText('Sent for sign-off', { timeout: 20_000 });
  await expect(page.getByTestId('decision-tier')).toBeDisabled();
  await expect(page.getByTestId('tier-lock-note')).toContainText('waits for sign-off');
  await expect(page.getByTestId('decision-tier-wrap')).toHaveAttribute('title', /Withdraw it or let it finish/);
  await expect(page.getByTestId('sole-open')).toBeVisible();
  await shot(page, '12-proposed-tier-locked');
  await guideIs(page, 'signoff', /Nobody else can approve this/, '5-sole');

  await openFromSidebar(page, '/approvals');
  const card = page.getByTestId('approval-card').filter({ hasText: NAME }).first();
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card.getByTestId('approval-author-note')).toContainText("you can't approve it yourself");
  await expect(card.getByTestId('approval-approve')).toHaveCount(0);
  await shot(page, '13-approvals-as-author');
  await card.getByTestId('approval-sole-open').click();
  const dlg = page.getByTestId('sole-dialog');
  await expect(dlg).toContainText('recorded as self-approved');
  await page.getByTestId('sole-reason').fill('too short');
  await expect(page.getByTestId('sole-approve')).toBeDisabled();
  await page.getByTestId('sole-reason').fill('Checked all five rules against the site safety plan and the four golden cases.');
  await expect(page.getByTestId('sole-approve')).toBeDisabled();
  await page.getByTestId('sole-confirm-check').check();
  await shot(page, '14-sole-dialog');
  await page.getByTestId('sole-approve').click();
  await expect(dlg).toHaveCount(0);
  const done = page.locator('[data-testid="approval-card"][data-status="approved"]').filter({ hasText: NAME }).first();
  await expect(done).toBeVisible({ timeout: 20_000 });
  await expect(done.getByTestId('self-approved')).toBeVisible();
  await shot(page, '15-approvals-self-approved');
});

test('publish, then it decides like gw.safety.exclusion', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  await expect(page.getByTestId('version-picker')).toContainText('Approved');
  await guideIs(page, 'publish', /Publish it to make it the version/, '6-publish');
  await page.getByTestId('publish').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Publish' }).click();
  await expect(page.getByTestId('workspace-notice')).toContainText('is now in force', { timeout: 20_000 });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByTestId('self-approved')).toBeVisible();
  await guideIs(page, 'publish', /is in force/, '7-published');
  await shot(page, '16-published-self-approved');
  await page.getByTestId('tab-history').click();
  await expect(page.getByTestId('history-tab').getByTestId('self-approved')).toBeVisible();

  // read-only once published: no editing controls, and a way to start a new draft
  await page.getByTestId('tab-rules').click();
  await expect(page.getByTestId('rule-editor')).toHaveAttribute('data-readonly', 'true');
  await expect(page.getByTestId('rule0-g-add')).toHaveCount(0);
  await expect(page.getByTestId('rule0-then-action-clear')).toHaveCount(0);
  await expect(page.getByTestId('hit-policy')).toHaveCount(0);
  await expect(page.getByTestId('readonly-new-draft')).toBeVisible();
  await shot(page, '17-published-read-only');

  let gwTok: string | null = null;
  try { gwTok = await tokenFor(page, ADMIN); } catch { gwTok = null; }
  const gwThere = gwTok ? (await api(page, gwTok, 'GET', '/api/decisions/gw.safety.exclusion')).status === 200 : false;
  for (const c of CASES) {
    const facts = { machine: { tip_speed_ms: Number(c.tip) }, worker: { clearance_m: Number(c.clear) } };
    const mine = await api(page, tok, 'POST', `/api/decisions/${KEY}/evaluate`, { facts });
    expect(mine.json.data.outcome, c.name).toBe('decided');
    expect(mine.json.data.result, c.name).toMatchObject(c.expected);
    if (gwThere) {
      const theirs = await api(page, gwTok!, 'POST', '/api/decisions/gw.safety.exclusion/evaluate', { facts });
      const pick = (r: any) => ({ action: r.action, margin_m: r.margin_m, reason: r.reason });
      expect(pick(mine.json.data.result), `${c.name} matches gw.safety.exclusion`).toEqual(pick(theirs.json.data.result));
    }
  }
});

test('paste from Excel into an empty decision makes the facts, outcomes and rules', async ({ page }) => {
  await login(page);
  await visit(page, '/decisions');
  await page.getByTestId('decision-new').click();
  await page.getByTestId('decision-name').fill(`Pasted zones ${RUN}`);
  await page.getByTestId('decision-key').fill(PASTE_KEY);
  await expect(page.getByTestId('decision-key-help')).toContainText('Free to use', { timeout: 10_000 });
  await page.getByTestId('decision-create').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${PASTE_KEY.replace(/\./g, '\\.')}`));
  await page.getByTestId('tab-table').click();
  await expect(page.getByTestId('paste-first')).toBeVisible();
  await page.getByTestId('paste-first-text').fill(PASTE);
  await expect(page.getByTestId('paste-preview')).toContainText('5 rows found, with a header row');
  await expect(page.getByTestId('paste-first-apply')).toContainText('5 rules, 2 new facts, 3 new outcomes');
  await shot(page, '18-paste-preview');
  await page.getByTestId('paste-first-apply').click();
  await expect(page.getByTestId('table-row-4')).toBeVisible();
  await expect(page.getByTestId('table-paste-msg')).toContainText('Added 5 rules');
  await saved(page);
  await expect(page.getByTestId(`table-1-${TIP}`)).toHaveValue('>= 0.5');
  await expect(page.getByTestId('table-4-out-reason')).toHaveValue('""');
  await shot(page, '19-pasted-table');
  const panel = page.getByTestId('try-panel');
  await panel.getByTestId(`try-fact-${TIP}`).pressSequentially('4.5', { delay: 40 });
  await panel.getByTestId(`try-fact-${CLEAR}`).pressSequentially('3', { delay: 40 });
  await expect(panel.getByTestId('try-result-value')).toContainText('"margin_m": 4', { timeout: 15_000 });
  const v = await api(page, tok, 'GET', `/api/decisions/${PASTE_KEY}/versions/1`);
  const doc = v.json.data.authoring;
  expect(doc.outputs.find((o: any) => o.field === 'margin_m').type).toBe('number');
  expect(doc.facts.find((f: any) => f.path === TIP).type).toBe('number');
  expect(doc.rules[1].when.all[0]).toMatchObject({ op: 'gte', value: 0.5 });
});

test('export the full decision and import it, and import Groundwork\u2019s own file', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  await page.getByTestId('export').click();
  const dl = page.waitForEvent('download');
  await page.getByTestId('export-full').click();
  const file = path.join(SHOTS, `${KEY}.json`);
  fs.mkdirSync(SHOTS, { recursive: true });
  await (await dl).saveAs(file);
  const exported = JSON.parse(fs.readFileSync(file, 'utf8'));
  expect(exported.format).toBe('abenix-decision-v1');
  expect(exported.tests).toHaveLength(4);

  await visit(page, '/decisions');
  await page.getByTestId('decision-import').click();
  await page.getByTestId('import-decision-file').setInputFiles(file);
  // the key is taken, so it defaults to a new decision under a free key and a new name
  await expect(page.getByTestId('import-target')).toContainText('already exists', { timeout: 15_000 });
  await expect(page.getByTestId('import-as-new')).toBeChecked();
  await expect(page.getByTestId('import-as-key')).not.toHaveValue('');
  await page.getByTestId('import-as-key').fill(COPY_KEY);
  await page.getByTestId('import-as-name').fill(`Copy of ${NAME}`);
  await expect(page.getByTestId('import-decision-preview')).toContainText(`Creates a new decision ${COPY_KEY} called Copy of ${NAME}`, { timeout: 15_000 });
  await expect(page.getByTestId('import-decision-preview')).toContainText('5 rules and 4 golden tests');
  await shot(page, '20-import-preview');
  await page.getByTestId('import-decision-go').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${COPY_KEY.replace(/\./g, '\\.')}`), { timeout: 20_000 });
  await expect(page.getByTestId('version-picker')).toContainText('Draft');

  // the same file again as a draft of the original: it matches, so nothing is offered
  await visit(page, '/decisions');
  await page.getByTestId('decision-import').click();
  await page.getByTestId('import-decision-file').setInputFiles(file);
  await expect(page.getByTestId('import-target')).toBeVisible({ timeout: 15_000 });

  test.skip(!fs.existsSync(GW_FILE), `no Groundwork file at ${GW_FILE}`);
  await visit(page, '/decisions');
  await page.getByTestId('decision-import').click();
  await page.getByTestId('import-decision-json').fill(fs.readFileSync(GW_FILE, 'utf8'));
  await expect(page.getByTestId('import-decision-preview')).toContainText('5 rules and 4 golden tests', { timeout: 15_000 });
  await expect(page.getByTestId('import-decision-preview')).toContainText(`Creates a new decision ${GW_KEY}`);
  await page.getByTestId('import-decision-go').click();
  await expect(page).toHaveURL(new RegExp(`/decisions/${GW_KEY.replace(/\./g, '\\.')}`), { timeout: 20_000 });
  const m = await api(page, tok, 'GET', `/api/decisions/${GW_KEY}`);
  expect(m.json.data.risk_tier).toBe('high');
  expect(m.json.data.test_count).toBe(4);
});

test('retire the version in force, then archive and restore the decision', async ({ page }) => {
  await login(page);
  await visit(page, `/decisions/${KEY}`);
  // at high risk switching it off needs a second person too, the only approver signs it in the same step
  await page.getByTestId('retire').click();
  await expect(page.getByRole('dialog')).toContainText('no version is in force');
  await expect(page.getByRole('dialog')).toContainText('you are the only person here who can. You sign it yourself in this step');
  await expect(page.getByTestId('retire-confirm')).toHaveText(/Sign it myself and retire/);
  await expect(page.getByTestId('retire-confirm')).toBeDisabled();
  await page.getByTestId('retire-reason').fill('The site moved to the new exclusion rules.');
  await expect(page.getByTestId('retire-confirm'), 'the self-approval tick is still needed').toBeDisabled();
  await page.getByTestId('retire-sole-sure').check();
  await page.waitForTimeout(400);
  await shot(page, '21-retire-confirm');
  await page.getByTestId('retire-confirm').click();
  await expect(page.getByTestId('workspace-notice')).toContainText('recorded as self-approved', { timeout: 20_000 });
  await expect(page.getByTestId('version-picker')).toContainText('Retired', { timeout: 20_000 });

  await page.getByTestId('archive').click();
  await expect(page.getByRole('dialog')).toContainText('can be restored from the list');
  await page.getByTestId('archive-reason').fill('Retired and replaced, keep it out of the list.');
  await page.getByTestId('archive-sole-sure').check();
  await page.getByTestId('archive-confirm').click();
  await expect(page).toHaveURL(/\/decisions(\?|$)/, { timeout: 20_000 });
  await expect(page.getByTestId('decisions-notice')).toContainText(`Archived ${KEY}`);
  await expect(page.getByTestId('decisions-undo-archive')).toHaveText('Undo, ask to restore it');
  await expect(page.getByTestId(`decision-row-${KEY}`)).toHaveCount(0);

  // a search finds it among the archived ones
  await page.getByLabel('Search decisions').fill('by hand');
  await expect(page.getByTestId('archived-matches')).toContainText('1 archived decision matches');
  await page.getByTestId('archived-matches-show').click();
  const row = page.getByTestId(`decision-archived-${KEY}`);
  await expect(row).toBeVisible({ timeout: 15_000 });
  await shot(page, '22-archived-list');
  await row.getByTestId(`decision-restore-${KEY}`).click();
  await page.getByTestId('restore-reason').fill('Needed again for the audit replay.');
  await page.getByTestId('restore-confirm').click();
  // nobody else here can approve, so step 2 opens straight away with the same reason
  await expect(page.getByTestId('decisions-notice')).toContainText('Step 1 of 2 done');
  const step2 = page.getByTestId('sole-dialog');
  await expect(step2).toContainText('Step 2 of 2');
  await expect(page.getByTestId('sole-reason')).toHaveValue('Needed again for the audit replay.');
  await page.waitForTimeout(400);
  await shot(page, '22a-restore-step-2');
  await page.getByTestId('sole-confirm-check').check();
  await page.getByTestId('sole-approve').click();
  await expect(step2).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId('decisions-notice')).toContainText('recorded as self-approved');
  await visit(page, '/decisions');
  // its only version was retired, so the card says nothing is in force rather than pretending
  await expect(page.getByTestId(`decision-row-${KEY}`).getByTestId('chip-retired')).toBeVisible({ timeout: 20_000 });
  await shot(page, '22b-restored-retired');
});

test('with a teammate who can sign: the author is told who can, the reviewer approves the publish, a lowering and the review after a raise', async ({ browser }) => {
  test.skip(!fs.existsSync(GW_FILE), `no Groundwork file at ${GW_FILE}`);
  test.setTimeout(10 * 60_000);
  const actx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const admin = await actx.newPage();
  const atok = await login(admin, ADMIN);

  // invite a reviewer from Team, they accept and set a password
  await visit(admin, '/settings/team');
  await admin.getByRole('button', { name: 'Invite Member' }).click();
  await admin.locator('input[placeholder="email@example.com"]').fill(REVIEWER.email);
  // a Member, and the box that would let them approve is left unticked, as a newcomer might
  await expect(admin.getByTestId('invite-can-approve')).not.toBeChecked();
  await shot(admin, '25-invite-can-approve');
  await admin.getByRole('button', { name: 'Send' }).click();
  const token = (await admin.getByTestId('invite-link').innerText({ timeout: 20_000 })).match(/token=([^\s&]+)/)?.[1];
  expect(token, 'the invite link carries a token').toBeTruthy();
  const rctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const reviewer = await rctx.newPage();
  await visit(reviewer, `/auth/accept-invite?token=${token}`);
  await reviewer.locator('#accept-full-name').fill(REVIEWER.name);
  await reviewer.locator('#accept-password').fill(REVIEWER.password);
  await reviewer.getByTestId('accept-submit').click();
  await reviewer.waitForURL(/\/dashboard/, { timeout: 30_000 });

  // the author brings in Groundwork's rules under a new key
  await visit(admin, '/decisions');
  await admin.getByTestId('decision-import').click();
  await admin.getByTestId('import-decision-json').fill(fs.readFileSync(GW_FILE, 'utf8'));
  await expect(admin.getByTestId('import-as-new')).toBeChecked({ timeout: 15_000 });
  await admin.getByTestId('import-as-key').fill(TWO_KEY);
  await admin.getByTestId('import-as-name').fill(`Two-person exclusion zones ${RUN}`);
  await expect(admin.getByTestId('import-decision-preview')).toContainText(`Creates a new decision ${TWO_KEY}`, { timeout: 15_000 });
  await admin.getByTestId('import-decision-go').click();
  await expect(admin).toHaveURL(new RegExp(`/decisions/${TWO_KEY.replace(/\./g, '\\.')}`), { timeout: 20_000 });
  await expect(admin.getByTestId('signoff-approvers')).toContainText('can approve', { timeout: 15_000 });
  await expect(admin.getByTestId('signoff-summary')).toContainText("can't approve it");
  await admin.getByTestId('check').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText(/4 golden tests pass/, { timeout: 20_000 });
  await admin.getByTestId('propose').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText('Sent for sign-off', { timeout: 20_000 });
  await expect(admin.getByTestId('sole-open')).toHaveCount(0);
  await guideIs(admin, 'signoff', /Waiting for/, '8-waiting-for-reviewer');

  // the author sees why they can't approve and who can, and no button that would fail
  const cardFor = (pg: Page, status: string) => pg.locator(`[data-testid="approval-card"][data-status="${status}"]`).filter({ has: pg.locator(`a[href*="${TWO_KEY}"]`) }).first();
  await visit(admin, '/approvals');
  const own = cardFor(admin, 'pending');
  await expect(own).toBeVisible({ timeout: 30_000 });
  await expect(own.getByTestId('approval-author-note')).toContainText("you can't approve it yourself");
  await expect(own.getByTestId('approval-who-can')).toBeVisible();
  await expect(own.getByTestId('approval-approve')).toHaveCount(0);
  await expect(own.getByTestId('approval-sole-open')).toHaveCount(0);
  await shot(admin, '23-author-told-who-can');

  // the new Member can't sign yet, and Approvals doesn't offer them a button that would fail
  await visit(reviewer, '/approvals');
  await expect(cardFor(reviewer, 'pending')).toHaveCount(0);

  // Team shows who can approve, and the row menu turns it on and off
  await visit(admin, '/settings/team');
  const row = admin.getByTestId(`member-${REVIEWER.email}`);
  await expect(row.getByTestId('member-approver')).toHaveCount(0);
  await row.getByRole('button', { name: `Actions for ${REVIEWER.email}` }).click();
  await expect(row.getByTestId('member-approver-toggle')).toHaveText('Let them approve decisions');
  await shot(admin, '29-team-approver-menu');
  await row.getByTestId('member-approver-toggle').click();
  await expect(row.getByTestId('member-approver')).toContainText('Can approve decisions', { timeout: 15_000 });
  await shot(admin, '30-team-approver-badge');
  await row.getByRole('button', { name: `Actions for ${REVIEWER.email}` }).click();
  await expect(row.getByTestId('member-approver-toggle')).toHaveText('Stop them approving decisions');
  await row.getByTestId('member-approver-toggle').click();
  await expect(row.getByTestId('member-approver')).toHaveCount(0, { timeout: 15_000 });
  // the admin gives them Review decisions from the decision page
  await visit(admin, `/decisions/${TWO_KEY}`);
  await admin.getByTestId('someone-missing').click();
  await admin.getByTestId('someone-missing-pick').selectOption({ label: `${REVIEWER.name} (${REVIEWER.email})` });
  await shot(admin, '26-someone-missing');
  await admin.getByTestId('someone-missing-give').click();
  await expect(admin.getByTestId('someone-missing-msg')).toContainText('can now approve decisions');
  const so = await api(admin, atok, 'GET', `/api/decisions/${TWO_KEY}/versions/1/sign-off`);
  expect(so.json.data.eligible_approvers.map((x: any) => x.email)).toContain(REVIEWER.email);

  // the reviewer is told they can approve, approves, and the author publishes
  await visit(reviewer, `/decisions/${TWO_KEY}`);
  await guideIs(reviewer, 'signoff', /You can approve this/, '9-reviewer');
  await visit(reviewer, '/approvals');
  await cardFor(reviewer, 'pending').getByTestId('approval-approve').click();
  await expect(cardFor(reviewer, 'approved')).toBeVisible({ timeout: 20_000 });
  await visit(admin, `/decisions/${TWO_KEY}`);
  await admin.getByTestId('publish').click();
  await admin.getByRole('dialog').getByRole('button', { name: 'Publish' }).click();
  await expect(admin.getByTestId('workspace-notice')).toContainText('is now in force', { timeout: 20_000 });
  await expect(admin.getByTestId('lifecycle-bar')).toContainText(`Approved by ${REVIEWER.name}`);

  // lowering waits for the reviewer, then applies
  await admin.getByTestId('decision-tier').selectOption('low');
  await admin.getByTestId('tier-reason').fill('Sensors now stop the machine on their own, reviewed with the site manager.');
  await admin.getByTestId('tier-confirm').click();
  await expect(admin.getByTestId('pending-tier-change')).toContainText('waiting for sign-off');
  await expect(admin.getByTestId('tier-change-sole')).toHaveCount(0);
  await visit(reviewer, '/approvals');
  const tierCard = reviewer.locator('[data-testid="approval-card"][data-status="pending"]').filter({ hasText: TWO_KEY }).filter({ has: reviewer.getByTestId('approval-tier-change') }).first();
  await expect(tierCard.getByTestId('approval-because')).toContainText('Asked because: “Sensors now stop the machine');
  await expect(tierCard.getByTestId('approval-requester')).toContainText('Asked by');
  await tierCard.getByTestId('approval-approve').click();
  await expect(reviewer.locator('[data-testid="approval-card"][data-status="approved"]').filter({ hasText: TWO_KEY }).filter({ has: reviewer.getByTestId('approval-tier-change') }).first()).toBeVisible({ timeout: 20_000 });
  await visit(admin, `/decisions/${TWO_KEY}`);
  await expect(admin.getByTestId('decision-tier')).toHaveValue('low', { timeout: 20_000 });
  await expect(admin.getByTestId('pending-tier-change')).toHaveCount(0);

  // a version published at low, then the tier raised: the version in force needs a high-risk review
  await admin.getByTestId('new-draft').click();
  await expect(admin.getByTestId('version-picker')).toContainText('Version 2');
  await admin.getByTestId('propose').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText('Approved', { timeout: 20_000 });
  await admin.getByTestId('publish').click();
  await admin.getByRole('dialog').getByRole('button', { name: 'Publish' }).click();
  await expect(admin.getByTestId('workspace-notice')).toContainText('is now in force', { timeout: 20_000 });
  await expect(admin.getByRole('dialog')).toHaveCount(0);
  await admin.getByTestId('decision-tier').selectOption('high');
  await expect(admin.getByRole('dialog')).toContainText('Raise the risk tier from Low to High?');
  await admin.getByTestId('tier-confirm').click();
  await expect(admin.getByTestId('decision-tier')).toHaveValue('high', { timeout: 20_000 });
  const m = await api(admin, atok, 'GET', `/api/decisions/${TWO_KEY}`);
  if (m.json.data.reattest === undefined) {
    test.info().annotations.push({ type: 'not yet', description: 'the API has no reattest field yet, the review after a raise was not checked' });
  } else {
    await expect(admin.getByTestId('reattest-notice')).toContainText('Version 2 is in force but was approved under Low risk. It needs a High-risk review.');
    await shot(admin, '24-reattest-notice');
    await guideIs(admin, 'signoff', /needs a High-risk review/, '10-review-after-raise');
    await visit(reviewer, '/approvals');
    const review = reviewer.locator('[data-testid="approval-card"][data-status="pending"]').filter({ has: reviewer.getByTestId('approval-reattest') }).filter({ hasText: TWO_KEY }).first();
    await review.getByTestId('approval-approve').click();
    await visit(admin, `/decisions/${TWO_KEY}`);
    await expect(admin.getByTestId('reattest-notice')).toHaveCount(0, { timeout: 20_000 });
  }
  // archiving it at high risk waits for the reviewer, who first sends one request back with Deny and a reason
  await visit(admin, `/decisions/${TWO_KEY}`);
  await admin.getByTestId('archive').click();
  await admin.getByTestId('archive-reason').fill('End of the two-person UAT run.');
  await admin.getByTestId('archive-confirm').click();
  await expect(admin.getByTestId('pending-action')).toContainText('waiting for sign-off');
  const inboxRow = (pg: Page) => pg.locator('[data-testid="inbox-approval"][data-kind="decision_archive"]').filter({ hasText: TWO_KEY }).first();
  await visit(reviewer, '/inbox?tab=approvals');
  const arch = inboxRow(reviewer);
  await expect(arch).toBeVisible({ timeout: 30_000 });
  await expect(arch.getByTestId('inbox-kind')).toHaveText('Archive a decision');
  await expect(arch.getByTestId('inbox-why')).toContainText('End of the two-person UAT run.');
  await expect(arch.getByTestId('inbox-requester')).toContainText('Asked by');
  await expect(arch.getByTestId('inbox-evidence')).toHaveAttribute('href', new RegExp(TWO_KEY.replace(/\./g, '\\.')));
  await shot(reviewer, '31-needs-you-archive-row');
  await arch.getByTestId('inbox-deny').click();
  await expect(reviewer.getByTestId('deny-dialog-confirm')).toBeDisabled();
  await reviewer.getByTestId('deny-dialog-reason').fill('Keep it until the site audit is over.');
  await shot(reviewer, '27-deny-with-reason');
  const sent = reviewer.waitForRequest((r) => r.url().includes('/signoff') && r.method() === 'POST');
  await reviewer.getByTestId('deny-dialog-confirm').click();
  expect((await sent).postDataJSON(), 'the reason typed in Needs you reaches the server').toMatchObject({ decision: 'deny', reason: 'Keep it until the site audit is over.' });
  await expect(reviewer.getByTestId('deny-dialog')).toHaveCount(0, { timeout: 20_000 });
  await expect(inboxRow(reviewer)).toHaveCount(0, { timeout: 20_000 });
  await visit(admin, `/decisions/${TWO_KEY}`);
  await expect(admin.getByTestId('last-denial')).toContainText('Keep it until the site audit is over.', { timeout: 20_000 });
  await shot(admin, '28-denial-shown');
  // the author's Approvals leads the denied card with the reviewer's words
  await visit(admin, '/approvals');
  const denied = admin.locator('[data-testid="approval-card"][data-status="denied"]').filter({ hasText: TWO_KEY }).filter({ has: admin.getByTestId('approval-lifecycle') }).first();
  await expect(denied.getByTestId('approval-refusal')).toContainText(`Denied by ${REVIEWER.name}: “Keep it until the site audit is over.”`, { timeout: 20_000 });
  await expect(denied.getByTestId('approval-because')).toContainText('Asked because: “End of the two-person UAT run.”');
  await expect(denied).not.toContainText('Signed off under the current tier');
  await denied.scrollIntoViewIfNeeded();
  await shot(admin, '32-author-sees-denial');
  await visit(admin, `/decisions/${TWO_KEY}`);
  await admin.getByTestId('archive').click();
  await admin.getByTestId('archive-reason').fill('The audit is over, archive it now.');
  await admin.getByTestId('archive-confirm').click();
  await expect(admin.getByTestId('pending-action')).toContainText('waiting for sign-off');
  // the author's own request sits apart from what they can sign
  await visit(admin, '/approvals');
  await expect(admin.getByTestId('approvals-yours').locator('[data-testid="approval-card"]').filter({ hasText: TWO_KEY }).first()).toBeVisible({ timeout: 20_000 });
  await expect(admin.getByTestId('approvals-tab-pending')).toContainText(/yours/);
  await admin.getByTestId('approvals-yours').scrollIntoViewIfNeeded();
  await shot(admin, '33-approvals-yours');
  // approving takes a high-risk rule out of service, so Needs you asks first
  await visit(reviewer, '/inbox?tab=approvals');
  await inboxRow(reviewer).getByTestId('inbox-approve').click();
  await expect(reviewer.getByRole('dialog')).toContainText('stops answering at once');
  // let the dialog finish fading in before the picture
  await reviewer.waitForTimeout(400);
  await shot(reviewer, '34-needs-you-approve-confirm');
  await reviewer.getByTestId('inbox-approve-confirm').click();
  await expect(inboxRow(reviewer)).toHaveCount(0, { timeout: 20_000 });
  expect((await api(admin, atok, 'GET', `/api/decisions/${TWO_KEY}`)).status).toBe(404);
  await rctx.close();
  await actx.close();
});

// the one-person workspace is made for this run, so what is left in it is left with it
test.afterAll(async ({ browser }) => {
  const p = await browser.newPage();
  await api(p, tok, 'DELETE', `/api/decisions/${PASTE_KEY}`);
  await p.close();
});
