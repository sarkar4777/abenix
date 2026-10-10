import { test, expect, type Page } from '@playwright/test';

/**
 * End-to-end UAT for the new persistent multi-turn chat:
 *   1) login
 *   2) /chat shows the new sidebar
 *   3) send a quality cross-portfolio question, get a non-apology answer
 *   4) send a follow-up that requires prior-turn context (same thread)
 *   5) the sidebar shows the thread, with a real title (auto-derived)
 *   6) reload the page → thread still there, click it → messages re-load
 *   7) "New chat" creates a fresh thread (sidebar count goes up)
 *   8) /clauses Library page renders + has tabs Library / Gaps
 *   9) /portfolio-schemas (in abenix) renders the new explainer
 *
 * Drives Chromium against the deployed cluster.
 *   BASE=http://localhost:3001  AF_BASE=http://localhost:3100
 *   API=http://localhost:8001
 */

const BASE = process.env.CIQ_BASE || 'http://localhost:3001';
const AF_BASE = process.env.AF_BASE || process.env.BASE_AB || 'http://localhost:3100';
const API  = process.env.CIQ_API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

async function login(page: Page) {
  const resp = await fetch(`${API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token, 'access_token in login response').toBeTruthy();
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify(u || {
        email: 'test@contractiq.com', role: 'analyst',
      }));
    } catch {}
  }, { t: token, u: me });
}

/** Sends one turn and returns the text of the reply it produced. */
async function sendChat(page: Page, message: string): Promise<string> {
  const replies = page.getByTestId('chat-msg-assistant');
  const before = await replies.count();
  // the message box is a textarea, Enter sends and Shift+Enter breaks the line
  const input = page.getByPlaceholder(/Ask about your contracts/i);
  await input.fill(message);
  await input.press('Enter');
  await expect(page.getByTestId('chat-msg-user').last()).toContainText(message.slice(0, 30));
  await expect(replies).toHaveCount(before + 1, { timeout: 240_000 });
  await expect(page.getByText('Analyzing your portfolio...')).toBeHidden({ timeout: 240_000 });
  return (await replies.last().innerText()) || '';
}

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => { await login(page); });

test.describe('ContractIQ · multi-turn chat threads', () => {

  test('1 — chat page shows the new thread sidebar + new chat button', async ({ page }) => {
    const resp = await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    expect(resp?.status(), '/chat HTTP').toBeLessThan(400);
    // The new sidebar has a "New chat" button + a "Cross-Contract Intelligence" header
    await expect(page.getByRole('button', { name: /new chat/i }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Cross-Contract Intelligence/i)).toBeVisible();
  });

  test('2 — send a quality cross-portfolio question, get a real answer (not "I apologise")', async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const body = await sendChat(page, "What's my total MW exposure expiring before 2030, and which contract carries the biggest share?");
    expect(body.length, 'a real reply, not an empty bubble').toBeGreaterThan(40);
    // the canned empty-portfolio reply means no agent ran and no thread exists,
    // run uat_contractiq_advanced first, its upload journey adds a contract
    expect(body, 'the test user has contracts to ask about').not.toMatch(/don't have any contracts yet/i);
    // The whole point of the inline brief: agent must NOT claim it can't access data
    expect(body).not.toMatch(/i apologise|i'm currently unable to access|cannot access the contract portfolio database/i);
    // Real answer should mention MW or a contract title
    expect(body).toMatch(/mw|contract|portfolio|total|capacity|expir/i);
  });

  test('3 — follow-up turn re-uses prior context in the same thread', async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    // First turn establishes context
    await sendChat(page, "List my top 3 contracts by total MW capacity.");
    // Second turn deliberately uses pronouns — only works if history is repacked
    const body = await sendChat(page, "Of those three, which one has the latest expiry date?");
    expect(body).not.toMatch(/which three|please clarify|i don't have prior|no prior context/i);
    // Should reference contract titles or specific dates
    expect(body).toMatch(/202\d|expir|date|contract/i);
  });

  test('4 — sidebar shows persisted threads with auto-derived titles + msg counts', async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2_000);
    const threadSidebar = page.getByTestId('chat-threads');
    await expect(threadSidebar.getByTestId('chat-thread').first()).toBeVisible({ timeout: 15_000 });
    const sidebarText = (await threadSidebar.textContent() || '').toLowerCase();
    // After tests 2 and 3 the persisted thread should be visible with the
    // auto-derived title (first user message was about MW exposure expiring
    // before 2030) and a message-count chip.
    expect(sidebarText).toMatch(/mw|exposure|expir|portfolio|contract/);
    expect(sidebarText).toMatch(/\d+\s*msg/);
  });

  test('5 — reload preserves the thread list; clicking re-opens its messages', async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2_000);
    const thread = page.getByTestId('chat-thread').first();
    await expect(thread).toBeVisible({ timeout: 15_000 });
    const firstTitle = (await thread.locator('p').first().textContent()) || '';
    expect(firstTitle.length).toBeGreaterThan(3);
    await thread.click();
    // Past turns re-render from the persisted thread
    await expect(page.getByTestId('chat-msg-assistant').first()).toBeVisible({ timeout: 15_000 });
    const reply = (await page.getByTestId('chat-msg-assistant').first().innerText()).toLowerCase();
    expect(reply).toMatch(/contract|portfolio|mw|expir/);
  });

  test('6 — "New chat" starts a fresh thread (does not pollute prior)', async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const threads = page.getByTestId('chat-thread');
    await expect(threads.first()).toBeVisible({ timeout: 15_000 });
    const beforeCount = await threads.count();
    await page.getByRole('button', { name: /new chat/i }).first().click();
    await expect(page.getByTestId('chat-msg-assistant')).toHaveCount(0);
    const reply = await sendChat(page, "What contract types do I have in my portfolio?");
    expect(reply.length).toBeGreaterThan(20);
    // a new thread, not another turn on the old one
    await expect(threads).toHaveCount(beforeCount + 1, { timeout: 20_000 });
  });

  test('7 — Clause Library renders with Library + Gaps tabs', async ({ page }) => {
    await page.goto(`${BASE}/clauses`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/Clause Library/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: /library/i }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /gaps/i }).first()).toBeVisible();
  });
});

test.describe('Abenix · Portfolio Schemas explainer', () => {
  test('8 — portfolio-schemas page shows the new "What is a Portfolio Schema?" panel', async ({ page }) => {
    // Abenix is auth-gated — bounce to landing page otherwise.
    const AF_API = process.env.AF_API || 'http://localhost:8000';
    const ADMIN_EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
    const ADMIN_PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

    const lr = await fetch(`${AF_API}/api/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
    });
    if (!lr.ok) {
      test.skip(true, `Abenix admin login HTTP ${lr.status} — set AF_EMAIL/AF_PASSWORD env`);
      return;
    }
    const lj = await lr.json();
    const token = lj.data?.access_token || lj.access_token;
    expect(token).toBeTruthy();

    await page.addInitScript(({ t }: { t: string }) => {
      try { localStorage.setItem('access_token', t); } catch {}
    }, { t: token });

    await page.goto(`${AF_BASE}/portfolio-schemas`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const body = await page.textContent('body') || '';
    // the explainer was rewritten as a three step how-it-works panel
    expect(body).toMatch(/Give your agents a table of records/i);
    expect(body).toMatch(/Bring your data/i);
    expect(body).toMatch(/Use it in an agent/i);
    expect(body).toMatch(/list_records/i);
  });
});
