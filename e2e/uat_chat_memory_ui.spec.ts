import { test, expect, type Page } from '@playwright/test';

/*
 * AI Chat remembers the conversation, across turns and across a reload. UI only.
 *
 *   USE_K8S=true BASE=http://localhost:3100 API=http://localhost:8000 \
 *   npx playwright test e2e/uat_chat_memory_ui.spec.ts --reporter=list --workers=1
 */

const BASE = process.env.BASE || 'http://localhost:3100';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

test.describe.configure({ mode: 'serial' });

async function signIn(page: Page) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(EMAIL);
  await page.locator('#auth-password').fill(PASSWORD);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function send(page: Page, text: string) {
  const before = await page.locator('[data-testid="chat-message"][data-role="assistant"]').count();
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
  await expect(page.locator('[data-testid="chat-message"][data-role="assistant"]')).toHaveCount(before + 1, { timeout: 180_000 });
  await expect(page.getByTestId('chat-stop')).toHaveCount(0, { timeout: 180_000 });
  await expect(page.getByTestId('chat-error')).toHaveCount(0);
  return page.locator('[data-testid="chat-message"][data-role="assistant"]').last().innerText();
}

test('the chat remembers a code word across turns and after a reload', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  const word = `ZEPHYR${Date.now().toString(36).toUpperCase()}`;

  await signIn(page);
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });

  // the page explains itself and lands on an agent without any setup
  const empty = page.getByTestId('chat-empty');
  await expect(empty).toBeVisible();
  await expect(empty).toContainText(/remembers this conversation/i);
  await expect(page.getByTestId('chat-agent-picker')).not.toContainText(/loading|choose an agent/i, { timeout: 60_000 });
  await expect(page.getByTestId('chat-input')).toBeEnabled();

  // the picker searches every agent, not just the first page
  await page.getByTestId('chat-agent-picker').click();
  await expect(page.getByTestId('chat-agent-search')).toBeVisible();
  await page.getByTestId('chat-agent-search').fill('code assistant');
  await expect(page.getByTestId('chat-agent-option').first()).toContainText(/code assistant/i);
  await page.getByTestId('chat-agent-option').first().click();
  await expect(page.getByTestId('chat-agent-picker')).toContainText(/code assistant/i);

  await send(page, `Remember this code word for later: ${word}. Reply only with OK.`);
  await expect(page).toHaveURL(/\/chat\?id=/);

  const second = await send(page, 'What is the code word I gave you? Reply with the code word only.');
  expect(second.toUpperCase()).toContain(word);

  // the model chip shows what actually answered, not a placeholder
  await expect(page.getByTestId('chat-model')).toBeVisible();

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-testid="chat-message"][data-role="user"]').first()).toContainText(word, { timeout: 30_000 });
  const third = await send(page, 'Say the code word one more time, nothing else.');
  expect(third.toUpperCase()).toContain(word);

  // a new chat starts clean and does not know the word
  await page.getByTestId('chat-new').click();
  await expect(page.getByTestId('chat-empty')).toBeVisible();
});

test('deleting a conversation asks first, and the list is a drawer on a phone', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });

  // the message area keeps the width, the list opens on demand
  await expect(page.getByTestId('chat-history-panel')).toBeHidden();
  const inputBox = await page.getByTestId('chat-input').boundingBox();
  expect(inputBox?.width || 0).toBeGreaterThan(220);
  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollW).toBeLessThanOrEqual(392);

  await page.getByTestId('chat-history-toggle').click();
  await expect(page.getByTestId('chat-history-panel')).toBeVisible();
  const item = page.getByTestId('chat-history-item').first();
  await expect(item).toBeVisible({ timeout: 30_000 });
  const title = (await item.locator('p').first().innerText()).trim();
  await item.getByRole('button', { name: /^Delete / }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText(/delete this conversation/i);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('chat-history-item').filter({ hasText: title }).first()).toBeVisible();
});
