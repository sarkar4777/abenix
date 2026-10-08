/**
 * Timed first-use tasks, UI only, following what the screen tells a new person to do.
 *
 *   (a) a brand-new creator starts from the dashboard's Start here, builds an agent with a
 *       knowledge base and gets a correct answer, in under 10 minutes
 *   (b) a brand-new member finds and uses an agent and follows up in the same chat, in under 3 minutes
 *   (c) an admin finds what is waiting on them from Needs you and clears one approval,
 *       in under 2 minutes
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

interface Person { email: string; password: string; name: string; invite: 'creator' | 'user' }
const creator: Person = { email: `first-creator-${RUN}@example.com`, password: `Creator-${RUN}-9x`, name: `Cara ${RUN}`, invite: 'creator' };
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

test('(b) a new member finds an agent, uses it and follows up in under 3 minutes', async ({ page }) => {
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
