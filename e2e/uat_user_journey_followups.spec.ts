/**
 * Follow-ups to the supplier risk journey, strictly through the UI.
 *
 * Builds on what uat_user_journey_ui.spec.ts left behind (test-results/user-journey.json):
 *   1. a second, non-admin teammate runs everything that was shared with them
 *   2. failure and recovery: code that cannot run, code that throws, a bad new version
 *   3. changing things after publishing: new code version, prompt edit, revert
 *   4. deleting things other work depends on, and restoring them
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const STATE = JSON.parse(fs.readFileSync(path.join('test-results', 'user-journey.json'), 'utf-8')) as {
  user: string;
  ids: Record<string, string>;
};
const OWNER = { email: STATE.user, password: 'RiskDesk!2026' };
const STAMP = (STATE.user.match(/riskdesk\.(\d+)@/) || [])[1] || '';
const MATE_STAMP = Date.now().toString().slice(-6);
const MATE = { email: `mo.member.${MATE_STAMP}@abenix.dev`, name: `Mo Member ${MATE_STAMP}`, password: 'MoMember!2026' };
const FIX = path.join(__dirname, 'fixtures', 'supplier_risk');
const SHOTS = path.join('test-results', 'user-journey-followups');
const OUT = path.join('test-results', 'user-journey-followups.json');
const NAMES = {
  asset: `supplier-risk-${STAMP}`,
  kb: `Procurement Policy ${STAMP}`,
  scorer: `Supplier Risk Scorer ${STAMP}`,
  analyst: `Policy Network Analyst ${STAMP}`,
};
const SUPPLIERS = JSON.stringify({
  suppliers: [
    { name: 'Nordtek', current_ratio: 0.8, debt_to_equity: 2.1, on_time_delivery_pct: 86, single_source: true, country_risk: 'medium' },
    { name: 'Alba Castings', current_ratio: 1.9, debt_to_equity: 0.4, on_time_delivery_pct: 99, single_source: false, country_risk: 'low' },
    { name: 'Vistula Polymers', current_ratio: 1.1, debt_to_equity: 1.2, on_time_delivery_pct: 93, single_source: true, country_risk: 'high' },
  ],
});
const ids = STATE.ids;

type Finding = { step: string; ok: boolean; what: string; screenshot?: string };
const findings: Finding[] = [];

async function record(page: Page, step: string, ok: boolean, what: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const screenshot = path.join(SHOTS, `${String(findings.length).padStart(2, '0')}-${step.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.png`);
  await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
  findings.push({ step, ok, what, screenshot });
  console.log(`  [${ok ? 'ok' : 'WALL'}] ${step}: ${what}`);
  expect.soft(ok, `${step}: ${what}`).toBeTruthy();
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function signIn(page: Page, email: string, password: string) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(email);
  await page.locator('#auth-password').fill(password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function signOut(page: Page) {
  const btn = page.locator('button[aria-label="Log out"]').first();
  if (await btn.count()) await btn.click();
  else {
    await page.locator('header button').last().click().catch(() => {});
    await page.locator('button[aria-label="Log out of your account"]').click();
  }
  await page.waitForURL((u) => new URL(u).pathname === '/', { timeout: 20_000 });
}

async function chat(page: Page, message: string, timeoutMs = 300_000) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  await page.waitForTimeout(1500);
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const n = await replies.count();
  const reply = n ? await replies.nth(n - 1).innerText() : '';
  const err = await page.locator('[role="alert"]').allInnerTexts().catch(() => [] as string[]);
  return `${reply}\n${err.join('\n')}`;
}

async function shareWith(page: Page, agentId: string, email: string) {
  await go(page, `/agents/${agentId}/info`);
  await page.getByTestId('agent-share').click();
  await page.getByTestId('share-email').fill(email);
  await page.getByTestId('share-permission').selectOption('execute').catch(() => {});
  await page.getByTestId('share-submit').click();
  await expect(page.locator('[role="dialog"]')).toContainText(email, { timeout: 15_000 });
  await page.keyboard.press('Escape');
}

async function openAsset(page: Page, name: string) {
  await go(page, '/code-runner');
  const item = page.locator(`[data-testid="code-asset-item"][data-name="${name}"]`);
  await expect(item).toBeVisible({ timeout: 30_000 });
  await item.click();
  await page.waitForTimeout(600);
  return item;
}

async function testRun(page: Page) {
  await page.getByTestId('code-test-input').fill(SUPPLIERS);
  await page.getByTestId('code-test-run').click();
  await expect(page.getByTestId('code-test-output')).not.toBeEmpty({ timeout: 240_000 });
  return page.getByTestId('code-test-output').innerText();
}

test.use({ viewport: { width: 1440, height: 900 } });

test('follow-ups: shared use, failures, changes and deletes', async ({ page }) => {
  test.setTimeout(60 * 60_000);
  page.on('dialog', (d) => d.accept());
  expect(ids.scorer && ids.analyst && ids.pipeline && ids.lead, 'run the journey spec first').toBeTruthy();

  try {
    // ── 1. a second teammate runs what was shared with them ─────────────
    await test.step('admin invites a second, non-admin teammate', async () => {
      await signIn(page, ADMIN.email, ADMIN.password);
      await go(page, '/settings/team');
      await page.getByRole('button', { name: 'Invite Member' }).click();
      await page.locator('input[placeholder="email@example.com"]').fill(MATE.email);
      await page.locator('select').last().selectOption('user');
      await page.getByRole('button', { name: 'Send' }).click();
      const link = page.getByTestId('invite-link');
      await expect(link).toBeVisible({ timeout: 15_000 });
      const invite = ((await link.innerText()) || (await link.inputValue().catch(() => ''))).trim();
      await signOut(page);
      await page.goto(invite.replace(/^https?:\/\/[^/]+/, BASE), { waitUntil: 'domcontentloaded' });
      await page.locator('#accept-full-name').fill(MATE.name);
      await page.locator('#accept-password').fill(MATE.password);
      await page.getByTestId('accept-submit').click();
      await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
      await record(page, 'second teammate joined', true, MATE.email);
      await signOut(page);
    });

    await test.step('the owner shares the desk with the teammate', async () => {
      await signIn(page, OWNER.email, OWNER.password);
      for (const id of [ids.scorer, ids.analyst, ids.pipeline, ids.lead]) await shareWith(page, id, MATE.email);
      await record(page, 'shared four agents', true, 'scorer, analyst, pipeline and lead shared to run');
      await signOut(page);
    });

    await test.step('the teammate runs each shared agent', async () => {
      await signIn(page, MATE.email, MATE.password);
      await go(page, `/agents/${ids.scorer}/info`);
      const shareVisible = await page.getByTestId('agent-share').isVisible().catch(() => false);
      const editVisible = await page.getByRole('link', { name: 'Edit' }).isVisible().catch(() => false);
      await record(page, 'run-only page', !shareVisible && !editVisible, `share shown=${shareVisible}, edit shown=${editVisible}`);

      await go(page, `/agents/${ids.scorer}/chat`);
      let t = await chat(page, `Score these suppliers: ${SUPPLIERS}`);
      await record(page, 'teammate runs scorer', /Nordtek/i.test(t) && /76/.test(t), `answer tail: ${t.slice(-250)}`);

      await go(page, `/agents/${ids.analyst}/chat`);
      t = await chat(page, 'Nordtek is red tier. Which plant is exposed and what safety stock does PRP-7 require?');
      await record(page, 'teammate runs analyst', /Brno/i.test(t) && /(eight|8)[\s-]*weeks?/i.test(t), `answer tail: ${t.slice(-250)}`);

      await go(page, `/agents/${ids.pipeline}/chat`);
      t = await chat(page, 'Run the supplier risk briefing.', 600_000);
      await record(page, 'teammate runs pipeline', /BRIEFING/.test(t) && /Brno/i.test(t), `answer tail: ${t.slice(-250)}`);

      await go(page, `/agents/${ids.lead}/chat`);
      t = await chat(page, `Run the desk for these suppliers: ${SUPPLIERS}`, 600_000);
      await record(page, 'teammate runs lead', /Nordtek/i.test(t) && /Brno/i.test(t), `answer tail: ${t.slice(-250)}`);
      await signOut(page);
    });

    // ── 2. failure and recovery ─────────────────────────────────────────
    await test.step('code that cannot run says why', async () => {
      await signIn(page, OWNER.email, OWNER.password);
      await go(page, '/code-runner');
      const broken = `broken-${MATE_STAMP}`;
      await page.getByPlaceholder('Name (e.g. sentiment-scorer)').fill(broken);
      await page.locator('input[type=file][accept=".zip"]').setInputFiles(path.join(FIX, 'supplier_risk_broken.zip'));
      await page.getByRole('button', { name: /Create & analyze/ }).click();
      const item = page.locator(`[data-testid="code-asset-item"][data-name="${broken}"]`);
      await expect(item).toHaveAttribute('data-status', /ready|failed/, { timeout: 120_000 });
      await item.click();
      const banner = page.getByTestId('code-asset-error');
      const shown = await banner.isVisible().catch(() => false);
      const text = shown ? await banner.innerText() : '';
      await record(page, 'unrunnable code explained', shown && text.length > 40, `banner: ${text.slice(0, 200)}`);
    });

    await test.step('code that throws shows its own error', async () => {
      const raises = `raises-${MATE_STAMP}`;
      await go(page, '/code-runner');
      await page.getByPlaceholder('Name (e.g. sentiment-scorer)').fill(raises);
      await page.locator('input[type=file][accept=".zip"]').setInputFiles(path.join(FIX, 'supplier_risk_raises.zip'));
      await page.getByRole('button', { name: /Create & analyze/ }).click();
      const item = page.locator(`[data-testid="code-asset-item"][data-name="${raises}"]`);
      await expect(item).toHaveAttribute('data-status', /ready|failed/, { timeout: 120_000 });
      await item.click();
      const out = await testRun(page);
      await record(page, 'exception surfaced', /debt_to_equity column/.test(out), `output: ${out.slice(0, 200)}`);
    });

    // ── 3. changing things after publishing ─────────────────────────────
    await test.step('a bad new version is refused and the live one stays', async () => {
      await openAsset(page, NAMES.asset);
      // start from the v1 code whatever an earlier run left live
      const start = Number(await page.getByTestId('code-version').getAttribute('data-version'));
      await page.getByTestId('code-version-input').setInputFiles(path.join(FIX, 'supplier_risk.zip'));
      await expect(page.getByTestId('code-version')).toHaveAttribute('data-version', String(start + 1), { timeout: 120_000 });
      const before = await page.getByTestId('code-version').getAttribute('data-version');
      await page.getByTestId('code-version-input').setInputFiles(path.join(FIX, 'supplier_risk_broken.zip'));
      await expect(page.getByTestId('code-version-error')).toBeVisible({ timeout: 120_000 });
      const msg = await page.getByTestId('code-version-error').innerText();
      const after = await page.getByTestId('code-version').getAttribute('data-version');
      await record(page, 'bad version refused', before === after && /still live/i.test(msg), `v${before} -> v${after}: ${msg.slice(0, 160)}`);
    });

    await test.step('a fixed version goes live for the agent, then is rolled back', async () => {
      await openAsset(page, NAMES.asset);
      const before = Number(await page.getByTestId('code-version').getAttribute('data-version'));
      await page.getByTestId('code-version-input').setInputFiles(path.join(FIX, 'supplier_risk_v2.zip'));
      await expect(page.getByTestId('code-version')).toHaveAttribute('data-version', String(before + 1), { timeout: 120_000 });
      let out = await testRun(page);
      await record(page, 'new version live', /SUPPLIER_RISK_ENGINE_V2/.test(out), `v${before + 1} test run marker V2`);

      await go(page, `/agents/${ids.scorer}/chat`);
      await chat(page, `Score these suppliers: ${SUPPLIERS}`);
      await page.getByTestId('chat-view-run').last().click();
      await page.waitForURL(/\/executions\//, { timeout: 20_000 });
      await expect(page.getByTestId('execution-steps')).toBeVisible({ timeout: 30_000 });
      await page.locator('button[aria-expanded]', { hasText: /^\s*Result/ }).first().click();
      const rec = await page.locator('main').innerText();
      await record(page, 'agent uses new version', /SUPPLIER_RISK_ENGINE_V2/.test(rec), 'scorer run recorded the V2 marker');

      await openAsset(page, NAMES.asset);
      await page.getByTestId(`code-restore-${before}`).click();
      await expect(page.getByTestId('code-version')).toHaveAttribute('data-version', String(before + 2), { timeout: 30_000 });
      out = await testRun(page);
      await record(page, 'rolled back', /SUPPLIER_RISK_ENGINE_V1/.test(out), `restored v${before} as v${before + 2}`);
    });

    await test.step('a prompt change reaches every caller and can be reverted', async () => {
      await go(page, `/builder?agent=${ids.analyst}`);
      await page.getByTestId('config-tab-prompt').click();
      const prompt = page.getByTestId('builder-system-prompt');
      const MARK = '\nEnd every answer with the line POLICY-DESK-V2.';
      // clear what an earlier run left, so the version before the edit has no marker
      const current = await prompt.inputValue();
      const original = current.split(MARK).join('');
      if (original !== current) {
        const cleaned = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes(`/api/agents/${ids.analyst}`));
        await prompt.fill(original);
        await page.getByTestId('builder-save-draft').click();
        await cleaned;
      }
      await prompt.fill(`${original}${MARK}`);
      const saved = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes(`/api/agents/${ids.analyst}`), { timeout: 30_000 });
      await page.getByTestId('builder-save-draft').click();
      const res = await saved;
      const banner = await page.getByTestId('builder-save-error').innerText().catch(() => '');
      await record(page, 'owner saves edit', res.ok() && !banner, `PUT ${res.status()} ${banner}`);
      await go(page, `/agents/${ids.analyst}/chat`);
      let t = await chat(page, 'Which plant does Nordtek supply?');
      await record(page, 'prompt change live', /POLICY-DESK-V2/.test(t), `answer tail: ${t.slice(-160)}`);

      await go(page, `/agents/${ids.analyst}/info`);
      await page.getByTestId('agent-versions').click();
      // the newest earlier version is the one before the edit, or the original if there is none
      await expect(page.getByTestId('version-restore-original')).toBeVisible({ timeout: 20_000 });
      const earlier = page.locator('[data-testid^="version-revert-"]');
      if (await earlier.count()) await earlier.first().click();
      else await page.getByTestId('version-restore-original').click();
      await page.getByTestId('version-revert-confirm').click();
      await expect(page.locator('body')).toContainText('Restored', { timeout: 15_000 });
      await page.waitForTimeout(2500);
      await go(page, `/agents/${ids.analyst}/chat`);
      t = await chat(page, 'Which plant does Nordtek supply?');
      await record(page, 'prompt reverted', !/POLICY-DESK-V2/.test(t) && /Brno|plant/i.test(t), `answer tail: ${t.slice(-160)}`);
    });

    // ── 4. deleting things others depend on ─────────────────────────────
    await test.step('deleting the scorer shows what breaks, then restore', async () => {
      await go(page, '/agents');
      const del = page.getByTestId(`agent-delete-${ids.scorer}`);
      await del.scrollIntoViewIfNeeded().catch(() => {});
      await del.click({ force: true });
      const deps = page.getByTestId('delete-dependents');
      await expect(deps).toBeVisible({ timeout: 20_000 });
      const listed = await deps.innerText();
      await record(
        page,
        'dependents listed',
        /Pipelines/i.test(listed) && /Triggers/i.test(listed) && /Agents/i.test(listed),
        `dialog: ${listed.replace(/\s+/g, ' ').slice(0, 220)}`,
      );
      await page.getByTestId('delete-confirm').click();
      await expect(page.getByTestId('delete-dialog')).toHaveCount(0, { timeout: 20_000 });

      await go(page, `/triggers?agent=${ids.scorer}`);
      await page.keyboard.press('Escape');
      const states = await page.locator('[data-testid^="trigger-row-"]', { hasText: NAMES.scorer }).locator('[data-testid^="trigger-state-"]').allInnerTexts();
      await record(page, 'triggers switched off', states.length > 0 && states.every((s) => /agent deleted/i.test(s)), `states: ${states.join(', ')}`);

      await go(page, `/agents/${ids.pipeline}/chat`);
      const t = await chat(page, 'Run the supplier risk briefing.', 600_000);
      await record(page, 'pipeline names the deleted agent', /was deleted/i.test(t), `answer tail: ${t.slice(-220)}`);

      await go(page, '/agents/manage');
      await page.getByTestId('deleted-agents-toggle').click();
      await page.getByTestId(`agent-restore-${ids.scorer}`).click();
      await expect(page.locator('body')).toContainText('restored', { timeout: 20_000 });
      await go(page, `/triggers?agent=${ids.scorer}`);
      await page.keyboard.press('Escape');
      const back = await page.locator('[data-testid^="trigger-row-"]', { hasText: NAMES.scorer }).locator('[data-testid^="trigger-state-"]').allInnerTexts();
      await record(page, 'restore brings triggers back', back.length > 0 && back.every((s) => /Active/.test(s)), `states: ${back.join(', ')}`);
    });

    await test.step('deleting the knowledge base and the code asset warns first', async () => {
      await go(page, '/knowledge');
      const card = page.locator(`[data-testid="kb-card"][data-name="${NAMES.kb}"]`);
      await expect(card).toBeVisible({ timeout: 20_000 });
      await card.hover();
      await card.locator('[data-testid^="kb-delete-"]').click();
      const deps = page.getByTestId('delete-dependents');
      await expect(deps).toBeVisible({ timeout: 20_000 });
      const listed = await deps.innerText();
      await record(page, 'kb dependents', /Agents/i.test(listed) && /Atlas graphs/i.test(listed), listed.replace(/\s+/g, ' ').slice(0, 200));
      await page.keyboard.press('Escape');

      await openAsset(page, NAMES.asset);
      await page.getByRole('button', { name: 'Delete' }).first().click();
      const adeps = page.getByTestId('delete-dependents');
      await expect(adeps).toBeVisible({ timeout: 20_000 });
      const alisted = await adeps.innerText();
      await record(page, 'asset dependents', new RegExp(NAMES.scorer).test(alisted), alisted.replace(/\s+/g, ' ').slice(0, 200));
      await page.keyboard.press('Escape');
    });
  } finally {
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), mate: MATE.email, findings }, null, 2));
  }
});
