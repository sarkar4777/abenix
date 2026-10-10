/**
 * Lostness gate: every page in the sidebar's full list, as every role, at phone and desktop width.
 *
 * For each route and role one of these must hold:
 *   - the page loads with a header and a purpose line (page-header, page-purpose), a visible
 *     primary action (page-primary-action) or a plain "nothing to do here" or permission
 *     explanation, no raw error codes outside code, kbd or pre, no JSON or stack traces,
 *     and no sideways scroll at 390 px or 1440 px
 *   - the purpose line is visible, at least 240 px wide on desktop or 160 px on a phone and at
 *     most 4 lines, the primary action sits inside the viewport, and the header does not overlap
 *     the content next to it
 *   - or the page says it is not available for this role and links onward
 *
 * The creator, member and viewer are invited from Settings, Team in beforeAll and removed in
 * afterAll. There is no viewer role yet, so the viewer is a Member with no extra permission sets.
 * Every failure is collected and reported in one table at the end.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_lostness_gate.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };
const VIEWPORTS = [PHONE, DESKTOP];
const OUT = path.join(__dirname, 'uat_lostness_gate');
const SIDEBAR = path.join(__dirname, '..', 'apps', 'web', 'src', 'components', 'layout', 'Sidebar.tsx');

type Role = 'admin' | 'creator' | 'member' | 'viewer';
interface Person { email: string; password: string; name: string; invite: 'admin' | 'creator' | 'user' }
interface Failure { role: Role; route: string; width: number; problem: string }

const people: Record<Role, Person> = {
  admin: { ...ADMIN, name: 'Admin', invite: 'admin' },
  creator: { email: `lost-creator-${RUN}@example.com`, password: `Creator-${RUN}-9x`, name: `Creator ${RUN}`, invite: 'creator' },
  member: { email: `lost-member-${RUN}@example.com`, password: `Member-${RUN}-9x`, name: `Member ${RUN}`, invite: 'user' },
  viewer: { email: `lost-viewer-${RUN}@example.com`, password: `Viewer-${RUN}-9x`, name: `Viewer ${RUN}`, invite: 'user' },
};
const failures: Failure[] = [];
const checked: Array<{ role: Role; route: string; width: number; verdict: string }> = [];

// one list: the hrefs in Sidebar.tsx, read at run time so a new entry is gated the day it lands
function sidebarRoutes(): string[] {
  const src = fs.readFileSync(SIDEBAR, 'utf-8');
  const block = src.slice(src.indexOf('const NAV_GROUPS'), src.indexOf('function useMiniStats'));
  const out: string[] = [];
  for (const m of block.matchAll(/\{[^{}]*?href:\s*'([^']+)'[^{}]*?\}/g)) {
    if (/external:\s*true/.test(m[0])) continue;
    if (!out.includes(m[1])) out.push(m[1]);
  }
  return out;
}
// LOSTNESS_ROUTES and LOSTNESS_ROLES narrow a run, CI uses them for a quick pass
const ALL_ROUTES = sidebarRoutes();
const ROUTES = process.env.LOSTNESS_ROUTES ? process.env.LOSTNESS_ROUTES.split(',').map((r) => r.trim()).filter(Boolean) : ALL_ROUTES;
const ROLES = (process.env.LOSTNESS_ROLES ? process.env.LOSTNESS_ROLES.split(',').map((r) => r.trim()) : ['admin', 'creator', 'member', 'viewer']) as Role[];

const RAW_CODE = /\b[A-Z]+(?:_[A-Z]+)*_(?:ERROR|FAILED|TIMEOUT|EXCEEDED|DENIED|NOT_FOUND|NOT_ALLOWED|INVALID|FORBIDDEN|VIOLATION|BLOCKED)\b/;
const RAW_ERROR: Array<{ re: RegExp; what: string; outsideCode?: boolean }> = [
  { re: /Traceback \(most recent call last\)/, what: 'a Python traceback' },
  { re: /\n\s+at \S+ \(\S+:\d+:\d+\)/, what: 'a JavaScript stack trace' },
  { re: /Unhandled Runtime Error|Application error: a client-side exception/i, what: 'a crash screen' },
  { re: /\{\s*"(data|error|detail|message|meta)"\s*:/, what: 'raw JSON' },
  { re: /\[object Object\]/, what: '[object Object]' },
  { re: /Internal Server Error|Server error \(\d{3}\)|\bHTTP \d{3}\b|status code \d{3}/i, what: 'a raw HTTP error' },
  { re: RAW_CODE, what: 'a raw error code', outsideCode: true },
  { re: /\bNaN\b|\bundefined\b/, what: 'NaN or undefined in the text' },
];
// "nothing to do here" or a permission explanation, both count as a way forward
const EXPLAINED = /view only\.|an admin can give you|nothing (to do|here|needs you|waiting)|no .{1,40} yet|you (do not|don't|cannot|can't) |needs? the .{1,60}(permission|capability|role)|ask (an|your) admin|only (admins|an admin)|not available|turned off|not (turned|switched) on|is off\b/i;
const NOT_FOR_ROLE = /not available|(do not|don't) have (access|permission)|needs? the .{1,60}(permission|capability|role)|only (admins|an admin)|ask (an|your) admin|admin(s)? only|not allowed/i;

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
}

async function signIn(page: Page, who: { email: string; password: string }) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

// invite from Settings, accept the link in a fresh browser
async function invite(page: Page, browser: Browser, who: Person) {
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).first().click();
  await page.getByPlaceholder('email@example.com').fill(who.email);
  await page.getByTestId('invite-role').selectOption(who.invite);
  await page.getByTestId('invite-send').click();
  const link = page.getByTestId('invite-link');
  await expect(link).toBeVisible({ timeout: 20_000 });
  const raw = ((await link.innerText()) || (await link.inputValue().catch(() => ''))).trim();
  const url = raw.startsWith('http') ? raw.replace(/^https?:\/\/[^/]+/, BASE) : `${BASE}${raw}`;
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p2 = await ctx.newPage();
  await p2.goto(url, { waitUntil: 'domcontentloaded' });
  await expect(p2.getByTestId('accept-title')).toBeVisible({ timeout: 30_000 });
  await p2.locator('#accept-full-name').fill(who.name);
  await p2.locator('#accept-password').fill(who.password);
  await p2.getByTestId('accept-submit').click();
  await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
}

async function visibleText(page: Page): Promise<string> {
  const main = page.locator('main').first();
  return ((await main.count()) ? await main.innerText().catch(() => '') : await page.locator('body').innerText()).slice(0, 60_000);
}

// visible text minus code, kbd and pre, where a code shown as a small reference is fine
async function textOutsideCode(page: Page): Promise<string> {
  return page.evaluate(() => {
    const root = document.querySelector('main') || document.body;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const parts: string[] = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!el || el.closest('code, kbd, pre, script, style')) continue;
      const shown = typeof el.checkVisibility === 'function' ? el.checkVisibility({ checkVisibilityCSS: true }) : el.getClientRects().length > 0;
      if (shown) parts.push(n.textContent || '');
    }
    return parts.join(' ').slice(0, 60_000);
  });
}

// the header has to read as a header: a real purpose line, the action on screen, nothing under it
async function headerLayout(page: Page) {
  return page.evaluate(() => {
    const header = Array.from(document.querySelectorAll('[data-testid="page-header"]')).find(
      (el) => el.getClientRects().length > 0,
    );
    if (!header) return null;
    const box = (el: Element) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    };
    const purposeEl = header.querySelector('[data-testid="page-purpose"]');
    let purpose = null as null | { width: number; lines: number; visible: boolean };
    if (purposeEl) {
      const r = purposeEl.getBoundingClientRect();
      const cs = getComputedStyle(purposeEl);
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5 || 20;
      const visible =
        r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0;
      purpose = { width: Math.round(r.width), lines: Math.round(r.height / lh), visible };
    }
    const actionEl = header.querySelector('[data-testid="page-primary-action"]');
    const action = actionEl && actionEl.getClientRects().length ? box(actionEl) : null;
    // the first visible in-flow sibling after the header, or after its nearest wrapper that has one
    let content = null as null | ReturnType<typeof box>;
    let contentName = '';
    for (let node: Element | null = header; node && node !== document.body && !content; node = node.parentElement) {
      for (let sib = node.nextElementSibling; sib; sib = sib.nextElementSibling) {
        const cs = getComputedStyle(sib);
        if (cs.position === 'fixed' || cs.position === 'absolute' || cs.display === 'none') continue;
        const r = sib.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        content = box(sib);
        const tid = sib.getAttribute('data-testid');
        contentName = `${sib.tagName.toLowerCase()}${tid ? `[${tid}]` : ''}`;
        break;
      }
    }
    return { header: box(header), purpose, action, content, contentName, vw: document.documentElement.clientWidth };
  });
}

async function check(page: Page, role: Role, route: string, width: number): Promise<string[]> {
  const problems: string[] = [];
  const errors: string[] = [];
  const onError = (e: Error) => errors.push(e.message.slice(0, 160));
  page.on('pageerror', onError);
  try {
    await go(page, route);
  } catch (e) {
    page.off('pageerror', onError);
    return [`did not load: ${String(e).slice(0, 160)}`];
  }
  // pages paint their header after the first fetch, give them a moment
  await page.getByTestId('page-header').first().waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(400);
  page.off('pageerror', onError);

  const landed = new URL(page.url()).pathname;
  const text = await visibleText(page);
  const header = await page.getByTestId('page-header').first().isVisible().catch(() => false);
  const purpose = header ? ((await page.getByTestId('page-purpose').first().innerText().catch(() => '')) || '').trim() : '';
  const primary = await page.getByTestId('page-primary-action').first().isVisible().catch(() => false);
  const onward = await page.locator('main a[href]:visible').count().catch(() => 0);
  const notForRole = NOT_FOR_ROLE.test(text) && onward > 0;

  if (errors.length) problems.push(`script error: ${errors[0]}`);
  if (!landed.startsWith(route.split('?')[0]) && !notForRole) problems.push(`sent to ${landed} with no explanation`);
  if (text.trim().length < 20) problems.push('blank page');

  if (!notForRole) {
    if (!header) problems.push('no page header (page-header)');
    else if (purpose.length < 10) problems.push('no purpose line (page-purpose)');
    if (!primary && !EXPLAINED.test(text)) problems.push('no primary action and no "nothing to do here" or permission note');
  }
  if (header) {
    const lay = await headerLayout(page);
    const minWidth = width <= PHONE.width ? 160 : 240;
    if (!lay?.purpose?.visible) {
      problems.push('purpose line is not visible');
    } else {
      if (lay.purpose.width < minWidth) problems.push(`purpose line is ${lay.purpose.width} px wide, under ${minWidth} px`);
      if (lay.purpose.lines > 4) problems.push(`purpose line wraps to ${lay.purpose.lines} lines, more than 4`);
    }
    if (lay?.action && (lay.action.left < -1 || lay.action.right > lay.vw + 1)) {
      problems.push(`primary action is off screen sideways (${Math.round(lay.action.left)} to ${Math.round(lay.action.right)} px, viewport ${lay.vw} px)`);
    }
    if (lay?.content) {
      const c = lay.content;
      const h = lay.header;
      const w = Math.min(h.right, c.right) - Math.max(h.left, c.left);
      const v = Math.min(h.bottom, c.bottom) - Math.max(h.top, c.top);
      if (w > 2 && v > 2) problems.push(`header overlaps the content next to it (${lay.contentName}, ${Math.round(w)} x ${Math.round(v)} px)`);
    }
  }
  const plain = await textOutsideCode(page).catch(() => text);
  for (const { re, what, outsideCode } of RAW_ERROR) {
    const m = (outsideCode ? plain : text).match(re);
    if (m) problems.push(`shows ${what}: "${m[0].trim().slice(0, 60)}"`);
  }
  const sideways = await page.evaluate(() => {
    const doc = document.documentElement;
    const main = document.querySelector('main');
    const over = (el: Element | null) => !!el && el.scrollWidth > el.clientWidth + 1;
    return { page: over(doc), main: over(main), widest: main ? main.scrollWidth : doc.scrollWidth };
  });
  if (sideways.page || sideways.main) problems.push(`scrolls sideways at ${width} px (content ${sideways.widest} px wide)`);

  checked.push({ role, route, width, verdict: problems.length ? 'fail' : notForRole ? 'not for this role, explained' : 'ok' });
  return problems;
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ browser }) => {
  test.setTimeout(6 * 60_000);
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.accept());
  await signIn(page, ADMIN);
  for (const role of ROLES) if (role !== 'admin') await invite(page, browser, people[role]);
  await ctx.close();
});

// people are removed through the API so a broken screen never leaves test users behind
test.afterAll(async ({ playwright }) => {
  const req = await playwright.request.newContext();
  try {
    const login = await req.post(`${API}/api/auth/login`, { data: ADMIN });
    const tok = (await login.json())?.data?.access_token;
    const headers = { Authorization: `Bearer ${tok}` };
    const members = (await (await req.get(`${API}/api/team/members`, { headers })).json())?.data || [];
    const list = Array.isArray(members) ? members : members.members || [];
    for (const role of ['creator', 'member', 'viewer'] as const) {
      const m = list.find((x: { email?: string }) => x.email === people[role].email);
      if (m?.id) await req.delete(`${API}/api/team/members/${m.id}`, { headers }).catch(() => {});
    }
  } finally {
    await req.dispose();
  }
});

for (const viewport of VIEWPORTS) {
  for (const role of ROLES) {
    test(`every sidebar page is clear for the ${role} at ${viewport.width} px`, async ({ browser }) => {
      test.setTimeout(Math.max(10, ROUTES.length) * 45_000);
      const ctx = await browser.newContext({ viewport });
      const page = await ctx.newPage();
      page.on('dialog', (d) => d.dismiss().catch(() => {}));
      await signIn(page, people[role]);
      for (const route of ROUTES) {
        const problems = await check(page, role, route, viewport.width).catch((e) => [`check crashed: ${String(e).slice(0, 160)}`]);
        for (const problem of problems) failures.push({ role, route, width: viewport.width, problem });
      }
      await ctx.close();
    });
  }
}

test('lostness report', async () => {
  expect(ALL_ROUTES.length, 'routes read from Sidebar.tsx').toBeGreaterThan(20);
  for (const r of ROUTES) expect(ALL_ROUTES, `${r} is a sidebar route`).toContain(r);
  fs.mkdirSync(OUT, { recursive: true });
  const rows = failures.map((f) => `| ${f.route} | ${f.role} | ${f.width} | ${f.problem.replace(/\|/g, '/')} |`);
  const md = [
    `# Lostness gate ${new Date().toISOString()}`,
    '',
    `${ROUTES.length} routes, ${checked.length} checks, ${failures.length} problems`,
    '',
    '| Route | Role | Width | Problem |',
    '| --- | --- | --- | --- |',
    ...rows,
    '',
  ].join('\n');
  fs.writeFileSync(path.join(OUT, 'report.md'), md);
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ routes: ROUTES, checked, failures }, null, 2));
  console.log(md);
  expect(failures, `${failures.length} lostness problems, see e2e/uat_lostness_gate/report.md`).toEqual([]);
});
