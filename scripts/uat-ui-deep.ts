/**
 * Comprehensive UI deep UAT — every sidebar link, every primary
 * action, every business-user journey, against the live Azure cluster.
 *
 * Phases:
 *   A. Authentication & onboarding (login, signup-as-fresh-user, logout)
 *   B. Sidebar route audit — discover every nav link and visit it
 *   C. Per-route primary-action exercises (chat send, agent create,
 *      KB upload, atlas explore, builder canvas, executions detail,
 *      settings save, moderation view, etc.)
 *   D. Cross-cutting checks: visible errors / 404 links /
 *      console errors / empty state quality / loading-stuck
 *   E. Business-user journey: "I just signed up, can I build my first
 *      agent in 10 minutes without help?"
 *
 * Output: BUGS_UI_DEEP.md with a row per finding (P0/P1/P2/GAP/UX/OK)
 * + screenshots under logs/uat/ui-deep/.
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';
const API = process.env.ABENIX_API || 'http://localhost:8000';

const REPORT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'ui-deep');
fs.mkdirSync(REPORT_DIR, { recursive: true });
const PROGRESS = path.join(REPORT_DIR, 'progress.log');
fs.writeFileSync(PROGRESS, '');

type Severity = 'P0' | 'P1' | 'P2' | 'UX' | 'GAP' | 'OK';
interface Finding {
  id: string;
  area: string;
  test: string;
  expected: string;
  actual: string;
  severity: Severity;
  screenshot?: string;
}
const findings: Finding[] = [];
let nextId = 1;
const consoleErrors: { url: string; text: string }[] = [];
const networkFails: { url: string; status: number }[] = [];

function record(area: string, test: string, expected: string, actual: string, severity: Severity, screenshot?: string) {
  const id = `U${String(nextId++).padStart(3, '0')}`;
  findings.push({ id, area, test, expected, actual, severity, screenshot });
  const tag = severity === 'OK' ? '✓' : severity === 'GAP' ? '!' : severity === 'UX' ? '~' : '✗';
  const line = `  ${tag} ${id} [${severity}] ${area} → ${test} — ${actual.slice(0, 140)}`;
  fs.appendFileSync(PROGRESS, line + '\n');
  process.stdout.write(line + '\n');
}

async function snap(page: Page, name: string): Promise<string> {
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  const file = path.join(REPORT_DIR, `${safe}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => {});
  return file;
}

function attachListeners(page: Page, label: string) {
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push({ url: page.url(), text: `[${label}] ${msg.text().slice(0, 200)}` });
    }
  });
  page.on('response', resp => {
    const url = resp.url();
    if (resp.status() >= 400 && !url.includes('favicon') && !url.startsWith('chrome-extension:') && !url.includes('/api/auth/me')) {
      networkFails.push({ url: url.slice(0, 200), status: resp.status() });
    }
  });
}

// ── A. Authentication ────────────────────────────────────────────

async function fireAdminDemoLogin(page: Page) {
  await page.locator('#auth-email').waitFor({ timeout: 25_000 });
  await page.waitForTimeout(1500);
  const fired = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
    if (!btn) return 'no Admin Demo';
    const k = Object.keys(btn).find(kk => kk.startsWith('__reactProps$'));
    if (!k) return 'no reactProps';
    (btn as any)[k].onClick();
    return 'fired';
  });
  return fired === 'fired';
}

async function testAuth(browser: Browser) {
  const area = 'A. Auth';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'auth');
  try {
    // Anonymous landing
    const resp = await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    const status = resp?.status() || 0;
    record(area, 'landing page reachable', '<400', `status=${status}`, status < 400 ? 'OK' : 'P1', await snap(page, 'A-landing'));

    // Login form copy
    const emailInput = page.locator('#auth-email');
    const hasEmail = (await emailInput.count()) > 0;
    record(area, 'email input present', 'visible', hasEmail ? 'present' : 'missing', hasEmail ? 'OK' : 'P0');

    // Demo button presence
    const demoBtns = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('button')).map(b => b.textContent?.trim()).filter(t => t && /demo/i.test(t));
    });
    record(area, 'demo-account buttons visible', 'at least one Demo button', `found=${demoBtns.join(',')}`, demoBtns.length > 0 ? 'OK' : 'P2');

    // Forgot-password link
    const forgot = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('a, button')).map(b => b.textContent?.trim()).find(t => t && /forgot|reset/i.test(t));
    });
    record(area, 'forgot-password link visible', 'present', forgot ? `'${forgot}'` : 'absent', forgot ? 'OK' : 'GAP');

    // Signup link
    const signupLink = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('a, button')).map(b => b.textContent?.trim()).find(t => t && /sign\s*up|register|create.*account/i.test(t));
    });
    record(area, 'signup link visible', 'present', signupLink ? `'${signupLink}'` : 'absent', signupLink ? 'OK' : 'GAP');

    // Admin demo login
    const ok = await fireAdminDemoLogin(page);
    if (!ok) {
      record(area, 'admin demo login click', 'redirects to dashboard', 'click failed', 'P0', await snap(page, 'A-demo-fail'));
    } else {
      await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
      const url = page.url();
      record(area, 'admin demo login lands authenticated', 'authed area', `url=${url}`, /\/(dashboard|atlas|agents|home)/.test(url) ? 'OK' : 'P0', await snap(page, 'A-after-login'));
    }

    // Logout discoverability — wait a beat for the sidebar to mount
    // and check both visible text and aria-label so screen-reader-only
    // labels (which we use for icon-only buttons) count.
    await page.waitForTimeout(2_000);
    const logoutVisible = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('button, a')).some(b => {
        const text = b.textContent || '';
        const aria = b.getAttribute('aria-label') || '';
        return /logout|sign.?out|log.?out/i.test(text) || /logout|sign.?out|log.?out/i.test(aria);
      });
    });
    record(area, 'logout option discoverable', 'visible somewhere', logoutVisible ? 'visible' : 'hidden', logoutVisible ? 'OK' : 'UX');
  } finally {
    await ctx.close();
  }
}

// ── B. Sidebar route audit ───────────────────────────────────────

async function discoverSidebarRoutes(page: Page): Promise<{ label: string; href: string }[]> {
  return await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('aside a[href], nav a[href]'));
    const out: { label: string; href: string }[] = [];
    for (const a of links) {
      const href = (a as HTMLAnchorElement).getAttribute('href') || '';
      const label = (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
      if (href && href.startsWith('/') && !href.startsWith('//') && label) {
        if (!out.find(o => o.href === href)) out.push({ label, href });
      }
    }
    return out;
  });
}

async function testRoute(page: Page, label: string, href: string) {
  const area = `B. ${href}`;
  try {
    const resp = await page.goto(`${BASE}${href}`, { waitUntil: 'domcontentloaded', timeout: 25_000 });
    const status = resp?.status() ?? 0;
    if (status >= 400) {
      record(area, `${label}: GET ${href}`, '<400', `status=${status}`, 'P1', await snap(page, `B-${href}`));
      return;
    }
    await page.waitForTimeout(2500);
    // innerText returns only visible/rendered text, not script content.
    // textContent picks up inlined JS (which always contains the word
    // "error" because of error boundaries) and triggers false positives.
    const body = (await page.evaluate(() => (document.body as HTMLElement).innerText || '')) || '';
    const lower = body.toLowerCase();

    // Empty/blank pages
    if (body.trim().length < 50) {
      record(area, `${label}: page not blank`, 'meaningful content', `body=${body.length} chars`, 'P1', await snap(page, `B-${href}`));
      return;
    }

    // Stuck loading
    const stuckLoading = /^\s*loading\s*\.?\.?\.?\s*$/i.test(body.trim()) || lower.includes('loading...') && body.length < 200;
    if (stuckLoading) {
      record(area, `${label}: not stuck on loading`, 'rendered content', 'looks stuck', 'P1', await snap(page, `B-${href}`));
      return;
    }

    // Visible error indicators — match phrases that indicate a real
    // user-facing error state, not just bare words like "failed" that
    // appear in legitimate stat labels (e.g., sidebar "Failed: 0").
    const errCues = lower.match(/something went wrong|stack trace|undefined is not|cannot read prop|failed to (fetch|load|parse|connect|apply|create|update|delete)|server error|an error (occurred|happened)|500 internal|503 service|unhandled (rejection|exception)|fatal error/);
    if (errCues) {
      const errExcerpt = errCues[0];
      record(area, `${label}: no visible error text`, 'no error cues', `cue='${errExcerpt}'`, 'P2', await snap(page, `B-${href}`));
      return;
    }

    // Empty state without CTA
    const isEmpty = /no (agents|executions|alerts|data|results|knowledge.bases|webhooks|tools|policies|memories|models|workflows|conversations)|nothing yet|get started by|create your first/i.test(body);
    const hasCTA = /create|new|add|build|upload|import|invite/i.test(body);
    if (isEmpty && !hasCTA) {
      record(area, `${label}: empty state has CTA`, 'visible CTA', 'empty without action', 'UX', await snap(page, `B-${href}`));
    } else {
      record(area, `${label}: page renders content`, 'content + interactive cues', `len=${body.length}`, 'OK');
    }
  } catch (e: any) {
    record(area, `${label}: navigate to ${href}`, 'no exception', `${e.message}`.slice(0, 150), 'P1');
  }
}

async function auditSidebar(browser: Browser) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'sidebar');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    const ok = await fireAdminDemoLogin(page);
    if (!ok) {
      record('B. Sidebar', 'login for sidebar audit', 'logged in', 'login failed', 'P0');
      return [];
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.waitForTimeout(2000);

    const routes = await discoverSidebarRoutes(page);
    record('B. Sidebar', 'sidebar route discovery', 'at least 8 links', `found ${routes.length}: ${routes.map(r => r.href).join(', ').slice(0, 250)}`, routes.length >= 8 ? 'OK' : 'P2');

    for (const { label, href } of routes) {
      await testRoute(page, label, href);
    }

    return routes;
  } finally {
    await ctx.close();
  }
}

// ── C. Primary-action exercises ──────────────────────────────────

async function exerciseChat(browser: Browser) {
  const area = 'C. Chat';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'chat');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    const ta = page.locator('textarea:not([disabled])').first();
    if ((await ta.count()) === 0) {
      record(area, 'chat textarea enabled on landing', 'enabled', 'still disabled / not present', 'P1', await snap(page, 'C-chat-disabled'));
      return;
    }
    record(area, 'chat textarea enabled by default', 'enabled', 'enabled', 'OK');

    // Send a calculator prompt
    await ta.fill('Use the calculator tool to compute 21 + 21.');
    const send = page.getByRole('button', { name: /send|submit|ask/i }).first();
    if ((await send.count()) > 0) await send.click();
    else await page.keyboard.press('Enter');
    await page.waitForTimeout(20_000);
    const after = (await page.textContent('body')) || '';
    const hasAnswer = /42|forty-two/i.test(after);
    record(area, 'simple calculator prompt → answer renders', '42 in body', hasAnswer ? 'answered' : 'no 42 in body', hasAnswer ? 'OK' : 'P2', await snap(page, 'C-chat-answer'));

    // Tool-use surfaced in UI?
    const toolUseShown = /calculator|tool call|using tool/i.test(after);
    record(area, 'tool-use surfaced in chat UI', 'visible tool indicator', toolUseShown ? 'visible' : 'absent', toolUseShown ? 'OK' : 'UX');

    // Agent picker discoverability
    const agentPicker = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('button, a, [role=combobox]')).some(el => /agent|model|select/i.test(el.textContent || ''));
    });
    record(area, 'agent picker visible in chat', 'present', agentPicker ? 'visible' : 'absent', agentPicker ? 'OK' : 'UX');
  } finally {
    await ctx.close();
  }
}

async function exerciseAgentCreate(browser: Browser) {
  const area = 'C. Agent create';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'agent-create');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    const r = await page.goto(`${BASE}/agents/new`, { waitUntil: 'domcontentloaded' }).catch(() => null);
    await page.waitForTimeout(3000);

    if (!r || r.status() >= 400) {
      record(area, '/agents/new reachable', '<400', `status=${r?.status() || 'unreachable'}`, 'P1');
      return;
    }
    record(area, '/agents/new reachable', '<400', `status=${r.status()}`, 'OK');

    const body = (await page.textContent('body')) || '';
    const hasName = body.includes('Name') || body.includes('name');
    const hasPrompt = /prompt|instruction|behavior/i.test(body);
    const hasToolPicker = /tool|select|calculator|web_search/i.test(body);
    const hasModel = /model|claude|gpt/i.test(body);
    record(area, 'builder shows name field', 'visible', hasName ? 'visible' : 'absent', hasName ? 'OK' : 'P1');
    record(area, 'builder shows system-prompt field', 'visible', hasPrompt ? 'visible' : 'absent', hasPrompt ? 'OK' : 'P1');
    record(area, 'builder shows tool picker', 'visible', hasToolPicker ? 'visible' : 'absent', hasToolPicker ? 'OK' : 'P1');
    record(area, 'builder shows model picker', 'visible', hasModel ? 'visible' : 'absent', hasModel ? 'OK' : 'UX');

    // Tool-picker grouping by category?
    const grouped = /core|data|enterprise|finance|integration|kyc|meeting|multimodal|pipeline/i.test(body) && body.match(/category|group/i);
    record(area, 'tool picker groups by category', 'category headings', grouped ? 'grouped' : 'flat list', grouped ? 'OK' : 'UX', await snap(page, 'C-agent-new'));
  } finally {
    await ctx.close();
  }
}

async function exerciseExecutions(browser: Browser) {
  const area = 'C. Executions';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'executions');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.goto(`${BASE}/executions`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const body = (await page.textContent('body')) || '';
    const hasList = /status|completed|failed|started|duration|cost|tokens/i.test(body);
    record(area, '/executions shows list with status cues', 'visible', hasList ? 'present' : 'absent', hasList ? 'OK' : 'P1', await snap(page, 'C-executions'));

    // Failure code grouping
    const hasFailureCode = /failure_code|PIPELINE_NODE_FAILED|LLM_RATE_LIMIT|MODERATION_BLOCKED/i.test(body);
    record(area, 'failed runs show failure_code', 'visible', hasFailureCode ? 'present' : 'absent', hasFailureCode ? 'OK' : 'UX');

    // Filter / search affordances
    const hasFilters = /filter|search|status|date|all|today|week/i.test(body);
    record(area, 'list has filter/search affordances', 'visible', hasFilters ? 'present' : 'absent', hasFilters ? 'OK' : 'UX');

    // Click into a row
    const firstRow = page.locator('tr, [role=row], a[href*="/executions/"]').first();
    if (await firstRow.count()) {
      await firstRow.click().catch(() => {});
      await page.waitForTimeout(2500);
      const detail = (await page.textContent('body')) || '';
      const hasTimeline = /node|step|tool|trace|timeline|input|output|duration/i.test(detail);
      record(area, 'execution detail shows timeline', 'visible', hasTimeline ? 'present' : 'absent', hasTimeline ? 'OK' : 'UX', await snap(page, 'C-execution-detail'));
    }
  } finally {
    await ctx.close();
  }
}

async function exerciseAtlas(browser: Browser) {
  const area = 'C. Atlas';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'atlas');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.goto(`${BASE}/atlas`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    const body = (await page.textContent('body')) || '';
    const hasCanvas = /node|edge|concept|ontology|graph|atlas/i.test(body);
    record(area, '/atlas canvas renders', 'visible', hasCanvas ? 'present' : 'absent', hasCanvas ? 'OK' : 'P1', await snap(page, 'C-atlas'));

    // Import / starter ontology buttons
    const hasImport = /import|fibo|core|starter|seed|bring/i.test(body);
    record(area, 'atlas offers starter ontologies / import', 'visible', hasImport ? 'present' : 'absent', hasImport ? 'OK' : 'UX');
  } finally {
    await ctx.close();
  }
}

async function exerciseKnowledge(browser: Browser) {
  const area = 'C. Knowledge';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'knowledge');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const body = (await page.textContent('body')) || '';
    const hasUpload = /upload|import|drag|drop|new.*kb|new.*knowledge|create/i.test(body);
    record(area, '/knowledge shows upload affordance', 'visible', hasUpload ? 'present' : 'absent', hasUpload ? 'OK' : 'P1', await snap(page, 'C-knowledge'));
  } finally {
    await ctx.close();
  }
}

async function exerciseSettings(browser: Browser) {
  const area = 'C. Settings';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'settings');
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});

    for (const sub of ['', '/security', '/billing', '/quotas', '/integrations']) {
      const href = `/settings${sub}`;
      const r = await page.goto(`${BASE}${href}`, { waitUntil: 'domcontentloaded' }).catch(() => null);
      await page.waitForTimeout(2000);
      const status = r?.status() ?? 0;
      const body = (await page.textContent('body')) || '';
      if (status >= 400) {
        record(area, `${href}`, '<400 or hidden', `status=${status}`, sub === '' ? 'P1' : 'GAP');
        continue;
      }
      const hasContent = body.length > 200;
      record(area, `${href} renders`, 'has content', hasContent ? `len=${body.length}` : 'empty/blank', hasContent ? 'OK' : (sub === '' ? 'P1' : 'GAP'), await snap(page, `C-settings${sub.replace(/\//g, '-') || '-main'}`));
    }
  } finally {
    await ctx.close();
  }
}

async function exerciseHelp(browser: Browser) {
  const area = 'C. Help';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    if (!(await fireAdminDemoLogin(page))) {
      record(area, 'login', 'OK', 'failed', 'P1'); return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    await page.goto(`${BASE}/help`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    const body = (await page.textContent('body')) || '';
    const hasTOC = /sidebar|table of contents|atlas|moderation|getting.started|first.agent|onboarding|create.agent/i.test(body);
    record(area, '/help has navigable TOC', 'topical sections', hasTOC ? 'present' : 'absent', hasTOC ? 'OK' : 'UX');

    const hasJourney = /first.agent|build.your.first|getting.started|new.user|10.minute|tutorial|walkthrough/i.test(body);
    record(area, '/help has "build your first agent" journey', 'guided onboarding', hasJourney ? 'present' : 'absent', hasJourney ? 'OK' : 'UX', await snap(page, 'C-help'));
  } finally {
    await ctx.close();
  }
}

// ── D. Cross-cutting ──

async function summariseCrossCutting() {
  const area = 'D. Cross-cutting';
  if (consoleErrors.length === 0) {
    record(area, 'console errors during run', '0', '0', 'OK');
  } else {
    const sample = consoleErrors.slice(0, 3).map(e => `${e.url.slice(BASE.length)}: ${e.text}`).join(' || ');
    record(area, 'console errors during run', '0', `${consoleErrors.length} errors. samples: ${sample}`, consoleErrors.length > 10 ? 'P1' : 'P2');
  }
  if (networkFails.length === 0) {
    record(area, '4xx/5xx responses observed', '0', '0', 'OK');
  } else {
    // Tally by route
    const byRoute: Record<string, number> = {};
    for (const f of networkFails) {
      const path = f.url.replace(BASE, '').replace(API, '').split('?')[0];
      byRoute[`${f.status} ${path}`] = (byRoute[`${f.status} ${path}`] || 0) + 1;
    }
    const top = Object.entries(byRoute).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `${k} (×${v})`).join(' || ');
    record(area, '4xx/5xx responses observed', '0', `${networkFails.length} fails. top: ${top}`, networkFails.length > 10 ? 'P1' : 'P2');
  }
}

// ── E. Business-user journey ───────────────────────────────────

async function businessUserJourney(browser: Browser) {
  const area = 'E. Business-user journey';
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'biz');
  try {
    // Fresh signup
    const email = `biz-uat-${Date.now()}@example.com`;
    const r = await fetch(`${API}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: 'BizPass123!', full_name: 'Business UAT' }),
    });
    if (!r.ok) {
      record(area, 'fresh signup', '201', `status=${r.status}`, 'P1'); return;
    }
    record(area, 'fresh signup creates tenant + user', '201', 'created', 'OK');

    // Programmatically log in via the UI (so cookies + localStorage land).
    // Click-then-fill on each input gives React time to mount its onChange
    // handler so the controlled-input state actually picks up the value.
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#auth-email').waitFor({ timeout: 25_000 });
    await page.waitForTimeout(2_000);
    await page.locator('#auth-email').click();
    await page.locator('#auth-email').fill(email);
    await page.locator('#auth-password').click();
    await page.locator('#auth-password').fill('BizPass123!');
    // Submit the form. Prefer the explicit testid; fall back to the
    // visible submit button inside the form, then to plain Enter.
    const submitBtn = page.locator('[data-testid="auth-submit"]').or(page.locator('form button[type=submit]')).first();
    if ((await submitBtn.count()) > 0) await submitBtn.click().catch(() => {});
    else await page.keyboard.press('Enter');
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});
    record(area, 'fresh user lands authenticated', 'authed area', `url=${page.url()}`, /dashboard|home|agents|atlas/.test(page.url()) ? 'OK' : 'P1', await snap(page, 'E-after-signup'));

    // Empty-state on /agents (fresh tenant has no custom agents)
    await page.goto(`${BASE}/agents`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const body = (await page.textContent('body')) || '';
    const hasGuidance = /create.your.first|build.an.agent|template|example|start.here|get.started|new.agent/i.test(body);
    record(area, '/agents has new-user guidance', 'visible CTA + walkthrough', hasGuidance ? 'present' : 'absent', hasGuidance ? 'OK' : 'UX', await snap(page, 'E-agents-empty'));

    // Dashboard usefulness for a fresh tenant
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const dash = (await page.textContent('body')) || '';
    const hasGettingStarted = /get.started|setup|onboard|first.agent|tutorial|walkthrough|next.step/i.test(dash);
    record(area, 'dashboard guides new user', 'getting-started cues', hasGettingStarted ? 'present' : 'absent', hasGettingStarted ? 'OK' : 'UX', await snap(page, 'E-dashboard-fresh'));

    // Billing / cost transparency
    const hasCost = /cost|spend|usage|tokens|\$|billing|free/i.test(dash);
    record(area, 'dashboard shows cost / spend', 'visible', hasCost ? 'present' : 'absent', hasCost ? 'OK' : 'UX');
  } finally {
    await ctx.close();
  }
}

// ── Main ─────────────────────────────────────────────────────────

(async () => {
  fs.appendFileSync(PROGRESS, `Deep UI UAT against ${BASE} (api ${API})\n\n`);
  const browser = await chromium.launch({ headless: true });
  try {
    await testAuth(browser);
    await auditSidebar(browser);
    await exerciseChat(browser);
    await exerciseAgentCreate(browser);
    await exerciseExecutions(browser);
    await exerciseAtlas(browser);
    await exerciseKnowledge(browser);
    await exerciseSettings(browser);
    await exerciseHelp(browser);
    await businessUserJourney(browser);
    await summariseCrossCutting();
  } finally {
    await browser.close();
  }

  // Write report
  const counts: Record<Severity, number> = { OK: 0, P0: 0, P1: 0, P2: 0, UX: 0, GAP: 0 };
  for (const f of findings) counts[f.severity]++;
  const reportPath = path.resolve(__dirname, '..', 'BUGS_UI_DEEP.md');
  const lines: string[] = [];
  lines.push('# Deep UI UAT — every link, every action, business-user perspective');
  lines.push('');
  lines.push(`**Date:** 2026-05-02 · **Environment:** Azure AKS via port-forward (BASE=${BASE})`);
  lines.push('');
  lines.push(`**Summary:** ${findings.length} checks — ${counts.OK} OK · ${counts.P0} P0 · ${counts.P1} P1 · ${counts.P2} P2 · ${counts.UX} UX · ${counts.GAP} GAP`);
  lines.push('');
  lines.push('## Findings (non-OK)');
  lines.push('');
  lines.push('| ID | Sev | Area | Test | Expected | Actual |');
  lines.push('|---|---|---|---|---|---|');
  for (const f of findings.filter(x => x.severity !== 'OK')) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.expected} | ${f.actual.replace(/\|/g, '\\|').slice(0, 200)} |`);
  }
  lines.push('');
  lines.push('## All checks');
  lines.push('');
  lines.push('| ID | Sev | Area | Test | Detail |');
  lines.push('|---|---|---|---|---|');
  for (const f of findings) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.actual.replace(/\|/g, '\\|').slice(0, 200)} |`);
  }
  fs.writeFileSync(reportPath, lines.join('\n'));
  fs.appendFileSync(PROGRESS, `\nReport: ${reportPath}\n`);
  fs.appendFileSync(PROGRESS, `Summary: OK=${counts.OK} P0=${counts.P0} P1=${counts.P1} P2=${counts.P2} UX=${counts.UX} GAP=${counts.GAP}\n`);
  process.stdout.write(`\nReport: ${reportPath}\nSummary: OK=${counts.OK} P0=${counts.P0} P1=${counts.P1} P2=${counts.P2} UX=${counts.UX} GAP=${counts.GAP}\n`);
})().catch(e => {
  fs.appendFileSync(PROGRESS, `FATAL: ${e}\n`);
  console.error('FATAL:', e);
  process.exit(1);
});
