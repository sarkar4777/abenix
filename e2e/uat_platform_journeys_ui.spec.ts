/**
 * Seven things people do with the platform, each done through the screens only.
 *
 *   1. Sign up     a new person registers on the landing page, builds and runs a first agent
 *   2. Approvals   a teammate is invited, a high tier decision needs them, the author cannot sign their own
 *   3. Knowledge   a document goes into a knowledge base, the agent answers from it and admits what it does not know
 *   4. Approve     an agent pauses on human_approval, one run is approved and one denied on /approvals
 *   5. Triggers    a webhook fired by an outside system and a schedule run now both produce real runs
 *   6. Moderation  a policy with a custom pattern blocks a chat message, then the default policy comes back
 *   7. Budget      the builder's daily budget lands where the platform enforces it
 *
 * The API is only used to read state back for assertions, to play the outside
 * system that fires a webhook, and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_platform_journeys_ui.spec.ts --workers=1
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { test, expect, type Browser, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const REVIEWER = { email: `reviewer-${RUN}@example.com`, name: `Rita Reviewer ${RUN}`, password: 'Reviewer123!' };
const NEWCOMER = { email: `newcomer-${RUN}@example.com`, name: `Nina Newcomer ${RUN}`, password: 'Newcomer123!' };
const KEY = `refunds.review.${RUN}`;
const DECISION = `Refund review ${RUN}`;
const KB = `Supplier handbook ${RUN}`;
const KB_AGENT = `Supplier Desk ${RUN}`;
const HITL_AGENT = `Refund Desk ${RUN}`;
const ECHO_AGENT = `Order Echo ${RUN}`;
const POLICY = `Block account numbers ${RUN}`;

const ids: { kbAgent?: string; hitlAgent?: string; echoAgent?: string; kb?: string; newcomerAgent?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function signIn(page: Page, who: { email: string; password: string }) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function freshPage(browser: Browser, who?: { email: string; password: string }) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.accept());
  if (who) await signIn(page, who);
  return page;
}

// read-only lookups for assertions, and cleanup
async function api(page: Page, method: string, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function chat(page: Page, message: string, timeoutMs = 300_000) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  const err = page.getByTestId('chat-error');
  if (await err.count()) return { text: '', error: await err.innerText() };
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 });
  return { text: await replies.nth(before).innerText(), error: '' };
}

async function openLastRun(page: Page) {
  const viewRun = page.getByTestId('chat-view-run').last();
  await expect(viewRun).toBeVisible({ timeout: 20_000 });
  await viewRun.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
}

async function expand(scope: ReturnType<Page['locator']>, title: string) {
  const btn = scope.getByRole('button', { name: new RegExp(`^${title}`) }).first();
  if ((await btn.getAttribute('aria-expanded')) !== 'true') await btn.click();
  return btn.locator('xpath=..');
}

async function addTool(page: Page, id: string) {
  const search = page.getByPlaceholder('Search tools, descriptions, params...');
  await search.fill(id);
  await page.getByTestId(`palette-tool-${id}`).first().click();
  await search.fill('');
  await expect(page.locator(`.react-flow__node[data-id="tool-${id}"]`)).toBeVisible();
}

async function buildAgent(page: Page, name: string, description: string, prompt: string, tools: string[] = []) {
  if (!page.url().includes('/builder')) await go(page, '/builder');
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill(description);
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(prompt);
  for (const t of tools) await addTool(page, t);
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  const id = new URL(page.url()).searchParams.get('agent') || '';
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
  expect(id).toBeTruthy();
  return id;
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

function approvalCard(page: Page, text: string) {
  return page.getByTestId('approval-card').filter({ hasText: text }).first();
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
});

test('a new person signs up on the landing page and runs a first agent in their own workspace', async ({ browser }) => {
  test.setTimeout(6 * 60_000);
  const page = await freshPage(browser);
  await go(page, '/');
  await page.getByRole('button', { name: 'Switch to register' }).click();
  await page.locator('#auth-full-name').fill(NEWCOMER.name);
  await page.locator('#auth-email').fill(NEWCOMER.email);
  // a short password is refused before the form is sent
  await page.locator('#auth-password').fill('short');
  await page.getByTestId('auth-submit').click();
  await expect(page).toHaveURL(new RegExp(`^${BASE}/?(\\?.*)?$`));
  await page.locator('#auth-password').fill(NEWCOMER.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });

  // a fresh workspace, nothing from other teams is visible
  await go(page, '/agents');
  await expect(page.locator('main')).not.toContainText(KB_AGENT);
  await go(page, '/builder');
  ids.newcomerAgent = await buildAgent(
    page,
    `First Agent ${RUN}`,
    'Turns a product idea into a one line pitch.',
    'You write one line product pitches. Reply with a single sentence that starts with "Pitch:".',
  );
  const reply = await chat(page, 'A reusable coffee cup that tracks how much you drink.');
  expect(reply.error).toBe('');
  expect(reply.text).toMatch(/Pitch:/);
  await page.context().close();
});

test('a reviewer is invited, the author cannot sign their own high tier decision, the reviewer returns then approves it', async ({ browser }) => {
  test.setTimeout(10 * 60_000);
  const admin = await freshPage(browser, ADMIN);

  // invite a second admin from the team page
  await go(admin, '/settings/team');
  await admin.getByRole('button', { name: 'Invite Member' }).click();
  await admin.locator('input[placeholder="email@example.com"]').fill(REVIEWER.email);
  await admin.locator('select').filter({ has: admin.locator('option[value="creator"]') }).first().selectOption('admin');
  await admin.getByRole('button', { name: 'Send' }).click();
  const linkText = await admin.getByTestId('invite-link').innerText({ timeout: 20_000 });
  const token = linkText.match(/token=([^\s&]+)/)?.[1];
  expect(token, 'the invite link carries a token').toBeTruthy();

  const reviewer = await freshPage(browser);
  await go(reviewer, `/auth/accept-invite?token=${token}`);
  await expect(reviewer.locator('#accept-email')).toHaveValue(REVIEWER.email, { timeout: 20_000 });
  await reviewer.locator('#accept-full-name').fill(REVIEWER.name);
  await reviewer.locator('#accept-password').fill(REVIEWER.password);
  await reviewer.getByTestId('accept-submit').click();
  await reviewer.waitForURL(/\/dashboard/, { timeout: 30_000 });

  // the author builds a high tier decision
  await go(admin, '/decisions');
  await admin.getByTestId('decision-new').or(admin.getByTestId('decision-start-blank')).first().click();
  await admin.getByTestId('decision-name').fill(DECISION);
  await admin.getByTestId('decision-key').fill(KEY);
  await admin.getByRole('radiogroup', { name: 'Risk tier' }).getByRole('radio', { name: /high/i }).click();
  await admin.getByTestId('decision-create').click();
  await expect(admin).toHaveURL(new RegExp(`/decisions/${KEY.replace(/\./g, '\\.')}`));
  await expect(admin.getByTestId('decision-tier')).toHaveValue('high');

  await admin.getByTestId('rule-add-first').click();
  await admin.getByTestId('rule-key').fill('refund.manual');
  await admin.getByTestId('rule-description').fill('Refunds above 1000 EUR are reviewed by a person');
  await addFactCondition(admin, 'rule0', '0', 'refund.amountEur', 'number');
  await admin.getByTestId('rule0-c0-op').selectOption('gt');
  await admin.getByTestId('rule0-c0-value').fill('1000');
  await admin.getByTestId('rule0-new-outcome').fill('review');
  await admin.getByTestId('rule0-add-outcome').click();
  await admin.getByTestId('rule0-then-review-value').fill('MANUAL');
  await admin.getByTestId('rule-citation').fill('Refund policy, section 2');
  await admin.getByTestId('rule-citation').press('Enter');
  await saved(admin);
  await admin.getByTestId('rule-add').click();
  await admin.getByTestId('rule-key').fill('refund.auto');
  await admin.getByTestId('rule-description').fill('Everything else refunds automatically');
  await admin.getByTestId('rule1-then-review-set').click();
  await admin.getByTestId('rule1-then-review-value').fill('AUTO');
  await admin.getByTestId('rule-citation').fill('Refund policy, section 1');
  await admin.getByTestId('rule-citation').press('Enter');
  await admin.getByTestId('version-valid-from').fill('2026-01-01');
  await saved(admin);

  const panel = admin.getByTestId('try-panel');
  await panel.getByTestId('try-fact-refund.amountEur').fill('2500');
  await expect(panel.getByTestId('try-result-value')).toContainText('MANUAL', { timeout: 15_000 });
  await admin.getByTestId('try-test-name').fill('Large refund goes to a person');
  await admin.getByTestId('try-save-test').click();
  await expect(panel).toContainText('Saved as a golden test');

  await admin.getByTestId('check').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText(/Ready/);
  await admin.getByTestId('propose').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText(/Sent for sign-off\. 1 approval is needed/);

  // the author's own approval is refused
  await go(admin, '/approvals');
  const own = approvalCard(admin, DECISION);
  await expect(own).toBeVisible({ timeout: 30_000 });
  await own.getByRole('button', { name: 'Approve' }).click();
  await expect(own.getByTestId('approval-error')).toContainText(/someone else/i);
  await expect(own).toHaveAttribute('data-status', 'pending');

  // the reviewer returns it with a reason
  await go(reviewer, '/approvals');
  const card = approvalCard(reviewer, DECISION);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole('button', { name: /Payload, signoff history/ }).click();
  await card.getByPlaceholder('Why are you approving, denying or returning it?').fill('Cite the refund policy version in rule 1 as well.');
  await card.getByTestId('approval-return').click();
  await expect(approvalCard(reviewer, DECISION)).toHaveAttribute('data-status', /returned/, { timeout: 20_000 });

  // the author sees why, proposes again, and the reviewer approves
  await go(admin, `/decisions/${KEY}`);
  const note = admin.getByTestId('returned-note');
  await expect(note).toContainText('Cite the refund policy version', { timeout: 20_000 });
  // the note stays while the author works on it, and goes once it is proposed again
  await admin.getByTestId('rule-card-1').click();
  await admin.getByTestId('rule-citation').fill('Refund policy v3, section 1');
  await admin.getByTestId('rule-citation').press('Enter');
  await saved(admin);
  await admin.reload();
  await expect(admin.getByTestId('returned-note')).toBeVisible({ timeout: 20_000 });
  await admin.getByTestId('check').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText(/Ready/);
  await expect(admin.getByTestId('returned-note')).toBeVisible();
  await admin.getByTestId('propose').click();
  await expect(admin.getByTestId('workspace-notice')).toContainText(/Sent for sign-off/);
  await expect(admin.getByTestId('returned-note')).toHaveCount(0);

  await go(reviewer, '/approvals');
  const again = reviewer.getByTestId('approval-card').filter({ hasText: DECISION }).and(reviewer.locator('[data-status="pending"]')).first();
  await expect(again).toBeVisible({ timeout: 30_000 });
  await again.getByRole('button', { name: 'Approve' }).click();
  await expect(reviewer.getByTestId('approval-card').filter({ hasText: DECISION }).and(reviewer.locator('[data-status="approved"]')).first()).toBeVisible({ timeout: 20_000 });

  await go(admin, `/decisions/${KEY}`);
  await admin.getByTestId('publish').click();
  await expect(admin.getByRole('dialog')).toContainText('from 2026-01-01');
  await admin.getByRole('dialog').getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(admin.getByTestId('workspace-notice')).toContainText('is now in force');
  const d = await api(admin, 'GET', `/api/decisions/${KEY}`);
  expect(d.json.data.published.length).toBe(1);
  await reviewer.context().close();
  await admin.context().close();
});

test('a document goes into a knowledge base and the agent answers from it and admits what it does not know', async ({ browser }) => {
  test.setTimeout(10 * 60_000);
  const page = await freshPage(browser, ADMIN);
  const doc = path.join(os.tmpdir(), `halvorsen-handbook-${RUN}.md`);
  fs.writeFileSync(doc, [
    '# Halvorsen Freight supplier handbook',
    '',
    'Supplier onboarding at Halvorsen Freight takes 23 business days from the signed contract.',
    'The escalation contact for late onboarding is Ingrid Solberg in the Bergen office.',
    'Invoices are paid on net 45 terms, and early payment discounts are never accepted.',
  ].join('\n'));

  await go(page, '/knowledge');
  await page.getByRole('button', { name: 'New Knowledge Base' }).click();
  await page.getByPlaceholder('e.g. Product Documentation').fill(KB);
  await page.getByPlaceholder('What kind of documents will this contain?').fill('Supplier onboarding, escalation and payment terms');
  await page.getByRole('button', { name: /^Create$/ }).click();
  const kbCard = page.locator(`[data-testid="kb-card"][data-name="${KB}"]`);
  await expect(kbCard).toBeVisible({ timeout: 30_000 });
  await kbCard.click();
  await page.getByTestId('kb-dropzone-input').setInputFiles(doc);
  const row = page.locator(`[data-testid="kb-doc-row"][data-name="${path.basename(doc)}"]`);
  await expect(row).toHaveAttribute('data-status', /ready|failed/, { timeout: 240_000 });
  await expect(row).toHaveAttribute('data-status', 'ready');
  ids.kb = page.url().match(/knowledge\/([0-9a-f-]{36})/)?.[1];

  // one click from the base to a builder with knowledge_search wired to it
  await page.getByTestId('kb-use-in-agent').click();
  await page.waitForURL(/\/builder\?.*kb=/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-knowledge_search"]')).toBeVisible({ timeout: 20_000 });
  ids.kbAgent = await buildAgent(
    page,
    KB_AGENT,
    'Answers supplier questions from the supplier handbook only.',
    'You answer questions about suppliers. Always call knowledge_search first and answer only from what it returns, naming the handbook. ' +
      'If the knowledge base does not contain the answer, reply exactly: "That is not in the knowledge base."',
  );

  const known = await chat(page, 'How long does supplier onboarding take at Halvorsen Freight, and who do I escalate to if it is late?');
  expect(known.error).toBe('');
  expect(known.text).toMatch(/23/);
  expect(known.text).toMatch(/Ingrid Solberg/);
  await openLastRun(page);
  const call = page.locator('[data-testid="tool-call"][data-tool="knowledge_search"]').first();
  await expect(call).toBeVisible({ timeout: 30_000 });
  await expect(await expand(call, 'Result')).toContainText('Halvorsen');

  await go(page, `/agents/${ids.kbAgent}/chat`);
  const unknown = await chat(page, 'What is the annual revenue of Halvorsen Freight?');
  expect(unknown.error).toBe('');
  expect(unknown.text).toMatch(/not in the knowledge base/i);
  await page.context().close();
});

test('an agent pauses for a person, one refund is approved and one denied on the Approvals page', async ({ browser }) => {
  test.setTimeout(12 * 60_000);
  const page = await freshPage(browser, ADMIN);
  await go(page, '/builder');
  ids.hitlAgent = await buildAgent(
    page,
    HITL_AGENT,
    'Sends customer refunds, each one signed off by a person first.',
    'You process refunds. For every refund request, call human_approval before anything else, with action set to ' +
      '"Refund <amount> EUR to order <order>" and details giving the reason. Wait for the result. ' +
      'If it is approved, reply "REFUND_SENT for order <order>". If it is denied, reply "REFUND_CANCELLED for order <order>". Never send a refund without approval.',
    ['human_approval'],
  );

  const approvals = await page.context().newPage();
  const decideOn = async (order: string, amount: string, button: 'Approve' | 'Deny') => {
    const pending = chat(page, `Please refund ${amount} EUR to order ${order}, the parcel arrived damaged.`, 600_000);
    await go(approvals, '/approvals');
    const card = approvalCard(approvals, `order ${order}`);
    await expect(card).toBeVisible({ timeout: 180_000 });
    await expect(card.getByTestId('approval-gate-kind')).toBeVisible();
    await card.getByRole('button', { name: button }).click();
    return pending;
  };

  const yes = await decideOn('7781', '450', 'Approve');
  expect(yes.error).toBe('');
  expect(yes.text).toMatch(/REFUND_SENT for order 7781/);
  await openLastRun(page);
  await expect(page.locator('[data-testid="tool-call"][data-tool="human_approval"]').first()).toBeVisible({ timeout: 30_000 });

  await go(page, `/agents/${ids.hitlAgent}/chat`);
  const no = await decideOn('7782', '9200', 'Deny');
  expect(no.error).toBe('');
  expect(no.text).toMatch(/REFUND_CANCELLED for order 7782/);
  await page.context().close();
});

test('a webhook fired by an outside system and a schedule run now both produce real runs', async ({ browser }) => {
  test.setTimeout(10 * 60_000);
  const page = await freshPage(browser, ADMIN);
  await go(page, '/builder');
  ids.echoAgent = await buildAgent(
    page,
    ECHO_AGENT,
    'Acknowledges order events from other systems.',
    'You acknowledge events. Reply with "TRIGGER OK:" followed by the exact text of the message you received.',
  );

  const createTrigger = async (kind: RegExp, message: string, cron?: string) => {
    await go(page, '/triggers');
    await page.getByRole('button', { name: 'New Trigger' }).click();
    await page.getByRole('button', { name: kind }).click();
    await page.locator('select').filter({ hasText: 'Select an agent...' }).selectOption({ label: ECHO_AGENT });
    if (cron) await page.getByPlaceholder('*/5 * * * * (every 5 minutes)').fill(cron);
    await page.getByPlaceholder('Message sent to the agent when triggered').fill(message);
    await page.getByRole('button', { name: 'Create Trigger' }).click();
    const row = page.locator('[data-testid^="trigger-row-"]').filter({ hasText: ECHO_AGENT }).filter({ hasText: cron ? /schedule|cron/i : /webhook/i }).first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    const tid = (await row.getAttribute('data-testid'))!.replace('trigger-row-', '');
    return { row, tid };
  };

  // the outside system posts to the URL shown on the trigger
  const hook = await createTrigger(/Webhook/, 'default webhook message');
  const url = (await hook.row.locator('code').innerText()).match(/https?:\/\/\S+/)?.[0];
  expect(url, 'the trigger shows its webhook URL').toBeTruthy();
  const before = await api(page, 'GET', `/api/executions?agent_id=${ids.echoAgent}&limit=20`);
  const seen = new Set(((before.json?.data || []) as any[]).map((e) => e.id));
  const fired = await page.request.post(url!, { data: { message: 'ORDER-5521 shipped from Rotterdam' } });
  expect(fired.status(), await fired.text()).toBeLessThan(300);
  let runId = '';
  await expect.poll(async () => {
    const r = await api(page, 'GET', `/api/executions?agent_id=${ids.echoAgent}&limit=20`);
    const run = ((r.json?.data || []) as any[]).find((e) => !seen.has(e.id) && e.status === 'completed');
    runId = run?.id || '';
    return runId;
  }, { timeout: 240_000, intervals: [3000] }).not.toBe('');
  await go(page, `/executions/${runId}`);
  await expect(page.locator('main')).toContainText('ORDER-5521', { timeout: 30_000 });
  await expect(page.locator('main')).toContainText('TRIGGER OK');

  // a nightly schedule is run now from its row
  const nightly = await createTrigger(/Schedule/, 'NIGHTLY-RECON for warehouse 4', '0 3 * * *');
  await page.getByTestId(`trigger-run-${nightly.tid}`).click();
  const link = page.getByTestId(`trigger-run-link-${nightly.tid}`);
  await expect(link).toBeVisible({ timeout: 30_000 });
  await link.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
  await expect.poll(async () => {
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    return page.locator('main').innerText();
  }, { timeout: 240_000, intervals: [5000] }).toMatch(/TRIGGER OK[\s\S]*NIGHTLY-RECON|NIGHTLY-RECON[\s\S]*TRIGGER OK/);
  await page.context().close();
});

test('a moderation policy with a custom pattern blocks a chat message, then the default policy is back in force', async ({ browser }) => {
  test.setTimeout(6 * 60_000);
  const page = await freshPage(browser, ADMIN);
  await go(page, '/moderation');
  await expect(page.getByTestId('moderation-page')).toBeVisible();
  const defaultRow = page.locator('[data-testid^="policy-row-"]').filter({ hasText: 'Default Policy' }).first();
  await expect(defaultRow).toBeVisible({ timeout: 20_000 });

  await page.getByTestId('policy-name-input').fill(POLICY);
  await page.getByTestId('policy-description-input').fill('Internal account numbers never go to a model');
  await page.getByTestId('policy-default-action').selectOption('block');
  await page.getByTestId('policy-custom-patterns').fill('ACCT-\\d{6}');
  await page.getByTestId('policy-pre-llm').check();
  await page.getByTestId('create-policy-button').click();
  const mine = page.locator('[data-testid^="policy-row-"]').filter({ hasText: POLICY }).first();
  await expect(mine).toBeVisible({ timeout: 20_000 });

  // the vet box shows what the policy does before anyone chats
  await page.getByTestId('vet-input').fill('Please move the balance to ACCT-123456 today.');
  await page.getByTestId('vet-button').click();
  await expect(page.getByTestId('vet-result-action')).toContainText(/block/i, { timeout: 20_000 });

  await go(page, `/agents/${ids.echoAgent}/chat`);
  const blocked = await chat(page, 'Move the balance to ACCT-123456 today.');
  const notice = page.getByTestId('moderation-notice');
  const said = `${blocked.error} ${(await notice.count()) ? await notice.innerText() : ''}`;
  expect(said, 'the chat says the message was blocked').toMatch(/block|moderation|policy/i);
  expect(blocked.text).not.toMatch(/TRIGGER OK: Move the balance to ACCT-123456/);

  // a message without the pattern still goes through
  const fine = await chat(page, 'Move the balance to the savings account today.');
  expect(fine.error).toBe('');
  expect(fine.text).toMatch(/TRIGGER OK/);

  await go(page, '/moderation');
  const back = page.locator('[data-testid^="policy-row-"]').filter({ hasText: 'Default Policy' }).first();
  await back.locator('[data-testid^="policy-toggle-"]').click();
  await expect(back.locator('[data-testid^="policy-toggle-"]')).toHaveText(/Deactivate/, { timeout: 20_000 });
  await expect(page.locator('[data-testid^="policy-row-"]').filter({ hasText: POLICY }).first().locator('[data-testid^="policy-toggle-"]')).toHaveText(/Activate/);
  await page.context().close();
});

test('the daily budget set in the builder is the one the platform enforces', async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  const page = await freshPage(browser, ADMIN);
  const slug = (await api(page, 'GET', `/api/agents/${ids.echoAgent}`)).json.data.slug;

  await go(page, `/builder?agent=${ids.echoAgent}`);
  await page.getByTestId('config-tab-advanced').click();
  await page.getByTestId('builder-daily-budget').fill('3.5');
  await page.getByTestId('builder-rate-limit').fill('12');
  await page.getByTestId('builder-save-draft').click();
  await expect(page.getByText(/Saved/).first()).toBeVisible({ timeout: 20_000 });

  // the scaling page reads the enforced columns
  await go(page, '/admin/scaling');
  const row = page.getByTestId(`agent-row-${slug}`);
  await expect(row).toContainText('$3.50', { timeout: 20_000 });

  // a reload of the builder shows the stored values, and clearing the budget removes the cap
  await go(page, `/builder?agent=${ids.echoAgent}`);
  await page.getByTestId('config-tab-advanced').click();
  await expect(page.getByTestId('builder-daily-budget')).toHaveValue('3.5');
  await expect(page.getByTestId('builder-rate-limit')).toHaveValue('12');
  await page.getByTestId('builder-daily-budget').fill('');
  await page.getByTestId('builder-save-draft').click();
  await expect(page.getByText(/Saved/).first()).toBeVisible({ timeout: 20_000 });
  await go(page, '/admin/scaling');
  await expect(page.getByTestId(`agent-row-${slug}`)).not.toContainText('$3.50', { timeout: 20_000 });
  await page.context().close();
});

test.afterAll(async ({ browser }) => {
  if (process.env.KEEP) return;
  const page = await browser.newPage();
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const tok = (await res.json())?.data?.access_token;
  const call = (method: string, p: string, data?: any) =>
    page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` }, data }).catch(() => null);
  // put the tenant's default moderation policy back if a failure left ours active
  const pols = (await (await call('GET', '/api/moderation/policies'))?.json().catch(() => null))?.data || [];
  const def = pols.find((p: any) => p.name === 'Default Policy');
  if (def && !def.is_active) await call('PATCH', `/api/moderation/policies/${def.id}`, { is_active: true });
  const trig = (await (await call('GET', '/api/triggers'))?.json().catch(() => null))?.data || [];
  for (const t of trig) if (t.agent_id === ids.echoAgent) await call('DELETE', `/api/triggers/${t.id}`);
  for (const id of [ids.kbAgent, ids.hitlAgent, ids.echoAgent].filter(Boolean)) await call('DELETE', `/api/agents/${id}`);
  if (ids.kb) await call('DELETE', `/api/knowledge-bases/${ids.kb}`);
  await call('DELETE', `/api/decisions/${KEY}`);
  await page.close();
});
