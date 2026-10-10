/**
 * Timed first-use tasks, UI only, following what the screen tells a new person to do.
 *
 *   (a) a brand-new creator starts from the dashboard's Start here, builds an agent with a
 *       knowledge base and gets a correct answer, in under 10 minutes
 *   (b) a brand-new member finds and uses an agent, follows up in the same chat and gives
 *       feedback on an answer with the thumbs, in under 3 minutes
 *   (c) an admin finds what is waiting on them from Needs you and clears one approval,
 *       in under 2 minutes
 *   (d) a new creator turns a pasted Excel table into a published decision, with a reviewer's
 *       sign-off, in under 10 minutes
 *
 * Each step looks for the on-screen guidance first (Start here steps, NextSteps cards, page
 * primary actions, the Needs you count). When the guidance is missing the task fails with the
 * step where a person would have been lost. Times per step go to e2e/uat_first_use_tasks/report.json.
 *
 * Setup that is not part of the timed path: the creator and member are invited from
 * Settings, Team, and the approval in (c) is raised through the approvals API, the way an
 * agent or SDK raises one.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_first_use_tasks.spec.ts --workers=1
 */
import { test, expect, type Browser, type Locator, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const OUT = path.join(__dirname, 'uat_first_use_tasks');
const FACT_CODE = `OL-${RUN.toUpperCase()}-7`;
const FACT_FILE = path.join(OUT, `orchard_lane_${RUN}.md`);
const APPROVAL_TITLE = `Refund order ${RUN} for 240 EUR`;
const DECISION_NAME = `Refund routing ${RUN}`;
// what a person copies out of Excel: a header row, then one rule per row
const REFUND_TABLE = [
  ['rule', 'refund.amount_eur', 'refund.reason', 'review', 'note'],
  ['refund.large', '>= 500', '', 'manual', 'Large refunds go to a person'],
  ['refund.damaged', '< 500', 'damaged', 'auto', 'Damaged goods are refunded straight away'],
  ['refund.other', '< 500', '', 'manual', 'Everything else is checked by a person'],
].map((r) => r.join('\t')).join('\n');

interface Person { email: string; password: string; name: string; invite: 'creator' | 'user'; canApprove?: boolean }
// the creator can also approve decisions, other people's, never their own
const creator: Person = { email: `first-creator-${RUN}@example.com`, password: `Creator-${RUN}-9x`, name: `Cara ${RUN}`, invite: 'creator', canApprove: true };
const member: Person = { email: `first-member-${RUN}@example.com`, password: `Member-${RUN}-9x`, name: `Milo ${RUN}`, invite: 'user' };

interface StepTime { step: string; seconds: number }
interface TaskResult { task: string; limitSeconds: number; seconds: number; ok: boolean; lostAt?: string; why?: string; steps: StepTime[] }
const results: TaskResult[] = [];

class Lost extends Error {
  constructor(public step: string, public why: string) {
    super(`lost at "${step}": ${why}`);
  }
}

// a timed task, every step names the guidance a person would follow
function timer(task: string, limitSeconds: number) {
  const started = Date.now();
  const steps: StepTime[] = [];
  let last = started;
  const r: TaskResult = { task, limitSeconds, seconds: 0, ok: false, steps };
  return {
    async step<T>(name: string, fn: () => Promise<T>): Promise<T> {
      try {
        return await test.step(name, fn);
      } catch (e) {
        if (e instanceof Lost) throw e;
        throw new Lost(name, String(e instanceof Error ? e.message : e).split('\n')[0].slice(0, 240));
      } finally {
        const now = Date.now();
        steps.push({ step: name, seconds: Math.round((now - last) / 100) / 10 });
        last = now;
      }
    },
    done(error?: unknown) {
      r.seconds = Math.round((Date.now() - started) / 100) / 10;
      if (error instanceof Lost) {
        r.lostAt = error.step;
        r.why = error.why;
      } else if (error) {
        r.lostAt = steps[steps.length - 1]?.step || 'start';
        r.why = String(error).slice(0, 240);
      }
      r.ok = !error && r.seconds <= limitSeconds;
      if (!error && !r.ok) {
        r.lostAt = 'overall';
        r.why = `took ${r.seconds}s, the limit is ${limitSeconds}s`;
      }
      results.push(r);
      return r;
    },
  };
}

// the guidance must be on screen, or the person is lost here
async function guidance(step: string, loc: Locator, why: string, timeout = 15_000) {
  const ok = await loc.first().waitFor({ state: 'visible', timeout }).then(() => true).catch(() => false);
  if (!ok) throw new Lost(step, why);
  return loc.first();
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
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

async function invite(page: Page, browser: Browser, who: Person) {
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).first().click();
  await page.getByPlaceholder('email@example.com').fill(who.email);
  await page.getByTestId('invite-role').selectOption(who.invite);
  if (who.canApprove) await page.getByTestId('invite-can-approve').check();
  await page.getByTestId('invite-send').click();
  const link = page.getByTestId('invite-link');
  await expect(link).toBeVisible({ timeout: 20_000 });
  const raw = ((await link.innerText()) || (await link.inputValue().catch(() => ''))).trim();
  const url = raw.startsWith('http') ? raw.replace(/^https?:\/\/[^/]+/, BASE) : `${BASE}${raw}`;
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p2 = await ctx.newPage();
  await p2.goto(url, { waitUntil: 'domcontentloaded' });
  await expect(p2.getByTestId('accept-title')).toBeVisible({ timeout: 30_000 });
  await p2.locator('#accept-full-name').fill(who.name);
  await p2.locator('#accept-password').fill(who.password);
  await p2.getByTestId('accept-submit').click();
  await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
}

async function apiAs(who: { email: string; password: string }, method: string, p: string, body?: unknown) {
  const login = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: who.email, password: who.password }),
  });
  const tok = (await login.json())?.data?.access_token;
  const res = await fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: res.status, json: await res.json().catch(() => null) };
}

async function lastReply(page: Page, timeoutMs = 240_000): Promise<string> {
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  await page.waitForTimeout(1000);
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const n = await replies.count();
  return n ? await replies.nth(n - 1).innerText() : '';
}

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

const state: { approvalId?: string } = {};

test.beforeAll(async ({ browser }) => {
  test.setTimeout(5 * 60_000);
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(
    FACT_FILE,
    `# Orchard Lane warehouse\n\nThe Orchard Lane warehouse opens at 06:30.\n\nThe door code for the Orchard Lane warehouse is ${FACT_CODE}.\n\nDeliveries go to bay 4.\n`,
  );
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.accept());
  await signIn(page, ADMIN);
  await invite(page, browser, creator);
  await invite(page, browser, member);
  await ctx.close();
});

test.afterAll(async () => {
  try {
    if (state.approvalId) await apiAs(ADMIN, 'POST', `/api/approvals/${state.approvalId}/signoff`, { decision: 'deny', reason: 'test cleanup' });
    const list = (await apiAs(ADMIN, 'GET', '/api/team/members')).json?.data;
    const members = Array.isArray(list) ? list : list?.members || [];
    for (const p of [creator, member]) {
      const m = members.find((x: { email?: string }) => x.email === p.email);
      if (m?.id) await apiAs(ADMIN, 'DELETE', `/api/team/members/${m.id}`);
    }
  } finally {
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(results, null, 2));
    for (const r of results) {
      console.log(`${r.ok ? 'PASS' : 'FAIL'} ${r.task}: ${r.seconds}s of ${r.limitSeconds}s${r.lostAt ? `, lost at "${r.lostAt}": ${r.why}` : ''}`);
      console.table(r.steps);
    }
  }
});

test('(a) a new creator builds an agent with knowledge and gets a right answer in under 10 minutes', async ({ page }) => {
  test.setTimeout(15 * 60_000);
  page.on('dialog', (d) => d.accept());
  await signIn(page, creator);
  const t = timer('creator builds an agent with a knowledge base', 600);
  const kbName = `Warehouse facts ${RUN}`;
  const agentName = `Warehouse helper ${RUN}`;
  let error: unknown;
  try {
    await t.step('Start here on the dashboard points at knowledge', async () => {
      await guidance('Start here', page.getByTestId('start-here'), 'the dashboard has no Start here guide for a new builder', 20_000);
      const go = await guidance(
        'Start here',
        page.getByTestId('start-here-add_knowledge-go'),
        'Start here has no "Give it knowledge" step with a button',
      );
      await go.click();
      await page.waitForURL(/\/knowledge/, { timeout: 20_000 });
    });

    await t.step('create a knowledge base from the page primary action', async () => {
      const create = await guidance(
        'create a knowledge base',
        page.getByTestId('page-primary-action').locator('a,button').or(page.getByRole('button', { name: /New Knowledge Base|Create your first/i })),
        'the Knowledge page has no visible way to create a knowledge base',
      );
      await create.click();
      await page.getByPlaceholder('e.g. Product Documentation').fill(kbName);
      await page.getByPlaceholder('What kind of documents will this contain?').fill('Facts about our warehouses');
      await page.getByRole('button', { name: /^Create$/ }).click();
      const card = page.locator(`[data-testid="kb-card"][data-name="${kbName}"]`);
      if (await card.isVisible({ timeout: 5_000 }).catch(() => false)) await card.click();
    });

    await t.step('upload the document the next steps ask for', async () => {
      await guidance(
        'upload',
        page.getByTestId('kb-next-steps').or(page.getByTestId('kb-upload-primary')),
        'after creating the knowledge base nothing says to upload documents',
      );
      await page.getByTestId('kb-dropzone-input').setInputFiles(FACT_FILE);
      const doc = page.locator('[data-testid="kb-doc-row"]').filter({ hasText: path.basename(FACT_FILE) });
      await expect(doc).toBeVisible({ timeout: 30_000 });
      await expect(doc).toHaveAttribute('data-status', /ready|failed/, { timeout: 300_000 });
      if ((await doc.getAttribute('data-status')) !== 'ready') throw new Lost('upload', 'the document failed to index and the page gives no way forward');
    });

    await t.step('Use in an agent opens the builder with the knowledge attached', async () => {
      const use = await guidance(
        'use in an agent',
        page.getByTestId('kb-use-in-agent').or(page.getByTestId('kb-next-steps-agent')),
        'once the document is ready nothing points at using it in an agent',
      );
      await use.click();
      await page.waitForURL(/\/builder\?.*kb=/, { timeout: 20_000 });
    });

    await t.step('name and instruct the agent, then save and publish', async () => {
      await guidance('builder', page.getByTestId('builder-name-button'), 'the builder did not open in a usable state', 30_000);
      await page.getByTestId('builder-name-button').click();
      await page.getByTestId('builder-name-input').fill(agentName);
      await page.getByTestId('builder-name-input').press('Enter');
      await page.getByTestId('config-tab-general').click();
      await page.getByTestId('builder-description').fill('Answers questions about our warehouses from the warehouse facts.');
      await page.getByTestId('builder-category').selectOption({ index: 1 }).catch(() => {});
      await page.getByTestId('config-tab-prompt').click();
      await page.getByTestId('builder-system-prompt').fill(
        'You answer questions about our warehouses. Always call knowledge_search first and answer only from what it returns. Quote codes exactly.',
      );
      await page.getByTestId('config-tab-knowledge').click().catch(() => {});
      const kbBox = page.getByLabel(kbName);
      if (await kbBox.isVisible({ timeout: 3_000 }).catch(() => false)) {
        if (!(await kbBox.isChecked())) throw new Lost('builder', 'the knowledge base did not arrive ticked from Use in an agent');
      }
      await page.getByTestId('builder-save-draft').click();
      await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
      const publish = await guidance('publish', page.getByTestId('builder-publish'), 'after saving there is no Publish button');
      await publish.click();
      await page.getByTestId('publish-visibility-org').click();
      await page.getByTestId('publish-submit').click();
      await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
    });

    await t.step('ask a question only the document answers', async () => {
      await guidance('chat', page.getByTestId('chat-input'), 'publishing did not land on a chat with the new agent', 20_000);
      await page.getByTestId('chat-input').fill('What is the door code for the Orchard Lane warehouse?');
      await page.getByTestId('chat-send').click();
      const reply = await lastReply(page);
      if (!reply.includes(FACT_CODE)) throw new Lost('answer', `the agent did not give the code from the document, it said: ${reply.slice(0, 160)}`);
    });
  } catch (e) {
    error = e;
  }
  const r = t.done(error);
  expect(r.ok, r.why || '').toBe(true);
});

test('(b) a new member finds an agent, uses it, follows up and gives feedback in under 3 minutes', async ({ page }) => {
  test.setTimeout(8 * 60_000);
  await signIn(page, member);
  const t = timer('member uses an agent and follows up', 180);
  let error: unknown;
  try {
    await t.step('Start here points at chat', async () => {
      await guidance('Start here', page.getByTestId('start-here'), 'the dashboard has no Start here guide for a new member', 20_000);
      const go = await guidance('Start here', page.getByTestId('start-here-try_chat-go'), 'Start here has no "Try an agent in chat" button');
      await go.click();
      await page.waitForURL(/\/chat/, { timeout: 20_000 });
    });

    await t.step('pick an agent and ask something', async () => {
      const input = await guidance('chat', page.getByTestId('chat-input'), 'the chat page has no message box', 20_000);
      if (await input.isDisabled().catch(() => false)) {
        const picker = await guidance('pick an agent', page.getByTestId('chat-agent-picker'), 'there is no way to choose an agent');
        await picker.click();
        const option = await guidance('pick an agent', page.getByTestId('chat-agent-option'), 'the agent list is empty for a new member');
        await option.click();
      }
      await input.fill('In one sentence, what can you help me with?');
      await page.getByTestId('chat-send').click();
      const reply = await lastReply(page, 120_000);
      if (reply.trim().length < 10) throw new Lost('use the agent', 'the agent gave no answer');
    });

    await t.step('Start here suggests a follow-up, and the agent remembers the thread', async () => {
      await go(page, '/dashboard');
      const step = await guidance(
        'follow up',
        page.getByTestId('start-here-follow_up-go'),
        'Start here has no next step after the first chat',
      );
      await step.click();
      await page.waitForURL(/\/chat/, { timeout: 20_000 });
      const history = page.getByTestId('chat-history-item').first();
      if (await history.isVisible({ timeout: 5_000 }).catch(() => false)) await history.click();
      const input = await guidance('follow up', page.getByTestId('chat-input'), 'the chat page has no message box', 20_000);
      await input.fill('Say that again in five words or fewer.');
      await page.getByTestId('chat-send').click();
      const reply = await lastReply(page, 120_000);
      if (reply.trim().length < 3) throw new Lost('follow up', 'the agent gave no answer to the follow-up');
    });

    await t.step('Start here asks for feedback, and the thumbs take it', async () => {
      await go(page, '/dashboard');
      const step = await guidance(
        'feedback',
        page.getByTestId('start-here-give_feedback-go'),
        'Start here has no "Give feedback on an answer" step after the follow-up',
      );
      await step.click();
      await page.waitForURL(/\/chat/, { timeout: 20_000 });
      const history = page.getByTestId('chat-history-item').first();
      if (await history.isVisible({ timeout: 5_000 }).catch(() => false)) await history.click();
      const answer = page.locator('[data-testid="chat-message"][data-role="assistant"]').last();
      const bar = await guidance('feedback', answer.getByTestId('chat-feedback'), 'the answer has no thumbs to rate it', 30_000);
      await bar.getByTestId('chat-feedback-down').click();
      const box = await guidance('feedback', bar.getByTestId('chat-feedback-box'), 'a thumbs down did not ask what it should have said');
      await box.getByTestId('chat-feedback-correction').fill('It should have answered in five words or fewer.');
      await box.getByTestId('chat-feedback-send').click();
      await guidance('feedback', bar.getByTestId('chat-feedback-thanks'), 'the correction was not confirmed', 20_000);
    });
  } catch (e) {
    error = e;
  }
  const r = t.done(error);
  expect(r.ok, r.why || '').toBe(true);
});

test('(c) an admin finds what waits on them in Needs you and clears one approval in under 2 minutes', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  // raised by the member, the way an agent or SDK asks for a sign-off
  const raised = await apiAs(member, 'POST', '/api/approvals', { title: APPROVAL_TITLE, payload: { summary: `Customer asked for a refund on order ${RUN}` } });
  expect(raised.status, 'approval raised').toBe(201);
  state.approvalId = raised.json?.data?.id;

  await signIn(page, ADMIN);
  const t = timer('admin clears an approval from Needs you', 120);
  let error: unknown;
  try {
    await t.step('Needs you in the sidebar shows a count', async () => {
      const link = await guidance('Needs you', page.locator('aside a[data-nav="/inbox"]'), 'the sidebar has no Needs you entry', 20_000);
      await guidance('Needs you', link.getByTestId('sidebar-inbox-count'), 'Needs you shows no count although an approval is waiting', 70_000);
      await link.click();
      await page.waitForURL(/\/inbox/, { timeout: 20_000 });
    });

    await t.step('the approvals tab lists the request', async () => {
      const tab = await guidance('approvals tab', page.getByTestId('inbox-tab-approvals'), 'Needs you has no Approvals tab');
      await tab.click();
      await guidance('approvals tab', page.getByTestId('inbox-approval').filter({ hasText: APPROVAL_TITLE }), 'the waiting approval is not listed', 20_000);
    });

    await t.step('approve it inline', async () => {
      const count = Number((await page.getByTestId('inbox-count-approvals').innerText()).replace('+', '')) || 0;
      const card = page.getByTestId('inbox-approval').filter({ hasText: APPROVAL_TITLE });
      await card.getByTestId('inbox-approve').click();
      await expect(card).toHaveCount(0, { timeout: 20_000 });
      await expect
        .poll(async () => Number((await page.getByTestId('inbox-count-approvals').innerText().catch(() => '0')).replace('+', '')) || 0, { timeout: 20_000 })
        .toBeLessThan(Math.max(count, 1));
      state.approvalId = undefined;
    });
  } catch (e) {
    error = e;
  }
  const r = t.done(error);
  expect(r.ok, r.why || '').toBe(true);
});

test('(d) a new creator turns a pasted Excel table into a published decision with a reviewer\'s sign-off in under 10 minutes', async ({ page, browser }) => {
  test.setTimeout(15 * 60_000);
  page.on('dialog', (d) => d.accept());
  await signIn(page, creator);
  const t = timer('creator pastes a table and publishes a decision with sign-off', 600);
  let error: unknown;
  const rctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const reviewer = await rctx.newPage();
  try {
    await t.step('find Decisions in the sidebar', async () => {
      let link = page.locator('aside a[href="/decisions"]').first();
      if (!(await link.isVisible({ timeout: 5_000 }).catch(() => false))) {
        const all = await guidance('find Decisions', page.getByTestId('sidebar-mode-toggle'), 'Decisions is not in the sidebar and nothing says how to show more');
        await all.click();
        link = page.locator('aside a[href="/decisions"]').first();
      }
      await guidance('find Decisions', link, 'the sidebar has no Decisions link');
      await link.click();
      await page.waitForURL(/\/decisions/, { timeout: 20_000 });
    });

    await t.step('start a new decision from the page action, at high risk so it needs a sign-off', async () => {
      const start = await guidance('new decision', page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank')), 'the Decisions page has no way to start a decision');
      await start.click();
      await page.getByTestId('decision-name').fill(DECISION_NAME);
      await guidance('new decision', page.getByTestId('decision-key-help').filter({ hasText: 'Free to use' }), 'the key is not confirmed as free', 15_000);
      await page.getByTestId('decision-tier-high').click();
      await page.getByTestId('decision-create').click();
      await page.waitForURL(/\/decisions\/[^/?]+/, { timeout: 20_000 });
    });

    await t.step('the guide says to paste the rules from Excel', async () => {
      const go = await guidance('paste', page.getByTestId('guide-action').filter({ hasText: 'Paste from Excel' }), 'the decision page does not say how to start on the rules', 20_000);
      await go.click();
      const box = await guidance('paste', page.getByTestId('paste-first-text'), 'the Table has no place to paste rows into an empty decision');
      await box.fill(REFUND_TABLE);
      const add = await guidance('paste', page.getByTestId('paste-first-apply'), 'the paste is not offered for review and adding');
      await add.click();
      await guidance('paste', page.getByTestId('table-row-2'), 'the pasted rows did not become rules');
      await expect(page.getByTestId('save-state')).toHaveText(/All changes saved/, { timeout: 20_000 });
    });

    await t.step('the guide says to keep a golden test from Try it', async () => {
      const go = await guidance('golden test', page.getByTestId('guide-action').filter({ hasText: 'Open Try it' }), 'after the paste nothing says to add a golden test', 20_000);
      await go.click();
      const amount = await guidance('golden test', page.getByTestId('try-fact-refund.amount_eur'), 'Try it has no field for the amount');
      await amount.fill('750');
      // Try it marks what else it needs, and the person fills it in
      const needed = page.getByTestId('try-fact-refund.reason-flag');
      if (await needed.isVisible({ timeout: 5_000 }).catch(() => false)) await page.getByTestId('try-fact-refund.reason').fill('changed my mind');
      await guidance('golden test', page.getByTestId('try-result-readable').filter({ hasText: 'manual' }), 'Try it did not decide 750 EUR goes to a person', 20_000);
      await page.getByTestId('try-test-name').fill('A large refund goes to a person');
      await page.getByTestId('try-save-test').click();
      await guidance('golden test', page.getByTestId('try-test-saved'), 'keeping the case as a test was not confirmed');
    });

    await t.step('the guide says to run Check, then to propose for sign-off', async () => {
      const check = await guidance('check', page.getByTestId('guide-action').filter({ hasText: /^Check/ }), 'after the test nothing says to run Check', 20_000);
      await check.click();
      await guidance('check', page.getByTestId('workspace-notice').filter({ hasText: /Ready/ }), 'Check did not say the rules are ready', 20_000);
      const propose = await guidance('propose', page.getByTestId('guide-action').filter({ hasText: /Propose/ }), 'after Check nothing says to propose it', 20_000);
      await propose.click();
      await guidance('propose', page.getByTestId('guide-text').filter({ hasText: /Waiting for/ }), 'after proposing the page does not say who it waits for', 20_000);
    });

    await t.step('a reviewer finds it in Needs you, reads the rules and approves it', async () => {
      await signIn(reviewer, ADMIN);
      const link = await guidance('review', reviewer.locator('aside a[data-nav="/inbox"]'), 'the reviewer has no Needs you entry', 20_000);
      await link.click();
      await reviewer.waitForURL(/\/inbox/, { timeout: 20_000 });
      const tab = await guidance('review', reviewer.getByTestId('inbox-tab-approvals'), 'Needs you has no Approvals tab');
      await tab.click();
      const card = await guidance('review', reviewer.getByTestId('inbox-approval').filter({ hasText: DECISION_NAME }), 'the rule change is not listed for the reviewer', 70_000);
      const rules = await guidance('review', card.getByTestId('inbox-evidence'), 'the request has no way to see the rules it changes');
      await rules.click();
      await reviewer.waitForURL(/\/decisions\//, { timeout: 20_000 });
      const approve = await guidance('review', reviewer.getByTestId('guide-action').filter({ hasText: /Approve/ }), 'the decision page does not tell the reviewer they can approve it', 20_000);
      await approve.click();
      await reviewer.waitForURL(/\/approvals/, { timeout: 20_000 });
      const pending = reviewer.locator('[data-testid="approval-card"][data-status="pending"]').filter({ hasText: DECISION_NAME });
      await guidance('review', pending.getByTestId('approval-effect'), 'the card does not say what approving does', 20_000);
      await pending.getByTestId('approval-approve').click();
      await guidance('review', reviewer.getByTestId('approval-decided'), 'approving did not say what happens next', 20_000);
    });

    await t.step('it is published from the decision page by someone who can', async () => {
      await page.reload({ waitUntil: 'domcontentloaded' });
      const text = await guidance('publish', page.getByTestId('guide-text').filter({ hasText: /Approved/ }), 'the author is not told it was approved', 30_000);
      await page.getByTestId('decision-guide').screenshot({ path: path.join(OUT, 'guide-approved-author-cannot-publish.png') }).catch(() => {});
      const own = page.getByTestId('guide-action').filter({ hasText: /^Publish/ });
      let who = page;
      if (!(await own.isVisible({ timeout: 3_000 }).catch(() => false))) {
        // a creator cannot publish: the guide says to ask, and the reviewer opens it from the note Approvals left
        if (!/ask someone who has it/i.test(await text.innerText())) throw new Lost('publish', 'the author cannot publish and is not told who can');
        const open = await guidance('publish', reviewer.getByTestId('approval-decided-open'), 'after approving there is no way back to the decision', 10_000);
        await open.click();
        await reviewer.waitForURL(/\/decisions\//, { timeout: 20_000 });
        who = reviewer;
      }
      const pub = await guidance('publish', who.getByTestId('guide-action').filter({ hasText: /^Publish/ }), 'Publish is not offered on the approved decision', 20_000);
      await pub.click();
      await who.getByRole('dialog').getByRole('button', { name: 'Publish' }).click();
      await guidance('publish', who.getByTestId('workspace-notice').filter({ hasText: 'is now in force' }), 'publishing was not confirmed', 20_000);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await guidance('publish', page.getByTestId('guide-text').filter({ hasText: /is in force/ }), 'the author does not see it is in force', 30_000);
    });
  } catch (e) {
    error = e;
  } finally {
    await rctx.close();
  }
  const r = t.done(error);
  const key = new URL(page.url()).pathname.split('/').pop();
  if (key) {
    // at high risk archiving waits for a second person, the creator gives it
    const arch = await apiAs(ADMIN, 'DELETE', `/api/decisions/${key}`, { reason: 'end of the first-use run' });
    const pending = arch.json?.data?.pending?.approval_id;
    if (pending) await apiAs(creator, 'POST', `/api/approvals/${pending}/signoff`, { decision: 'approve', reason: 'test cleanup' });
  }
  expect(r.ok, r.why || '').toBe(true);
});
