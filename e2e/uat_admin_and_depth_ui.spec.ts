/**
 * Admin and depth screens, used the way an admin and an agent owner use them.
 *
 *   1. Agents        build a memory agent and an agent on a model only a pricing row knows
 *   2. Memories      the agent saves facts, view them, delete one, delete all
 *   3. DLQ           the pricing row goes, the run fails into the dead letter queue, the agent is fixed, replay finishes
 *   4. Comments      star the agent, comment, resolve, delete, unstar
 *   5. Search        open the palette by shortcut and by click, find an agent, a page and a run, keyboard only
 *   6. Shell         drive a pipeline's shell with commands, history and completion
 *   7. Archives      archive old ML invocation rows, restore them, put the retention back
 *   8. Audit log     find my own actions with the filters, check the trail
 *   9. Catalogue     view and edit an ML model, put it back
 *  10. Market data   add a source, test it, remove it
 *  11. Observability every action lands somewhere real
 *  12. Subscription  verify, switch off, back on
 *  13. Cognify       a 0 budget stops the next job with a message, then put back
 *  14. Phone width   these screens at 390px
 *
 * The API is only used to read state back and to clean up.
 *
 *   USE_K8S=true BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_admin_and_depth_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';
import { ADMIN, api, expectFitsPhone, expectReadable, go, lastReply, nav, shooter, signIn } from './helpers/depth';

const RUN = Date.now().toString(36);
const shot = shooter(path.join(__dirname, 'uat_admin_and_depth_ui'));
const MEM_AGENT = `UAT Memory ${RUN}`;
const DLQ_AGENT = `UAT Dead Letter ${RUN}`;
const DLQ_MODEL = `uat-dlq-${RUN}`;
const SOURCE = `UAT rates ${RUN}`;
const COLOUR = 'teal';
const HARBOUR = `Lisbon-${RUN}`;

const ids: { memAgent?: string; dlqAgent?: string; price?: string; connector?: string; retention?: number; mlDesc?: string; mlId?: string; budget?: number | null; subOff?: boolean } = {};

test.describe.configure({ mode: 'default' });
test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

async function buildAgent(page: Page, o: { name: string; prompt: string; model?: string; tools?: string[] }) {
  await nav(page, '/agents');
  await page.getByRole('link', { name: 'New Agent' }).first().click();
  await page.waitForURL(/\/builder/);
  await page.getByTestId('builder-name-button').click({ timeout: 30_000 });
  await page.getByTestId('builder-name-input').fill(o.name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill(`Depth spec agent ${RUN}`);
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(o.prompt);
  if (o.model) {
    await page.getByTestId('config-tab-model').click();
    await page.getByTestId('model-picker-select').selectOption(o.model);
  }
  for (const t of o.tools || []) {
    await page.getByPlaceholder('Search tools, descriptions, params...').fill(t);
    const tool = page.getByTestId(`palette-tool-${t}`);
    if ((await tool.getAttribute('aria-pressed')) !== 'true') await tool.click();
    await expect(tool).toHaveAttribute('aria-pressed', 'true');
  }
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  const id = new URL(page.url()).searchParams.get('agent')!;
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
  return id;
}

async function ask(page: Page, text: string) {
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
  return lastReply(page);
}

test('a memory agent saves facts, view them, delete one, delete all', async ({ page }) => {
  test.setTimeout(12 * 60_000);
  ids.memAgent = await buildAgent(page, {
    name: MEM_AGENT,
    prompt: 'When the user tells you something to remember, call memory_store once with a short snake_case key and the value, then reply "Saved." When asked about something, call memory_recall first and answer from it in one short sentence.',
    tools: ['memory_store', 'memory_recall'],
  });
  await ask(page, `Remember that my favourite colour is ${COLOUR}.`);
  await ask(page, `Remember that my home harbour is ${HARBOUR}.`);
  const recalled = await ask(page, 'What is my favourite colour?');
  expect(recalled.toLowerCase()).toContain(COLOUR);

  await go(page, `/agents/${ids.memAgent}/info`);
  await page.getByText('Browse and manage stored memories').click();
  await page.waitForURL(/\/memories$/);
  const rows = page.getByTestId('memory-row');
  await expect(rows).toHaveCount(2, { timeout: 30_000 });
  await expect(rows.filter({ hasText: COLOUR })).toHaveCount(1);
  await page.getByTestId('memories-search').fill('Lisbon');
  await expect(rows).toHaveCount(1, { timeout: 20_000 });
  await page.getByTestId('memories-search').fill('');
  await expect(rows).toHaveCount(2, { timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '01-memories');

  const lisbon = rows.filter({ hasText: 'Lisbon' });
  await lisbon.getByTestId('memory-delete').click();
  await expect(rows).toHaveCount(1, { timeout: 20_000 });
  const left = (await api(page, 'GET', `/api/agents/${ids.memAgent}/memories`)).json.data as any[];
  expect(left).toHaveLength(1);
  expect(left[0].value).toContain(COLOUR);

  await page.getByTestId('memories-clear-all').click();
  await expect(page.getByTestId('memories-empty')).toBeVisible({ timeout: 20_000 });
  expect((await api(page, 'GET', `/api/agents/${ids.memAgent}/memories`)).json.data).toHaveLength(0);
  await shot(page, '02-memories-cleared');
});

test('star, comment, resolve and delete on an agent', async ({ page }) => {
  test.skip(!ids.memAgent, 'needs the memory agent');
  await go(page, `/agents/${ids.memAgent}/info`);
  const star = page.getByTestId('agent-favorite');
  await expect(star).toHaveAttribute('data-on', '0', { timeout: 20_000 });
  await star.click();
  await expect(star).toHaveAttribute('data-on', '1', { timeout: 20_000 });
  await nav(page, '/agents');
  await expect(page.getByTestId('agents-starred').getByText(MEM_AGENT)).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('agents-starred').getByText(MEM_AGENT).click();
  await page.waitForURL(new RegExp(`/agents/${ids.memAgent}/info`));

  await page.getByTestId('agent-tab-comments').click();
  const box = page.getByTestId('agent-comments');
  await expect(box.getByTestId('comments-empty')).toBeVisible({ timeout: 20_000 });
  await box.getByTestId('comment-input').fill(`It forgot the harbour once (${RUN}).`);
  await box.getByTestId('comment-submit').click();
  await expect(box.getByTestId('comment-row')).toHaveCount(1, { timeout: 20_000 });
  await box.getByTestId('comment-input').fill(`Second note ${RUN}`);
  await box.getByTestId('comment-input').press('Control+Enter');
  await expect(box.getByTestId('comment-row')).toHaveCount(2, { timeout: 20_000 });
  await box.getByTestId('comment-row').filter({ hasText: 'forgot the harbour' }).getByTestId('comment-resolve').click();
  await expect(box.getByTestId('comment-row')).toHaveCount(1, { timeout: 20_000 });
  await box.getByTestId('comments-toggle-resolved').click();
  await expect(box.locator('[data-testid="comment-row"][data-resolved="1"]')).toHaveCount(1);
  await shot(page, '05-comments');
  await box.getByTestId('comment-row').filter({ hasText: 'Second note' }).getByTestId('comment-delete').click();
  await expect(box.getByTestId('comment-row').filter({ hasText: 'Second note' })).toHaveCount(0, { timeout: 20_000 });
  const comments = (await api(page, 'GET', `/api/agents/${ids.memAgent}/comments`)).json.data as any[];
  expect(comments).toHaveLength(1);
  expect(comments[0].is_resolved).toBe(true);

  await star.click();
  await expect(star).toHaveAttribute('data-on', '0', { timeout: 20_000 });
  const favs = (await api(page, 'GET', '/api/agents/favorites')).json.data as any[];
  expect(favs.some((f) => f.agent_id === ids.memAgent)).toBe(false);
});

test('global search: shortcut and click, an agent, a page and a run, by keyboard', async ({ page }) => {
  test.skip(!ids.memAgent, 'needs the memory agent');
  await go(page, '/dashboard');
  const palette = page.getByTestId('command-palette');
  const input = page.getByTestId('command-palette-input');

  // by shortcut, an agent, picked with the arrow keys
  await page.keyboard.press('Control+k');
  await expect(palette).toBeVisible();
  await input.fill(MEM_AGENT);
  const agentItem = page.locator(`[data-testid="command-palette-item"][data-category="Agents"]`).filter({ hasText: MEM_AGENT });
  await expect(agentItem).toBeVisible({ timeout: 20_000 });
  const items = page.getByTestId('command-palette-item');
  const idx = await items.evaluateAll((els, name) => els.findIndex((e) => e.textContent?.includes(name as string)), MEM_AGENT);
  for (let i = 0; i < idx; i++) await input.press('ArrowDown');
  await expect(items.nth(idx)).toHaveAttribute('data-selected', 'true');
  await shot(page, '06-palette-agent');
  await input.press('Enter');
  await page.waitForURL(new RegExp(`/agents/${ids.memAgent}/info`));
  await expect(palette).toHaveCount(0);

  // by click, a page
  await page.getByTestId('open-search').click();
  await expect(palette).toBeVisible();
  await input.fill('archives');
  await expect(page.locator('[data-testid="command-palette-item"][data-href="/admin/archives"]')).toBeVisible({ timeout: 20_000 });
  await page.locator('[data-testid="command-palette-item"][data-href="/admin/archives"]').click();
  await page.waitForURL(/\/admin\/archives/);

  // a run, by what it was asked
  await page.keyboard.press('Control+k');
  await input.fill(HARBOUR);
  const run = page.locator('[data-testid="command-palette-item"][data-category="Runs"]').first();
  await expect(run).toBeVisible({ timeout: 20_000 });
  await run.hover();
  await input.press('Enter');
  await page.waitForURL(/\/executions\/[0-9a-f-]{36}/);
  await expect(page.getByText(HARBOUR).first()).toBeVisible({ timeout: 20_000 });

  // Escape closes, nonsense says nothing found
  await page.keyboard.press('Control+k');
  await input.fill(`zzqx-${RUN}`);
  await expect(page.getByTestId('command-palette-empty')).toBeVisible({ timeout: 20_000 });
  await input.press('Escape');
  await expect(palette).toHaveCount(0);
});

test('a run on a model nobody knows any more lands in the DLQ and replays after the fix', async ({ page }) => {
  test.setTimeout(15 * 60_000);
  // a model the platform only knows from its pricing row
  await nav(page, '/admin/llm-pricing');
  await page.getByLabel('Model id').fill(DLQ_MODEL);
  await page.getByLabel('Provider').selectOption('openai');
  await page.getByLabel('Price per million input tokens ($)', { exact: true }).fill('0.1');
  await page.getByLabel('Price per million output tokens ($)', { exact: true }).fill('0.2');
  await page.getByTestId('add-pricing-submit').click();
  await expect(page.getByTestId(`row-${DLQ_MODEL}`)).toBeVisible({ timeout: 20_000 });
  ids.price = ((await api(page, 'GET', '/api/admin/llm-pricing')).json.data.rows as any[]).find((r) => r.model === DLQ_MODEL).id;

  ids.dlqAgent = await buildAgent(page, {
    name: DLQ_AGENT,
    prompt: 'Reply with exactly one short sentence that repeats the user message back.',
    model: DLQ_MODEL,
  });
  const first = await ask(page, `First check ${RUN}`);
  expect(first.length).toBeGreaterThan(0);

  // the pricing row is removed, the runtime forgets the model within its one minute cache
  await nav(page, '/admin/llm-pricing');
  await page.getByRole('button', { name: `Delete pricing for ${DLQ_MODEL}` }).click();
  await expect(page.getByTestId(`row-${DLQ_MODEL}`)).toHaveCount(0, { timeout: 20_000 });
  ids.price = undefined;
  await page.waitForTimeout(75_000);

  const input = `Dead letter check ${RUN}`;
  await go(page, `/agents/${ids.dlqAgent}/chat`);
  await page.getByTestId('chat-input').fill(input);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: 180_000 });

  await nav(page, '/admin/dlq');
  const card = page.locator(`[data-testid="dlq-card"][data-agent="${DLQ_AGENT}"]`).first();
  await expect(async () => {
    await page.getByRole('button', { name: 'Refresh' }).first().click();
    await expect(card).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 120_000 });
  await expect(card).toContainText(/Unknown model|uat-dlq/i);
  await card.getByRole('button', { name: 'Original input' }).click();
  await expect(card).toContainText(input);
  await expectReadable(page);
  await shot(page, '03-dlq-card');

  // the owner points the agent at a model that exists
  await go(page, `/builder?agent=${ids.dlqAgent}`);
  await page.getByTestId('config-tab-model').click({ timeout: 30_000 });
  await page.getByTestId('model-picker-select').selectOption('claude-haiku-4-5');
  await page.getByTestId('builder-save-draft').click();
  await expect.poll(async () => (await api(page, 'GET', `/api/agents/${ids.dlqAgent}`)).json.data.model_config.model, { timeout: 30_000 }).toBe('claude-haiku-4-5');

  await nav(page, '/admin/dlq');
  await card.getByTestId('dlq-replay').click();
  await expect(page.getByTestId('dlq-notice')).toContainText('Replay started', { timeout: 30_000 });
  const href = await page.getByTestId('dlq-notice-link').getAttribute('href');
  const replayId = href!.split('/').pop()!;
  await expect.poll(async () => (await api(page, 'GET', `/api/executions/${replayId}`)).json?.data?.status, { timeout: 240_000, intervals: [3_000] }).toBe('completed');
  await page.getByTestId('dlq-notice-link').click();
  await page.waitForURL(new RegExp(`/executions/${replayId}`));
  await expect(page.getByText(input).first()).toBeVisible({ timeout: 30_000 });
  await shot(page, '04-dlq-replayed');
  await nav(page, '/admin/dlq');
  await expect(card.getByTestId('dlq-replay-link')).toBeVisible({ timeout: 20_000 });
});

test('a pipeline shell answers commands, recalls history and completes words', async ({ page }) => {
  const agents = (await api(page, 'GET', '/api/agents?limit=100&sort=name&search=Customer%20Support%20Pipeline')).json.data as any[];
  const pipe = agents.find((a) => a.model_config?.mode === 'pipeline');
  test.skip(!pipe, 'no pipeline to drive');
  await go(page, `/agents/${pipe.id}/info`);
  await page.getByRole('link', { name: 'Shell' }).click();
  await page.waitForURL(/\/shell$/);
  const inputBox = page.getByTestId('shell-input');
  await page.getByTestId('shell-try').filter({ hasText: 'show workflow' }).click();
  const entries = page.getByTestId('shell-entry');
  await expect(entries).toHaveCount(1);
  await expect(entries.first()).toHaveAttribute('data-loading', '0', { timeout: 60_000 });
  await expect(entries.first()).not.toContainText('error:');
  await inputBox.fill('show runs');
  await inputBox.press('Enter');
  await expect(entries).toHaveCount(2);
  await expect(entries.nth(1)).toHaveAttribute('data-loading', '0', { timeout: 60_000 });
  await expect(entries.nth(1)).not.toContainText('error:');
  // up arrow brings back the last command
  await inputBox.press('ArrowUp');
  await expect(inputBox).toHaveValue('show runs');
  await inputBox.fill('');
  // Tab completes a verb
  await inputBox.fill('hel');
  await inputBox.press('Tab');
  await expect(inputBox).toHaveValue(/^help/);
  await inputBox.press('Enter');
  await expect(entries).toHaveCount(3);
  await expect(entries.nth(2)).toHaveAttribute('data-loading', '0', { timeout: 60_000 });
  // a typo is answered with a suggestion
  await inputBox.fill('shwo workflow');
  await inputBox.press('Enter');
  await expect(entries.nth(3)).toContainText(/did you mean|error/, { timeout: 60_000 });
  await expectReadable(page);
  await shot(page, '07-shell');
});

test('archives: run one, restore it, put the retention back', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  const table = 'ml_model_invocations';
  await nav(page, '/admin/archives');
  const days = page.getByTestId(`retention-days-${table}`);
  ids.retention = Number(await days.inputValue());
  await days.fill('1');
  await page.getByTestId(`retention-save-${table}`).click();
  await expect(page.getByTestId('archives-notice')).toContainText('keeps 1 days', { timeout: 20_000 });

  await page.getByTestId(`archive-trigger-${table}`).click();
  await page.getByRole('button', { name: 'Archive now' }).click();
  await expect(page.getByTestId('archives-notice')).toContainText(`Archive of ${table} started`, { timeout: 120_000 });
  const runs = (await api(page, 'GET', `/api/admin/archives?table=${table}&limit=1`)).json.data.items as any[];
  const run = runs[0];
  expect(run.status).toBe('completed');
  test.skip(run.rows_archived === 0, 'nothing old enough to archive in this tenant');
  await shot(page, '08-archive-run');

  await page.getByTestId(`archive-restore-${run.id}`).click();
  await page.getByRole('button', { name: 'Restore', exact: true }).click();
  await expect(page.getByTestId('archives-notice')).toContainText(`Restored ${run.rows_archived.toLocaleString()} row`, { timeout: 120_000 });
  await expect(page.getByTestId(`archive-restored-${run.id}`)).toBeVisible();
  const after = ((await api(page, 'GET', `/api/admin/archives?table=${table}&limit=5`)).json.data.items as any[]).find((r) => r.id === run.id);
  expect(after.restored_rows).toBe(run.rows_archived);
  await shot(page, '09-archive-restored');

  await days.fill(String(ids.retention));
  await page.getByTestId(`retention-save-${table}`).click();
  await expect(page.getByTestId('archives-notice')).toContainText(`keeps ${ids.retention} days`, { timeout: 20_000 });
  ids.retention = undefined;
});

test('audit log: find my own actions with the filters, check the trail', async ({ page }) => {
  await nav(page, '/admin/audit');
  await expect(page.getByTestId('audit-row').first()).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('audit-verify').click();
  await expect(page.getByTestId('audit-verify-result')).toBeVisible({ timeout: 60_000 });
  await page.getByTestId('audit-filter-actor').selectOption({ label: `Me (${ADMIN.email})` });
  await page.getByTestId('audit-filter-action').selectOption('audit.verified');
  const rows = page.getByTestId('audit-row');
  await expect(rows.first()).toHaveAttribute('data-action', 'audit.verified', { timeout: 20_000 });
  const me = (await api(page, 'GET', '/api/auth/me')).json.data.user.id;
  await expect(rows.first()).toHaveAttribute('data-actor', me);
  const actors = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-actor')));
  expect(new Set(actors)).toEqual(new Set([me]));
  await page.getByTestId('audit-filter-action').selectOption('');
  await page.getByTestId('audit-filter-q').fill(`zzqx-${RUN}`);
  await expect(page.getByTestId('audit-empty')).toContainText('Nothing matches', { timeout: 20_000 });
  await page.getByTestId('audit-filter-clear').click();
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '10-audit');
});

test('models catalogue: view and edit a model, then put it back', async ({ page }) => {
  await nav(page, '/admin/models');
  const row = page.getByTestId('ml-row-iris-sample');
  await expect(row).toBeVisible({ timeout: 20_000 });
  const before = ((await api(page, 'GET', '/api/ml-models')).json.data as any[]).find((m) => m.name === 'iris-sample');
  ids.mlId = before.id;
  ids.mlDesc = before.description || '';
  await row.getByTestId('ml-edit-iris-sample').click();
  const modal = page.getByTestId('ml-edit-modal');
  await expect(modal.getByTestId('ml-edit-description')).toHaveValue(ids.mlDesc);
  await modal.getByTestId('ml-edit-description').fill(`Iris sample checked by the depth spec ${RUN}`);
  await modal.getByTestId('ml-edit-tags').fill(`demo, uat-${RUN}`);
  await modal.getByTestId('ml-edit-save').click();
  await expect(row).toContainText(`checked by the depth spec ${RUN}`, { timeout: 20_000 });
  await expect(row).toContainText(`uat-${RUN}`);
  const after = (await api(page, 'GET', `/api/ml-models/${ids.mlId}`)).json.data;
  expect(after.tags).toContain(`uat-${RUN}`);
  await shot(page, '11-models-edited');
  await row.getByTestId('ml-edit-iris-sample').click();
  await modal.getByTestId('ml-edit-description').fill(ids.mlDesc);
  await modal.getByTestId('ml-edit-tags').fill((before.tags || []).join(', '));
  await modal.getByTestId('ml-edit-save').click();
  await expect(row).not.toContainText(`uat-${RUN}`, { timeout: 20_000 });
  ids.mlId = undefined;
  // the AI model list is there to read too
  await expect(page.getByTestId('llm-row-claude-haiku-4-5')).toBeVisible();
});

test('market data: add a source, test it, remove it', async ({ page }) => {
  await nav(page, '/admin/market-sources');
  await page.getByTestId('market-add').click();
  const modal = page.getByTestId('market-add-modal');
  await modal.getByTestId('market-add-save').click();
  await expect(modal.getByRole('alert')).toContainText('Give it a name');
  await modal.getByTestId('market-add-name').fill(SOURCE);
  await modal.getByTestId('market-add-url').fill('http://api.frankfurter.app/latest');
  await modal.getByTestId('market-add-save').click();
  await expect(modal.getByRole('alert')).toContainText('https://');
  await modal.getByTestId('market-add-url').fill('https://api.frankfurter.app/latest');
  await modal.getByTestId('market-add-save').click();
  const row = page.getByTestId(`market-row-${SOURCE}`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  const c = ((await api(page, 'GET', '/api/connectors')).json.data as any[]).find((x) => x.name === SOURCE);
  ids.connector = c.id;
  expect(c.config.category).toBe('market_data');
  // the add tests it straight away, test again by hand
  await row.getByTestId(`test-${SOURCE}`).click();
  await expect.poll(async () => ((await api(page, 'GET', `/api/connectors/${ids.connector}`)).json.data.last_test_at), { timeout: 60_000 }).toBeTruthy();
  const tested = (await api(page, 'GET', `/api/connectors/${ids.connector}`)).json.data;
  await expect(row).toContainText(tested.last_test_ok ? 'live' : 'unavailable', { timeout: 20_000 });
  await shot(page, '12-market-tested');
  await row.getByTestId(`remove-${SOURCE}`).click();
  await page.getByTestId('market-remove-confirm').click();
  await expect(row).toHaveCount(0, { timeout: 20_000 });
  expect((await api(page, 'GET', `/api/connectors/${ids.connector}`)).status).toBe(404);
  ids.connector = undefined;
});

test('observability: each action opens a working page', async ({ page }) => {
  await nav(page, '/observability');
  const hub = page.getByTestId('observability-hub');
  await expect(hub).toBeVisible();
  const internal = ['Open Executions', 'Open Analytics', 'Live Debug stream', 'Open Alerts', 'Review Queue'];
  for (const label of internal) {
    await go(page, '/observability');
    const link = page.getByRole('link', { name: label }).first();
    const href = await link.getAttribute('href');
    await link.click();
    await page.waitForURL((u) => u.pathname.startsWith(href!), { timeout: 20_000 });
    await expect(page.locator('main h1, main h2').first()).toBeVisible({ timeout: 20_000 });
    await expectReadable(page);
  }
  await go(page, '/observability');
  await page.getByTestId('observability-cluster-link').click();
  await page.waitForURL(/\/admin\/cluster/);
  await go(page, '/observability');
  const grafana = page.getByRole('link', { name: /Grafana Tempo/ });
  expect(await grafana.getAttribute('target')).toBe('_blank');
  expect(await grafana.getAttribute('href')).toMatch(/^https?:\/\/.+\/explore/);
});

test('Claude subscription: verify, switch off, back on', async ({ page }) => {
  await nav(page, '/admin/llm-settings');
  const card = page.getByTestId('claude-subscription-section');
  await expect(card.getByTestId('subscription-status-badge')).toHaveText('active', { timeout: 20_000 });
  await card.getByTestId('subscription-verify').click();
  await expect(card.getByTestId('subscription-verify-result')).toContainText('Verified', { timeout: 120_000 });
  await shot(page, '13-subscription-verified');
  const toggle = card.getByTestId('subscription-enabled-toggle');
  ids.subOff = true;
  try {
    await toggle.click();
    await expect(card.getByTestId('subscription-status-badge')).toHaveText('configured, off', { timeout: 20_000 });
    expect((await api(page, 'GET', '/api/admin/settings/subscription')).json.data.enabled).toBe(false);
  } finally {
    if (!(await toggle.isChecked())) await toggle.click();
    await expect(card.getByTestId('subscription-status-badge')).toHaveText('active', { timeout: 20_000 });
  }
  ids.subOff = false;
  expect((await api(page, 'GET', '/api/admin/settings/subscription')).json.data.enabled).toBe(true);
});

test('cognify: a 0 budget stops the next job with a message, then put back', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  const kbs = ((await api(page, 'GET', '/api/knowledge-bases?limit=100')).json.data as any[]).filter((k) => k.status === 'ready' && k.doc_count > 0);
  test.skip(!kbs.length, 'no knowledge base with documents');
  const kb = kbs[0];
  await nav(page, '/settings/cognify');
  const budget = page.getByTestId('cognify-budget');
  const cfg = (await api(page, 'GET', '/api/knowledge/cognify-config')).json.data;
  ids.budget = cfg.daily_budget_usd;
  await budget.fill('0');
  await page.getByTestId('cognify-save').click();
  await expect(page.getByTestId('cognify-saved')).toBeVisible({ timeout: 20_000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('cognify-budget')).toHaveValue('0', { timeout: 20_000 });

  await go(page, `/knowledge/${kb.id}/engine`);
  await page.getByTestId('run-cognify').click();
  const failed = page.locator('[data-testid="cognify-job"][data-status="failed"]').filter({ hasText: 'budget' }).first();
  await expect(async () => {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(failed).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 180_000 });
  await expect(failed.getByTestId('cognify-job-error')).toContainText('Daily Cognify budget of $0.00 is used up');
  await shot(page, '14-cognify-budget-stop');

  await nav(page, '/settings/cognify');
  await page.getByTestId('cognify-budget').fill(ids.budget == null ? '' : String(ids.budget));
  await page.getByTestId('cognify-save').click();
  await expect(page.getByTestId('cognify-saved')).toBeVisible({ timeout: 20_000 });
  expect((await api(page, 'GET', '/api/knowledge/cognify-config')).json.data.daily_budget_usd).toBe(ids.budget ?? null);
  ids.budget = undefined;
});

test('phone width: these screens fit 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = ['/admin/dlq', '/admin/archives', '/admin/audit', '/admin/models', '/admin/market-sources', '/admin/rbac', '/observability', '/admin/llm-settings', '/settings/cognify'];
  if (ids.memAgent) routes.push(`/agents/${ids.memAgent}/info`, `/agents/${ids.memAgent}/memories`);
  for (const r of routes) {
    await go(page, r);
    await page.waitForTimeout(800);
    await expectFitsPhone(page, r);
    await shot(page, `phone-${r.replace(/[^a-z0-9]+/gi, '-')}`);
  }
  await page.getByTestId('open-search').click();
  await expect(page.getByTestId('command-palette-input')).toBeFocused();
  await page.getByTestId('command-palette-input').fill('arch');
  await page.waitForTimeout(600);
  await expectFitsPhone(page, 'search palette');
  await shot(page, 'phone-palette');
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await signIn(page, ADMIN);
  if (ids.subOff) await api(page, 'PATCH', '/api/admin/settings/llm.subscription.enabled', { value: 'true' });
  if (ids.budget !== undefined) {
    const cfg = (await api(page, 'GET', '/api/knowledge/cognify-config')).json.data;
    await api(page, 'PUT', '/api/knowledge/cognify-config', { ...cfg, daily_budget_usd: ids.budget });
  }
  if (ids.retention) await api(page, 'PUT', '/api/admin/archives/retention-policies/ml_model_invocations', { retention_days: ids.retention, enabled: true });
  if (ids.price) await api(page, 'DELETE', `/api/admin/llm-pricing/${ids.price}`);
  if (ids.connector) await api(page, 'DELETE', `/api/connectors/${ids.connector}`);
  for (const id of [ids.memAgent, ids.dlqAgent]) if (id) await api(page, 'DELETE', `/api/agents/${id}`);
  await ctx.close();
});
