/**
 * Saudi Tourism Analytics — Deep UI UAT
 *
 * Probes every route the standalone Saudi Tourism app exposes against the
 * live dev cluster (web at http://localhost:3002, API at http://localhost:8002).
 *
 * Phases:
 *   A. Auth — try demo creds button on landing; if that fails, register a
 *      fresh user via the API and inject a token into localStorage.
 *   B. Route audit — visit /dashboard, /upload, /regional, /analytics,
 *      /chat, /reports, /simulations and capture status/length/rendered.
 *   C. Deep flows — Seed-Data, Dashboard-KPIs, Regional-Drilldown,
 *      Analytics-Tabs, Chat-NLQ, 5x Reports, 1x Simulation.
 *   D. Errors — collect console errors + 4xx/5xx network failures.
 *
 * Output:
 *   logs/uat/apps/sauditourism-ui-report.md
 *   logs/uat/apps/sauditourism-screens/<slug>.png  (one per route + flow)
 *
 * Run:  npx tsx scripts/uat-sauditourism-ui.ts
 */

import { chromium, type Browser, type Page, type ConsoleMessage } from 'playwright';
import fs from 'fs';
import path from 'path';

const WEB = process.env.SAUDI_WEB || 'http://localhost:3002';
const API = process.env.SAUDI_API || 'http://localhost:8002';

const OUT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'apps');
const SHOTS = path.join(OUT_DIR, 'sauditourism-screens');
fs.mkdirSync(SHOTS, { recursive: true });
const REPORT = path.join(OUT_DIR, 'sauditourism-ui-report.md');

type Severity = 'P0' | 'P1' | 'P2' | 'UX' | 'GAP' | 'OK';

interface RouteResult {
  route: string;
  status: number;
  bodyLen: number;
  rendered: boolean;
  visibleError: string;
  screenshot: string;
  notes: string;
}
interface FlowResult {
  name: string;
  pass: boolean;
  detail: string;
  screenshot?: string;
}
interface Bug {
  id: string;
  severity: Severity;
  area: string;
  symptom: string;
}

const consoleErrors: { route: string; text: string }[] = [];
const netFails: { route: string; url: string; status: number }[] = [];
const routeResults: RouteResult[] = [];
const flows: FlowResult[] = [];
const bugs: Bug[] = [];
const ctaClicks: { route: string; cta: string; result: string }[] = [];
let bugId = 1;
let currentRoute = '/';

function bug(severity: Severity, area: string, symptom: string) {
  bugs.push({ id: `B${String(bugId++).padStart(2, '0')}`, severity, area, symptom });
}

function log(line: string) {
  process.stdout.write(line + '\n');
}

async function snap(page: Page, name: string): Promise<string> {
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  const file = path.join(SHOTS, `${safe}.png`);
  try { await page.screenshot({ path: file, fullPage: true }); } catch {}
  return path.basename(file);
}

function attachListeners(page: Page) {
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      consoleErrors.push({ route: currentRoute, text: msg.text().slice(0, 240) });
    }
  });
  page.on('pageerror', err => {
    consoleErrors.push({ route: currentRoute, text: `pageerror: ${String(err).slice(0, 240)}` });
  });
  page.on('response', resp => {
    const url = resp.url();
    if (resp.status() >= 400 && !url.includes('favicon') && !url.startsWith('chrome-extension:') && !url.includes('_next/static')) {
      netFails.push({ route: currentRoute, url: url.slice(0, 200), status: resp.status() });
    }
    // SDK-empty-output heuristic — agent endpoint with empty output.
    if (resp.status() === 200 && /\/(execute|recommend|itinerary|brief|run)/i.test(url)) {
      const ct = resp.headers()['content-type'] || '';
      if (ct.includes('application/json')) {
        resp.text().then(t => {
          if (!t || t.length < 4) return;
          let body: any = null;
          try { body = JSON.parse(t); } catch { return; }
          const data = body?.data ?? body;
          if (data && typeof data === 'object') {
            const out = data.output ?? data.output_message ?? data.result;
            const mode = data.mode;
            if ((out === '' || out === null) && (mode === 'async' || data.execution_id)) {
              bug('P0', 'SDK', `Empty agent output: ${url.slice(0, 160)} (mode=${mode ?? 'n/a'})`);
            }
          }
        }).catch(() => {});
      }
    }
  });
}

// ── auth helpers ────────────────────────────────────────────────

async function apiRegister(): Promise<{ token: string; email: string } | null> {
  const ts = Date.now();
  const email = `test-tourism-${ts}@example.com`;
  try {
    const res = await fetch(`${API}/api/st/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: 'TestPass123!', full_name: 'Tourism UAT', organization: 'UAT' }),
    });
    const j: any = await res.json();
    if (j?.data?.access_token) return { token: j.data.access_token, email };
    log(`[auth] register failed: ${JSON.stringify(j).slice(0, 160)}`);
  } catch (e: any) { log(`[auth] register threw: ${e?.message}`); }
  return null;
}

async function apiLoginDemo(): Promise<{ token: string; email: string } | null> {
  try {
    const res = await fetch(`${API}/api/st/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'test@sauditourism.gov.sa', password: 'TestPass123!' }),
    });
    const j: any = await res.json();
    if (j?.data?.access_token) return { token: j.data.access_token, email: 'test@sauditourism.gov.sa' };
  } catch {}
  return null;
}

async function injectToken(page: Page, token: string, email: string) {
  await page.goto(WEB + '/', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ tk, em }: { tk: string; em: string }) => {
    localStorage.setItem('st_token', tk);
    localStorage.setItem('st_refresh_token', tk);
    localStorage.setItem('st_user', JSON.stringify({ email: em, full_name: 'Tourism UAT', role: 'analyst' }));
  }, { tk: token, em: email });
}

// ── route visit ────────────────────────────────────────────────

async function visitRoute(page: Page, route: string, settle = 4000): Promise<RouteResult> {
  currentRoute = route;
  let status = 0;
  let bodyLen = 0;
  let visibleError = '';
  let rendered = false;
  let notes = '';
  try {
    const resp = await page.goto(WEB + route, { waitUntil: 'domcontentloaded', timeout: 25000 });
    status = resp?.status() ?? 0;
    await page.waitForTimeout(settle);
    const body = await page.locator('body').innerText().catch(() => '');
    bodyLen = body.length;
    rendered = bodyLen > 50;
    // Look for visible error containers (red-tinted boxes the app uses)
    const errLoc = page.locator('.bg-red-900\\/20, [class*="text-red-300"], [class*="text-red-400"]').first();
    if (await errLoc.count() > 0) {
      const t = (await errLoc.innerText().catch(() => '')).trim();
      if (t && t.length < 400) visibleError = t.replace(/\s+/g, ' ');
    }
    // Did sidebar render? (signals layout/auth ok)
    const navItems = await page.locator('nav a').count().catch(() => 0);
    notes = `nav-links=${navItems}`;
  } catch (e: any) { notes = `navigation error: ${e?.message?.slice(0, 100)}`; }
  const slug = `route_${route.replace(/[^a-z0-9]/gi, '_') || 'root'}`;
  const screenshot = await snap(page, slug);
  return { route, status, bodyLen, rendered, visibleError, screenshot, notes };
}

// ── deep flows ────────────────────────────────────────────────

async function flowSeedData(page: Page) {
  currentRoute = '/upload';
  const name = 'Seed-Data';
  await page.goto(WEB + '/upload', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  // Click "Seed Test Data" / "Seed All Test Data"
  const seedBtn = page.locator('button', { hasText: /seed/i }).first();
  if (await seedBtn.count() === 0) {
    flows.push({ name, pass: false, detail: 'Seed button not found' });
    bug('P0', 'Upload', 'Seed Test Data button not found on /upload');
    return;
  }
  ctaClicks.push({ route: '/upload', cta: 'Seed Test Data', result: 'clicked' });
  await seedBtn.click();
  // Wait for seeding to complete (API call) then for dataset list to populate
  await page.waitForTimeout(20000);
  const datasets = await page.locator('p.text-sm.font-medium, .text-white.truncate, [class*="font-medium"]').filter({ hasText: /visitor|hotel|revenue|satisfaction|strategy|neom/i }).count().catch(() => 0);
  // Fallback — count list rows
  const listRows = await page.locator('div.flex.items-center.gap-4').count().catch(() => 0);
  const shot = await snap(page, 'flow_seed_data');
  if (datasets >= 3 || listRows >= 3) {
    flows.push({ name, pass: true, detail: `Seeded ${Math.max(datasets, listRows)} datasets visible`, screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: `After seeding, only ${Math.max(datasets, listRows)} datasets visible (expected 6)`, screenshot: shot });
    bug('P1', 'Upload', `Seed completed but fewer than 6 datasets rendered (saw ${Math.max(datasets, listRows)})`);
  }
}

async function flowDashboardKPIs(page: Page) {
  currentRoute = '/dashboard';
  const name = 'Dashboard-KPIs';
  await page.goto(WEB + '/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  const runBtn = page.locator('button', { hasText: /run ai analytics/i }).first();
  if (await runBtn.count() === 0) {
    flows.push({ name, pass: false, detail: '"Run AI Analytics" button missing' });
    bug('P0', 'Dashboard', 'Run AI Analytics CTA missing');
    return;
  }
  ctaClicks.push({ route: '/dashboard', cta: 'Run AI Analytics', result: 'clicked' });
  await runBtn.click();
  // Agent can take 30-90s; poll up to 120s
  const start = Date.now();
  let success = false;
  while (Date.now() - start < 120000) {
    await page.waitForTimeout(3000);
    const loading = await page.locator('text=/Analyzing via Abenix/i').count();
    if (loading === 0) {
      // Look for AI KPI cards (Total Visitors, Revenue, etc.)
      const kpi = await page.locator('text=/Total Visitors|Revenue \\(SAR\\)|Hotel Occupancy|Satisfaction/i').count();
      if (kpi >= 2) { success = true; break; }
    }
  }
  const shot = await snap(page, 'flow_dashboard_kpis');
  if (success) {
    flows.push({ name, pass: true, detail: 'AI KPI cards rendered', screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: 'No AI KPIs after 120s', screenshot: shot });
    bug('P1', 'Dashboard', 'AI Analytics did not render KPIs within 120s (agent timeout or empty)');
  }
}

async function flowRegionalDrilldown(page: Page) {
  currentRoute = '/regional';
  const name = 'Regional-Drilldown';
  await page.goto(WEB + '/regional', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const runBtn = page.locator('button', { hasText: /run regional analysis/i }).first();
  if (await runBtn.count() === 0) {
    flows.push({ name, pass: false, detail: 'Run Regional Analysis CTA missing' });
    bug('P0', 'Regional', 'Run Regional Analysis CTA missing');
    return;
  }
  ctaClicks.push({ route: '/regional', cta: 'Run Regional Analysis', result: 'clicked' });
  await runBtn.click();
  const start = Date.now();
  let cardCount = 0;
  while (Date.now() - start < 120000) {
    await page.waitForTimeout(3000);
    cardCount = await page.locator('h3.font-semibold.text-white').count().catch(() => 0);
    const loading = await page.locator('text=/Analyzing regions/i').count();
    if (loading === 0 && cardCount >= 1) break;
  }
  // Drill into first region card
  let drillOk = false;
  if (cardCount >= 1) {
    const firstCard = page.locator('div.cursor-pointer').first();
    if (await firstCard.count() > 0) {
      ctaClicks.push({ route: '/regional', cta: 'Click first region card', result: 'clicked' });
      await firstCard.click().catch(() => {});
      await page.waitForTimeout(1500);
      const detail = await page.locator('text=/Detailed View/i').count();
      drillOk = detail > 0;
    }
  }
  const shot = await snap(page, 'flow_regional_drilldown');
  if (cardCount >= 1) {
    flows.push({ name, pass: true, detail: `${cardCount} region cards rendered, drilldown=${drillOk}`, screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: 'No region cards after agent run', screenshot: shot });
    bug('P1', 'Regional', 'No region cards rendered after Run Regional Analysis');
  }
}

async function flowAnalyticsTabs(page: Page) {
  currentRoute = '/analytics';
  const name = 'Deep-Analytics';
  await page.goto(WEB + '/analytics', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  const refresh = page.locator('button', { hasText: /refresh analysis/i }).first();
  if (await refresh.count() === 0) {
    flows.push({ name, pass: false, detail: 'Refresh Analysis CTA missing' });
    bug('P0', 'Analytics', 'Refresh Analysis CTA missing');
    return;
  }
  ctaClicks.push({ route: '/analytics', cta: 'Refresh Analysis', result: 'clicked' });
  await refresh.click();
  const start = Date.now();
  let charts = 0;
  while (Date.now() - start < 150000) {
    await page.waitForTimeout(4000);
    charts = await page.locator('div.recharts-wrapper, svg.recharts-surface').count().catch(() => 0);
    const loading = await page.locator('text=/Analyzing\\.\\.\\./i').count();
    if (loading === 0 && charts >= 1) break;
  }
  const shot = await snap(page, 'flow_analytics');
  if (charts >= 1) {
    flows.push({ name, pass: true, detail: `${charts} charts rendered (time-series / segmentation / revenue)`, screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: 'No charts rendered', screenshot: shot });
    bug('P1', 'Analytics', 'No deep-analytics charts rendered after refresh');
  }
}

async function flowChatNLQ(page: Page) {
  currentRoute = '/chat';
  const name = 'Chat-NLQ';
  await page.goto(WEB + '/chat', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const input = page.locator('input[placeholder*="Ask about"]').first();
  if (await input.count() === 0) {
    flows.push({ name, pass: false, detail: 'Chat input missing' });
    bug('P0', 'Chat', 'Chat input missing on /chat');
    return;
  }
  await input.fill('What is the visitor outlook for Q4 2024 in Al-Ula?');
  const sendBtn = page.locator('form button[type="submit"]').first();
  ctaClicks.push({ route: '/chat', cta: 'Send chat message', result: 'clicked' });
  await sendBtn.click();
  const start = Date.now();
  let assistantMsg = '';
  while (Date.now() - start < 120000) {
    await page.waitForTimeout(3000);
    // Wait until "st-chat agent analyzing..." disappears
    const analyzing = await page.locator('text=/st-chat agent analyzing/i').count();
    if (analyzing === 0) {
      // Look for assistant bubble (prose div)
      const proseBubble = page.locator('div.prose').last();
      if (await proseBubble.count() > 0) {
        assistantMsg = (await proseBubble.innerText().catch(() => '')).trim();
        if (assistantMsg.length > 30) break;
      }
    }
  }
  const shot = await snap(page, 'flow_chat_nlq');
  if (assistantMsg.length > 30) {
    flows.push({ name, pass: true, detail: `Got ${assistantMsg.length}-char assistant response`, screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: `No useful assistant response (got ${assistantMsg.length} chars)`, screenshot: shot });
    bug('P1', 'Chat', 'Chat agent did not return a response within 120s');
  }
}

async function flowReports(page: Page) {
  currentRoute = '/reports';
  await page.goto(WEB + '/reports', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  // The page lists report types fetched from /api/st/reports/types — we click each "Play" button
  const buttons = await page.locator('button:has(h3)').all();
  if (buttons.length === 0) {
    flows.push({ name: 'Reports', pass: false, detail: 'No report-type buttons rendered' });
    bug('P0', 'Reports', 'No report types rendered (types API empty?)');
    return;
  }
  log(`[reports] found ${buttons.length} report types`);
  // Click up to 5 reports — one of each
  const max = Math.min(5, buttons.length);
  for (let i = 0; i < max; i++) {
    const btn = page.locator('button:has(h3)').nth(i);
    let title = '';
    try { title = (await btn.locator('h3').innerText()).trim(); } catch {}
    ctaClicks.push({ route: '/reports', cta: `Generate "${title}"`, result: 'clicked' });
    await btn.click().catch(() => {});
    // Wait for the agent
    const start = Date.now();
    let content = '';
    while (Date.now() - start < 150000) {
      await page.waitForTimeout(4000);
      const generating = await page.locator('text=/Generating report/i').count();
      if (generating === 0) {
        const viewer = page.locator('div.prose.prose-invert').last();
        if (await viewer.count() > 0) {
          content = (await viewer.innerText().catch(() => '')).trim();
          if (content.length > 80) break;
        }
      }
    }
    const shot = await snap(page, `flow_report_${i + 1}_${title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}`);
    const flowName = `Report-${i + 1}-${title || `type${i + 1}`}`;
    if (content.length > 80) {
      flows.push({ name: flowName, pass: true, detail: `${content.length} chars rendered`, screenshot: shot });
    } else {
      flows.push({ name: flowName, pass: false, detail: `No content (${content.length} chars)`, screenshot: shot });
      bug('P1', 'Reports', `Report "${title}" did not render content within 150s`);
    }
  }
}

async function flowSimulation(page: Page) {
  currentRoute = '/simulations';
  const name = 'Simulation-1';
  await page.goto(WEB + '/simulations', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  const runBtn = page.locator('button', { hasText: /run simulation/i }).first();
  if (await runBtn.count() === 0) {
    flows.push({ name, pass: false, detail: 'Run Simulation CTA missing' });
    bug('P0', 'Simulations', 'Run Simulation CTA missing');
    return;
  }
  ctaClicks.push({ route: '/simulations', cta: 'Run Simulation', result: 'clicked' });
  await runBtn.click();
  const start = Date.now();
  let metrics = 0;
  let recs = 0;
  while (Date.now() - start < 150000) {
    await page.waitForTimeout(4000);
    const running = await page.locator('text=/Running simulation/i').count();
    if (running === 0) {
      // key_metrics renders as 2-col grid; recommendations render as <ul><li>
      metrics = await page.locator('div.text-lg.font-bold.text-green-300').count().catch(() => 0);
      recs = await page.locator('ul li').count().catch(() => 0);
      if (metrics >= 1 || recs >= 1) break;
    }
  }
  const shot = await snap(page, 'flow_simulation');
  if (metrics >= 1 || recs >= 1) {
    flows.push({ name, pass: true, detail: `metrics=${metrics}, recommendations=${recs}`, screenshot: shot });
  } else {
    flows.push({ name, pass: false, detail: 'No key_metrics/recommendations rendered', screenshot: shot });
    bug('P1', 'Simulations', 'Simulation did not render key_metrics or recommendations within 150s');
  }
}

// ── report writer ────────────────────────────────────────────────

function writeReport(meta: { user: string; auth: string }) {
  const passes = flows.filter(f => f.pass).length;
  const fails = flows.filter(f => !f.pass).length;
  const broken = bugs.filter(b => b.severity === 'P0').length;
  const summary = `Routes ${routeResults.length} / CTAs ${ctaClicks.length} / Deep flows ${flows.length} · passes ${passes} · fails ${fails} · broken ${broken}`;
  log('\n' + '='.repeat(70) + '\n' + summary + '\n' + '='.repeat(70));

  const lines: string[] = [];
  lines.push(`# Saudi Tourism — Deep UI UAT Report\n`);
  lines.push(`_Web: ${WEB}  ·  API: ${API}  ·  ${new Date().toISOString()}_`);
  lines.push(`_Auth: ${meta.auth} (${meta.user})_\n`);
  lines.push(`**${summary}**\n`);

  // Per-route
  lines.push(`## Per-route table\n`);
  lines.push(`| Route | HTTP | Body len | Rendered | Visible error | Screenshot |`);
  lines.push(`|---|---|---|---|---|---|`);
  for (const r of routeResults) {
    const err = r.visibleError ? r.visibleError.slice(0, 80) : '—';
    lines.push(`| ${r.route} | ${r.status} | ${r.bodyLen} | ${r.rendered ? 'yes' : 'NO'} | ${err} | ${r.screenshot} |`);
  }
  lines.push('');

  // CTAs
  lines.push(`## CTAs clicked (${ctaClicks.length})\n`);
  lines.push(`| Route | CTA | Result |`);
  lines.push(`|---|---|---|`);
  for (const c of ctaClicks) lines.push(`| ${c.route} | ${c.cta} | ${c.result} |`);
  lines.push('');

  // Deep flows
  lines.push(`## Deep-flow results\n`);
  lines.push(`| Flow | Pass | Detail | Screenshot |`);
  lines.push(`|---|---|---|---|`);
  for (const f of flows) {
    lines.push(`| ${f.name} | ${f.pass ? 'PASS' : 'FAIL'} | ${f.detail} | ${f.screenshot || '—'} |`);
  }
  lines.push('');

  // Console errors top-10
  lines.push(`## Console errors (top 10 of ${consoleErrors.length})\n`);
  if (consoleErrors.length === 0) lines.push('_None_\n');
  else {
    for (const e of consoleErrors.slice(0, 10)) lines.push(`- [${e.route}] ${e.text}`);
    lines.push('');
  }

  // 4xx / 5xx
  lines.push(`## 4xx / 5xx network responses (${netFails.length})\n`);
  if (netFails.length === 0) lines.push('_None_\n');
  else {
    lines.push(`| Route | Status | URL |`);
    lines.push(`|---|---|---|`);
    for (const n of netFails.slice(0, 30)) lines.push(`| ${n.route} | ${n.status} | ${n.url} |`);
    lines.push('');
  }

  // Bugs
  lines.push(`## Bugs found (${bugs.length}, severity-ordered)\n`);
  const order: Severity[] = ['P0', 'P1', 'P2', 'UX', 'GAP', 'OK'];
  bugs.sort((a, b) => order.indexOf(a.severity) - order.indexOf(b.severity));
  if (bugs.length === 0) lines.push('_None — every flow rendered._\n');
  else {
    lines.push(`| ID | Severity | Area | Symptom |`);
    lines.push(`|---|---|---|---|`);
    for (const b of bugs) lines.push(`| ${b.id} | ${b.severity} | ${b.area} | ${b.symptom} |`);
    lines.push('');
  }

  // UI gaps for business users
  lines.push(`## UI gaps for business users\n`);
  const gaps: string[] = [];
  if (flows.find(f => f.name === 'Dashboard-KPIs' && !f.pass)) {
    gaps.push('Dashboard auto-load: KPIs only render after the user clicks "Run AI Analytics" — most ministry users will land on /dashboard expecting numbers immediately.');
  }
  if (flows.find(f => f.name === 'Deep-Analytics' && !f.pass)) {
    gaps.push('Deep Analytics has no built-in tab switcher; the spec calls for time-series / segmentation / revenue tabs but the page renders all sections in one scroll.');
  }
  if (consoleErrors.length > 0) {
    gaps.push(`${consoleErrors.length} console errors observed — reduces trust for a Ministry-of-Tourism audience.`);
  }
  if (netFails.length > 0) {
    gaps.push(`${netFails.length} HTTP 4xx/5xx during the session — error toasts to the user are minimal.`);
  }
  // Always-on gaps from inspection
  gaps.push('Reports page renders raw markdown via dangerouslySetInnerHTML regex — tables & lists collapse to <br/> in some cases, hurting executive readability.');
  gaps.push('No bilingual (Arabic/English) toggle visible — a KSA-government audience expects one.');
  gaps.push('No "export to PDF / send to my email" CTA on reports or simulations.');
  if (gaps.length === 0) lines.push('_No major gaps observed in this run._\n');
  else { for (const g of gaps) lines.push(`- ${g}`); lines.push(''); }

  fs.writeFileSync(REPORT, lines.join('\n'));
  log(`\nReport written: ${REPORT}`);
  log(`Screenshots: ${SHOTS}`);
}

// ── main ────────────────────────────────────────────────────────

(async () => {
  log(`[init] WEB=${WEB}  API=${API}`);

  // Auth — try demo first, register if it fails
  let auth = await apiLoginDemo();
  let authMode = 'demo-creds';
  if (!auth) {
    log('[auth] demo login failed, registering fresh user');
    auth = await apiRegister();
    authMode = 'registered';
  }
  if (!auth) {
    log('[auth] FATAL — cannot authenticate; aborting');
    bug('P0', 'Auth', 'Both demo login and fresh registration failed');
    fs.writeFileSync(REPORT, '# Saudi Tourism UAT — Aborted\n\nCould not authenticate against ' + API + '\n');
    process.exit(1);
  }
  log(`[auth] OK as ${auth.email} via ${authMode}`);

  const browser: Browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  attachListeners(page);

  // Landing snap before auth
  currentRoute = '/';
  await page.goto(WEB + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  await snap(page, 'route__landing');

  await injectToken(page, auth.token, auth.email);
  log('[auth] token injected into localStorage');

  // Phase B — route audit
  const routes = ['/dashboard', '/upload', '/regional', '/analytics', '/chat', '/reports', '/simulations'];
  for (const r of routes) {
    log(`[route] visiting ${r}`);
    const result = await visitRoute(page, r);
    routeResults.push(result);
    if (!result.rendered) bug('P0', 'Route', `${r} did not render (status=${result.status}, bodyLen=${result.bodyLen})`);
    if (result.visibleError) bug('P1', 'Route', `${r} shows visible error: ${result.visibleError.slice(0, 100)}`);
  }

  // Phase C — deep flows (order matters: seed first, then dashboard depends on seeded data)
  log('[flow] Seed-Data');
  await flowSeedData(page);
  log('[flow] Dashboard-KPIs');
  await flowDashboardKPIs(page);
  log('[flow] Regional-Drilldown');
  await flowRegionalDrilldown(page);
  log('[flow] Deep-Analytics');
  await flowAnalyticsTabs(page);
  log('[flow] Chat-NLQ');
  await flowChatNLQ(page);
  log('[flow] Reports (5x)');
  await flowReports(page);
  log('[flow] Simulation');
  await flowSimulation(page);

  await browser.close();
  writeReport({ user: auth.email, auth: authMode });
})().catch(e => {
  log('[fatal] ' + (e?.message || e));
  fs.writeFileSync(REPORT, `# Saudi Tourism UAT — Fatal\n\n${String(e)}\n`);
  process.exit(1);
});
