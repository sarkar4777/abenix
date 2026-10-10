/**
 * A Member is never offered something that fails after the click.
 *
 * A fresh Member is invited from Settings, Team. On every page they can reach from the sidebar or Ctrl+K
 * that is about people, decisions, approvals or risk, the spec:
 *   - checks the page says it is view only where the Member can't change things, in plain words
 *   - fails if a control that only an admin or author could use (approve, delete, invite, save...) is shown enabled
 *   - presses every other enabled button in the page, confirms any dialog it opens, and fails on any 403 the click causes
 * Then Ctrl+K: decisions are found by name, and plain words about approving lead to Team and Approvals, as admin and as Member.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_member_view_only.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const MEMBER = { email: `viewonly-${RUN}@example.com`, password: `Member-${RUN}-9x`, name: `Vera Viewer ${RUN}` };
const OUT = path.join(__dirname, 'uat_member_view_only');

// the pages, with the view-only note each must show to a Member
const PAGES: { route: string; note?: string }[] = [
  { route: '/settings/team', note: 'team-view-only' },
  { route: '/decisions', note: 'decisions-view-only' },
  { route: '/decisions/sample_plant_limits', note: 'decision-view-only' },
  { route: '/decisions/gw.safety.exclusion', note: 'decision-view-only' },
  { route: '/decisions/reference-sets' },
  { route: '/approvals', note: 'approvals-view-only' },
  { route: '/inbox?tab=approvals', note: 'inbox-cannot-approve-rules' },
  { route: '/admin/risk#tiers', note: 'risk-view-only' },
  { route: '/admin/risk#switches', note: 'risk-view-only' },
  { route: '/admin/risk#tools', note: 'risk-view-only' },
  { route: '/admin/risk#audit', note: 'risk-view-only' },
  { route: '/admin/permissions' },
];

// controls a Member can never use on these pages, so they must not be offered
const ADMIN_ONLY = /^(approve|deny|return for changes|delete|remove|archive|retire|restore|publish|propose|withdraw|discard|send|invite|save|use defaults|reset|resume|stop|verify|new draft|new decision|import|let them approve|stop them approving|set as|give them)/i;
// buttons that only change what is shown, or that a Member may use, are pressed
const NEVER_PRESS = /sign out|log out|show all tools|show essentials/i;

interface Finding { route: string; problem: string }
const findings: Finding[] = [];
const pressed: Array<{ route: string; label: string; result: string }> = [];

async function go(page: Page, route: string) {
  // a change of hash alone would not reload the page, so the tab it names would not open
  if (route.includes('#')) await page.goto('about:blank');
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
  await page.waitForTimeout(500);
}

async function login(page: Page, who: { email: string; password: string }) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: who });
  expect(r.ok(), `login ${who.email}`).toBeTruthy();
  const t = (await r.json()).data.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, t);
}

async function invite(browser: Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await login(page, ADMIN);
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).first().click();
  await page.getByPlaceholder('email@example.com').fill(MEMBER.email);
  await page.getByTestId('invite-role').selectOption('user');
  await expect(page.getByTestId('invite-can-approve')).not.toBeChecked();
  await page.getByTestId('invite-send').click();
  const raw = (await page.getByTestId('invite-link').innerText({ timeout: 20_000 })).trim();
  const url = raw.startsWith('http') ? raw.replace(/^https?:\/\/[^/]+/, BASE) : `${BASE}${raw}`;
  const p2 = await ctx.newPage();
  await p2.goto(url, { waitUntil: 'domcontentloaded' });
  await p2.locator('#accept-full-name').fill(MEMBER.name);
  await p2.locator('#accept-password').fill(MEMBER.password);
  await p2.getByTestId('accept-submit').click();
  await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
}

// visible, enabled buttons in the page body, by their accessible text
async function buttonsIn(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const main = document.querySelector('main') || document.body;
    const out: string[] = [];
    for (const b of Array.from(main.querySelectorAll('button'))) {
      const el = b as HTMLButtonElement;
      if (el.disabled || el.closest('fieldset[disabled]') || el.getAttribute('aria-disabled') === 'true') continue;
      if (!el.getClientRects().length) continue;
      const label = (el.getAttribute('aria-label') || el.innerText || el.title || '').replace(/\s+/g, ' ').trim();
      if (label) out.push(label);
    }
    return out;
  });
}

test.describe.configure({ mode: 'default' });
test.setTimeout(15 * 60_000);

test.beforeAll(async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  await invite(browser);
});

test.afterAll(async ({ playwright }) => {
  const req = await playwright.request.newContext();
  try {
    const tok = (await (await req.post(`${API}/api/auth/login`, { data: ADMIN })).json())?.data?.access_token;
    const headers = { Authorization: `Bearer ${tok}` };
    const body = (await (await req.get(`${API}/api/team/members`, { headers })).json())?.data || {};
    const m = (Array.isArray(body) ? body : body.members || []).find((x: { email?: string }) => x.email === MEMBER.email);
    if (m?.id) await req.delete(`${API}/api/team/members/${m.id}`, { headers }).catch(() => {});
  } finally {
    await req.dispose();
  }
});

test('a Member is told what is view only, and no button they can press ends in a 403', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.dismiss().catch(() => {}));
  await login(page, MEMBER);
  const refused: string[] = [];
  page.on('response', (r) => { if (r.status() === 403 && r.url().startsWith(API)) refused.push(`${r.request().method()} ${new URL(r.url()).pathname}`); });

  for (const { route, note } of PAGES) {
    await go(page, route);
    refused.length = 0;
    if (note) {
      const shown = await page.getByTestId(note).first().isVisible().catch(() => false);
      if (!shown) findings.push({ route, problem: `no view-only note (${note})` });
    }
    const labels = await buttonsIn(page);
    for (const label of labels.filter((l) => ADMIN_ONLY.test(l))) findings.push({ route, problem: `offers "${label}", which a Member can't use` });

    const toPress = Array.from(new Set(labels.filter((l) => !ADMIN_ONLY.test(l) && !NEVER_PRESS.test(l)))).slice(0, 25);
    for (const label of toPress) {
      await go(page, route);
      refused.length = 0;
      const btn = page.locator('main button:visible:enabled').filter({ hasText: label }).first();
      const byAria = page.locator(`main button[aria-label="${label.replace(/"/g, '\\"')}"]:visible:enabled`).first();
      const target = (await btn.count()) ? btn : byAria;
      if (!(await target.count())) continue;
      await target.click({ timeout: 4_000 }).catch(() => {});
      await page.waitForTimeout(500);
      // a dialog it opened is confirmed with its main button, the way someone would
      const dialog = page.getByRole('dialog').last();
      if (await dialog.isVisible().catch(() => false)) {
        const confirm = dialog.locator('button:visible:enabled').filter({ hasNotText: /cancel|close|dismiss/i }).last();
        const confirmLabel = ((await confirm.innerText().catch(() => '')) || '').trim();
        if (confirmLabel && ADMIN_ONLY.test(confirmLabel)) findings.push({ route, problem: `"${label}" opens a dialog offering "${confirmLabel}"` });
        else if (await confirm.count()) await confirm.click({ timeout: 3_000 }).catch(() => {});
        await page.waitForTimeout(800);
        await page.keyboard.press('Escape').catch(() => {});
      }
      await page.waitForTimeout(400);
      if (refused.length) findings.push({ route, problem: `"${label}" ended in 403: ${refused.join(', ')}` });
      pressed.push({ route, label, result: refused.length ? '403' : 'ok' });
    }
  }
  await ctx.close();

  fs.mkdirSync(OUT, { recursive: true });
  const md = [
    `# Member view-only sweep ${new Date().toISOString()}`,
    '',
    `${PAGES.length} pages, ${pressed.length} buttons pressed, ${findings.length} problems`,
    '',
    '| Page | Problem |',
    '| --- | --- |',
    ...findings.map((f) => `| ${f.route} | ${f.problem.replace(/\|/g, '/')} |`),
    '',
    '## Pressed',
    '',
    '| Page | Button | Result |',
    '| --- | --- | --- |',
    ...pressed.map((p) => `| ${p.route} | ${p.label.replace(/\|/g, '/')} | ${p.result} |`),
    '',
  ].join('\n');
  fs.writeFileSync(path.join(OUT, 'report.md'), md);
  console.log(md);
  expect(findings, `${findings.length} problems, see e2e/uat_member_view_only/report.md`).toEqual([]);
});

async function palette(page: Page, q: string) {
  await page.evaluate(() => window.dispatchEvent(new Event('abenix:open-command-palette')));
  const input = page.getByTestId('command-palette-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill(q);
  await page.waitForTimeout(700);
  return page.getByTestId('command-palette-item');
}

test('Ctrl+K finds decisions by name and plain words about approving, for an admin and a Member', async ({ browser }) => {
  for (const who of [ADMIN, MEMBER]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await login(page, who);
    await go(page, '/dashboard');
    const items = await palette(page, 'sample plant');
    await expect(items.filter({ hasText: 'Sample plant limits' }).first(), `${who.email}: a decision by its name`).toHaveAttribute('data-href', '/decisions/sample_plant_limits', { timeout: 10_000 });
    await page.keyboard.press('Escape');
    await palette(page, 'who can approve');
    await expect(page.locator('[data-testid="command-palette-item"][data-href="/settings/team"]').first(), `${who.email}: who can approve leads to Team`).toBeVisible();
    await expect(page.locator('[data-testid="command-palette-item"][data-href="/approvals"]').first(), `${who.email}: and to Approvals`).toBeVisible();
    if (who === MEMBER) await expect(page.locator('[data-testid="command-palette-item"][data-href="/settings/team"]').first()).toContainText('Team (view only)');
    await page.keyboard.press('Escape');
    await palette(page, 'zzqq nothing like this');
    await expect(page.getByTestId('command-palette-empty')).toContainText('Nothing found');
    await expect(page.getByTestId('command-palette-search-docs')).toBeVisible();
    await expect(page.getByTestId('command-palette-help')).toBeVisible();
    await ctx.close();
  }
});
