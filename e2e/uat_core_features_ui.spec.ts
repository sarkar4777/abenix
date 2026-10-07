/**
 * The features fixed this release, from the screens only, as a new user would use them.
 *
 *   1. Persona KB      note + .md upload, Use in an agent, publish, chat answers from the note, delete the note
 *   2. ML Models       sample iris model, good and bad predictions, invocations, corrupt upload, delete, Use in Agent preset
 *   3. BPM Analyzer    run the sample, thread in the list, ?thread= restores it, plain error if the LLM is out
 *   4. Settings        avatar upload and remove, notification toggle survives a reload, phone section picker
 *   5. Tools           search, expand, full description and arguments, portfolio entries
 *   6. Alerts + Atlas  readable failure groups or empty state, Atlas History panel
 *   7. Phone width     no sideways scroll on the main pages at 390px
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_core_features_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const SCOPE = `uat-${RUN}`;
const HUB = `NBP-${RUN}`;
const AGENT = `Persona assistant ${RUN}`;
const BAD_MODEL = `corrupt-${RUN}`;
const BPM_TITLE = 'Vendor invoice approval (sample)';

const DIR = path.join(__dirname, 'uat_core_features_ui');
const FIX = path.join(DIR, 'fixtures');
const SHOTS = path.join(DIR, 'shots');
const LLM_MS = 300_000;

const ids: { agent?: string; badModel?: string; thread?: string; atlas?: string; avatarBefore?: string | null } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
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

async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const headers: Record<string, string> = { Authorization: `Bearer ${tok}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers,
    data: body === undefined ? undefined : JSON.stringify(body),
  });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function chat(page: Page, message: string, timeoutMs = LLM_MS) {
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

async function openScope(page: Page) {
  await go(page, '/persona');
  await page.getByTestId('persona-scopes').getByRole('button', { name: SCOPE, exact: true }).click();
  await expect(page.getByText(`Items in scope "${SCOPE}"`)).toBeVisible();
}

// the list does not poll, so reload until the item reads ready
async function waitReady(page: Page, title: string) {
  const item = page.getByTestId('persona-item').filter({ hasText: title });
  if (await item.filter({ hasText: 'ready' }).count()) return;
  await expect(async () => {
    await openScope(page);
    await expect(item).toContainText('ready', { timeout: 5_000 });
  }).toPass({ timeout: 90_000 });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

// a message a person can read, not a stack trace or a JSON dump
function expectPlain(msg: string) {
  expect(msg.trim().length).toBeGreaterThan(0);
  expect(msg.length).toBeLessThan(800);
  expect(msg).not.toMatch(/Traceback|File "[^"]+", line \d+|^\s*[{[]\s*"|Exception:|\bat [\w.$]+ \(/);
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('Persona KB: a note and a file feed an agent that answers from them', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await go(page, '/persona');
  await expect(page.getByRole('heading', { name: 'Persona KB' })).toBeVisible();
  await expect(page.getByTestId('persona-howto')).toContainText('Use it in an agent');

  // a fresh scope so the empty state is what a new user sees
  await page.getByLabel('New scope').fill(SCOPE);
  await page.getByRole('button', { name: 'Add scope' }).click();
  await expect(page.getByText(`Items in scope "${SCOPE}"`)).toBeVisible();
  await expect(page.getByTestId('persona-empty')).toBeVisible({ timeout: 20_000 });
  await shot(page, '01-persona-empty');
  // no kubectl advice, the key is set from the admin screen
  await expect(page.getByText('abenix-secrets')).toHaveCount(0);
  const voiceLink = page.getByTestId('persona-voice-configure');
  if (await voiceLink.count()) await expect(voiceLink).toHaveAttribute('href', /\/admin\/tool-config#ELEVENLABS_API_KEY/);

  await page.getByRole('button', { name: '+ Add note' }).click();
  await expect(page.getByLabel('Note scope')).toHaveValue(SCOPE);
  await page.getByPlaceholder('Title', { exact: true }).fill(`Hub ${RUN}`);
  await page.getByPlaceholder(/Anything you want your bot to know/).fill(`My preferred hub is ${HUB}. I trade gas there every morning.`);
  await page.getByRole('button', { name: 'Save note' }).click();

  const note = page.getByTestId('persona-item').filter({ hasText: `Hub ${RUN}` });
  await expect(note).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('persona-error')).toHaveCount(0);
  await expect(note.getByTestId('persona-item-error')).toHaveCount(0);
  await waitReady(page, `Hub ${RUN}`);

  // a small markdown file into the same scope
  await page.getByPlaceholder(/Title \(optional/).fill(`Desk notes ${RUN}`);
  await expect(page.getByLabel('Upload scope')).toHaveValue(SCOPE);
  await page.getByLabel('File to upload').setInputFiles(path.join(FIX, 'desk-notes.md'));
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  const file = page.getByTestId('persona-item').filter({ hasText: `Desk notes ${RUN}` });
  await expect(file).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('persona-error')).toHaveCount(0);
  await waitReady(page, `Desk notes ${RUN}`);
  await expect(file.getByTestId('persona-item-error')).toHaveCount(0);
  await shot(page, '02-persona-items');

  const items = await api(page, 'GET', `/api/persona/items?scope=${encodeURIComponent(SCOPE)}`);
  const rows = (items.json?.data || []) as any[];
  expect(rows.map((r) => r.title)).toEqual(expect.arrayContaining([`Hub ${RUN}`, `Desk notes ${RUN}`]));
  for (const r of rows) {
    expect(r.status).toBe('indexed');
    expect(r.chunk_count).toBeGreaterThan(0);
  }

  // cross-feature: the builder opens with Persona RAG pinned to this scope
  const use = page.getByTestId('persona-use-in-agent');
  await expect(use).toHaveAttribute('href', new RegExp(`tool=persona_rag&persona_scope=${SCOPE}`));
  await use.click();
  await page.waitForURL(/\/builder\?.*tool=persona_rag/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-persona_rag"]')).toBeVisible({ timeout: 20_000 });
  await shot(page, '03-persona-builder');

  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Answers questions about me from my persona notes.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await expect(page.getByTestId('builder-system-prompt')).toHaveValue(new RegExp(`persona_rag with scope '${SCOPE}'`));

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.agent = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.agent).toBeTruthy();
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });

  const a = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(a.json.data.model_config.tools).toContain('persona_rag');

  const answer = await chat(page, 'What is my preferred hub?');
  console.log(`\n--- persona answer ---\n${answer}\n---`);
  expect(answer.toLowerCase()).toContain(HUB.toLowerCase());
  await shot(page, '04-persona-chat');

  // delete the note through its confirmation
  await openScope(page);
  const noteAgain = page.getByTestId('persona-item').filter({ hasText: `Hub ${RUN}` });
  await expect(noteAgain).toBeVisible({ timeout: 20_000 });
  await noteAgain.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(noteAgain).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId('persona-error')).toHaveCount(0);
  const after = await api(page, 'GET', `/api/persona/items?scope=${encodeURIComponent(SCOPE)}`);
  expect(((after.json?.data || []) as any[]).some((r) => r.title === `Hub ${RUN}`)).toBe(false);
});

test('ML Models: sample model predicts, bad input and a corrupt file get plain errors', async ({ page }) => {
  test.setTimeout(4 * 60_000);
  await go(page, '/ml-models');
  await expect(page.getByTestId('ml-howto')).toBeVisible();
  await page.getByTestId('ml-try-sample').click();
  const detail = page.getByTestId('ml-detail');
  await expect(detail).toContainText('iris-sample', { timeout: 60_000 });
  await expect(page.getByTestId('ml-status')).toHaveText('Ready');

  const list = await api(page, 'GET', '/api/ml-models');
  const iris = ((list.json?.data || []) as any[]).find((m) => m.name === 'iris-sample' && m.status === 'ready');
  expect(iris).toBeTruthy();
  const invBefore = await api(page, 'GET', `/api/ml-models/${iris.id}/invocations?limit=50`);
  const totalBefore = Number(invBefore.json?.data?.total ?? (invBefore.json?.data?.items || []).length);

  // the example row
  await page.getByRole('button', { name: 'Reset to example' }).click();
  await page.getByTestId('ml-predict').click();
  const result = page.getByTestId('ml-predict-result');
  await expect(result).toBeVisible({ timeout: 30_000 });
  await expect(result).toContainText('Predicted');
  await expect(page.getByTestId('ml-predict-error')).toHaveCount(0);
  await shot(page, '05-ml-predict-ok');

  // two values where four are expected
  await page.getByTestId('ml-predict-input').fill('{"features": [5.1, 3.5]}');
  await page.getByTestId('ml-predict').click();
  const predErr = page.getByTestId('ml-predict-error');
  await expect(predErr).toBeVisible({ timeout: 30_000 });
  await expect(predErr).toContainText('expects 4 features');
  expectPlain(await predErr.innerText());
  await shot(page, '06-ml-predict-wrong-count');

  await expect(page.getByText(/^[1-9]\d* shown$/)).toBeVisible({ timeout: 20_000 });
  await expect(async () => {
    const inv = await api(page, 'GET', `/api/ml-models/${iris.id}/invocations?limit=50`);
    const total = Number(inv.json?.data?.total ?? (inv.json?.data?.items || []).length);
    expect(total).toBeGreaterThan(totalBefore);
  }).toPass({ timeout: 20_000 });

  // cross-feature: Use in Agent opens the builder with the ML tool set to this model, then back out
  await page.getByTestId('ml-use-in-agent').click();
  await page.waitForURL(/\/builder\?.*tool=ml_model&model_name=iris-sample/, { timeout: 20_000 });
  await expect(page.locator('.react-flow__node[data-id="tool-ml_model"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('builder-name-button')).toContainText('iris-sample agent');
  await shot(page, '07-ml-builder-preset');
  await page.goBack();
  await page.waitForURL(/\/ml-models/, { timeout: 20_000 });

  // a file that is not a model
  await go(page, '/ml-models');
  await page.getByTestId('ml-file-input').setInputFiles(path.join(FIX, 'corrupt-model.joblib'));
  await page.locator('#ml-name').fill(BAD_MODEL);
  await page.getByTestId('ml-upload-submit').click();
  const upErr = page.getByTestId('ml-upload-error');
  await expect(upErr).toBeVisible({ timeout: 60_000 });
  expectPlain(await upErr.innerText());

  const reason = page.getByTestId('ml-error-reason');
  await expect(reason).toBeVisible({ timeout: 20_000 });
  await expect(reason).toContainText('could not be loaded');
  expectPlain(await reason.innerText());
  await expect(detail).toContainText(BAD_MODEL);
  await expect(detail).not.toContainText('ACTIVE');
  await expect(page.getByTestId('ml-use-in-agent')).toHaveCount(0);
  await expect(page.getByTestId('ml-deploy')).toHaveCount(0);
  await expect(page.getByTestId('ml-test-panel')).toHaveCount(0);
  const badRow = page.getByTestId('ml-model-row').filter({ hasText: BAD_MODEL });
  await expect(badRow).toContainText('Error');
  await expect(badRow).not.toContainText('ACTIVE');
  await shot(page, '08-ml-corrupt');

  const bad = ((await api(page, 'GET', '/api/ml-models')).json?.data || []).find((m: any) => m.name === BAD_MODEL);
  expect(bad?.status).toBe('error');
  ids.badModel = bad?.id;

  await page.getByRole('button', { name: 'Delete Version', exact: true }).click();
  const modal = page.getByRole('dialog');
  await expect(modal).toContainText(`Delete ${BAD_MODEL}`);
  await modal.getByRole('button', { name: 'Delete version', exact: true }).click();
  await expect(page.getByTestId('ml-model-row').filter({ hasText: BAD_MODEL })).toHaveCount(0, { timeout: 20_000 });
  const gone = ((await api(page, 'GET', '/api/ml-models')).json?.data || []).some((m: any) => m.name === BAD_MODEL);
  expect(gone).toBe(false);
  ids.badModel = undefined;
});

test('BPM Analyzer: the sample runs, shows in the list and reopens from its link', async ({ page }) => {
  test.setTimeout(8 * 60_000);
  await go(page, '/bpm-analyzer');
  await expect(page.getByTestId('bpm-empty-state')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('try-sample').click();

  // either the thread opens or an upload error banner explains why not
  const banner = page.getByTestId('bpm-banners').getByRole('alert');
  await expect.poll(async () => {
    if (/[?&]thread=/.test(page.url())) return 'thread';
    if (await banner.count()) return 'error';
    return '';
  }, { timeout: 120_000, intervals: [1_000] }).not.toBe('');

  if (!/[?&]thread=/.test(page.url())) {
    const msg = await banner.first().innerText();
    expectPlain(msg);
    test.info().annotations.push({ type: 'llm-unavailable', description: `BPM upload failed: ${msg}` });
    await shot(page, '09-bpm-upload-error');
    return;
  }
  ids.thread = new URL(page.url()).searchParams.get('thread') || '';
  expect(ids.thread).toBeTruthy();
  await expect(page.getByRole('heading', { level: 1 }).first()).toContainText(BPM_TITLE, { timeout: 30_000 });
  await shot(page, '09-bpm-analyzing');

  await expect.poll(async () => {
    const t = await api(page, 'GET', `/api/bpm-analyzer/threads/${ids.thread}`);
    return t.json?.data?.thread?.status || '';
  }, { timeout: LLM_MS, intervals: [5_000] }).not.toBe('analyzing');
  await expect(page.getByTestId('bpm-pending')).toHaveCount(0, { timeout: 30_000 });

  const t = await api(page, 'GET', `/api/bpm-analyzer/threads/${ids.thread}`);
  const status = t.json?.data?.thread?.status;
  const msgs = (t.json?.data?.messages || []) as any[];
  const lastReply = [...msgs].reverse().find((m) => m.role === 'assistant');
  const messages = page.getByTestId('bpm-messages');

  let succeeded = false;
  if (status === 'ready' && t.json?.data?.thread?.has_report) {
    succeeded = true;
    await expect(page.getByTestId('next-steps')).toBeVisible({ timeout: 30_000 });
    await expect(messages).toContainText('BPM PROCESS ANALYST');
    await expect(page.getByTestId('download-pdf')).toBeVisible();
  } else {
    const text = String(lastReply?.content || '').replace(/^\[error\]\s*/, '');
    expect(text, 'a failed analysis must leave a reply that says why').toBeTruthy();
    expectPlain(text);
    await expect(messages).toContainText(text.slice(0, 60), { timeout: 30_000 });
    test.info().annotations.push({ type: 'llm-unavailable', description: `BPM analysis ${status}: ${text.slice(0, 300)}` });
  }
  await shot(page, '10-bpm-result');

  // the thread is in the list on the left
  const drawer = page.getByTestId('thread-drawer');
  await expect(drawer.getByTestId('thread-item').filter({ hasText: BPM_TITLE }).first()).toBeVisible();

  // a reload from the link restores the same thread
  await go(page, `/bpm-analyzer?thread=${ids.thread}`);
  await expect(page.getByTestId('bpm-empty-state')).toHaveCount(0);
  await expect(page.getByRole('heading', { level: 1 }).first()).toContainText(BPM_TITLE, { timeout: 30_000 });
  await expect(messages).toBeVisible();
  if (succeeded) await expect(page.getByTestId('next-steps')).toBeVisible({ timeout: 30_000 });
  else await expect(messages).toContainText(String(lastReply.content).replace(/^\[error\]\s*/, '').slice(0, 60));
  expect(page.url()).toContain(`thread=${ids.thread}`);
  await shot(page, '11-bpm-restored');
});

test('Settings: picture upload and remove, notification toggle persists, phone section picker', async ({ page }) => {
  const prof = await api(page, 'GET', '/api/settings/profile');
  ids.avatarBefore = prof.json?.data?.avatar_url ?? null;

  await go(page, '/settings/profile');
  await expect(page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible();
  await page.getByTestId('avatar-file').setInputFiles(path.join(FIX, 'avatar.png'));
  const img = page.getByTestId('avatar-preview');
  await expect(img).toBeVisible({ timeout: 30_000 });
  await expect(img).toHaveAttribute('src', /\/api\/settings\/avatars\//);
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth), { timeout: 15_000 }).toBeGreaterThan(0);
  const up = await api(page, 'GET', '/api/settings/profile');
  expect(up.json?.data?.avatar_url).toMatch(/^\/api\/settings\/avatars\//);
  await shot(page, '12-settings-avatar');

  await page.getByTestId('avatar-remove').click();
  await expect(page.getByTestId('avatar-preview')).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId('avatar-remove')).toHaveCount(0);
  const cleared = await api(page, 'GET', '/api/settings/profile');
  expect(cleared.json?.data?.avatar_url ?? null).toBeNull();

  // notification preference survives a reload
  await go(page, '/settings/notifications');
  const sw = page.getByTestId('pref-team_updates');
  await expect(sw).toBeVisible({ timeout: 20_000 });
  const was = (await sw.getAttribute('aria-checked')) === 'true';
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', String(!was));
  await page.getByTestId('notif-save').click();
  await expect(page.getByText('Preferences saved', { exact: true })).toBeVisible({ timeout: 20_000 });
  await go(page, '/settings/notifications');
  await expect(page.getByTestId('pref-team_updates')).toHaveAttribute('aria-checked', String(!was), { timeout: 20_000 });
  const prefs = await api(page, 'GET', '/api/settings/notifications');
  expect(prefs.json?.data?.team_updates).toBe(!was);
  await shot(page, '13-settings-notifications');
  // put it back the same way
  await page.getByTestId('pref-team_updates').click();
  await page.getByTestId('notif-save').click();
  await expect(page.getByText('Preferences saved', { exact: true })).toBeVisible({ timeout: 20_000 });

  // on a phone the side nav gives way to a section picker
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/settings/profile');
  const picker = page.getByTestId('settings-section-select');
  await expect(picker).toBeVisible({ timeout: 20_000 });
  await expect(picker).toHaveValue('/settings/profile');
  await expect(page.locator('aside nav a[href="/settings/api-keys"]').first()).toBeHidden();
  await shot(page, '14-settings-phone-picker');
  await picker.selectOption('/settings/notifications');
  await page.waitForURL(/\/settings\/notifications/, { timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('settings-section-select')).toHaveValue('/settings/notifications');
});

test('Tools catalogue: search, open a tool, see its description, arguments and portfolio entries', async ({ page }) => {
  const tools = ((await api(page, 'GET', '/api/tools')).json?.data || []) as any[];
  const persona = tools.find((t) => t.id === 'persona_rag');
  expect(persona, 'persona_rag is in the catalogue').toBeTruthy();

  await go(page, '/tools');
  await expect(page.getByRole('heading', { name: 'Tools catalogue' })).toBeVisible();
  await page.getByLabel('Search tools').fill('persona_rag');
  const row = page.getByTestId('tool-row-persona_rag');
  await expect(row).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('tool-toggle-persona_rag').click();
  const details = page.getByTestId('tool-details-persona_rag');
  await expect(details).toBeVisible();
  await expect(details).toContainText('Arguments');
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim();
  const head = norm(String(persona.description || '')).slice(0, 30);
  if (head) expect(norm(await details.innerText())).toContain(head);
  const props = Object.keys(persona.input_schema?.properties || {});
  for (const p of props.slice(0, 5)) await expect(details.locator('code', { hasText: p }).first()).toBeVisible();
  await expect(page.getByTestId('tool-use-persona_rag')).toHaveAttribute('href', /\/builder\?tool=persona_rag/);
  await shot(page, '15-tools-details');

  const portfolio = tools.filter((t) => String(t.id).startsWith('portfolio_'));
  if (!portfolio.length) {
    test.info().annotations.push({ type: 'skipped-check', description: 'no active portfolio schema, so no Portfolio: entries to check' });
    return;
  }
  await page.getByLabel('Search tools').fill('Portfolio:');
  for (const t of portfolio.slice(0, 3)) {
    await expect(page.getByTestId(`tool-row-${t.id}`)).toContainText(String(t.name));
    expect(String(t.name)).toMatch(/^Portfolio: /);
  }
  await page.getByTestId(`tool-toggle-${portfolio[0].id}`).click();
  await expect(page.getByTestId(`tool-details-${portfolio[0].id}`)).toContainText('operation');
  await shot(page, '16-tools-portfolio');
});

test('Alerts and Atlas: failure groups read well, Atlas history opens', async ({ page }) => {
  await go(page, '/alerts');
  await expect(page.getByRole('heading', { name: 'Alerts', exact: true })).toBeVisible();
  const groups = ((await api(page, 'GET', '/api/analytics/failures?hours=24')).json?.data || []) as any[];
  if (!groups.length) {
    await expect(page.getByText('No failed runs in the last 24 hours.')).toBeVisible({ timeout: 20_000 });
  } else {
    const g = groups[0];
    const btn = page.getByRole('button', { name: new RegExp(String(g.failure_code)) }).first();
    await expect(btn).toBeVisible({ timeout: 20_000 });
    await expect(btn).not.toContainText('No description for this cause yet');
    await btn.click();
    await expect(page.getByText('Sample error message')).toBeVisible();
    const affected = page.getByText(/^Affected agents \(\d+\)$/).locator('..');
    await expect(affected.locator('[aria-label="Loading agent name"]')).toHaveCount(0, { timeout: 20_000 });
    // agents show by name, never as a bare id
    expect(await affected.innerText()).not.toMatch(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i);
  }
  await shot(page, '17-alerts');

  await go(page, '/atlas');
  await expect(page.getByTestId('atlas-root')).toBeVisible();
  const graphs = ((await api(page, 'GET', '/api/atlas/graphs')).json?.data?.graphs || []) as any[];
  if (!graphs.length) {
    await page.getByRole('button', { name: 'New atlas' }).click();
    await page.getByPlaceholder('e.g. Trade-lifecycle ontology').fill(`UAT atlas ${RUN}`);
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(`UAT atlas ${RUN}`, { timeout: 20_000 });
    const after = ((await api(page, 'GET', '/api/atlas/graphs')).json?.data?.graphs || []) as any[];
    ids.atlas = after.find((x) => x.name === `UAT atlas ${RUN}`)?.id;
  }
  await expect(page.getByTestId('atlas-node-count')).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'History', exact: true }).click();
  const hist = page.getByTestId('atlas-history');
  await expect(hist).toBeVisible();
  await expect(hist).toContainText(/v\d+|No snapshots yet/, { timeout: 20_000 });
  await shot(page, '18-atlas-history');
  await page.getByRole('button', { name: 'Close history' }).click();
  await expect(hist).toHaveCount(0);
});

test('Phone width: no sideways scroll on the main pages', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = ['/persona', '/ml-models', '/bpm-analyzer', '/portfolio-schemas', '/chat', '/settings/profile'];
  const wide: string[] = [];
  for (const [i, route] of routes.entries()) {
    await go(page, route);
    await page.waitForTimeout(1_500);
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    await shot(page, `${19 + i}-phone${route.replace(/\//g, '-')}`);
    if (m.sw > m.iw + 1) wide.push(`${route} scrollWidth=${m.sw} innerWidth=${m.iw}`);
  }
  expect(wide, wide.join('\n')).toEqual([]);
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await signIn(page);
  if (ids.agent) await api(page, 'DELETE', `/api/agents/${ids.agent}`);
  const left = ((await api(page, 'GET', `/api/persona/items?scope=${encodeURIComponent(SCOPE)}`)).json?.data || []) as any[];
  for (const it of left) await api(page, 'DELETE', `/api/persona/items/${it.id}`);
  if (ids.badModel) await api(page, 'DELETE', `/api/ml-models/${ids.badModel}`);
  if (ids.thread) await api(page, 'DELETE', `/api/bpm-analyzer/threads/${ids.thread}`);
  if (ids.atlas) await api(page, 'DELETE', `/api/atlas/graphs/${ids.atlas}`);
  // only a typed link can be put back, an uploaded picture was replaced on the server
  if (ids.avatarBefore && !ids.avatarBefore.startsWith('/api/')) {
    await api(page, 'PUT', '/api/settings/profile', { avatar_url: ids.avatarBefore });
  }
  await page.close();
});
