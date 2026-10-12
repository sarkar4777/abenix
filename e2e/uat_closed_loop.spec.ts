/**
 * The closed loop, through the screens a person uses: a stream, a rule, an agent that reads and
 * proposes a command, a person who approves it, the asset that takes it, and an app that hears it.
 *
 *   1. Telemetry          open the asset, Watch this asset with an agent
 *   2. Agents             create a Machine health watcher from the template in one click
 *   3. Builder            device_command: the asset and the signal it may set, approval always
 *   4. Rules              a rule on a live signal that runs the agent, previewed with What it will receive
 *   5. The rule fires     the agent reads device_state and signal_history and proposes the command
 *   6. Approvals          the command card shows the asset, the value, the reason and history, approved
 *   7. Telemetry          the new value is seen on the asset
 *   8. SDK                a subscriber script hears telemetry.rule_fired, approval.requested,
 *                         telemetry.command_sent, execution.completed with the agent's answer and
 *                         telemetry.firing_completed with the step outputs
 *
 * Runs once on the testbed's Modbus energy meter, and once on Groundwork's EX1 PC. A target that is
 * not streaming is skipped with the reason. The API is only used to read state for assertions and
 * to clean up. Timings for each hop go to e2e/uat_closed_loop/timings-<target>.json.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_closed_loop.spec.ts --workers=1
 *   LOOP_TARGETS=testbed or groundwork runs one of them
 */
import { test, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const OUT = path.join(__dirname, 'uat_closed_loop');
const WIDTHS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];
const SDK_PATH = path.resolve(__dirname, '..', 'packages', 'sdk', 'python');
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

interface Target {
  id: string;
  group: string;
  node: string;
  rulePart: string;
  ruleSignal: string;
  ruleAbove: number;
  part: string;
  signal: string;
  value: string | number;
  restore?: string | number;
}

const setpoint = 20 + Math.floor(Math.random() * 60);
const TARGETS: Target[] = [
  { id: 'testbed', group: 'energy', node: 'meter-1', rulePart: '', ruleSignal: 'Voltage_V', ruleAbove: 1, part: '', signal: 'Setpoint_kW', value: setpoint },
  { id: 'groundwork', group: 'groundwork', node: 'ipc-ex1', rulePart: 'engine', ruleSignal: 'Engine/Speed_rpm', ruleAbove: -1, part: 'safety', signal: 'Mode/Set', value: 'safe', restore: 'auto' },
].filter((t) => !process.env.LOOP_TARGETS || process.env.LOOP_TARGETS.split(',').includes(t.id));

test.describe.configure({ mode: 'serial' });
test.setTimeout(900_000);
fs.mkdirSync(OUT, { recursive: true });

async function shot(page: Page, name: string) {
  const size = page.viewportSize();
  for (const w of WIDTHS) {
    await page.setViewportSize(w);
    await page.waitForTimeout(500);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect.soft(wide, `${name} at ${w.width} px scrolls sideways`).toBeLessThanOrEqual(1);
    await page.screenshot({ path: path.join(OUT, `${name}-${w.width}.png`), fullPage: true });
  }
  if (size) await page.setViewportSize(size);
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
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

// reads for assertions and cleanup only
async function api(page: Page, method: string, p: string, data?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` }, data: data as never });
  let json: any = null;
  try { json = await res.json(); } catch { /* empty */ }
  return { status: res.status(), json };
}

async function pickSignal(page: Page, testId: string, signal: string) {
  const input = page.getByTestId(`${testId}-input`);
  await input.fill(signal);
  const opt = page.locator(`[data-testid="${testId}-option"][data-signal="${signal}"]`).first();
  if (await opt.isVisible().catch(() => false)) await opt.click();
  else await input.press('Escape');
}

// the app's side: a small script on the Python SDK, printing each event as one JSON line
const SUBSCRIBER = `
import asyncio, json, os, sys, time
sys.path.insert(0, os.environ["SDK_PATH"])
from abenix_sdk import Abenix, bootstrap_key

async def main():
    key = await bootstrap_key(os.environ["API"], os.environ["EMAIL"], os.environ["PASSWORD"], os.environ["KEY_NAME"])
    forge = Abenix(api_key=key, base_url=os.environ["API"])
    print(json.dumps({"ready": True}), flush=True)
    types = ["telemetry.rule_fired", "approval.requested", "approval.resolved", "telemetry.command_sent", "execution.completed", "execution.failed", "telemetry.firing_completed"]
    async for ev in forge.events.stream(types):
        print(json.dumps({"received_at": int(time.time() * 1000), **ev}, default=str), flush=True)

asyncio.run(main())
`;

interface Heard { received_at: number; id: number; type: string; occurred_at: string; data: Record<string, any> }

function subscribe(keyName: string): { proc: ChildProcessWithoutNullStreams; events: Heard[]; ready: Promise<void>; log: string[] } {
  const file = path.join(OUT, 'subscriber.py');
  fs.writeFileSync(file, SUBSCRIBER);
  const proc = spawn(PYTHON, [file], {
    env: { ...process.env, SDK_PATH, API, EMAIL: ADMIN.email, PASSWORD: ADMIN.password, KEY_NAME: keyName, PYTHONUNBUFFERED: '1' },
  });
  const events: Heard[] = [];
  const log: string[] = [];
  let buf = '';
  let ok: () => void = () => {};
  const ready = new Promise<void>((r) => { ok = r; });
  proc.stdout.on('data', (d: Buffer) => {
    buf += d.toString();
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try {
        const doc = JSON.parse(line);
        if (doc.ready) ok();
        else events.push(doc);
      } catch { log.push(line); }
    }
  });
  proc.stderr.on('data', (d: Buffer) => log.push(d.toString()));
  return { proc, events, ready, log };
}

async function waitFor<T>(what: string, fn: () => T | undefined | null, ms: number): Promise<T> {
  const until = Date.now() + ms;
  for (;;) {
    const v = fn();
    if (v) return v;
    if (Date.now() > until) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 500));
  }
}

for (const T of TARGETS) {
  test(`closed loop on ${T.id}: stream, rule, agent, approval, command, app`, async ({ page }) => {
    const tag = `${T.id}-${RUN}`;
    const ruleName = `Closed loop ${tag}`;
    const keyName = `uat closed loop ${tag}`;
    const made: { agent?: string; rule?: string } = {};
    let sub: ReturnType<typeof subscribe> | null = null;
    await page.setViewportSize(WIDTHS[0]);
    await signIn(page);

    const live = await api(page, 'GET', `/api/telemetry/devices/${T.group}/${T.node}`);
    test.skip(live.status !== 200 || !live.json?.data?.online, `${T.group}/${T.node} is not streaming. Install the ${T.id === 'testbed' ? 'testbed with deploy.sh testbed and add its sources' : 'Groundwork PCs'} first.`);

    try {
      sub = subscribe(keyName);
      await Promise.race([sub.ready, new Promise((_, no) => setTimeout(() => no(new Error(`the SDK subscriber did not start: ${sub!.log.join(' ')}`)), 60_000))]);

      // 1. Telemetry: the asset, then Watch this asset with an agent
      await go(page, `/telemetry?group=${encodeURIComponent(T.group)}&node=${encodeURIComponent(T.node)}${T.part ? `&device=${encodeURIComponent(T.part)}` : ''}`);
      await expect(page.getByTestId('tel-device-detail')).toBeVisible({ timeout: 30_000 });
      const before = page.locator(`[data-testid="tel-metric-row"][data-metric="${T.signal}"] [data-testid="tel-metric-value"]`).first();
      await expect(before).toBeVisible({ timeout: 30_000 });
      const valueBefore = (await before.innerText()).trim();
      // a new value, so the change is seen
      if (typeof T.value === 'number' && Number.parseFloat(valueBefore) === T.value) T.value += 1;
      if (typeof T.value === 'string' && valueBefore === T.value) T.value = T.value === 'safe' ? 'hold' : 'safe';
      await page.getByTestId('tel-watch-agent').click();
      await page.waitForURL(/\/telemetry\/agents/, { timeout: 20_000 });

      // 2. Agents: one click from the template
      await expect(page.getByTestId('telemetry-agents-page')).toBeVisible();
      await expect(page.getByTestId('telemetry-agents-asset-select')).toHaveValue(`${T.group}/${T.node}`, { timeout: 20_000 });
      const chip = page.getByTestId('telemetry-agents-signals').getByRole('button', { name: T.signal, exact: true });
      if (await chip.isVisible({ timeout: 10_000 }).catch(() => false) && (await chip.getAttribute('aria-pressed')) !== 'true') await chip.click();
      await shot(page, `${T.id}-01-agent-templates`);
      await page.getByTestId('agent-template-create-machine-health-watcher').click();
      const created = page.getByTestId('telemetry-agents-created');
      await expect(created).toBeVisible({ timeout: 30_000 });
      made.agent = (await created.getAttribute('data-agent-id')) || undefined;
      expect(made.agent).toMatch(/^[0-9a-f-]{36}$/);
      const ruleHref = await page.getByTestId('telemetry-agents-new-rule').getAttribute('href');
      await shot(page, `${T.id}-02-agent-created`);

      // 3. Builder: device_command's policy
      await page.getByTestId('telemetry-agents-open-builder').click();
      await page.waitForURL(/\/builder\?agent=/, { timeout: 20_000 });
      await page.locator('.react-flow__node[data-id="tool-device_command"]').click({ timeout: 30_000 });
      const policy = page.getByTestId('device-command-policy');
      await expect(policy).toBeVisible();
      await expect(page.getByTestId('policy-assets')).toContainText(`${T.group}/${T.node}`);
      if (!(await page.getByTestId('policy-signals').isVisible().catch(() => false)) || !(await page.getByTestId('policy-signals').innerText()).includes(T.signal)) {
        await page.getByTestId('policy-signal-input').fill(T.signal);
        await page.getByTestId('policy-signal-input-add').click();
      }
      await expect(page.getByTestId('policy-signals')).toContainText(T.signal);
      await page.getByTestId('policy-approval-always').check();
      await page.getByTestId('policy-confirm').fill('6000');
      await expect(page.getByTestId('policy-summary')).toContainText('A person approves every command first.');
      await shot(page, `${T.id}-03-device-command-policy`);
      await expect(page.getByTestId('builder-save-draft')).toBeDisabled({ timeout: 20_000 });
      const saved = await api(page, 'GET', `/api/agents/${made.agent}`);
      const pol = saved.json?.data?.model_config?.tool_config?.device_command?.parameter_defaults?.policy;
      expect(pol, 'the policy is saved with the agent').toMatchObject({ approval: 'always', confirm_timeout_ms: 6000 });
      expect(pol.signals).toContain(T.signal);

      // 4. Rules: a rule on a live signal that runs the agent
      expect(ruleHref).toContain(`run_agent=${made.agent}`);
      await go(page, ruleHref!);
      await expect(page.getByTestId('rule-builder')).toBeVisible();
      await page.getByTestId('scope-part').selectOption(T.rulePart);
      await pickSignal(page, 'cond-signal', T.ruleSignal);
      await page.getByTestId('cond-op').selectOption('>');
      await page.getByTestId('cond-value').fill(String(T.ruleAbove));
      await page.getByTestId('rule-cooldown').fill('3600');
      await expect(page.getByTestId('action-0-agent')).toHaveValue(made.agent!);
      await page.getByTestId('action-0-run-message').fill(
        `Acceptance drill for the closed loop. Read ${T.group}/${T.node} with device_state and the last 15 minutes of ${T.ruleSignal} with signal_history, ` +
        `then set ${T.signal} to ${T.value} on asset ${T.group}/${T.node}${T.part ? ` part ${T.part}` : ''} with device_command, citing what you read as the reason.`,
      );
      await page.getByTestId('action-0-receives').click();
      await expect(page.getByTestId('action-0-receives-body')).toBeVisible();
      await expect(page.getByTestId('action-0-receives-message')).toContainText('Acceptance drill', { timeout: 20_000 });
      await page.getByTestId('rule-name').fill(ruleName);
      await shot(page, `${T.id}-04-rule-run-step`);
      const savedAt = Date.now();
      await page.getByTestId('rule-save').click();
      await page.waitForURL(/\/telemetry\/rules\/[0-9a-f-]{36}$/, { timeout: 20_000 });
      made.rule = page.url().split('/').pop()!;

      // 5. The rule fires and the agent starts
      const firing = page.locator('[data-testid="rule-history"] [data-testid="firing"]').first();
      await expect(firing, 'the rule fires live').toBeVisible({ timeout: 120_000 });
      const fired = await waitFor('telemetry.rule_fired in the app', () => sub!.events.find((e) => e.type === 'telemetry.rule_fired' && e.data.rule_id === made.rule), 120_000);

      // 6. Approvals: the command card, approved
      const asked = await waitFor('approval.requested in the app', () => sub!.events.find((e) => e.type === 'approval.requested' && e.data.gate_kind === 'telemetry.command' && e.data.agent_id === made.agent), 360_000);
      await go(page, '/approvals');
      const card = page.locator(`[data-testid="approval-card"][data-approval-id="${asked.data.approval_id}"]`);
      await expect(card).toBeVisible({ timeout: 30_000 });
      await expect(card.getByTestId('command-approval')).toBeVisible();
      await expect(card.getByTestId('command-approval-value')).toHaveText(String(T.value));
      await expect(card.getByTestId('command-approval-reason')).toBeVisible();
      await expect(card.getByTestId('command-approval-change')).toContainText(T.signal);
      await card.scrollIntoViewIfNeeded();
      await shot(page, `${T.id}-05-approval-command`);
      await card.getByTestId('approval-approve').click();
      await page.getByTestId('approval-approve-confirm').click();
      const approvedClick = Date.now();
      await expect(card).toHaveAttribute('data-status', 'approved', { timeout: 30_000 }).catch(() => {});

      // 7. The command lands, the app hears it, the value changes on the asset
      const sent = await waitFor('telemetry.command_sent in the app', () => sub!.events.find((e) => e.type === 'telemetry.command_sent' && e.data.agent_id === made.agent), 120_000);
      expect(sent.data.published).toBe(true);
      expect(sent.data.approval_id).toBe(asked.data.approval_id);
      expect(sent.data.reason?.length).toBeGreaterThan(3);
      await go(page, `/telemetry?group=${encodeURIComponent(T.group)}&node=${encodeURIComponent(T.node)}${T.part ? `&device=${encodeURIComponent(T.part)}` : ''}`);
      const after = page.locator(`[data-testid="tel-metric-row"][data-metric="${T.signal}"] [data-testid="tel-metric-value"]`).first();
      await expect(after, `${T.signal} reads ${T.value} on Telemetry`).toContainText(String(T.value), { timeout: 30_000 });
      await shot(page, `${T.id}-06-telemetry-after`);

      // 8. The agent's answer and the step outputs, in the app and on the firing
      const execId = sent.data.execution_id;
      const done = await waitFor('the agent run to end', () => sub!.events.find((e) => (e.type === 'execution.completed' || e.type === 'execution.failed') && e.data.execution_id === execId), 300_000);
      expect(done.type, `the agent run ended with: ${done.data.error || done.data.failure_code}`).toBe('execution.completed');
      expect(done.data.output, 'execution.completed carries the agent output').toBeTruthy();
      const finished = await waitFor('telemetry.firing_completed', () => sub!.events.find((e) => e.type === 'telemetry.firing_completed' && e.data.rule_id === made.rule), 120_000);
      expect(finished.data.steps[0].kind).toBe('run');
      expect(finished.data.steps[0].status).toBe('ok');
      expect(finished.data.steps[0].output).toBeTruthy();
      await go(page, `/telemetry/rules/${made.rule}`);
      const step = page.locator('[data-testid="rule-history"] [data-testid="firing-step"][data-kind="run"]').first();
      await expect(step).toHaveAttribute('data-status', 'ok', { timeout: 60_000 });
      await step.getByTestId('firing-step-toggle').click();
      await expect(step.getByTestId('firing-step-output')).not.toHaveText('Nothing');
      await expect(step.getByTestId('firing-step-link')).toHaveAttribute('href', `/executions/${execId}`);
      await shot(page, `${T.id}-07-firing-steps`);

      const t = sent.data.timings || {};
      const firedAt = Number(fired.data.at) || Date.parse(fired.occurred_at);
      const timings = {
        target: T.id,
        rule_saved_at: savedAt,
        fired_at: firedAt,
        heard_rule_fired_ms: fired.received_at - firedAt,
        agent_to_approval_ms: (t.approval_requested_at || asked.received_at) - firedAt,
        approval_requested_at: t.approval_requested_at,
        approved_click_at: approvedClick,
        approved_at: t.approved_at,
        approval_to_publish_ms: t.published_at && t.approved_at ? t.published_at - t.approved_at : null,
        published_at: t.published_at,
        send_checks_ms: t.checks_ms,
        confirm_ms: t.confirm_ms,
        confirmed: sent.data.confirmed,
        heard_command_sent_ms: t.published_at ? sent.received_at - t.published_at : null,
        heard_execution_completed_after_fire_ms: done.received_at - firedAt,
        agent_run_ms: done.data.duration_ms,
        value_before: valueBefore,
        value_after: String(T.value),
        execution_id: execId,
        approval_id: asked.data.approval_id,
      };
      const resolved = sub!.events.find((e) => e.type === 'approval.resolved' && e.data.approval_id === asked.data.approval_id);
      expect(resolved?.data.decided_by?.name, 'approval.resolved says who decided').toBeTruthy();
      expect(resolved?.data.decided_at, 'approval.resolved says when').toBeTruthy();
      expect.soft(timings.approval_to_publish_ms ?? 0, 'approve to publish, the target is under 200 ms').toBeLessThan(500);
      fs.writeFileSync(path.join(OUT, `timings-${T.id}.json`), JSON.stringify(timings, null, 2));
      console.log(`closed loop ${T.id}:`, JSON.stringify(timings));
    } finally {
      sub?.proc.kill();
      if (made.rule) await api(page, 'DELETE', `/api/telemetry/rules/${made.rule}`).catch(() => {});
      if (made.agent) await api(page, 'DELETE', `/api/agents/${made.agent}`).catch(() => {});
      const keys = await api(page, 'GET', '/api/api-keys').catch(() => null);
      for (const k of (keys?.json?.data || []) as Array<{ id: string; name: string }>) {
        if (k.name === keyName) await api(page, 'DELETE', `/api/api-keys/${k.id}`).catch(() => {});
      }
      if (T.restore !== undefined) {
        await api(page, 'POST', '/api/telemetry/command', { group: T.group, node: T.node, device: T.part, signal: T.signal, value: T.restore, reason: 'Closed loop UAT puts the machine back as it was' }).catch(() => {});
      }
    }
  });
}
