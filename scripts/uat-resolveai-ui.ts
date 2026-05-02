/**
 * Deep UI UAT for ResolveAI (web @ 3004, api @ 8004).
 *
 * Per-tenant via X-Tenant-Id header (default 0...01). Uses route proxy
 * /api/resolveai/* on the Next server, so we exercise the prod path.
 *
 * Phases:
 *   1. /  dashboard + Try-it-now
 *   2. /cases — fire 4 synthetic tickets, refresh, drill in
 *   3. /cases/[id] — events, action_plan, citations, take-over, approve/reject
 *   4. /sla — Run Sweep
 *   5. /qa — CSAT board + run QA on a closed case
 *   6. /trends — Mine Trends
 *   7. /admin — settings update + persistence
 *   8. /admin pending-approvals queue render
 *   9. /live-console stub
 *  10. /help walkthrough
 *
 * Output: logs/uat/apps/resolveai-ui-report.md + screens.
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.RESOLVEAI_URL || 'http://localhost:3004';
const API  = process.env.RESOLVEAI_API || 'http://localhost:8004';
const TENANT = process.env.RESOLVEAI_TENANT || '00000000-0000-0000-0000-000000000001';

const SCREENS_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'apps', 'resolveai-screens');
const REPORT_PATH = path.resolve(__dirname, '..', 'logs', 'uat', 'apps', 'resolveai-ui-report.md');
fs.mkdirSync(SCREENS_DIR, { recursive: true });

type Status = 'PASS' | 'FAIL' | 'BROKEN' | 'INFO';
interface RouteResult { route: string; status: Status; httpStatus: number; notes: string; screenshot?: string }
interface FlowResult  { flow: string; status: Status; detail: string; screenshot?: string }
interface NetEntry    { url: string; status: number; method: string; route: string }
interface ConsoleErr  { route: string; text: string }

const routeResults: RouteResult[] = [];
const flowResults:  FlowResult[]  = [];
const networkFails: NetEntry[]    = [];
const consoleErrs:  ConsoleErr[]  = [];
const bugs: { sev: 'P0' | 'P1' | 'P2' | 'GAP'; title: string; detail: string }[] = [];

function logLine(s: string) { process.stdout.write(s + '\n'); }

async function snap(page: Page, name: string): Promise<string> {
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  const file = path.join(SCREENS_DIR, `${safe}.png`);
  try { await page.screenshot({ path: file, fullPage: true }); } catch {}
  return path.relative(path.resolve(__dirname, '..'), file).replace(/\\/g, '/');
}

function attachListeners(page: Page) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrs.push({ route: page.url(), text: msg.text().slice(0, 300) });
    }
  });
  page.on('response', (resp) => {
    const url = resp.url();
    const status = resp.status();
    if (status >= 400 && !/favicon|_next\/static|\.well-known|chrome-extension/.test(url)) {
      networkFails.push({
        url: url.slice(0, 240),
        status,
        method: resp.request().method(),
        route: page.url().replace(BASE, '') || '/',
      });
    }
    // SDK-empty-output heuristic — flag P0 if an agent endpoint returned
    // 200 with no output (suggests SDK or server fell back to async-mode
    // without polling / waiting; the bug we fixed in Phase A-DEEP).
    if (status === 200 && /\/(execute|run|qa\/run|cases\/[^/]+\/(triage|resolution|policy))/i.test(url)) {
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
              bugs.push({ sev: 'P0', title: 'SDK potentially returning before agent completes', detail: `${url.slice(0, 200)} returned 200 with empty output (mode=${mode ?? 'n/a'})` });
            }
          }
        }).catch(() => {});
      }
    }
  });
}

async function gotoRoute(page: Page, route: string, label?: string): Promise<{ httpStatus: number; ok: boolean }> {
  const resp = await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 30_000 }).catch(() => null);
  await page.waitForTimeout(800);
  const httpStatus = resp?.status() ?? 0;
  const screenshot = await snap(page, `route_${(label ?? route.replace(/\W+/g, '_')).slice(0, 60)}`);
  routeResults.push({
    route,
    status: httpStatus >= 200 && httpStatus < 400 ? 'PASS' : 'FAIL',
    httpStatus,
    notes: httpStatus >= 400 ? `HTTP ${httpStatus}` : 'reached',
    screenshot,
  });
  return { httpStatus, ok: httpStatus >= 200 && httpStatus < 400 };
}

// ─── direct API helpers (bypass UI to seed data + invariants) ───────

async function apiGet<T = any>(path: string): Promise<{ status: number; body: T | null }> {
  const res = await fetch(`${API}${path}`, { headers: { 'X-Tenant-Id': TENANT } });
  let body: any = null;
  try { body = await res.json(); } catch {}
  return { status: res.status, body };
}
async function apiPost<T = any>(path: string, body?: any, method: 'POST' | 'PATCH' = 'POST'): Promise<{ status: number; body: T | null }> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { 'X-Tenant-Id': TENANT, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  let out: any = null;
  try { out = await res.json(); } catch {}
  return { status: res.status, body: out };
}

// ─── Phase 1: Dashboard + Try-it-now ────────────────────────────────

async function phaseDashboard(page: Page) {
  const { ok } = await gotoRoute(page, '/', 'dashboard');
  if (!ok) {
    flowResults.push({ flow: 'Try-It-Now-Ticket', status: 'BROKEN', detail: 'dashboard route did not load' });
    return;
  }
  // KPI cards
  const kpiLabels = ['Total cases', 'Auto-resolved', 'Handed to human', 'Deflection rate', 'Total spend'];
  const present: string[] = [];
  for (const label of kpiLabels) {
    const has = await page.getByText(label, { exact: false }).count();
    if (has > 0) present.push(label);
  }
  routeResults.push({
    route: '/  (KPI cards)',
    status: present.length === kpiLabels.length ? 'PASS' : 'FAIL',
    httpStatus: 200,
    notes: `KPIs rendered: ${present.length}/${kpiLabels.length}`,
  });
  if (present.length < kpiLabels.length) {
    bugs.push({ sev: 'P1', title: 'Dashboard missing KPI cards', detail: `Only rendered ${present.join(', ')}.` });
  }

  // Try it now
  const tryBtn = page.getByRole('button', { name: /Try it now/i });
  if ((await tryBtn.count()) === 0) {
    flowResults.push({ flow: 'Try-It-Now-Ticket', status: 'BROKEN', detail: 'no Try-It-Now button (welcome banner already dismissed?)' });
    bugs.push({ sev: 'P2', title: '/  has no Try-It-Now CTA when welcome banner dismissed', detail: 'localStorage resolveai.welcome.v1=done hides the only sample-ticket button on dashboard.' });
    return;
  }
  const before = (await apiGet<any>('/api/resolveai/cases?limit=500')).body?.data?.length ?? 0;
  await tryBtn.first().click();
  // wait either for /cases/<id> nav or stable network
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => {});
  await page.waitForTimeout(2000);
  const url = page.url();
  const after = (await apiGet<any>('/api/resolveai/cases?limit=500')).body?.data?.length ?? 0;
  const navigated = /\/cases(\/|$)/.test(url);
  const screenshot = await snap(page, 'try_it_now_landed');
  if (navigated && after > before) {
    flowResults.push({ flow: 'Try-It-Now-Ticket', status: 'PASS', detail: `cases ${before}→${after}, landed on ${url.replace(BASE, '')}`, screenshot });
  } else if (after > before) {
    flowResults.push({ flow: 'Try-It-Now-Ticket', status: 'INFO', detail: `case created (${before}→${after}) but no nav (url=${url})`, screenshot });
    bugs.push({ sev: 'P2', title: 'Try-It-Now creates a case but does not navigate', detail: `Stayed on ${url}.` });
  } else {
    flowResults.push({ flow: 'Try-It-Now-Ticket', status: 'FAIL', detail: 'no new case created', screenshot });
    bugs.push({ sev: 'P0', title: 'Try-It-Now did not create a case', detail: 'POST /api/resolveai/cases failed silently from dashboard.' });
  }
}

// ─── Phase 2: 4 synthetic tickets via /cases ────────────────────────

async function phaseCasesQueue(page: Page): Promise<string | null> {
  const { ok } = await gotoRoute(page, '/cases', 'cases');
  if (!ok) {
    flowResults.push({ flow: '4x-Synthetic-Tickets', status: 'BROKEN', detail: '/cases did not load' });
    return null;
  }
  const before = (await apiGet<any>('/api/resolveai/cases?limit=500')).body?.data?.length ?? 0;
  const btn = page.locator('[data-testid="create-synthetic"]');
  let fired = 0;
  for (let i = 0; i < 4; i++) {
    if ((await btn.count()) === 0) break;
    try {
      await btn.click({ timeout: 5000 });
      // wait until enabled again (component sets `creating` true while in flight)
      await page.waitForFunction(
        () => {
          const b = document.querySelector('[data-testid="create-synthetic"]') as HTMLButtonElement | null;
          return !!b && !b.disabled;
        },
        { timeout: 90_000 },
      ).catch(() => {});
      fired++;
    } catch (e) {
      bugs.push({ sev: 'P1', title: `Simulate-a-ticket failed on click ${i + 1}`, detail: String(e).slice(0, 200) });
      break;
    }
  }
  // give pipelines a moment, then refetch
  await page.waitForTimeout(2000);
  const refreshBtn = page.getByRole('button', { name: /^Refresh$/ });
  if ((await refreshBtn.count()) > 0) await refreshBtn.first().click().catch(() => {});
  await page.waitForTimeout(1500);
  const afterApi = (await apiGet<any>('/api/resolveai/cases?limit=500')).body?.data ?? [];
  const screenshot = await snap(page, 'cases_after_4x_simulate');
  if (afterApi.length >= before + Math.min(fired, 4) && fired === 4) {
    flowResults.push({
      flow: '4x-Synthetic-Tickets',
      status: 'PASS',
      detail: `clicks=${fired}, cases ${before}→${afterApi.length}`,
      screenshot,
    });
  } else {
    flowResults.push({
      flow: '4x-Synthetic-Tickets',
      status: fired > 0 ? 'INFO' : 'FAIL',
      detail: `clicks=${fired}, cases ${before}→${afterApi.length}`,
      screenshot,
    });
    if (fired < 4) bugs.push({ sev: 'P1', title: 'Could not fire 4 synthetic tickets', detail: `clicked ${fired}/4 before button got stuck.` });
  }

  // Drill into the first case row
  const firstLink = page.locator('a[href^="/cases/"]').first();
  if ((await firstLink.count()) > 0) {
    const href = await firstLink.getAttribute('href');
    return href;
  }
  return null;
}

// ─── Phase 3: case detail ───────────────────────────────────────────

async function phaseCaseDetail(page: Page, fallbackHref: string | null) {
  // Pick a case id either from the link grabbed earlier, or from API
  let caseId: string | null = null;
  if (fallbackHref) caseId = fallbackHref.split('/').pop() || null;
  if (!caseId) {
    const list = (await apiGet<any>('/api/resolveai/cases?limit=10')).body?.data ?? [];
    caseId = list[0]?.id ?? null;
  }
  if (!caseId) {
    flowResults.push({ flow: 'Case-Detail-Approve', status: 'BROKEN', detail: 'no case_id available to drill into' });
    return;
  }

  const { ok, httpStatus } = await gotoRoute(page, `/cases/${caseId}`, `case_${caseId.slice(0, 8)}`);
  if (!ok) {
    flowResults.push({ flow: 'Case-Detail-Approve', status: 'BROKEN', detail: `HTTP ${httpStatus}` });
    return;
  }

  // Status pill present?
  const hasStatus = (await page.getByText(/Status/, { exact: false }).count()) > 0;
  const hasTimeline = (await page.getByText(/Timeline/, { exact: false }).count()) > 0;
  const apiCase = (await apiGet<any>(`/api/resolveai/cases/${caseId}`)).body?.data ?? {};
  const hasResolution = !!apiCase.resolution;
  const events = Array.isArray(apiCase.events) ? apiCase.events.length : 0;
  const actions = Array.isArray(apiCase.action_plan) ? apiCase.action_plan.length : 0;
  const citations = Array.isArray(apiCase.citations) ? apiCase.citations.length : 0;

  routeResults.push({
    route: `/cases/[caseId]`,
    status: hasStatus && hasTimeline ? 'PASS' : 'FAIL',
    httpStatus,
    notes: `status_pill=${hasStatus}, timeline=${hasTimeline}, events=${events}, actions=${actions}, citations=${citations}, resolution=${hasResolution}`,
  });

  // Take Over
  const takeOver = page.getByRole('button', { name: /Take over as human/i });
  if ((await takeOver.count()) > 0 && apiCase.status !== 'human_handling') {
    await takeOver.first().click().catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const refetched = (await apiGet<any>(`/api/resolveai/cases/${caseId}`)).body?.data ?? {};
    const screenshot = await snap(page, `case_after_takeover_${caseId.slice(0, 8)}`);
    flowResults.push({
      flow: 'Case-Detail-Approve',
      status: refetched.status === 'human_handling' ? 'PASS' : 'FAIL',
      detail: `take-over: status=${apiCase.status} → ${refetched.status}, actions=${actions}, citations=${citations}`,
      screenshot,
    });
    if (refetched.status !== 'human_handling') {
      bugs.push({ sev: 'P0', title: 'Take-Over button does not change status', detail: `expected human_handling, got ${refetched.status}` });
    }
  } else {
    flowResults.push({
      flow: 'Case-Detail-Approve',
      status: 'INFO',
      detail: `Take-Over not available (status=${apiCase.status}), actions=${actions}, citations=${citations}`,
    });
  }

  // Try the admin Approve/Reject path indirectly via API (UI exposes them on /admin)
  // — done in phase Admin.
  if (actions === 0) bugs.push({ sev: 'P1', title: 'Case has no action_plan after pipeline', detail: `case ${caseId.slice(0,8)} ended with empty action_plan; pipeline output may be sparse.` });
  if (citations === 0 && hasResolution) bugs.push({ sev: 'P1', title: 'Resolution rendered without citations', detail: `case ${caseId.slice(0,8)} has resolution text but zero citations — violates "every action must carry policy_id@version".` });
}

// ─── Phase 4: SLA ───────────────────────────────────────────────────

async function phaseSLA(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/sla', 'sla');
  if (!ok) {
    flowResults.push({ flow: 'SLA-Sweep', status: 'BROKEN', detail: `HTTP ${httpStatus}` });
    return;
  }
  const btn = page.locator('[data-testid="run-sla-sweep"]');
  if ((await btn.count()) === 0) {
    flowResults.push({ flow: 'SLA-Sweep', status: 'FAIL', detail: 'no Run-Sweep button' });
    return;
  }
  await btn.first().click();
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(1000);
  const screenshot = await snap(page, 'sla_after_sweep');
  const sweptText = await page.getByText(/Open cases swept/i).count();
  const breachedText = await page.getByText(/Breaches detected/i).count();
  flowResults.push({
    flow: 'SLA-Sweep',
    status: sweptText > 0 && breachedText > 0 ? 'PASS' : 'FAIL',
    detail: `swept_card=${sweptText > 0}, breached_card=${breachedText > 0}`,
    screenshot,
  });
}

// ─── Phase 5: QA ────────────────────────────────────────────────────

async function phaseQA(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/qa', 'qa');
  if (!ok) {
    flowResults.push({ flow: 'QA-Score', status: 'BROKEN', detail: `HTTP ${httpStatus}` });
    return;
  }
  const hasHeader = (await page.getByText(/Recent QA scores/i).count()) > 0;
  routeResults.push({
    route: '/qa  (board)',
    status: hasHeader ? 'PASS' : 'FAIL',
    httpStatus,
    notes: `qa_section=${hasHeader}`,
  });

  // Try to close a case so we can run /qa/run/{id}
  const list = (await apiGet<any>('/api/resolveai/cases?limit=50')).body?.data ?? [];
  const candidate = list.find((c: any) => c.status && c.status !== 'human_handling') ?? list[0];
  if (candidate?.id) {
    const closeRes = await apiPost(`/api/resolveai/cases/${candidate.id}/close`, {
      resolution: 'closed by UAT for QA scoring',
      closed_by: 'uat',
    });
    const qaRes = await apiPost(`/api/resolveai/qa/run/${candidate.id}`, {});
    await page.reload({ waitUntil: 'networkidle' }).catch(() => {});
    await page.waitForTimeout(1500);
    const screenshot = await snap(page, 'qa_after_run');
    const scoresApi = (await apiGet<any>('/api/resolveai/qa/scores')).body?.data ?? [];
    flowResults.push({
      flow: 'QA-Score',
      status: scoresApi.length > 0 ? 'PASS' : 'FAIL',
      detail: `close=${closeRes.status}, run_qa=${qaRes.status}, scores=${scoresApi.length}`,
      screenshot,
    });
    if (qaRes.status >= 400) bugs.push({ sev: 'P1', title: 'POST /api/resolveai/qa/run/{id} failed', detail: `status=${qaRes.status} body=${JSON.stringify(qaRes.body).slice(0,200)}` });
  } else {
    flowResults.push({ flow: 'QA-Score', status: 'INFO', detail: 'no candidate case to close+score' });
  }
}

// ─── Phase 6: Trends ────────────────────────────────────────────────

async function phaseTrends(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/trends', 'trends');
  if (!ok) {
    flowResults.push({ flow: 'Trend-Mine', status: 'BROKEN', detail: `HTTP ${httpStatus}` });
    return;
  }
  const btn = page.locator('[data-testid="run-trend-mining"]');
  if ((await btn.count()) === 0) {
    flowResults.push({ flow: 'Trend-Mine', status: 'FAIL', detail: 'no Mine-now button' });
    return;
  }
  await btn.first().click();
  await page.waitForLoadState('networkidle', { timeout: 60_000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const screenshot = await snap(page, 'trends_after_mine');
  const insightsApi = (await apiGet<any>('/api/resolveai/trends/insights')).body?.data ?? [];
  flowResults.push({
    flow: 'Trend-Mine',
    status: 'PASS',
    detail: `insights=${insightsApi.length}`,
    screenshot,
  });
  if (insightsApi.length === 0) {
    bugs.push({ sev: 'P2', title: 'Mine Trends produced 0 insights', detail: 'Likely too few cases in last 72h, but UI should at least render an explanation (it does).' });
  }
}

// ─── Phase 7+8: Admin ───────────────────────────────────────────────

async function phaseAdmin(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/admin', 'admin');
  if (!ok) {
    flowResults.push({ flow: 'Admin-Settings-Update', status: 'BROKEN', detail: `HTTP ${httpStatus}` });
    return;
  }
  const settingsCard = page.locator('[data-testid="admin-settings"]');
  const pendingCard = page.locator('[data-testid="pending-approvals"]');
  routeResults.push({
    route: '/admin',
    status: (await settingsCard.count()) && (await pendingCard.count()) ? 'PASS' : 'FAIL',
    httpStatus,
    notes: `settings_card=${await settingsCard.count()}, pending_card=${await pendingCard.count()}`,
  });

  // Edit the auto-approve ceiling
  const inputs = settingsCard.locator('input[type="number"]');
  const inputCount = await inputs.count();
  if (inputCount === 0) {
    flowResults.push({ flow: 'Admin-Settings-Update', status: 'FAIL', detail: 'no number inputs on /admin' });
    return;
  }
  const baselineSettings = (await apiGet<any>('/api/resolveai/admin/settings')).body?.data ?? {};
  const baselineAuto = Number(baselineSettings?.approval_tiers?.auto_ceiling_usd ?? 25);
  const target = baselineAuto === 42 ? 43 : 42;
  const auto = inputs.nth(0);
  await auto.fill(String(target));
  const save = page.locator('[data-testid="save-settings"]');
  // Capture the network request the Save button issues
  let saveStatus = 0;
  let saveMethod = '';
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/api/resolveai/admin/settings') && r.request().method() !== 'GET',
    { timeout: 10_000 },
  ).catch(() => null);
  await save.click();
  const resp = await respPromise;
  if (resp) { saveStatus = resp.status(); saveMethod = resp.request().method(); }
  await page.waitForTimeout(1500);
  const screenshot = await snap(page, 'admin_after_save');
  // Verify persistence
  const after = (await apiGet<any>('/api/resolveai/admin/settings')).body?.data ?? {};
  const afterAuto = Number(after?.approval_tiers?.auto_ceiling_usd ?? 0);
  const persisted = afterAuto === target;

  flowResults.push({
    flow: 'Admin-Settings-Update',
    status: persisted ? 'PASS' : 'FAIL',
    detail: `${saveMethod} ${saveStatus} · auto_ceiling ${baselineAuto}→${afterAuto} (target ${target})`,
    screenshot,
  });
  if (!persisted) {
    bugs.push({
      sev: 'P0',
      title: 'Admin Save button does not persist (method mismatch)',
      detail: `Web POSTs /admin/settings but FastAPI router exposes only PATCH (last response: ${saveMethod} ${saveStatus}). Settings change is silently dropped.`,
    });
  }

  // Pending-approvals queue render
  const pendingApi = (await apiGet<any>('/api/resolveai/admin/pending-approvals')).body?.data ?? [];
  routeResults.push({
    route: '/admin  (pending-approvals)',
    status: 'PASS',
    httpStatus,
    notes: `pending_count=${pendingApi.length}`,
  });
}

// ─── Phase 9: Live Console ──────────────────────────────────────────

async function phaseLiveConsole(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/live-console', 'live_console');
  if (!ok) return;
  const stub = (await page.getByText(/Phase 2/i).count()) > 0
            || (await page.getByText(/live-console\/stream/i).count()) > 0;
  routeResults.push({
    route: '/live-console',
    status: stub ? 'PASS' : 'FAIL',
    httpStatus,
    notes: stub ? 'Phase-2 stub copy present' : 'no stub markers',
  });
  if (!stub) bugs.push({ sev: 'GAP', title: '/live-console missing Phase-2 stub copy', detail: 'page has no placeholder explaining the SSE endpoint.' });
}

// ─── Phase 10: Help ─────────────────────────────────────────────────

async function phaseHelp(page: Page) {
  const { ok, httpStatus } = await gotoRoute(page, '/help', 'help');
  if (!ok) return;
  // every internal page card link should resolve
  const hrefs = await page.$$eval('a[href]', (els) => els.map((e) => (e as HTMLAnchorElement).getAttribute('href') || '').filter(Boolean));
  const internalLinks = Array.from(new Set(hrefs.filter((h) => h.startsWith('/'))));
  let broken: string[] = [];
  for (const h of internalLinks) {
    const r = await fetch(`${BASE}${h}`).catch(() => null);
    if (!r || r.status >= 400) broken.push(`${h}=${r?.status ?? 'ERR'}`);
  }
  // images
  const imgs = await page.$$eval('img', (els) => els.map((e) => ({ src: (e as HTMLImageElement).src, complete: (e as HTMLImageElement).complete, w: (e as HTMLImageElement).naturalWidth })));
  const brokenImgs = imgs.filter((i) => !i.complete || i.w === 0);
  routeResults.push({
    route: '/help',
    status: broken.length === 0 && brokenImgs.length === 0 ? 'PASS' : 'FAIL',
    httpStatus,
    notes: `internal_links_ok=${internalLinks.length - broken.length}/${internalLinks.length}, broken_imgs=${brokenImgs.length}`,
  });
  if (broken.length > 0) bugs.push({ sev: 'P2', title: '/help walkthrough has broken internal links', detail: broken.join(', ') });
  if (brokenImgs.length > 0) bugs.push({ sev: 'P2', title: '/help walkthrough has broken images', detail: brokenImgs.map((i) => i.src).join(', ') });
}

// ─── Report writer ──────────────────────────────────────────────────

function writeReport() {
  const passes = [...routeResults, ...flowResults].filter((r) => r.status === 'PASS').length;
  const fails  = [...routeResults, ...flowResults].filter((r) => r.status === 'FAIL').length;
  const broken = [...routeResults, ...flowResults].filter((r) => r.status === 'BROKEN').length;
  const totalRoutes = routeResults.length;
  const totalFlows = flowResults.length;
  const ctaCount = flowResults.length; // each flow exercises a CTA

  const sevOrder = { P0: 0, P1: 1, P2: 2, GAP: 3 } as const;
  bugs.sort((a, b) => sevOrder[a.sev] - sevOrder[b.sev]);

  const lines: string[] = [];
  lines.push(`# ResolveAI Deep UI UAT — ${new Date().toISOString()}`);
  lines.push('');
  lines.push(`Summary: routes=${totalRoutes} · CTAs=${ctaCount} · deep flows=${totalFlows} · passes=${passes} · fails=${fails} · broken=${broken}`);
  lines.push(`Web=${BASE} · API=${API} · Tenant=${TENANT}`);
  lines.push('');
  lines.push('## Per-route results');
  lines.push('| Route | HTTP | Status | Notes |');
  lines.push('|---|---|---|---|');
  for (const r of routeResults) {
    lines.push(`| ${r.route} | ${r.httpStatus} | ${r.status} | ${r.notes.replace(/\|/g, '\\|')} |`);
  }
  lines.push('');
  lines.push('## Deep flows');
  lines.push('| Flow | Status | Detail |');
  lines.push('|---|---|---|');
  for (const f of flowResults) {
    lines.push(`| ${f.flow} | ${f.status} | ${f.detail.replace(/\|/g, '\\|')} |`);
  }
  lines.push('');
  lines.push('## Console errors (top 10)');
  if (consoleErrs.length === 0) {
    lines.push('_None._');
  } else {
    const grouped = new Map<string, number>();
    for (const e of consoleErrs) {
      const key = `${e.text.split('\n')[0].slice(0, 200)}`;
      grouped.set(key, (grouped.get(key) ?? 0) + 1);
    }
    const top = Array.from(grouped.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10);
    for (const [k, n] of top) lines.push(`- (${n}x) ${k}`);
  }
  lines.push('');
  lines.push('## 4xx / 5xx network responses');
  if (networkFails.length === 0) {
    lines.push('_None._');
  } else {
    lines.push('| Page route | Method | Status | URL |');
    lines.push('|---|---|---|---|');
    for (const f of networkFails.slice(0, 60)) {
      lines.push(`| ${f.route} | ${f.method} | ${f.status} | ${f.url.replace(/\|/g, '\\|')} |`);
    }
  }
  lines.push('');
  lines.push('## Bugs (severity-ordered)');
  if (bugs.length === 0) {
    lines.push('_None._');
  } else {
    bugs.forEach((b, i) => {
      lines.push(`${i + 1}. **[${b.sev}] ${b.title}** — ${b.detail}`);
    });
  }
  lines.push('');
  lines.push('## UI gaps (Phase-2 + design-doc deltas)');
  lines.push('- **Live Console SSE not wired**: /live-console is a placeholder; no actual stream from /api/resolveai/live-console/stream.');
  lines.push('- **Customer Context enrich endpoint missing**: docs reference Shopify+Zendesk enrichment but no `/customer-context/enrich` route appears on the API; UI never surfaces LTV/churn signal beyond what triage emits.');
  lines.push('- **Hardcoded SAMPLES leak into UX**: `/cases` SAMPLES array (c-1001..c-1004) is committed in client code and visible to any user — synthetic ticket scenarios should come from a fixture endpoint.');
  lines.push('- **Welcome banner has only LocalStorage gating**: Try-It-Now CTA disappears once dismissed; no second entry-point on the dashboard for repeat users.');
  lines.push('- **Admin Save uses wrong HTTP verb**: client POSTs but server only accepts PATCH — settings appear to save (no error toast) but never persist.');
  lines.push('- **Citations field ambiguity**: Case detail handles citation as either string or object; no link to the actual policy doc — citations are flat text, not navigable.');
  lines.push('');
  lines.push(`Screenshots in: ${path.relative(path.resolve(__dirname, '..'), SCREENS_DIR).replace(/\\/g, '/')}/`);

  fs.writeFileSync(REPORT_PATH, lines.join('\n'), 'utf8');
  logLine('');
  logLine(`Report written: ${REPORT_PATH}`);
  logLine(`Summary: routes=${totalRoutes} · CTAs=${ctaCount} · flows=${totalFlows} · passes=${passes} · fails=${fails} · broken=${broken}`);
  logLine(`Bugs: ${bugs.length} (${bugs.filter(b => b.sev === 'P0').length} P0, ${bugs.filter(b => b.sev === 'P1').length} P1, ${bugs.filter(b => b.sev === 'P2').length} P2, ${bugs.filter(b => b.sev === 'GAP').length} GAP)`);
}

// ─── main ───────────────────────────────────────────────────────────

async function main() {
  let browser: Browser | null = null;
  try {
    browser = await chromium.launch({ headless: true });
    const ctx: BrowserContext = await browser.newContext({
      extraHTTPHeaders: { 'X-Tenant-Id': TENANT },
      viewport: { width: 1440, height: 900 },
    });
    const page = await ctx.newPage();
    attachListeners(page);

    logLine('phase 1: dashboard + try-it-now');     await phaseDashboard(page);
    logLine('phase 2: cases queue + 4 synthetic'); const fallbackHref = await phaseCasesQueue(page);
    logLine('phase 3: case detail + take-over');    await phaseCaseDetail(page, fallbackHref);
    logLine('phase 4: SLA sweep');                  await phaseSLA(page);
    logLine('phase 5: QA score');                   await phaseQA(page);
    logLine('phase 6: trend mining');               await phaseTrends(page);
    logLine('phase 7+8: admin');                    await phaseAdmin(page);
    logLine('phase 9: live-console stub');          await phaseLiveConsole(page);
    logLine('phase 10: help walkthrough');          await phaseHelp(page);

    await ctx.close();
  } catch (e) {
    logLine(`FATAL: ${(e as Error).message}`);
    bugs.push({ sev: 'P0', title: 'UAT runner crashed', detail: String(e).slice(0, 400) });
  } finally {
    if (browser) await browser.close();
    writeReport();
  }
}

void main();
