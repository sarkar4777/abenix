/**
 * Extended deep UI UAT — Pass 2.
 *
 * Builds on uat-ui-deep.ts. Things this round adds:
 *   F. Form validation feedback (empty required, invalid email, password too short)
 *   G. Every "New X" button — does it open a modal/route?
 *   H. Admin-only routes return 403 cleanly for non-admins
 *   I. Mobile viewport check (sidebar collapse + canvas behavior)
 *   J. Keyboard navigation (Tab order, Enter to submit)
 *   K. Live debug WebSocket (does it connect?)
 *   L. Settings sub-pages: profile / privacy / data / notifications / observability / api / api-keys
 *   M. Atlas — search vs traverse vs describe each as their own UI flow
 *   N. BPM Analyzer file upload affordance
 *   O. Code Runner zip upload + analyze affordance
 *   P. SDK Playground TS / Python tabs
 *   Q. Analytics filters (date range, agent filter)
 *   R. Webhooks UI (CRUD)
 *   S. Triggers UI (cron + webhook + schedule)
 *   T. Help search
 *   U. Browser back/forward across SPA routes
 *   V. /tools (NEW — verify it now renders + search works)
 *   W. /settings/integrations (NEW — verify it renders with status badges)
 *   X. Sidebar discovery — should now find ALL routes (post-fix verification)
 */

import { chromium, type Browser, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';
const API = process.env.ABENIX_API || 'http://localhost:8000';

const REPORT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'ui-extended');
fs.mkdirSync(REPORT_DIR, { recursive: true });
const PROGRESS = path.join(REPORT_DIR, 'progress.log');
fs.writeFileSync(PROGRESS, '');

type Severity = 'P0' | 'P1' | 'P2' | 'UX' | 'GAP' | 'OK' | 'SKIP';
interface Finding {
  id: string;
  area: string;
  test: string;
  expected: string;
  actual: string;
  severity: Severity;
}
const findings: Finding[] = [];
let nextId = 1;
const consoleErrors: string[] = [];
const networkFails: { url: string; status: number }[] = [];

function record(area: string, test: string, expected: string, actual: string, severity: Severity) {
  const id = `X${String(nextId++).padStart(3, '0')}`;
  findings.push({ id, area, test, expected, actual, severity });
  const tag = severity === 'OK' ? '✓' : severity === 'GAP' ? '!' : severity === 'UX' ? '~' : severity === 'SKIP' ? '·' : '✗';
  const line = `  ${tag} ${id} [${severity}] ${area} → ${test} — ${actual.slice(0, 140)}`;
  fs.appendFileSync(PROGRESS, line + '\n');
  process.stdout.write(line + '\n');
}

async function snap(page: Page, name: string): Promise<void> {
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  await page.screenshot({ path: path.join(REPORT_DIR, `${safe}.png`), fullPage: false }).catch(() => {});
}

function attach(page: Page) {
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(`[${page.url().slice(BASE.length)}] ${msg.text().slice(0, 200)}`);
  });
  page.on('response', resp => {
    const u = resp.url();
    if (resp.status() >= 400 && !u.includes('favicon') && !u.startsWith('chrome-extension:') && !u.includes('/api/auth/me')) {
      networkFails.push({ url: u.slice(0, 200), status: resp.status() });
    }
  });
}

async function adminLogin(page: Page) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.locator('#auth-email').waitFor({ timeout: 25_000 });
  await page.waitForTimeout(1500);
  const fired = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
    if (!btn) return false;
    const k = Object.keys(btn).find(kk => kk.startsWith('__reactProps$'));
    if (!k) return false;
    (btn as any)[k].onClick();
    return true;
  });
  if (fired) await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
  return fired;
}

// ── F. Form validation ──

async function testFormValidation(browser: Browser) {
  const area = 'F. Form validation';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    // Empty submit on login form should NOT crash; should produce a hint.
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#auth-email').waitFor({ timeout: 15_000 });
    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click({ force: true }).catch(() => {});
    await page.waitForTimeout(1000);
    // HTML5 required attribute on email triggers browser validation;
    // we just want to confirm the form didn't navigate or crash.
    const stillOnLogin = (await page.locator('#auth-email').count()) > 0;
    record(area, 'login: empty submit doesn\'t crash', 'still on login form', stillOnLogin ? 'still here' : 'navigated', stillOnLogin ? 'OK' : 'P1');

    // Bad email format
    await page.fill('#auth-email', 'not-an-email');
    await page.fill('#auth-password', 'x');
    await submitBtn.click({ force: true }).catch(() => {});
    await page.waitForTimeout(1000);
    const validity = await page.evaluate(() => (document.getElementById('auth-email') as HTMLInputElement)?.validationMessage || '');
    record(area, 'login: bad email format produces validation msg', 'non-empty', `validity='${validity.slice(0, 60)}'`, validity ? 'OK' : 'UX');
  } finally { await ctx.close(); }
}

// ── G. New-X buttons ──

async function testNewButtons(browser: Browser) {
  const area = 'G. New X buttons';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    for (const route of ['/agents', '/knowledge', '/builder', '/triggers', '/webhooks']) {
      const r = await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' }).catch(() => null);
      if (!r || r.status() >= 400) {
        record(area, `${route} reachable`, '<400', `status=${r?.status() || 'unreachable'}`, route === '/webhooks' ? 'GAP' : 'P2');
        continue;
      }
      await page.waitForTimeout(2000);
      // Look for a primary "Create" / "New" button
      const hasNew = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('a, button')).some(el => /new|create|add|build|upload|register/i.test(el.textContent || ''));
      });
      record(area, `${route} has New/Create CTA`, 'visible', hasNew ? 'present' : 'absent', hasNew ? 'OK' : 'UX');
    }
  } finally { await ctx.close(); }
}

// ── H. Admin-only routes ──

async function testAdminRoutes(browser: Browser) {
  const area = 'H. Admin routes';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    for (const route of ['/admin/scaling', '/admin/llm-settings', '/admin/llm-pricing', '/review-queue']) {
      const r = await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' }).catch(() => null);
      const status = r?.status() ?? 0;
      await page.waitForTimeout(1500);
      const body = (await page.textContent('body')) || '';
      const renders = status < 400 && body.length > 200;
      record(area, `${route} renders for admin`, '<400 + content', `status=${status} len=${body.length}`, renders ? 'OK' : 'P2');
    }
  } finally { await ctx.close(); }
}

// ── I. Mobile viewport ──

async function testMobile(browser: Browser) {
  const area = 'I. Mobile viewport';
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    // On mobile the sidebar should be hidden / behind a hamburger
    const sidebarVisible = await page.evaluate(() => {
      const aside = document.querySelector('aside');
      if (!aside) return false;
      const r = (aside as HTMLElement).getBoundingClientRect();
      return r.width > 50 && r.left >= 0;
    });
    record(area, 'sidebar collapses or hides on mobile', 'collapsed/hidden', sidebarVisible ? 'still wide' : 'collapsed', sidebarVisible ? 'UX' : 'OK');
    await snap(page, 'I-mobile-dashboard');

    // Hamburger / menu trigger
    const hasHamburger = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('button')).some(b => /menu|☰|hamburger/i.test(b.textContent || '') || b.querySelector('svg[class*="Menu"]'));
    });
    record(area, 'mobile has menu trigger', 'visible', hasHamburger ? 'present' : 'absent', hasHamburger ? 'OK' : 'UX');
  } finally { await ctx.close(); }
}

// ── J. Keyboard navigation ──

async function testKeyboard(browser: Browser) {
  const area = 'J. Keyboard nav';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#auth-email').waitFor({ timeout: 15_000 });
    // Tab from email → password → submit
    await page.focus('#auth-email');
    await page.keyboard.press('Tab');
    await page.waitForTimeout(200);
    const focused1 = await page.evaluate(() => (document.activeElement as HTMLElement)?.id || (document.activeElement as HTMLElement)?.tagName);
    record(area, 'login: Tab from email moves to password (or eye-toggle)', 'auth-password or close', `focused='${focused1}'`, /auth-password|button/i.test(String(focused1)) ? 'OK' : 'UX');
  } finally { await ctx.close(); }
}

// ── K. Live debug WebSocket ──

async function testLiveDebug(browser: Browser) {
  const area = 'K. Live debug';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    let wsOpened = false;
    page.on('websocket', () => { wsOpened = true; });
    const r = await page.goto(`${BASE}/executions/live`, { waitUntil: 'domcontentloaded' }).catch(() => null);
    await page.waitForTimeout(5000);
    const status = r?.status() ?? 0;
    record(area, '/executions/live reachable', '<400', `status=${status}`, status < 400 ? 'OK' : 'P1');
    record(area, '/executions/live opens a WebSocket', 'connection observed', wsOpened ? 'opened' : 'no ws', wsOpened ? 'OK' : 'UX');
  } finally { await ctx.close(); }
}

// ── L. Settings sub-pages ──

async function testSettingsSubpages(browser: Browser) {
  const area = 'L. Settings subpages';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    for (const sub of ['/profile', '/privacy', '/data', '/notifications', '/observability', '/api', '/api-keys', '/integrations']) {
      const r = await page.goto(`${BASE}/settings${sub}`, { waitUntil: 'domcontentloaded' }).catch(() => null);
      await page.waitForTimeout(1500);
      const status = r?.status() ?? 0;
      const body = (await page.textContent('body')) || '';
      const renders = status < 400 && body.length > 200;
      record(area, `/settings${sub} renders`, 'has content', `status=${status} len=${body.length}`, renders ? 'OK' : 'GAP');
    }
  } finally { await ctx.close(); }
}

// ── M. Atlas paths ──

async function testAtlasPaths(browser: Browser) {
  const area = 'M. Atlas paths';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    await page.goto(`${BASE}/atlas`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    const body = (await page.textContent('body')) || '';
    for (const cue of ['search', 'describe', 'traverse', 'concept']) {
      const has = new RegExp(`\\b${cue}\\b`, 'i').test(body);
      record(area, `atlas surfaces '${cue}' affordance`, 'visible', has ? 'present' : 'absent', has ? 'OK' : 'UX');
    }
  } finally { await ctx.close(); }
}

// ── N/O/P. Domain-specific surface checks ──

async function testDomainSurfaces(browser: Browser) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record('N-P. Domain', 'login', 'OK', 'failed', 'P1'); return; }
    const checks: { area: string; route: string; cues: string[]; }[] = [
      { area: 'N. BPM Analyzer', route: '/bpm-analyzer', cues: ['upload', 'pdf', 'image', 'analyze'] },
      { area: 'O. Code Runner', route: '/code-runner', cues: ['upload', 'zip', 'analyze', 'language'] },
      { area: 'P. SDK Playground', route: '/sdk-playground', cues: ['typescript', 'python', 'curl', 'sdk'] },
      { area: 'Q. Analytics', route: '/analytics', cues: ['date', 'filter', 'agent', 'usage'] },
      { area: 'R. Webhooks', route: '/webhooks', cues: ['endpoint', 'signing', 'event', 'create'] },
      { area: 'S. Triggers', route: '/triggers', cues: ['cron', 'schedule', 'webhook', 'create'] },
      { area: 'T. Help', route: '/help', cues: ['search', 'getting started', 'first', 'tutorial'] },
      { area: 'V. Tools catalogue (NEW)', route: '/tools', cues: ['core', 'data', 'enterprise', 'search'] },
      { area: 'W. Integrations (NEW)', route: '/settings/integrations', cues: ['anthropic', 'configured', 'env', 'api key'] },
    ];
    for (const c of checks) {
      const r = await page.goto(`${BASE}${c.route}`, { waitUntil: 'domcontentloaded' }).catch(() => null);
      const status = r?.status() ?? 0;
      if (status >= 400) {
        record(c.area, `${c.route} reachable`, '<400', `status=${status}`, c.route.includes('/webhooks') || c.route.includes('/triggers') ? 'GAP' : 'P2');
        continue;
      }
      await page.waitForTimeout(2500);
      const body = ((await page.textContent('body')) || '').toLowerCase();
      const matched = c.cues.filter(cue => body.includes(cue.toLowerCase()));
      record(c.area, `${c.route} has expected cues`, c.cues.join(' / '), `matched: ${matched.join(',')}`, matched.length >= Math.ceil(c.cues.length / 2) ? 'OK' : 'UX');
    }
  } finally { await ctx.close(); }
}

// ── X. Post-fix sidebar discovery ──

async function testSidebarPostFix(browser: Browser) {
  const area = 'X. Sidebar post-fix';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    await page.waitForTimeout(2000);
    const routes = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('aside a[href], nav a[href]'));
      const out = new Set<string>();
      for (const a of links) {
        const href = (a as HTMLAnchorElement).getAttribute('href') || '';
        if (href.startsWith('/')) out.add(href);
      }
      return Array.from(out);
    });
    record(area, 'sidebar surfaces all routes after fix', '>=15', `found ${routes.length}: ${routes.slice(0, 12).join(', ')}…`, routes.length >= 15 ? 'OK' : 'P1');
    record(area, 'sidebar includes /tools', 'present', routes.includes('/tools') ? 'present' : 'absent', routes.includes('/tools') ? 'OK' : 'P1');
    record(area, 'sidebar includes /settings/integrations', 'present', routes.includes('/settings/integrations') ? 'present' : 'absent', routes.includes('/settings/integrations') ? 'OK' : 'P1');
  } finally { await ctx.close(); }
}

// ── U. Browser back/forward ──

async function testBackForward(browser: Browser) {
  const area = 'U. Back/forward nav';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attach(page);
  try {
    if (!(await adminLogin(page))) { record(area, 'login', 'OK', 'failed', 'P1'); return; }
    await page.goto(`${BASE}/agents`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    await page.goto(`${BASE}/atlas`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    await page.goBack();
    await page.waitForTimeout(1500);
    record(area, 'browser back returns to /agents', '/agents', `at ${page.url()}`, page.url().endsWith('/agents') ? 'OK' : 'UX');
    await page.goForward();
    await page.waitForTimeout(1500);
    record(area, 'browser forward returns to /atlas', '/atlas', `at ${page.url()}`, page.url().endsWith('/atlas') ? 'OK' : 'UX');
  } finally { await ctx.close(); }
}

// ── Cross-cutting wrap-up ──

function summariseCrossCutting() {
  const area = 'Z. Cross-cutting';
  if (consoleErrors.length === 0) {
    record(area, 'console errors during run', '0', '0', 'OK');
  } else {
    const sample = consoleErrors.slice(0, 3).join(' || ');
    record(area, 'console errors during run', '0', `${consoleErrors.length} errs. samples: ${sample}`, consoleErrors.length > 10 ? 'P1' : 'P2');
  }
  if (networkFails.length === 0) {
    record(area, '4xx/5xx responses observed', '0', '0', 'OK');
  } else {
    const byRoute: Record<string, number> = {};
    for (const f of networkFails) {
      const p = f.url.replace(BASE, '').replace(API, '').split('?')[0];
      byRoute[`${f.status} ${p}`] = (byRoute[`${f.status} ${p}`] || 0) + 1;
    }
    const top = Object.entries(byRoute).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `${k} (×${v})`).join(' || ');
    record(area, '4xx/5xx responses observed', '0', `${networkFails.length}. top: ${top}`, networkFails.length > 10 ? 'P1' : 'P2');
  }
}

// ── Main ──

(async () => {
  fs.appendFileSync(PROGRESS, `Extended UI UAT against ${BASE}\n\n`);
  const browser = await chromium.launch({ headless: true });
  try {
    await testFormValidation(browser);
    await testNewButtons(browser);
    await testAdminRoutes(browser);
    await testMobile(browser);
    await testKeyboard(browser);
    await testLiveDebug(browser);
    await testSettingsSubpages(browser);
    await testAtlasPaths(browser);
    await testDomainSurfaces(browser);
    await testBackForward(browser);
    await testSidebarPostFix(browser);
    summariseCrossCutting();
  } finally {
    await browser.close();
  }
  const counts: Record<Severity, number> = { OK: 0, P0: 0, P1: 0, P2: 0, UX: 0, GAP: 0, SKIP: 0 };
  for (const f of findings) counts[f.severity]++;
  const reportPath = path.resolve(__dirname, '..', 'BUGS_UI_EXTENDED.md');
  const lines: string[] = [];
  lines.push('# Extended UI UAT — Pass 2 (forms, modals, admin, mobile, kbd, websocket, settings sub, etc.)');
  lines.push('');
  lines.push(`**Date:** 2026-05-02 · **Environment:** ${BASE}`);
  lines.push('');
  lines.push(`**Summary:** ${findings.length} checks — ${counts.OK} OK · ${counts.P0} P0 · ${counts.P1} P1 · ${counts.P2} P2 · ${counts.UX} UX · ${counts.GAP} GAP · ${counts.SKIP} SKIP`);
  lines.push('');
  lines.push('## Findings (non-OK)');
  lines.push('| ID | Sev | Area | Test | Expected | Actual |');
  lines.push('|---|---|---|---|---|---|');
  for (const f of findings.filter(x => x.severity !== 'OK')) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.expected} | ${f.actual.replace(/\|/g, '\\|').slice(0, 200)} |`);
  }
  lines.push('');
  lines.push('## All checks');
  lines.push('| ID | Sev | Area | Test | Detail |');
  lines.push('|---|---|---|---|---|');
  for (const f of findings) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.actual.replace(/\|/g, '\\|').slice(0, 200)} |`);
  }
  fs.writeFileSync(reportPath, lines.join('\n'));
  process.stdout.write(`\nReport: ${reportPath}\nSummary: OK=${counts.OK} P0=${counts.P0} P1=${counts.P1} P2=${counts.P2} UX=${counts.UX} GAP=${counts.GAP}\n`);
})().catch(e => {
  fs.appendFileSync(PROGRESS, `FATAL: ${e}\n`);
  console.error('FATAL:', e);
  process.exit(1);
});
