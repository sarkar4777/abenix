/**
 * Meetings from the screens only: rehearsal, then a real LiveKit room.
 *
 *   1. Persona      add a note the bot can cite
 *   2. Create       new meeting, start is blocked until a topic is set, set the scope
 *   3. Rehearse     typed turns: in scope with a citation, outside scope declined,
 *                   pricing handed back and answered, latency shown, nothing live touched
 *   4. Live         a second Chromium with a fake mic joins the room from the product's join page,
 *                   the bot is started from the meeting page and shows in the participant list,
 *                   the wav asks a question, the reply lands in the transcript, an off-topic
 *                   question is declined, End meeting saves the transcript and summary
 *   5. Phone width  meeting and rehearsal pages at 390 px
 *   6. Delete       with confirmation
 *
 * When a live piece cannot work here (no LiveKit keys, no speech to text key, LiveKit not
 * reachable from this machine) the test asserts the product's own explanation and records
 * what was not verified as a test annotation.
 *
 * The fake mic plays e2e/fixtures/meetings/question.wav once. Rebuild it offline with
 *   powershell -ExecutionPolicy Bypass -File e2e/fixtures/meetings/make-question-wav.ps1
 * Any 16 kHz mono wav with the same two questions works, for example from espeak-ng or say.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_meetings_ui.spec.ts --workers=1
 */
import { test, expect, chromium, type Page, type Browser } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const SHOTS = path.join(__dirname, 'uat_meetings_ui', 'shots');
const WAV = path.join(__dirname, 'fixtures', 'meetings', 'question.wav');
const BOT_WAIT = 4 * 60_000;
const STAMP = Date.now().toString(36);
const NOTE_TITLE = 'Project roadmap status (meetings UAT)';
const NOTE_TEXT = 'Roadmap update: the authentication module ships in October and the billing rework moves to the first quarter.';

const state: { meetingId?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });
test.setTimeout(30 * 60_000);

function note(kind: string, description: string) {
  test.info().annotations.push({ type: kind, description });
  console.log(`[${kind}] ${description}`);
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
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

async function api(page: Page, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  // another rollout can drop the local forward for a few seconds, its wrapper brings it back
  let res;
  try {
    res = await page.request.get(`${API}${p}`, { headers: { Authorization: `Bearer ${tok}` } });
  } catch {
    await page.waitForTimeout(8_000);
    res = await page.request.get(`${API}${p}`, { headers: { Authorization: `Bearer ${tok}` } });
  }
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), data: json?.data ?? json };
}

async function noSideScroll(page: Page) {
  const over = await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth);
  expect(over, 'page scrolls sideways').toBeLessThanOrEqual(1);
}

async function sayInRehearsal(page: Page, text: string) {
  const before = await page.getByTestId('rehearsal-bot-line').count();
  await page.getByTestId('rehearsal-input').fill(text);
  await page.getByTestId('rehearsal-send').click();
  await expect(page.getByTestId('rehearsal-turn').filter({ hasText: text.slice(0, 30) })).toBeVisible({ timeout: BOT_WAIT });
  return before;
}

test('a persona note the bot can cite', async ({ page }) => {
  await signIn(page);
  await go(page, '/persona');
  // one stable note, so repeated runs do not pile up copies
  const existing = page.getByTestId('persona-item').filter({ hasText: NOTE_TITLE });
  await page.getByTestId('persona-item').first().or(page.getByTestId('persona-empty')).waitFor({ timeout: 30_000 });
  if (await existing.count()) return;
  await page.getByRole('button', { name: '+ Add note' }).click();
  await page.getByPlaceholder('Title', { exact: true }).fill(NOTE_TITLE);
  await page.getByPlaceholder(/Anything you want your bot to know/).fill(NOTE_TEXT);
  await page.getByRole('button', { name: 'Save note' }).click();
  await expect(page.getByTestId('persona-item').filter({ hasText: NOTE_TITLE })).toBeVisible({ timeout: 60_000 });
});

test('create a meeting, start waits for a topic, set the scope', async ({ page }) => {
  await signIn(page);
  await go(page, '/meetings');
  await page.getByTestId('new-meeting-btn').click();
  await expect(page.getByTestId('new-meeting-create')).toBeDisabled();
  await page.getByTestId('new-meeting-title').fill(`UAT meeting ${STAMP}`);
  await page.getByTestId('new-meeting-create').click();
  await page.waitForURL(/\/meetings\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  state.meetingId = page.url().split('/meetings/')[1];

  // no topic yet: start is disabled and says why
  await expect(page.getByTestId('start-bot')).toBeDisabled();
  await expect(page.getByTestId('start-blocked')).toContainText('at least one topic');

  await page.getByTestId('edit-scope').click();
  await page.getByTestId('scope-allow').fill('project roadmap');
  await page.getByTestId('scope-allow').press('Enter');
  await page.getByTestId('scope-defer').fill('pricing');
  await page.getByTestId('scope-defer').press('Enter');
  await page.getByTestId('save-scope').click();
  await expect(page.getByTestId('scope-badge')).toHaveAttribute('data-set', 'true', { timeout: 20_000 });
  await expect(page.getByTestId('meeting-status')).toHaveText('authorized');
  await expect(page.getByTestId('start-bot')).toBeEnabled();
  const m = (await api(page, `/api/meetings/${state.meetingId}`)).data;
  expect(m.scope_allow).toEqual(['project roadmap']);
  expect(m.scope_defer).toEqual(['pricing']);
  await shot(page, '01-meeting-scoped');
});

test('rehearse: answers in scope with a citation, declines off topic, hands pricing back', async ({ page }) => {
  await signIn(page);
  await go(page, `/meetings/${state.meetingId}`);
  await page.getByTestId('rehearse-meeting').click();
  await page.waitForURL(/\/rehearse$/);
  await expect(page.getByTestId('rehearsal-banner')).toContainText('This is a rehearsal');
  await page.getByTestId('rehearsal-start').click();
  await expect(page.getByTestId('rehearsal-status')).toBeVisible();

  // in scope, from the persona note
  let before = await sayInRehearsal(page, 'Hey assistant, what is the status of the project roadmap?');
  await expect(page.getByTestId('rehearsal-scope').filter({ hasText: 'inside' }).first()).toBeVisible({ timeout: BOT_WAIT });
  await expect(page.getByTestId('rehearsal-bot-line')).toHaveCount(before + 1, { timeout: BOT_WAIT });
  const cites = page.getByTestId('rehearsal-citations');
  if (await cites.count()) {
    await expect(cites.first()).toContainText(/found/);
    note('verified', `rehearsal cited persona notes: ${(await cites.first().innerText()).replace(/\s+/g, ' ').slice(0, 160)}`);
  } else {
    note('not-verified', 'the agent answered without calling persona_rag, so no citation was shown');
  }
  await expect(page.getByTestId('rehearsal-latency').first()).toContainText('replied in');
  note('verified', `rehearsal reply latency: ${await page.getByTestId('rehearsal-latency').first().innerText()}`);
  await shot(page, '02-rehearsal-in-scope');

  // outside scope
  before = await sayInRehearsal(page, 'Hey assistant, who do you think will win the football match tonight?');
  await expect(page.locator('[data-testid="rehearsal-scope"][data-decision="decline"]').first()).toBeVisible({ timeout: BOT_WAIT });
  await expect(page.getByTestId('rehearsal-bot-line')).toHaveCount(before + 1, { timeout: BOT_WAIT });
  await shot(page, '03-rehearsal-declined');

  // handed back, then answered by the user
  before = await sayInRehearsal(page, 'Hey assistant, can you confirm the pricing for us today?');
  await expect(page.getByTestId('rehearsal-deferral')).toBeVisible({ timeout: BOT_WAIT });
  await shot(page, '04-rehearsal-handed-back');
  await page.getByTestId('rehearsal-deferral-answer').fill('Pricing comes in the written proposal on Friday.');
  await page.getByTestId('rehearsal-deferral-send').click();
  await expect(page.getByTestId('rehearsal-deferral-done').first()).toContainText('You answered', { timeout: 30_000 });
  await expect(page.getByTestId('rehearsal-bot-line').last()).toContainText(/proposal|Friday/i, { timeout: BOT_WAIT });

  await page.getByTestId('rehearsal-end').click();
  await expect(page.getByTestId('rehearsal-status')).toHaveAttribute('data-status', 'closed', { timeout: BOT_WAIT });
  await shot(page, '05-rehearsal-ended');

  // the real meeting was never touched
  const m = (await api(page, `/api/meetings/${state.meetingId}`)).data;
  expect(m.status).toBe('authorized');
  expect(m.transcript || []).toHaveLength(0);
});

test('live: a fake participant joins the room, the bot answers and declines, end saves it', async ({ page }) => {
  await signIn(page);
  const ready = (await api(page, '/api/meetings/readiness')).data;
  await go(page, `/meetings/${state.meetingId}`);

  if (!ready.livekit_ready) {
    await expect(page.getByTestId('meetings-readiness')).toContainText('LiveKit');
    await expect(page.getByTestId('start-bot')).toBeDisabled();
    await expect(page.getByTestId('start-blocked')).toContainText('LiveKit');
    await expect(page.getByTestId('join-meeting')).toHaveAttribute('aria-disabled', 'true');
    note('not-verified', `live join skipped, LiveKit keys missing: ${ready.missing.join(', ')}. The page explains it.`);
    return;
  }
  if (!ready.stt_ready) {
    await expect(page.getByTestId('meetings-voice-readiness')).toContainText('speech to text');
  }

  let human: Browser | null = null;
  try {
    human = await chromium.launch({
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        `--use-file-for-fake-audio-capture=${WAV}%noloop`,
        '--autoplay-policy=no-user-gesture-required',
      ],
    });
    const ctx = await human.newContext({ viewport: { width: 1280, height: 860 }, permissions: ['microphone'] });
    const room = await ctx.newPage();
    await signIn(room);
    await go(room, `/meetings/${state.meetingId}/join`);
    await room.getByTestId('join-connect').click();
    const panel = room.getByTestId('join-panel');
    await expect(panel).toHaveAttribute('data-phase', /connected|error/, { timeout: 60_000 });
    if ((await panel.getAttribute('data-phase')) === 'error') {
      // one retry, a rollout elsewhere may have dropped the LiveKit forward for a moment
      await room.waitForTimeout(8_000);
      await room.getByTestId('join-connect').click();
      await expect(panel).toHaveAttribute('data-phase', /connected|error/, { timeout: 60_000 });
    }
    if ((await panel.getAttribute('data-phase')) === 'error') {
      await expect(room.getByTestId('join-error')).toContainText('could not reach the LiveKit server');
      note('not-verified', `browser could not reach LiveKit: ${await room.getByTestId('join-error').innerText()}`);
      await shot(room, '06-join-error');
      return;
    }
    note('verified', 'human joined the LiveKit room from the product join page');

    // start the bot from the meeting page, then see it in both participant lists
    await page.getByTestId('start-bot').click();
    await expect(page.getByTestId('meeting-status')).toHaveText('live', { timeout: 30_000 });
    await expect(room.locator('[data-testid="join-participant"][data-bot="true"]')).toBeVisible({ timeout: BOT_WAIT });
    await expect(page.locator('[data-testid="room-participant"][data-bot="true"]')).toBeVisible({ timeout: 60_000 });
    note('verified', 'bot joined the room and shows in the participant list');
    await shot(room, '06-room-with-bot');

    const botLines = page.getByTestId('transcript-bot-line');
    if (ready.stt_ready) {
      await room.getByTestId('join-mic').click();
      await expect(room.getByTestId('join-mic')).toHaveAttribute('data-on', 'true');
      await expect(page.getByTestId('transcript-line').filter({ hasText: /roadmap/i }).first()).toBeVisible({ timeout: BOT_WAIT });
      await expect(botLines.first()).toBeVisible({ timeout: BOT_WAIT });
      note('verified', `voice question heard, bot replied: ${(await botLines.first().innerText()).slice(0, 160)}`);
      await expect(page.locator('[data-testid="meeting-decision"][data-kind="decline"]').first()).toBeVisible({ timeout: BOT_WAIT });
      await expect.poll(() => botLines.count(), { timeout: BOT_WAIT }).toBeGreaterThanOrEqual(2);
      note('verified', `spoken off-topic question was declined: ${(await botLines.nth(1).innerText()).slice(0, 160)}`);
    } else {
      // the product says why speech is not heard, chat still works
      await room.getByTestId('join-mic').click();
      await expect(page.locator('[data-testid="meeting-decision"][data-kind="notice"]').filter({ hasText: 'speech into text' }).first())
        .toBeVisible({ timeout: BOT_WAIT });
      note('not-verified', 'spoken question: no speech to text key, the decision log explains it. Using room chat instead.');
      await room.getByTestId('join-chat-input').fill('Hey assistant, what is the status of the project roadmap?');
      await room.getByTestId('join-chat-send').click();
      await expect(botLines.first()).toBeVisible({ timeout: BOT_WAIT });
      note('verified', `chat question in the live room, bot replied: ${(await botLines.first().innerText()).slice(0, 160)}`);
      const n = await botLines.count();
      await room.getByTestId('join-chat-input').fill('Hey assistant, who do you think will win the football match tonight?');
      await room.getByTestId('join-chat-send').click();
      await expect(page.locator('[data-testid="meeting-decision"][data-kind="decline"]').first()).toBeVisible({ timeout: BOT_WAIT });
      await expect(botLines).toHaveCount(n + 1, { timeout: BOT_WAIT });
      note('verified', 'off-topic chat question in the live room was declined');
    }
    if (!ready.tts_ready) note('not-verified', 'bot voice: no TTS key, replies went to the room chat');
    await expect(room.getByTestId('join-chat-line').first()).toBeVisible({ timeout: 60_000 });
    await shot(page, '07-live-transcript');

    // end gracefully, the bot writes a summary and everything is kept
    await page.getByTestId('end-meeting').click();
    await page.getByTestId('confirm-action').click();
    await expect(page.getByTestId('meeting-status')).toHaveText('done', { timeout: 30_000 });
    await expect(page.getByTestId('meeting-summary')).toHaveAttribute('data-state', 'summary', { timeout: BOT_WAIT });
    note('verified', `summary saved: ${(await page.getByTestId('meeting-summary').innerText()).slice(0, 200)}`);
    await page.reload();
    await expect(page.getByTestId('transcript-bot-line').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('meeting-summary')).toHaveAttribute('data-state', 'summary');
    const m = (await api(page, `/api/meetings/${state.meetingId}`)).data;
    expect(m.status).toBe('done');
    expect(m.finalized).toBe(true);
    expect(m.summary).toBeTruthy();
    expect(m.transcript_count).toBeGreaterThan(0);
    await shot(page, '08-ended-with-summary');
  } finally {
    await human?.close();
  }
});

test('meeting and rehearsal pages fit a phone', async ({ page }) => {
  await signIn(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of [`/meetings`, `/meetings/${state.meetingId}`, `/meetings/${state.meetingId}/rehearse`, `/meetings/${state.meetingId}/join`]) {
    await go(page, route);
    await page.waitForTimeout(800);
    await noSideScroll(page);
  }
  await go(page, `/meetings/${state.meetingId}/rehearse`);
  await shot(page, '09-rehearse-390');
});

test('delete asks first, then the meeting is gone', async ({ page }) => {
  await signIn(page);
  await go(page, `/meetings/${state.meetingId}`);
  await page.getByTestId('delete-meeting').click();
  await expect(page.getByTestId('confirm-action')).toBeVisible();
  await page.getByTestId('confirm-action').click();
  await page.waitForURL(/\/meetings$/, { timeout: 30_000 });
  expect((await api(page, `/api/meetings/${state.meetingId}`)).status).toBe(404);
});
