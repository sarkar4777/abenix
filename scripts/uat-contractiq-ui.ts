/**
 * Deep UI UAT for ContractIQ (live cluster).
 *
 *   - Logs in via UI as test@contractiq.com
 *   - Visits every documented route
 *   - Captures status / body length / render OK / visible errors / screenshot
 *   - Clicks every primary CTA on each page and verifies "something happens"
 *   - Deep flows: Upload+Extract, Chat, Briefing, Anomaly Scan, Stress Test
 *   - Captures console errors and 4xx/5xx network responses
 *   - Writes logs/uat/apps/contractiq-ui-report.md and prints summary table
 *
 * Run with: npx tsx scripts/uat-contractiq-ui.ts
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

// ── Config ─────────────────────────────────────────────────────────────────
const BASE = process.env.CIQ_URL || 'http://localhost:3001';
const API = process.env.CIQ_API || 'http://localhost:8001';
const EMAIL = 'test@contractiq.com';
const PASSWORD = 'TestPass123!';

const ROOT = path.resolve(__dirname, '..');
const REPORT_DIR = path.join(ROOT, 'logs', 'uat', 'apps');
const SHOTS_DIR = path.join(REPORT_DIR, 'contractiq-screens');
const REPORT_PATH = path.join(REPORT_DIR, 'contractiq-ui-report.md');
const PROGRESS = path.join(REPORT_DIR, 'contractiq-ui-progress.log');
fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.mkdirSync(SHOTS_DIR, { recursive: true });
fs.writeFileSync(PROGRESS, '');

const TEST_PDF = path.join(ROOT, 'contractiq', 'test-contracts', 'solar_ppa_uae_250mw.pdf');

// ── State ──────────────────────────────────────────────────────────────────
type RouteResult = {
  route: string;
  status: number | string;
  bodyLen: number;
  renderOk: boolean;
  topError: string;
  ctaFired: boolean;
  ctaLabel: string;
  shot: string;
};
const routeResults: RouteResult[] = [];

type FlowResult = {
  name: string;
  pass: boolean;
  evidence: string;
};
const flowResults: FlowResult[] = [];

type ConsoleErr = { route: string; text: string };
const consoleErrors: ConsoleErr[] = [];

type NetFail = { route: string; url: string; status: number };
const networkFails: NetFail[] = [];

type Bug = { sev: 'P0' | 'P1' | 'P2' | 'UX'; route: string; repro: string };
const bugs: Bug[] = [];

let currentRoute = '/';

function log(s: string) {
  const line = `[${new Date().toISOString().slice(11, 19)}] ${s}`;
  process.stdout.write(line + '\n');
  fs.appendFileSync(PROGRESS, line + '\n');
}

function attachListeners(page: Page) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const t = msg.text().slice(0, 240);
      // Filter known noisy ones
      if (t.includes('favicon') || t.includes('Failed to load resource: the server responded with a status of 404')) return;
      consoleErrors.push({ route: currentRoute, text: t });
    }
  });
  page.on('response', (resp) => {
    const url = resp.url();
    const status = resp.status();
    if (status >= 400 && !url.includes('favicon') && !url.includes('/_next/') && !url.includes('hot-update')) {
      networkFails.push({ route: currentRoute, url: url.slice(0, 220), status });
    }
    // SDK regression heuristic: agent-driven endpoints that return 200 with
    // an empty output body smell like the async-mode bug where the SDK
    // (or server) returned before the agent finished. Flag as P0.
    if (status === 200 && /\/(execute|chat|insights|extract|brief|stress|anomal|run)/i.test(url)) {
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
              bugs.push({ sev: 'P0', route: currentRoute, repro: `SDK-empty-output: ${url.slice(0, 160)} returned 200 with empty output (mode=${mode ?? 'n/a'})` });
            }
          }
        }).catch(() => {});
      }
    }
  });
  page.on('pageerror', (err) => {
    consoleErrors.push({ route: currentRoute, text: `pageerror: ${err.message.slice(0, 240)}` });
  });
}

async function snap(page: Page, name: string): Promise<string> {
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  const file = path.join(SHOTS_DIR, `${safe}.png`);
  try {
    await page.screenshot({ path: file, fullPage: false });
  } catch {
    /* ignore */
  }
  return path.relative(REPORT_DIR, file).replace(/\\/g, '/');
}

// ── Login ──────────────────────────────────────────────────────────────────
async function login(page: Page): Promise<boolean> {
  currentRoute = '/login';
  log(`login → goto ${BASE}/`);
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(800);

  // Click "Sign In" in nav to open modal
  const signInBtn = page.locator('button', { hasText: 'Sign In' }).first();
  try {
    await signInBtn.click({ timeout: 5000 });
  } catch {
    // try Get Started
    const gs = page.locator('button', { hasText: 'Get Started' }).first();
    await gs.click({ timeout: 5000 });
  }

  await page.waitForTimeout(500);

  // Fill email + password (modal form)
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await snap(page, '00_login_filled');

  // Submit (the form button says "Sign In" again — click the one inside form)
  const submitBtn = page.locator('button[type="submit"]', { hasText: /Sign In/ }).first();
  await submitBtn.click({ timeout: 5000 });

  // Wait for redirect
  try {
    await page.waitForURL(/\/dashboard/, { timeout: 25000 });
    log('login → success, on /dashboard');
    await snap(page, '01_dashboard_after_login');
    return true;
  } catch (e: any) {
    const errText = await page.locator('p.text-red-400').first().textContent().catch(() => '');
    log(`login FAILED: ${errText || e.message}`);
    await snap(page, '00_login_failed');
    bugs.push({ sev: 'P0', route: '/login', repro: `Login failed: ${errText || 'no redirect to /dashboard within 25s'}` });
    return false;
  }
}

// ── Per-route walk ─────────────────────────────────────────────────────────
const PRIMARY_CTA_PATTERNS = [
  // Specific to ContractIQ
  /^Generate Briefing$/i,
  /^Generate$/i,
  /^Run Scan$/i,
  /^Scan$/i,
  /^Run Test$/i,
  /^Run Stress Test$/i,
  /^Run Scenario$/i,
  /^Run$/i,
  /^Refresh$/i,
  /^Recompute$/i,
  /^Reconcile$/i,
  /^Detect$/i,
  /^New$/i,
  /^Create$/i,
  /^Upload$/i,
  /^New Contract$/i,
  /^Generate Term Sheet$/i,
  /^Build Hedge$/i,
  /^Compare$/i,
  /^Detect Anomalies$/i,
];

async function findPrimaryCta(page: Page): Promise<{ label: string; loc: any } | null> {
  // Try button text exact-match against patterns first
  const buttons = page.locator('button:visible');
  const count = await buttons.count();
  for (let i = 0; i < Math.min(count, 60); i++) {
    const b = buttons.nth(i);
    const txt = (await b.textContent().catch(() => ''))?.trim() || '';
    if (!txt) continue;
    for (const pat of PRIMARY_CTA_PATTERNS) {
      if (pat.test(txt)) {
        return { label: txt, loc: b };
      }
    }
  }
  // Fallback: first non-icon button with > 2-char text near top
  for (let i = 0; i < Math.min(count, 30); i++) {
    const b = buttons.nth(i);
    const txt = (await b.textContent().catch(() => ''))?.trim() || '';
    if (!txt || txt.length < 3 || txt.length > 40) continue;
    if (/sign|logout|settings|menu|close|back|toggle/i.test(txt)) continue;
    return { label: txt, loc: b };
  }
  return null;
}

async function visitRoute(page: Page, route: string): Promise<RouteResult> {
  currentRoute = route;
  log(`route → ${route}`);
  let status: number | string = 0;
  page.once('response', (r) => {
    if (r.url().includes(route) && status === 0) status = r.status();
  });

  let httpStatus: number | string = 0;
  try {
    const resp = await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    httpStatus = resp?.status() ?? 0;
  } catch (e: any) {
    httpStatus = `err: ${e.message.slice(0, 80)}`;
  }

  await page.waitForTimeout(2000); // let client-side render

  // Render check: bodyText length, no "Loading…" alone
  const bodyText = (await page.locator('body').innerText().catch(() => '')) || '';
  const bodyLen = bodyText.length;
  const stuckLoading = /^\s*(Loading\.{1,3}|Loading)\s*$/i.test(bodyText.trim()) || (bodyLen < 80 && /loading/i.test(bodyText));
  const renderOk = bodyLen >= 80 && !stuckLoading;

  // Visible error text
  let topError = '';
  const errSelectors = [
    'text=/Something went wrong/i',
    'text=/Failed to/i',
    'text=/Error:/i',
    '.text-red-400',
    '.text-red-500',
    '[role="alert"]',
  ];
  for (const sel of errSelectors) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 200 }).catch(() => false)) {
        const t = (await el.textContent().catch(() => ''))?.trim() || '';
        if (t && t.length < 200 && !/Get Started/.test(t)) {
          topError = t;
          break;
        }
      }
    } catch {}
  }

  const safeName = route.replace(/^\//, '').replace(/[^a-z0-9_-]/gi, '_') || 'root';
  const shot = await snap(page, `route_${safeName}`);

  // Try CTA
  let ctaFired = false;
  let ctaLabel = '';
  try {
    const cta = await findPrimaryCta(page);
    if (cta) {
      ctaLabel = cta.label;
      const beforeUrl = page.url();
      const beforeLen = bodyLen;
      await cta.loc.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(1800);
      const afterUrl = page.url();
      const afterLen = (await page.locator('body').innerText().catch(() => '')).length;
      // "something happened" = url change OR body length change > 30 OR a modal appeared OR a toast
      const modalVisible = await page.locator('[role="dialog"], .modal, [data-state="open"]').first().isVisible({ timeout: 200 }).catch(() => false);
      const toastVisible = await page.locator('[data-sonner-toast], .toast, .Toastify__toast').first().isVisible({ timeout: 200 }).catch(() => false);
      ctaFired = afterUrl !== beforeUrl || Math.abs(afterLen - beforeLen) > 30 || modalVisible || toastVisible;
      // Navigate back to original route if we drifted
      if (afterUrl !== beforeUrl && !afterUrl.includes(route)) {
        await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(500);
      }
    }
  } catch (e: any) {
    log(`CTA error on ${route}: ${e.message.slice(0, 80)}`);
  }

  const result: RouteResult = {
    route,
    status: httpStatus,
    bodyLen,
    renderOk,
    topError,
    ctaFired,
    ctaLabel,
    shot,
  };
  routeResults.push(result);

  // Bug heuristics
  if (!renderOk) bugs.push({ sev: 'P1', route, repro: `Render failed: bodyLen=${bodyLen} stuckLoading=${stuckLoading}` });
  if (bodyLen > 0 && bodyLen < 200) bugs.push({ sev: 'P2', route, repro: `Suspiciously thin page: bodyLen=${bodyLen}` });
  if (typeof httpStatus === 'number' && httpStatus >= 400) bugs.push({ sev: 'P0', route, repro: `HTTP ${httpStatus} on initial GET` });
  if (topError) bugs.push({ sev: 'P1', route, repro: `Visible error text: "${topError.slice(0, 100)}"` });
  if (/Coming soon|Stub|Not implemented|TODO/i.test(bodyText)) bugs.push({ sev: 'UX', route, repro: 'Page contains "Coming soon"/stub-style text' });

  return result;
}

// ── Routes ─────────────────────────────────────────────────────────────────
const ROUTES = [
  '/dashboard',
  '/upload',
  '/contracts',
  '/chat',
  '/compare',
  '/clauses',
  '/insights',
  '/insights/briefing',
  '/insights/renewals',
  '/insights/force-majeure',
  '/insights/reconciliation',
  '/insights/families',
  '/insights/anomalies',
  '/insights/version-diff',
  '/insights/stress-test',
  '/insights/hedge',
  '/market',
  '/valuation',
  '/credit-risk',
  '/credit-risk/kyc',
  '/timeline',
  '/deal-clusters',
  '/help',
];

// ── Deep flows ─────────────────────────────────────────────────────────────
async function flowUploadExtract(page: Page): Promise<FlowResult> {
  const name = 'Upload+Extract';
  log(`flow → ${name}`);
  try {
    if (!fs.existsSync(TEST_PDF)) {
      return { name, pass: false, evidence: `Test PDF missing at ${TEST_PDF}` };
    }
    currentRoute = '/upload';
    await page.goto(`${BASE}/upload`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(1500);

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(TEST_PDF);
    log(`upload → file selected: ${path.basename(TEST_PDF)}`);
    await snap(page, 'flow_upload_01_selected');
    await page.waitForTimeout(1500);

    // Look for explicit "Upload"/"Process" button
    const startBtn = page
      .locator('button:visible')
      .filter({ hasText: /Upload|Process|Start|Extract|Submit/i })
      .first();
    if (await startBtn.count()) {
      await startBtn.click({ timeout: 3000 }).catch(() => {});
    }

    // Poll for upload completion: URL changes to /contracts/[id] OR a status reaches "ready"/"completed"
    const start = Date.now();
    let contractId = '';
    let extracted = false;
    while (Date.now() - start < 90000) {
      const url = page.url();
      const m = url.match(/\/contracts\/([\w-]{6,})/);
      if (m) {
        contractId = m[1];
        log(`upload → redirected to contract ${contractId}`);
        break;
      }
      // OR check for "completed" / "ready" status text
      const txt = (await page.locator('body').innerText().catch(() => '')) || '';
      if (/extraction.*(complete|ready|done|success)/i.test(txt) || /uploaded successfully/i.test(txt)) {
        extracted = true;
        break;
      }
      await page.waitForTimeout(2500);
    }

    if (!contractId && !extracted) {
      // Try /contracts list — find newest one
      await page.goto(`${BASE}/contracts`, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(1500);
      const firstLink = page.locator('a[href^="/contracts/"]:visible').first();
      if (await firstLink.count()) {
        const href = await firstLink.getAttribute('href');
        if (href) {
          contractId = href.split('/').pop() || '';
          await firstLink.click({ timeout: 3000 }).catch(() => {});
          await page.waitForTimeout(2500);
        }
      }
    }

    await snap(page, 'flow_upload_02_after');

    if (contractId) {
      await page.goto(`${BASE}/contracts/${contractId}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(3000);
      const detailText = (await page.locator('body').innerText().catch(() => '')) || '';
      await snap(page, 'flow_upload_03_detail');
      const hasClauses = /clause/i.test(detailText);
      const hasFields = /counterparty|notional|capacity|MW|tenor|start date|effective/i.test(detailText);
      // Also walk into /contracts and grab the first one for "Open the first contract" route check
      routeResults.push({
        route: '/contracts/[id]',
        status: 200,
        bodyLen: detailText.length,
        renderOk: detailText.length > 200,
        topError: '',
        ctaFired: false,
        ctaLabel: '(detail page)',
        shot: 'contractiq-screens/flow_upload_03_detail.png',
      });
      if (hasClauses && hasFields) {
        return { name, pass: true, evidence: `contract=${contractId}, clauses+fields visible (bodyLen=${detailText.length})` };
      }
      return {
        name,
        pass: false,
        evidence: `contract=${contractId} but missing ${hasClauses ? '' : 'clauses '}${hasFields ? '' : 'fields'} (bodyLen=${detailText.length})`,
      };
    }

    return { name, pass: false, evidence: `No redirect to /contracts/[id] after 90s and no completion text` };
  } catch (e: any) {
    return { name, pass: false, evidence: `Exception: ${e.message.slice(0, 200)}` };
  }
}

async function flowChat(page: Page): Promise<FlowResult> {
  const name = 'Chat';
  log(`flow → ${name}`);
  try {
    currentRoute = '/chat';
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);

    const QUESTION = "what's the total notional exposure across my portfolio?";

    // Find textarea or input
    const textarea = page
      .locator('textarea:visible, input[type="text"]:visible')
      .filter({ hasNot: page.locator('input[type="email"]') })
      .first();
    if (!(await textarea.count())) {
      return { name, pass: false, evidence: 'No chat textarea/input found' };
    }
    await textarea.fill(QUESTION);
    await snap(page, 'flow_chat_01_typed');

    // Find send button
    const sendBtn = page.locator('button:visible').filter({ hasText: /Send|Ask|Submit/i }).first();
    if (await sendBtn.count()) {
      await sendBtn.click({ timeout: 3000 }).catch(() => {});
    } else {
      await textarea.press('Enter').catch(() => {});
    }

    // Wait for reply
    const start = Date.now();
    let replyLen = 0;
    while (Date.now() - start < 60000) {
      const txt = (await page.locator('body').innerText().catch(() => '')) || '';
      // very rough: total chat text includes question + reply
      const aboveQ = txt.split(QUESTION)[1] || '';
      replyLen = aboveQ.replace(/\s+/g, ' ').trim().length;
      if (replyLen > 60) break;
      await page.waitForTimeout(2500);
    }
    await snap(page, 'flow_chat_02_reply');
    if (replyLen > 60) {
      return { name, pass: true, evidence: `reply length=${replyLen} chars` };
    }
    return { name, pass: false, evidence: `No reply or empty reply within 60s (replyLen=${replyLen})` };
  } catch (e: any) {
    return { name, pass: false, evidence: `Exception: ${e.message.slice(0, 200)}` };
  }
}

async function flowGenerateOnRoute(
  flowName: string,
  route: string,
  ctaPattern: RegExp,
  page: Page,
  waitMs = 60000
): Promise<FlowResult> {
  log(`flow → ${flowName} @ ${route}`);
  try {
    currentRoute = route;
    await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);
    const before = (await page.locator('body').innerText().catch(() => '')) || '';
    const beforeLen = before.length;

    const btn = page.locator('button:visible').filter({ hasText: ctaPattern }).first();
    if (!(await btn.count())) {
      await snap(page, `flow_${flowName.replace(/\W/g, '_')}_no_cta`);
      return { name: flowName, pass: false, evidence: `CTA matching ${ctaPattern} not found on ${route}` };
    }
    await btn.click({ timeout: 3000 }).catch(() => {});
    log(`${flowName} → CTA clicked, waiting up to ${waitMs / 1000}s for content`);

    const start = Date.now();
    let added = 0;
    while (Date.now() - start < waitMs) {
      const after = (await page.locator('body').innerText().catch(() => '')) || '';
      added = after.length - beforeLen;
      if (added > 200) break;
      // also check for visible error
      if (/error|failed/i.test(after) && !/Force Majeure/i.test(after)) {
        // soft signal — keep waiting unless severe
      }
      await page.waitForTimeout(2500);
    }
    await snap(page, `flow_${flowName.replace(/\W/g, '_')}_after`);
    if (added > 200) {
      return { name: flowName, pass: true, evidence: `bodyLen Δ=${added}` };
    }
    return { name: flowName, pass: false, evidence: `No new content within ${waitMs / 1000}s (Δ=${added})` };
  } catch (e: any) {
    return { name: flowName, pass: false, evidence: `Exception: ${e.message.slice(0, 200)}` };
  }
}

// ── Open first contract (for /contracts/[id] route) ────────────────────────
async function visitFirstContract(page: Page): Promise<void> {
  currentRoute = '/contracts';
  await page.goto(`${BASE}/contracts`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForTimeout(1800);
  const link = page.locator('a[href^="/contracts/"]:visible').first();
  if (!(await link.count())) {
    log('first-contract → no contract link found');
    return;
  }
  const href = await link.getAttribute('href');
  if (!href) return;
  await page.goto(`${BASE}${href}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForTimeout(2500);
  currentRoute = href;
  const text = (await page.locator('body').innerText().catch(() => '')) || '';
  const shot = await snap(page, `route_contracts_id_${href.split('/').pop()}`);
  routeResults.push({
    route: '/contracts/[id]',
    status: 200,
    bodyLen: text.length,
    renderOk: text.length > 200,
    topError: '',
    ctaFired: false,
    ctaLabel: '(contract detail)',
    shot,
  });
}

// ── Main ───────────────────────────────────────────────────────────────────
async function main() {
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx: BrowserContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page: Page = await ctx.newPage();
  attachListeners(page);

  const ok = await login(page);
  if (!ok) {
    log('Login failed — aborting deep flows but writing partial report.');
    await writeReport();
    await browser.close();
    process.exit(1);
  }

  // Deep flow: upload first so we have at least one contract
  const fUpload = await flowUploadExtract(page);
  flowResults.push(fUpload);

  // Then walk routes
  for (const r of ROUTES) {
    await visitRoute(page, r);
  }

  // Also hit /contracts/[id] explicitly (first contract)
  await visitFirstContract(page);

  // Other deep flows
  flowResults.push(await flowChat(page));
  flowResults.push(
    await flowGenerateOnRoute('Briefing', '/insights/briefing', /Generate|Run|Create Briefing/i, page, 90000)
  );
  flowResults.push(
    await flowGenerateOnRoute('AnomalyScan', '/insights/anomalies', /Scan|Detect|Run|Find/i, page, 90000)
  );
  flowResults.push(
    await flowGenerateOnRoute('StressTest', '/insights/stress-test', /Run|Simulate|Stress|Generate/i, page, 90000)
  );

  await writeReport();
  await browser.close();
}

// ── Report writer ──────────────────────────────────────────────────────────
function uniq(arr: string[]): string[] {
  return Array.from(new Set(arr));
}

async function writeReport() {
  const passes = flowResults.filter((f) => f.pass).length + routeResults.filter((r) => r.renderOk).length;
  const fails = flowResults.filter((f) => !f.pass).length + routeResults.filter((r) => !r.renderOk).length;
  const broken = bugs.filter((b) => b.sev === 'P0').length;
  const ctaCount = routeResults.filter((r) => r.ctaLabel).length;

  const summary = `${routeResults.length} routes / ${ctaCount} CTAs / ${flowResults.length} deep flows tested · ${passes} passes · ${fails} fails · ${broken} broken`;

  let md = `# ContractIQ deep UI UAT report\n\n`;
  md += `Run: ${new Date().toISOString()}\n\n`;
  md += `**Summary:** ${summary}\n\n`;

  md += `## Per-route results\n\n`;
  md += `| Route | Status | BodyLen | RenderOK | CTA | CTAFired | TopError |\n`;
  md += `|---|---|---|---|---|---|---|\n`;
  for (const r of routeResults) {
    const errCell = (r.topError || '').slice(0, 60).replace(/\|/g, '\\|');
    const ctaCell = (r.ctaLabel || '-').slice(0, 28).replace(/\|/g, '\\|');
    md += `| ${r.route} | ${r.status} | ${r.bodyLen} | ${r.renderOk ? 'yes' : 'NO'} | ${ctaCell} | ${r.ctaFired ? 'yes' : 'no'} | ${errCell} |\n`;
  }

  md += `\n## Deep flows\n\n`;
  md += `| Flow | Result | Evidence |\n|---|---|---|\n`;
  for (const f of flowResults) {
    md += `| ${f.name} | ${f.pass ? 'PASS' : 'FAIL'} | ${f.evidence.replace(/\|/g, '\\|').slice(0, 220)} |\n`;
  }

  md += `\n## Console errors (top 10 unique)\n\n`;
  const uniqErrs = uniq(consoleErrors.map((e) => `${e.text}`)).slice(0, 10);
  if (!uniqErrs.length) md += '_None_\n';
  for (const e of uniqErrs) {
    md += `- ${e.replace(/\|/g, '\\|').slice(0, 220)}\n`;
  }

  md += `\n## 4xx/5xx network responses\n\n`;
  if (!networkFails.length) md += '_None_\n';
  // Dedupe by route+status+pathish
  const seen = new Set<string>();
  for (const n of networkFails) {
    const key = `${n.route}|${n.status}|${n.url.replace(/[?].*/, '')}`;
    if (seen.has(key)) continue;
    seen.add(key);
    md += `- [${n.status}] route=\`${n.route}\` → ${n.url}\n`;
  }

  md += `\n## Bugs found (severity-ordered)\n\n`;
  bugs.sort((a, b) => {
    const order = { P0: 0, P1: 1, P2: 2, UX: 3 } as Record<string, number>;
    return order[a.sev] - order[b.sev];
  });
  if (!bugs.length) md += '_None — every route rendered + every CTA fired._\n';
  bugs.forEach((b, i) => {
    md += `${i + 1}. **[${b.sev}]** \`${b.route}\` — ${b.repro}\n`;
  });

  md += `\n## UI gaps for business users\n\n`;
  // Heuristics for gaps
  const gapNotes: string[] = [];
  for (const r of routeResults) {
    if (!r.ctaFired && r.ctaLabel && r.ctaLabel !== '-' && !/contract detail/i.test(r.ctaLabel)) {
      gapNotes.push(`\`${r.route}\` — CTA "${r.ctaLabel}" produced no visible state change`);
    }
    if (r.bodyLen > 0 && r.bodyLen < 600 && r.renderOk) {
      gapNotes.push(`\`${r.route}\` — page rendered but very thin (${r.bodyLen} chars), likely empty-state with no guidance`);
    }
  }
  for (const f of flowResults) {
    if (!f.pass) gapNotes.push(`Deep flow **${f.name}** failed: ${f.evidence}`);
  }
  if (!gapNotes.length) md += '_No major business-user gaps detected._\n';
  uniq(gapNotes).slice(0, 25).forEach((g, i) => {
    md += `${i + 1}. ${g}\n`;
  });

  md += `\n---\n`;
  md += `Screenshots in \`logs/uat/apps/contractiq-screens/\`. Progress log at \`logs/uat/apps/contractiq-ui-progress.log\`.\n`;

  fs.writeFileSync(REPORT_PATH, md);
  log(`report written: ${REPORT_PATH}`);

  // Stdout summary table
  process.stdout.write('\n========================================\n');
  process.stdout.write(`SUMMARY: ${summary}\n`);
  process.stdout.write('========================================\n');
  process.stdout.write('| Route | Status | Len | RenderOK | CTA | Fired |\n');
  for (const r of routeResults) {
    process.stdout.write(`| ${r.route} | ${r.status} | ${r.bodyLen} | ${r.renderOk ? 'Y' : 'N'} | ${(r.ctaLabel || '-').slice(0, 22)} | ${r.ctaFired ? 'Y' : 'N'} |\n`);
  }
  process.stdout.write('\nDeep flows:\n');
  for (const f of flowResults) {
    process.stdout.write(`  - ${f.name}: ${f.pass ? 'PASS' : 'FAIL'} — ${f.evidence.slice(0, 120)}\n`);
  }
  process.stdout.write(`\nBugs: ${bugs.length} (P0=${bugs.filter((b) => b.sev === 'P0').length}, P1=${bugs.filter((b) => b.sev === 'P1').length}, P2=${bugs.filter((b) => b.sev === 'P2').length}, UX=${bugs.filter((b) => b.sev === 'UX').length})\n`);
}

main().catch((e) => {
  log(`fatal: ${e.message}`);
  console.error(e);
  process.exit(2);
});
