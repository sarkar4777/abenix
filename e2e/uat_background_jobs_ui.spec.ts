/**
 * Background jobs, seen working end to end from the screens.
 *
 *   1. Jobs page     admin only, every job explains itself, shots at 1440 and 390
 *   2. Trigger       an every-minute cron fires on its own, the run says Started by <trigger> (schedule)
 *   3. Evaluation    a suite on an every-minute schedule runs on its own
 *   4. Escalation    a Medium tier set to 1 minute escalates a waiting approval to admins
 *   5. Source Watch  a new source with a 5 minute interval is checked without Check now
 *   6. Retention     Run now with the shortest windows the screens allow removes expired items
 *   7. Jobs page     last run and next run move on their own, Run now shows its result
 *
 * The API is only used to read state back, to create an approval (an agent does that in real life)
 * and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_background_jobs_ui.spec.ts --workers=1
 *
 * Needs a working LLM credential (Claude Haiku 4.5, override with JOBS_MODEL) and outbound internet for
 * Source Watch (STABLE_URL, default https://example.com).
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { openFromSidebar } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const MODEL = process.env.JOBS_MODEL || 'claude-haiku-4-5-20251001';
const STABLE_URL = process.env.STABLE_URL || 'https://example.com';
const RUN = Date.now().toString(36);
const AGENT = `Jobs echo ${RUN}`;
const TRIGGER = `Every minute ${RUN}`;
const SUITE = `Jobs schedule ${RUN}`;
const SOURCE = `UAT jobs source ${RUN}`;
const APPROVAL = `Jobs escalation ${RUN}`;
const ARCHIVE_TABLE = process.env.JOBS_ARCHIVE_TABLE || 'ml_model_invocations';

const DIR = path.join(__dirname, 'uat_background_jobs_ui');
const SHOTS = path.join(DIR, 'shots');

let token = '';
const ids: {
  agent?: string;
  trigger?: string;
  suite?: string;
  source?: string;
  approval?: string;
  mediumBefore?: Record<string, unknown>;
  modRetention?: Record<string, number>;
  lessonDays?: number;
  archivePolicy?: { retention_days: number; enabled: boolean };
} = {};

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  expect(res.ok(), `login ${ADMIN.email}`).toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  const call = () => page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  });
  // one retry, a reused keep-alive socket can be closed under us
  const res = await call().catch(() => call());
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function job(page: Page, id: string) {
  const list = (await api(page, 'GET', '/api/admin/jobs')).json?.data?.jobs || [];
  return list.find((j: any) => j.id === id);
}

// Run now from the jobs page, confirming when it asks, and return the result line
async function runNow(page: Page, id: string, destructive: boolean) {
  await go(page, `/admin/jobs?job=${id}`);
  const card = page.getByTestId(`job-card-${id}`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByTestId(`job-run-${id}`).click();
  if (destructive) {
    const confirm = page.getByTestId('job-confirm-run');
    await expect(confirm).toBeVisible();
    await expect(page.getByRole('dialog')).toContainText(/removed|deleted|archive|zero/i);
    await confirm.click();
  }
  const result = card.getByTestId(`job-result-${id}`);
  await expect(result).toBeVisible({ timeout: 120_000 });
  return { card, text: (await result.innerText()).trim() };
}

// independent tests, one flake must not hide the rest
test.describe.configure({ mode: 'default' });
test.use({ viewport: { width: 1440, height: 900 } });

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await login(page);
  const r = await api(page, 'POST', '/api/agents', {
    name: AGENT,
    system_prompt: 'You are a test agent. Reply with exactly the single word PONG and nothing else.',
    model_config: { model: MODEL, temperature: 0, tools: [], max_tokens: 32 },
  });
  expect(r.status, JSON.stringify(r.json)).toBeLessThan(300);
  ids.agent = r.json.data.id;
  // the scheduler turns a trigger off when its agent is still a draft
  const pub = await api(page, 'POST', `/api/agents/${ids.agent}/publish`, { visibility: 'tenant' });
  expect(pub.status, JSON.stringify(pub.json)).toBeLessThan(300);
  await page.close();
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await login(page);
  const steps: [string, () => Promise<unknown>][] = [
    ['trigger', async () => ids.trigger && api(page, 'DELETE', `/api/triggers/${ids.trigger}`)],
    ['suite', async () => ids.suite && api(page, 'DELETE', `/api/evals/suites/${ids.suite}`)],
    ['source', async () => ids.source && api(page, 'DELETE', `/api/sources/${ids.source}`)],
    ['approval', async () => ids.approval && api(page, 'POST', `/api/approvals/${ids.approval}/signoff`, { decision: 'deny', reason: 'UAT clean-up' })],
    ['medium tier', async () => {
      if (!ids.mediumBefore) return;
      if (Object.keys(ids.mediumBefore).length) await api(page, 'PUT', '/api/governance/risk/medium', ids.mediumBefore);
      else await api(page, 'DELETE', '/api/governance/risk/medium');
    }],
    ['moderation retention', async () => ids.modRetention && api(page, 'PUT', '/api/moderation/retention', ids.modRetention)],
    ['lesson retention', async () => ids.lessonDays && api(page, 'PUT', '/api/improvements/retention', { retention_days: ids.lessonDays })],
    ['archive policy', async () => ids.archivePolicy && api(page, 'PUT', `/api/admin/archives/retention-policies/${ARCHIVE_TABLE}`, ids.archivePolicy)],
    ['agent', async () => ids.agent && api(page, 'DELETE', `/api/agents/${ids.agent}`)],
  ];
  for (const [name, fn] of steps) {
    try { await fn(); } catch (e) { console.warn(`clean-up ${name} failed: ${e}`); }
  }
  await page.close();
});

test('the jobs page is in the sidebar and explains every job', async ({ page }) => {
  await login(page);
  await go(page, '/dashboard');
  await openFromSidebar(page, '/admin/jobs');
  await expect(page.getByTestId('jobs-title')).toHaveText('Background jobs');
  await expect(page.getByTestId('page-purpose')).toContainText('Everything the platform does on its own');
  const data = (await api(page, 'GET', '/api/admin/jobs')).json.data;
  expect(data.scheduler_running).toBe(true);
  expect(data.recording).toBe(true);
  const wanted = [
    'check_due_triggers', 'eval_schedules', 'escalate_approvals', 'watch_sources', 'improvements_watch',
    'moderation_retention', 'lesson_retention', 'prune_events', 'nightly_archive', 'reset_monthly_quotas',
    'sweep_stale_executions', 'score_drift_backlog',
  ];
  for (const id of wanted) {
    const card = page.getByTestId(`job-card-${id}`);
    await expect(card, id).toBeVisible();
    await expect(card.getByTestId(`job-what-${id}`)).not.toBeEmpty();
    await expect(card).toContainText('Why it matters:');
    await expect(card.getByTestId(`job-schedule-${id}`)).toHaveText(/Every|Daily|Monthly/);
    await expect(card.getByTestId(`job-next-run-${id}`)).not.toBeEmpty();
  }
  await expect(page.getByTestId('job-schedule-escalate_approvals')).toHaveText('Every minute');
  await expect(page.getByTestId('job-schedule-reset_monthly_quotas')).toHaveText('Monthly on day 1 at 00:00 UTC');
  // the job that has to be live by now has run
  await expect(page.getByTestId('job-last-run-check_due_triggers')).not.toHaveText('Never', { timeout: 60_000 });
  // filtering
  await page.getByTestId('jobs-filter-destructive').click();
  await expect(page.getByTestId('job-card-check_due_triggers')).toHaveCount(0);
  await expect(page.getByTestId('job-card-prune_events')).toBeVisible();
  await page.getByTestId('jobs-filter-all').click();
  await page.getByTestId('jobs-search').fill('zzzz nothing');
  await expect(page.getByTestId('jobs-empty')).toContainText('No job matches');
  await page.getByTestId('jobs-search').fill('');
  await shot(page, '01-jobs-1440');
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/admin/jobs');
  await expect(page.getByTestId('job-card-check_due_triggers')).toBeVisible({ timeout: 30_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, 'no sideways scroll at 390px').toBeLessThanOrEqual(1);
  await shot(page, '02-jobs-390');
});

test('a trigger on an every-minute cron fires on its own', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await login(page);
  await go(page, `/triggers?agent=${ids.agent}`);
  const dlg = page.getByRole('dialog', { name: 'Create Trigger' });
  if (!(await dlg.isVisible().catch(() => false))) await page.getByRole('button', { name: 'New Trigger' }).first().click();
  await expect(dlg).toBeVisible({ timeout: 20_000 });
  await dlg.getByLabel('Agent').selectOption(ids.agent!);
  await dlg.getByRole('button', { name: /Schedule/ }).click();
  await dlg.getByLabel('Cron Expression').fill('* * * * *');
  await dlg.getByLabel('Default Message').fill('ping');
  await dlg.getByLabel('Name').fill(TRIGGER);
  await dlg.getByRole('button', { name: 'Create Trigger' }).click();
  await expect(dlg).toHaveCount(0, { timeout: 20_000 });
  const trig = (await api(page, 'GET', `/api/triggers?agent_id=${ids.agent}`)).json.data.find((t: any) => t.name === TRIGGER);
  ids.trigger = trig.id;
  const before = await job(page, 'check_due_triggers');

  // nobody presses Run, the scheduler has to start it
  let execId = '';
  await expect.poll(async () => {
    const r = await api(page, 'GET', `/api/executions?trigger_id=${trig.id}&limit=5`);
    const hit = (r.json?.data || []).find((e: any) => e.trigger_id === trig.id && e.trigger_kind === 'schedule');
    execId = hit?.id || '';
    return execId;
  }, { timeout: 150_000, intervals: [5_000] }).not.toBe('');
  // we must stop it before it fires again and again
  await go(page, `/executions/${execId}`);
  await expect(page.getByTestId('execution-started-by')).toContainText(`Started by ${TRIGGER} (schedule)`, { timeout: 30_000 });
  await shot(page, '03-trigger-fired-on-its-own');
  await api(page, 'DELETE', `/api/triggers/${ids.trigger}`);
  ids.trigger = undefined;

  const after = await job(page, 'check_due_triggers');
  expect(after.run_count).toBeGreaterThan(before.run_count);
  expect(after.history.some((r: any) => /trigger(s)? started/.test(r.summary))).toBe(true);
  await go(page, '/admin/jobs?job=check_due_triggers');
  await page.getByTestId('job-history-toggle-check_due_triggers').click();
  await expect(page.getByTestId('job-card-check_due_triggers').getByTestId('job-history-row').first()).toContainText(/started/);
});

test('an evaluation suite on a schedule runs on its own', async ({ page }) => {
  test.setTimeout(8 * 60_000);
  await login(page);
  await go(page, '/evals');
  await page.getByTestId('eval-new-suite').click();
  await page.getByTestId('eval-suite-agent').selectOption(ids.agent!);
  const gating = page.getByTestId('eval-suite-gating');
  if (await gating.isChecked()) await gating.uncheck();
  await page.getByTestId('eval-suite-name').fill(SUITE);
  await page.getByTestId('eval-suite-create').click();
  await expect(page.getByTestId('eval-suite-title')).toHaveText(SUITE, { timeout: 20_000 });
  ids.suite = page.url().split('/evals/')[1].split(/[?#]/)[0];
  await page.getByTestId('eval-add-case').click();
  const ed = page.getByTestId('eval-case-editor').first();
  await ed.getByTestId('eval-case-name').fill('Says pong');
  await ed.getByTestId('eval-case-input').fill('ping');
  await ed.getByTestId('assertion-add').click();
  await page.getByTestId('assertion-add-contains').click();
  await ed.getByTestId('a0-value').fill('PONG');
  await ed.getByTestId('eval-case-save').click();
  await expect(page.getByTestId('eval-cases')).toContainText('Says pong');

  await page.getByTestId('eval-tab-settings').click();
  await page.getByTestId('eval-settings-schedule').selectOption('__custom');
  await page.getByTestId('eval-settings-cron').fill('* * * * *');
  await page.getByTestId('eval-settings-save').click();
  await expect(page.getByTestId('eval-settings').getByRole('status')).toHaveText('Saved.', { timeout: 20_000 });
  const suite = (await api(page, 'GET', `/api/evals/suites/${ids.suite}`)).json.data;
  expect(suite.schedule_cron).toBe('* * * * *');
  expect(suite.next_run_at).toBeTruthy();

  let runId = '';
  await expect.poll(async () => {
    const runs = (await api(page, 'GET', `/api/evals/suites/${ids.suite}/runs?limit=5`)).json?.data || [];
    runId = runs.find((r: any) => r.triggered_by === 'schedule')?.id || '';
    return runId;
  }, { timeout: 200_000, intervals: [5_000] }).not.toBe('');
  // stop the schedule from the screen before it runs again
  await page.getByTestId('eval-settings-schedule').selectOption('');
  await page.getByTestId('eval-settings-save').click();
  await expect(page.getByTestId('eval-settings').getByRole('status')).toHaveText('Saved.', { timeout: 20_000 });

  await go(page, `/evals/${ids.suite}`);
  await page.getByTestId('eval-tab-runs').click();
  await expect(page.getByTestId('eval-runs-table')).toContainText('Scheduled', { timeout: 30_000 });
  await shot(page, '04-eval-ran-on-schedule');
  const ej = await job(page, 'eval_schedules');
  expect(ej.history.some((r: any) => /suites? started on schedule/.test(r.summary))).toBe(true);
});

test('a waiting approval escalates to admins after the tier minutes', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await login(page);
  const tiers = (await api(page, 'GET', '/api/governance/risk')).json.data.tiers as any[];
  ids.mediumBefore = tiers.find((t) => t.tier === 'medium').overrides || {};

  await go(page, '/admin/risk');
  const card = page.getByTestId('tier-card-medium');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByTestId('tier-escalate-unit-medium').selectOption('minutes');
  // out of range is refused in words
  await card.getByTestId('tier-escalate-medium').fill('50000');
  await expect(card).toContainText('Use a whole number of minutes from 0 to 43200.');
  await expect(card.getByTestId('tier-save-medium')).toBeDisabled();
  await card.getByTestId('tier-escalate-medium').fill('1');
  await card.getByTestId('tier-save-medium').click();
  await expect(card.getByTestId('tier-msg-medium')).toContainText('Saved', { timeout: 20_000 });
  const saved = ((await api(page, 'GET', '/api/governance/risk')).json.data.tiers as any[]).find((t) => t.tier === 'medium');
  expect(saved.effective.publish_approvals.escalate_after_minutes).toBe(1);
  await shot(page, '05-escalate-after-1-minute');

  const created = await api(page, 'POST', '/api/approvals', { title: APPROVAL, risk_tier: 'medium', required_signoffs: 1, expires_seconds: 900 });
  expect(created.status, JSON.stringify(created.json)).toBeLessThan(300);
  ids.approval = created.json.data.id;
  expect(created.json.data.policy?.escalate_after_minutes ?? 1).toBe(1);

  await expect.poll(async () => {
    const n = (await api(page, 'GET', '/api/notifications?per_page=50')).json?.data || [];
    return n.some((x: any) => String(x.title).includes(`Approval waiting over 1 min: ${APPROVAL}`));
  }, { timeout: 200_000, intervals: [5_000] }).toBe(true);
  const ej = await job(page, 'escalate_approvals');
  expect(ej.history.some((r: any) => /approvals? escalated/.test(r.summary))).toBe(true);
});

test('a Source Watch source with a short interval is checked on its own', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await login(page);
  await go(page, '/sources');
  await page.getByTestId(/source-add(-empty)?$/).first().click();
  await page.getByTestId('source-url').fill(STABLE_URL);
  await expect(page.getByTestId('source-url-check')).toContainText('can be watched', { timeout: 20_000 });
  await page.getByTestId('source-name').fill(SOURCE);
  await page.getByTestId('source-cadence').selectOption('custom');
  await page.getByLabel('Minutes between checks').fill('5');
  await page.getByTestId('source-test-fetch').click();
  await expect(page.getByTestId('source-preview')).toBeVisible({ timeout: 60_000 });
  await page.getByTestId('source-save').click();
  await expect(page.getByTestId('source-title')).toHaveText(SOURCE, { timeout: 20_000 });
  const src = ((await api(page, 'GET', '/api/sources')).json.data as any[]).find((s) => s.name === SOURCE);
  ids.source = src.id;
  expect(src.cadence_minutes).toBe(5);
  // no Check now, the scheduler has to pick it up
  await expect.poll(async () => (await api(page, 'GET', `/api/sources/${src.id}`)).json?.data?.check_count || 0,
    { timeout: 150_000, intervals: [5_000] }).toBeGreaterThan(0);
  await page.reload();
  await page.getByTestId('source-tab-snapshots').click();
  await expect(page.getByTestId('snapshot-timeline').locator('li')).toHaveCount(1, { timeout: 30_000 });
  await shot(page, '07-source-checked-on-its-own');
  const after = (await api(page, 'GET', `/api/sources/${src.id}`)).json.data;
  expect(new Date(after.next_check_at).getTime() - new Date(after.last_checked_at).getTime()).toBeLessThanOrEqual(5 * 60_000 + 5_000);
  const wj = await job(page, 'watch_sources');
  expect(wj.history.some((r: any) => /sources? checked/.test(r.summary))).toBe(true);
});

test('retention purges remove expired items with Run now', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await login(page);

  // moderation: 0 days for held text is the shortest the retention card allows
  const decided = async () => {
    const r = await api(page, 'GET', '/api/moderation/reviews?status=decided&limit=100');
    return (r.json?.data || []) as any[];
  };
  const before = (await decided()).filter((x) => x.content_available);
  const ret = (await api(page, 'GET', '/api/moderation/retention')).json.data;
  ids.modRetention = { held_content_days: ret.held_content_days, decision_record_days: ret.decision_record_days, event_preview_days: ret.event_preview_days };
  await go(page, '/moderation');
  const rc = page.getByTestId('retention-card');
  await rc.scrollIntoViewIfNeeded();
  await page.getByTestId('retention-held_content_days').fill('0');
  await page.getByTestId('retention-save').click();
  await expect(page.getByTestId('retention-saved')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('retention-run-now').click();
  await page.waitForURL(/\/admin\/jobs\?job=moderation_retention/);
  const mod = await runNow(page, 'moderation_retention', true);
  if (before.length) {
    expect(mod.text).toMatch(/held texts? removed/);
    const left = (await decided()).filter((x) => x.content_available && before.some((b) => b.id === x.id));
    expect(left, 'decided reviews still holding full text').toHaveLength(0);
  } else {
    expect(mod.text).toMatch(/Done in .*\.( Nothing was past its retention\.| .*removed| .*cleared)/);
  }
  await shot(page, '08-moderation-purge');
  await api(page, 'PUT', '/api/moderation/retention', ids.modRetention);
  ids.modRetention = undefined;

  // lessons: 7 days is the floor, nothing younger may go
  const lr = (await api(page, 'GET', '/api/improvements/retention')).json.data;
  ids.lessonDays = lr.retention_days;
  const lessonsBefore = (await api(page, 'GET', '/api/improvements/overview')).json?.data?.counts?.open_lessons;
  await go(page, '/improvements');
  const card = page.getByTestId('lesson-retention');
  await card.scrollIntoViewIfNeeded();
  await page.getByTestId('lesson-retention-days').fill('3');
  await expect(page.getByTestId('lesson-retention-error')).toContainText(`from ${lr.min_days} to ${lr.max_days}`);
  await expect(page.getByTestId('lesson-retention-save')).toBeDisabled();
  await page.getByTestId('lesson-retention-days').fill(String(lr.min_days));
  if (lr.retention_days !== lr.min_days) {
    await page.getByTestId('lesson-retention-save').click();
    await expect(page.getByTestId('lesson-retention-msg')).toContainText('Saved', { timeout: 20_000 });
  }
  await page.getByTestId('lesson-retention-run').click();
  const les = await runNow(page, 'lesson_retention', true);
  expect(les.text).toMatch(/^Done in /);
  expect(les.text).toMatch(/Nothing was past its retention\.|deleted/);
  const lessonsAfter = (await api(page, 'GET', '/api/improvements/overview')).json?.data?.counts?.open_lessons;
  if (!/lessons? deleted/.test(les.text)) expect(lessonsAfter).toBe(lessonsBefore);
  await api(page, 'PUT', '/api/improvements/retention', { retention_days: ids.lessonDays });
  ids.lessonDays = undefined;

  // events: fixed windows, delivered attempts after 30 days and sent events after 7
  const ev = await runNow(page, 'prune_events', true);
  expect(ev.text).toMatch(/^Done in .*(deleted|Nothing was old enough to delete\.)/);
  await shot(page, '09-event-prune');

  // archives: 1 day is the shortest the policy form allows
  const policies = (await api(page, 'GET', '/api/admin/archives/retention-policies')).json.data.items as any[];
  const pol = policies.find((p) => p.source_table === ARCHIVE_TABLE);
  ids.archivePolicy = { retention_days: pol.retention_days, enabled: pol.enabled };
  await go(page, '/admin/archives');
  await page.getByTestId(`retention-days-${ARCHIVE_TABLE}`).fill('0');
  await page.getByTestId(`retention-days-${ARCHIVE_TABLE}`).fill('1');
  await page.getByTestId(`retention-save-${ARCHIVE_TABLE}`).click();
  await expect(page.getByTestId('archives-notice')).toContainText('keeps 1 days', { timeout: 20_000 });
  // the server refuses what the form would not allow
  const bad = await api(page, 'PUT', `/api/admin/archives/retention-policies/${ARCHIVE_TABLE}`, { retention_days: 0 });
  expect(bad.status).toBe(400);
  const runsBefore = ((await api(page, 'GET', '/api/admin/archives')).json.data.items as any[]).map((r) => r.id);
  const arc = await runNow(page, 'nightly_archive', true);
  expect(arc.text).toMatch(/^(Done in .*(rows? archived|No table had rows past its retention\.)|Still running)/);
  let newRun: any = null;
  await expect.poll(async () => {
    const runs = (await api(page, 'GET', '/api/admin/archives')).json.data.items as any[];
    newRun = runs.find((r) => r.source_table === ARCHIVE_TABLE && !runsBefore.includes(r.id) && r.status === 'completed');
    return !!newRun;
  }, { timeout: 240_000, intervals: [5_000] }).toBe(true);
  await go(page, '/admin/archives');
  const row = page.locator(`[data-testid="archive-run"][data-id="${newRun.id}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await shot(page, '10-archive-run');
  if (newRun.rows_archived > 0) {
    // the archived rows are gone from the live table, put them back so the next run of this spec has data
    await row.getByTestId(`archive-restore-${newRun.id}`).click();
    const dlg = page.getByRole('dialog');
    if (await dlg.isVisible().catch(() => false)) await dlg.getByRole('button').last().click();
    await expect(page.getByTestId(`archive-restored-${newRun.id}`)).toBeVisible({ timeout: 120_000 });
  }
  await api(page, 'PUT', `/api/admin/archives/retention-policies/${ARCHIVE_TABLE}`, ids.archivePolicy);
  ids.archivePolicy = undefined;
});

test('the jobs page moves last run and next run on its own and shows a Run now result', async ({ page }) => {
  test.setTimeout(4 * 60_000);
  await login(page);
  await go(page, '/admin/jobs?job=check_due_triggers');
  const id = 'check_due_triggers';
  const last = page.getByTestId(`job-last-run-${id}`);
  const next = page.getByTestId(`job-next-run-${id}`);
  await expect(next).toHaveText(/^in \d+s$|^due now$/, { timeout: 30_000 });
  const firstLast = await last.getAttribute('title');
  // the page refreshes itself every 10 seconds, the job runs every 30
  await expect.poll(async () => await last.getAttribute('title'), { timeout: 90_000, intervals: [3_000] }).not.toBe(firstLast);
  await expect(last).toHaveText(/just now|\d+s ago/);
  await expect(page.getByTestId(`job-outcome-${id}`)).toHaveAttribute('data-outcome', /ok|running/);

  const r = await runNow(page, 'escalate_approvals', false);
  expect(r.text).toMatch(/^(Done|Skipped) in /);
  await expect(page.getByTestId('job-last-by-escalate_approvals')).toHaveText(`Run now by ${ADMIN.email}`, { timeout: 20_000 });
  const j = await job(page, 'escalate_approvals');
  expect(j.manual_count).toBeGreaterThan(0);
  expect(j.last_trigger).toBe('manual');
  await shot(page, '11-run-now-result');
  // the audit log has it
  const audit = await api(page, 'GET', '/api/admin/audit?action=job.run_now&limit=5');
  if (audit.status === 200) expect(JSON.stringify(audit.json)).toContain('escalate_approvals');
});
