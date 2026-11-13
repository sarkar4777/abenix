/**
 * QuoteIQ end-to-end, driven as the sales-desk reviewer.
 *
 * The journey is: the platform probe is healthy, the inbox holds the example
 * emails, the next email is processed through the RFQ pipeline, its status and
 * line count match test-data/expected-outcomes.json, and a person reviews the
 * result — editing and sending a draft (the Abenix approval is signed), or
 * reading the internal escalation.
 *
 * Processing and review go through the QuoteIQ UI the way a reviewer does it.
 * The API is only read, to assert what was persisted.
 *
 * Run: npx playwright test e2e/uat_quoteiq.spec.ts
 *      (QUOTEIQ_BASE and QUOTEIQ_API move it off localhost:3008 / :8008)
 */

import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { artifactDir } from './uat_helpers/artifacts';

const WEB = process.env.QUOTEIQ_BASE || 'http://localhost:3008';
const API = process.env.QUOTEIQ_API || 'http://localhost:8008';
const SHOTS = artifactDir('quoteiq');

type Email = Record<string, any>;

const EXPECTED: Record<string, { status: string; lines: number }> = Object.fromEntries(
  (JSON.parse(fs.readFileSync(
    path.resolve(__dirname, '..', 'quoteiq', 'test-data', 'expected-outcomes.json'), 'utf8',
  )).emails as any[]).map((e) => [
    e.file.replace(/\.txt$/, ''),
    {
      status: { Success: 'success', 'Need customer clarification': 'clarification', Escalated: 'escalated' }[
        e.expected_status as string]!,
      lines: e.lines.length,
    },
  ]),
);

async function getData<T>(request: APIRequestContext, url: string): Promise<T | null> {
  const r = await request.get(url);
  if (!r.ok()) return null;
  const body = await r.json().catch(() => null);
  return ((body as any)?.data ?? null) as T | null;
}

/**
 * Was the run killed by an upstream provider rather than by the pipeline?
 * Reads the execution's own error, so a genuine failure is never waved
 * through as "the provider was down".
 */
async function providerFailure(request: APIRequestContext, email: Email): Promise<string | null> {
  const signatures = [
    /API key not valid/i, /API_KEY_INVALID/i, /rate.?limit/i, /429/, /insufficient_quota/i,
    /credit balance/i, /OAuth access token has been revoked/i, /overloaded/i,
  ];
  const haystacks = [String(email.error || '')];
  const executionId = email.run?.execution_id;
  const abenixApi = process.env.API || 'http://localhost:8000';
  if (executionId) {
    try {
      const login = await request.post(`${abenixApi}/api/auth/login`, {
        data: {
          email: process.env.AF_EMAIL || 'admin@abenix.dev',
          password: process.env.AF_PASSWORD || 'Admin123456',
        },
      });
      const token = (await login.json()).data.access_token;
      const ex = await request.get(`${abenixApi}/api/executions/${executionId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (ex.ok()) haystacks.push(JSON.stringify(await ex.json()).slice(0, 4000));
    } catch {
      /* fall back to the email's own error */
    }
  }
  for (const h of haystacks) {
    for (const sig of signatures) {
      const m = h.match(sig);
      if (m) return `${m[0]} (execution ${executionId || 'n/a'})`;
    }
  }
  return null;
}

async function resetFromTheMenu(page: Page) {
  await page.getByTestId('menu').click();
  await page.getByTestId('reset-example').click();
  await page.getByTestId('dialog-confirm').click();
  await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('totals')).toContainText('0 processed', { timeout: 15_000 });
}

test('quoteiq: the platform probe is honest about connectivity', async ({ request }) => {
  const p = await getData<any>(request, `${API}/api/qq/platform`);
  expect(p, 'platform probe answered').toBeTruthy();
  console.log(`  reachable=${p.reachable} pipeline=${p.pipeline_registered} drafter=${p.drafter_registered} key=${p.api_key_set}`);
  expect(p.api_key_set, 'QUOTEIQ_ABENIX_API_KEY is set').toBeTruthy();
  expect(p.reachable, `Abenix unreachable: ${p.detail}`).toBeTruthy();
  expect(p.pipeline_registered, `pipeline missing: ${p.detail}`).toBeTruthy();
  expect(p.drafter_registered, `drafter missing: ${p.detail}`).toBeTruthy();
});

test('quoteiq: the inbox holds every example email', async ({ request }) => {
  const rows = await getData<any[]>(request, `${API}/api/qq/emails`);
  expect(Array.isArray(rows), 'inbox loads').toBeTruthy();
  expect(rows!.map((r) => r.id).sort(), 'one row per example email').toEqual(Object.keys(EXPECTED).sort());
  for (const r of rows!) {
    expect(r.from_email, `${r.id} has a sender address`).toMatch(/@.+\.example$/);
    expect(r.subject, `${r.id} has a subject`).toBeTruthy();
  }
});

test('quoteiq: every view renders', async ({ page }) => {
  const first = Object.keys(EXPECTED).sort()[0];
  // Each page renders from the API after it loads, so wait for its first data.
  const views: [string, () => Promise<void>][] = [
    ['/', () => expect(page.getByTestId('totals')).toContainText(/\d+ emails/, { timeout: 15_000 })],
    [`/emails/${first}`, () => expect(page.getByTestId('received')).toContainText('From:', { timeout: 15_000 })],
  ];
  for (const [route, rendered] of views) {
    const resp = await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded' });
    expect(resp?.status(), `${route} HTTP`).toBeLessThan(400);
    await rendered();
    const body = (await page.textContent('body')) || '';
    expect(/Application error|Internal Server Error|This page broke/i.test(body), `${route}: error page`).toBeFalsy();
    expect(body.length, `${route}: looks blank`).toBeGreaterThan(200);
  }
  await page.goto(`${WEB}/emails/no-such-email`);
  await expect(page.getByText('No email with the id')).toBeVisible({ timeout: 15_000 });
});

test('quoteiq: process the next email in the UI and review it end to end', async ({ page, request }) => {
  test.setTimeout(900_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${WEB}/`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('totals')).toContainText('emails', { timeout: 20_000 });

  // Every email processed already? Start the example again, from the menu.
  let stats = await getData<any>(request, `${API}/api/qq/stats`);
  if (!stats?.waiting) await resetFromTheMenu(page);
  const rows = (await getData<any[]>(request, `${API}/api/qq/emails`)) || [];
  const next = rows.find((r) => r.status === 'waiting');
  expect(next, 'a waiting email').toBeTruthy();
  const id: string = next!.id;
  console.log(`  processing ${id}`);

  await page.getByTestId('process-next').click();
  await expect(page.getByTestId(`row-${id}`)).toContainText(/Processing|Success|Clarify|Escalated/, { timeout: 15_000 });
  await page.getByTestId(`row-${id}`).click();
  await expect(page.getByTestId('step-tracker')).toBeVisible({ timeout: 15_000 });

  // Poll the API rather than trusting the page, so this asserts persisted state.
  let email: Email = {};
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 10_000));
    email = (await getData<Email>(request, `${API}/api/qq/emails/${id}`)) || {};
    if (email.status && email.status !== 'processing') break;
    if (i % 6 === 5) console.log(`    ...${(i + 1) * 10}s, ${email.run?.lines_done ?? 0} lines searched`);
  }
  console.log(`  final status: ${email.status} (${email.lines?.length} lines)`);

  if (email.status === 'system_error') {
    // A dead or throttled LLM provider is an environment problem, not a
    // defect in this app. Anything else is a real failure.
    const detail = await providerFailure(request, email);
    if (detail) test.skip(true, `LLM provider unavailable — ${detail}`);
    throw new Error(`run failed: ${email.error}`);
  }
  expect(email.run?.execution_id, 'no execution id — the pipeline never fired').toBeTruthy();
  expect(email.status, `${id} reached its expected status`).toBe(EXPECTED[id].status);
  expect(email.lines.length, `${id} has its expected lines`).toBe(EXPECTED[id].lines);
  for (const line of email.lines) {
    expect(line.customer_reference, `line ${line.line_ref} kept the customer's words`).toBeTruthy();
    if (email.status === 'success') {
      expect(line.outcome, `line ${line.line_ref} matched`).toBe('matched');
      expect(line.pricing?.prices?.length, `line ${line.line_ref} is priced by the code asset`).toBeGreaterThan(0);
    }
  }

  await page.reload();
  await expect(page.getByTestId('lines')).toContainText(email.lines[0].customer_reference.slice(0, 12), { timeout: 15_000 });
  await page.getByTestId('toggle-how-1').click();
  await expect(page.getByTestId('how-1')).toContainText('Filters sent');

  if (email.status === 'escalated') {
    await expect(page.getByTestId('escalation-panel')).toBeVisible();
    await expect(page.getByTestId('escalation-panel')).toContainText(/FW-\d{5}/);
    await page.screenshot({ path: path.join(SHOTS, `${id}-escalated-1440.png`), fullPage: true });
    return;
  }

  // A draft, and its review open in Abenix.
  const draft = email.drafts.at(-1);
  expect(draft?.approval?.status, `review not raised: ${draft?.approval_error}`).toBe('pending');
  expect(draft.ai.to, 'the reply goes to the sender in the headers').toBe(email.from_email);
  await expect(page.getByTestId('draft-panel')).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, `${id}-draft-1440.png`), fullPage: true });

  // Asking the customer needs a note of its own.
  await page.getByTestId('ask').click();
  await expect(page.getByTestId('dialog-confirm')).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel' }).click();

  // Edit, then send: the approval is signed and the edited text is what was sent.
  await page.getByTestId('edit').click();
  const body = await page.getByTestId('edit-body').inputValue();
  await page.getByTestId('edit-body').fill(`${body}\n\nWe look forward to hearing from you.`);
  await page.getByTestId('save-edits').click();
  await expect(page.getByTestId('edited-badge')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('send').click();
  await expect(page.getByTestId('sent-panel')).toBeVisible({ timeout: 30_000 });

  const sent = (await getData<Email>(request, `${API}/api/qq/emails/${id}`))!;
  const last = sent.drafts.at(-1);
  expect(sent.review, 'the email shows as sent').toBe('sent');
  expect(last.approval.status, 'the Abenix approval was approved').toBe('approved');
  expect(last.sent.edited, 'the edited text was sent').toBeTruthy();
  expect(last.sent.body).toContain('We look forward to hearing from you.');
  await page.screenshot({ path: path.join(SHOTS, `${id}-sent-1440.png`), fullPage: true });
});
