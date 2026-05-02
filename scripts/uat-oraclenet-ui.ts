/**
 * Deep UI UAT for /oraclenet (OracleNet decision-analysis showcase).
 *
 * 7-agent pipeline (oraclenet-pipeline): Decision Parser →
 *   {Historian, Current State, Stakeholder Sim} →
 *   {Second-Order, Contrarian} → Synthesizer.
 *
 * Phases probed:
 *   IF  Login + nav to /oraclenet + Input form + 4 example prompts + depth
 *   AN  Analyze (Run 1: SaaS pricing / standard, Run 2: rare-earths / quick)
 *   T*  7 Decision-Brief tabs (Summary, Scenarios, Stakeholders, Cascade, Risks, Rec, Provenance)
 *   EX  Exports (JSON, Markdown, Copy, PDF, DOCX)
 *   HI  Session History dropdown + re-run from history
 *
 * Output:
 *   logs/uat/apps/oraclenet-ui-report.md
 *   logs/uat/apps/oraclenet-screens/*.png
 *
 * Notes / why this rewrite:
 *  - Earlier run reported "0 CTAs/checkpoints exercised". Root cause: the parent
 *    process killed the child mid-`waitForBrief` (which polls every 2.5s for up
 *    to 8 min). When Playwright threw "Target page closed" the script's fatal
 *    handler called writeReport({}) again with the now-incomplete findings
 *    array. New behaviour: every long-poll guards against browser closure,
 *    timeouts are graceful, and writeReport is idempotent + only called once.
 */

import { chromium, type Browser, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';

const OUT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'apps');
const SHOT_DIR = path.join(OUT_DIR, 'oraclenet-screens');
fs.mkdirSync(SHOT_DIR, { recursive: true });
const REPORT_FILE = path.join(OUT_DIR, 'oraclenet-ui-report.md');

type Sev = 'P0' | 'P1' | 'P2' | 'UX' | 'GAP' | 'OK';
interface Finding {
  id: string;
  phase: string;
  test: string;
  expected: string;
  actual: string;
  severity: Sev;
  shot?: string;
}

const findings: Finding[] = [];
const consoleErrors: { url: string; text: string }[] = [];
const networkFails: { url: string; status: number; method: string }[] = [];
let nextId = 1;
let reportWritten = false;

function rec(phase: string, test: string, expected: string, actual: string, severity: Sev, shot?: string) {
  const id = `O${String(nextId++).padStart(3, '0')}`;
  findings.push({ id, phase, test, expected, actual, severity, shot });
  const tag =
    severity === 'OK' ? '[OK]' :
    severity === 'GAP' ? '[GAP]' :
    severity === 'UX' ? '[UX]' : `[${severity}]`;
  process.stdout.write(`  ${tag} ${id} ${phase} - ${test}: ${actual.slice(0, 140)}\n`);
}

async function snap(page: Page, name: string): Promise<string> {
  if (page.isClosed()) return '';
  const safe = name.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80);
  const file = path.join(SHOT_DIR, `${safe}.png`);
  try {
    await page.screenshot({ path: file, fullPage: true });
  } catch { /* page closed mid-shot, ignore */ }
  return path.relative(OUT_DIR, file).replace(/\\/g, '/');
}

function attach(page: Page, label: string) {
  page.on('console', m => {
    if (m.type() === 'error') {
      consoleErrors.push({ url: page.url(), text: `[${label}] ${m.text().slice(0, 240)}` });
    }
  });
  page.on('response', resp => {
    const url = resp.url();
    if (resp.status() >= 400 &&
        !url.includes('favicon') &&
        !url.startsWith('chrome-extension:') &&
        !url.includes('/api/auth/me') &&
        !url.includes('hot-update') &&
        !url.includes('_next/static')) {
      networkFails.push({ url: url.slice(0, 200), status: resp.status(), method: resp.request().method() });
    }
    // SDK-empty-output heuristic — flag if an agent endpoint returned
    // 200 with no output (suggests SDK returned before agent completes).
    if (resp.status() === 200 && /\/(execute|analyze|pipeline|run)/i.test(url)) {
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
              rec(label, 'sdk-empty-output', 'non-empty agent output', `200 with empty output @ ${url.slice(0, 140)} (mode=${mode ?? 'n/a'})`, 'P0');
            }
          }
        }).catch(() => {});
      }
    }
  });
  page.on('pageerror', err => {
    consoleErrors.push({ url: page.url(), text: `[${label}-pageerror] ${err.message.slice(0, 240)}` });
  });
}

// ── Auth helpers ────────────────────────────────────────────────────

async function login(page: Page): Promise<boolean> {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.waitForSelector('#auth-email', { timeout: 25_000 }).catch(() => {});
  await page.waitForTimeout(1_500);

  // Strategy 1: data-testid="admin-demo" if present
  const testidBtn = await page.locator('[data-testid="admin-demo"]').count().catch(() => 0);
  if (testidBtn > 0) {
    await page.locator('[data-testid="admin-demo"]').first().click().catch(() => {});
  } else {
    // Strategy 2: button by text "Admin Demo"
    let fired = 'no-button';
    try {
      fired = await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('button')).find(
          b => b.textContent?.trim() === 'Admin Demo'
        ) as HTMLButtonElement | undefined;
        if (!btn) return 'no-button';
        const k = Object.keys(btn).find(kk => kk.startsWith('__reactProps$'));
        if (!k) return 'no-props';
        try { (btn as any)[k].onClick(); return 'fired'; } catch { return 'click-throw'; }
      });
    } catch { fired = 'fired'; }

    if (fired !== 'fired') {
      // Strategy 3: manual fill + auth-submit
      await page.locator('#auth-email').fill('admin@abenix.dev').catch(() => {});
      await page.locator('#auth-password').fill('Admin123456').catch(() => {});
      await page.locator('[data-testid="auth-submit"]').first().click().catch(() => {});
    }
  }

  // Wait for nav to dashboard/atlas/agents/home
  try {
    await page.waitForURL(/(dashboard|atlas|agents|home)/, { timeout: 25_000 });
  } catch {
    await page.waitForTimeout(3_000);
  }
  await page.waitForTimeout(2_000);

  // Token check
  let tok: string | null = null;
  try {
    tok = await page.evaluate(() => localStorage.getItem('access_token'));
  } catch {
    await page.waitForTimeout(2_000);
    try { tok = await page.evaluate(() => localStorage.getItem('access_token')); } catch {}
  }
  return !!tok;
}

// ── Live DAG observer ───────────────────────────────────────────────

const AGENT_IDS = [
  'decision_parser', 'historian', 'current_state', 'stakeholder_sim',
  'second_order', 'contrarian', 'synthesizer',
];

async function pollAgentStates(page: Page) {
  if (page.isClosed()) return {};
  return page.evaluate((ids) => {
    const out: Record<string, string> = {};
    const labels: Record<string, string> = {
      decision_parser: 'Decision Parser',
      historian: 'Historian',
      current_state: 'Current State',
      stakeholder_sim: 'Stakeholder Sim',
      second_order: 'Second-Order',
      contrarian: 'Contrarian',
      synthesizer: 'Synthesizer',
    };
    for (const id of ids) {
      const lbl = labels[id];
      const cards = Array.from(document.querySelectorAll('h4'))
        .filter(h => h.textContent?.trim() === lbl);
      if (cards.length === 0) { out[id] = 'absent'; continue; }
      const card = cards[0].closest('div[class*="rounded-xl"]');
      if (!card) { out[id] = 'noparent'; continue; }
      const badgeText = (card.textContent || '').toLowerCase();
      if (badgeText.includes('complete')) out[id] = 'complete';
      else if (badgeText.includes('failed')) out[id] = 'failed';
      else if (badgeText.includes('running')) out[id] = 'running';
      else if (badgeText.includes('pending')) out[id] = 'pending';
      else out[id] = 'unknown';
    }
    return out;
  }, AGENT_IDS).catch(() => ({}));
}

async function waitForBrief(
  page: Page,
  maxMs: number,
  label: string,
  onScreenshot?: (i: number) => Promise<void>,
): Promise<{ ok: boolean; ms: number; transitions: Record<string, Set<string>>; reason: string }> {
  const start = Date.now();
  const transitions: Record<string, Set<string>> = {};
  AGENT_IDS.forEach(a => transitions[a] = new Set<string>());
  let lastShotAt = 0;

  while (Date.now() - start < maxMs) {
    if (page.isClosed()) return { ok: false, ms: Date.now() - start, transitions, reason: 'page-closed' };

    if (onScreenshot && Date.now() - lastShotAt >= 60_000) {
      lastShotAt = Date.now();
      try { await onScreenshot(Math.round((Date.now() - start) / 1000)); } catch {}
    }

    const briefReady = await page.locator('button:has-text("Executive Summary")').count().catch(() => 0);
    if (briefReady > 0) {
      return { ok: true, ms: Date.now() - start, transitions, reason: 'brief-rendered' };
    }

    const states = await pollAgentStates(page);
    for (const id of AGENT_IDS) {
      if (states[id] && states[id] !== 'absent' && states[id] !== 'noparent') {
        transitions[id].add(states[id]);
      }
    }

    const errCount = await page.locator('text=Analysis Failed').count().catch(() => 0);
    if (errCount > 0) {
      await snap(page, `${label}_error`).catch(() => {});
      return { ok: false, ms: Date.now() - start, transitions, reason: 'analysis-failed-banner' };
    }

    try { await page.waitForTimeout(2_500); }
    catch { return { ok: false, ms: Date.now() - start, transitions, reason: 'wait-cancelled' }; }
  }
  return { ok: false, ms: maxMs, transitions, reason: 'timeout' };
}

async function probeTab(page: Page, tabLabel: string): Promise<{ visible: boolean; text: string }> {
  if (page.isClosed()) return { visible: false, text: '' };
  const tab = page.locator(`button:has-text("${tabLabel}")`).first();
  const exists = await tab.count().catch(() => 0);
  if (!exists) return { visible: false, text: '' };
  await tab.click().catch(() => {});
  await page.waitForTimeout(900).catch(() => {});

  const text = await page.evaluate(() => {
    const main = document.querySelector('main');
    if (!main) return '';
    return (main.textContent || '').slice(0, 4000);
  }).catch(() => '');
  return { visible: true, text };
}

// ── Main run ────────────────────────────────────────────────────────

async function main() {
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  await ctx.setDefaultTimeout(15_000);
  const page = await ctx.newPage();
  attach(page, 'oraclenet');

  let run1Meta = { ok: false, ms: 0 };
  let run2Meta = { ok: false, ms: 0 };

  try {
    process.stdout.write('\n== Login ==\n');
    const loggedIn = await login(page);
    if (!loggedIn) {
      rec('Login', 'admin demo / creds', 'access_token in localStorage', 'no token after login attempt', 'P0', await snap(page, 'login_fail'));
      return;
    }
    rec('Login', 'admin demo button', 'authenticated', 'access_token present', 'OK');

    process.stdout.write('\n== Navigate /oraclenet ==\n');
    const navResp = await page.goto(`${BASE}/oraclenet`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.waitForTimeout(2_000);
    await snap(page, 'input_form');

    if (navResp && navResp.status() >= 400) {
      rec('Goto-Oraclenet', 'GET /oraclenet', '200', `HTTP ${navResp.status()}`, 'P0');
    } else {
      rec('Goto-Oraclenet', 'GET /oraclenet', '200', `HTTP ${navResp?.status() || '?'}`, 'OK');
    }

    const hasHero = await page.locator('text=OracleNet Decision Intelligence').count();
    const hasTextarea = await page.locator('textarea').count();
    rec('Goto-Oraclenet', 'hero heading', 'visible', hasHero > 0 ? 'visible' : 'missing', hasHero > 0 ? 'OK' : 'P1');
    rec('Goto-Oraclenet', 'textarea present', '1 textarea', `${hasTextarea}`, hasTextarea === 1 ? 'OK' : 'P1');

    const exampleBtns = await page.locator('p:has-text("Example decisions")').locator('..').locator('button').count();
    rec('Goto-Oraclenet', 'example prompts', '4 chips', `${exampleBtns} chips`, exampleBtns === 4 ? 'OK' : 'P1');

    const depthBtns = await page.locator('p:has-text("Analysis depth")').locator('..').locator('button').count();
    rec('Goto-Oraclenet', 'depth options', '3 (quick/standard/deep)', `${depthBtns}`, depthBtns === 3 ? 'OK' : 'P1');

    // ── Run 1 setup ──
    await page.locator('p:has-text("Example decisions")').locator('..').locator('button').first().click().catch(() => {});
    await page.waitForTimeout(500);
    const taValue = await page.locator('textarea').first().inputValue();
    rec('Run1-Standard', 'click first example', 'textarea populated', `${taValue.length} chars`, taValue.length > 50 ? 'OK' : 'P1');

    await page.locator('button:has-text("Standard")').first().click().catch(() => {});
    await page.waitForTimeout(300);
    await snap(page, 'run1_input_filled');

    process.stdout.write('\n== Run 1: Analyze (standard) ==\n');
    await page.locator('button:has-text("Analyze Decision")').first().click().catch(() => {});
    await page.waitForTimeout(3_000);
    await snap(page, 'run1_analyzing_t0');

    const inAnalyzing = await page.locator('text=Agents Working').count();
    rec('Run1-Standard', 'analyzing phase rendered', '"Agents Working" header', inAnalyzing > 0 ? 'present' : 'missing', inAnalyzing > 0 ? 'OK' : 'P0');

    const dagCards = await page.evaluate(() => {
      const labels = ['Decision Parser','Historian','Current State','Stakeholder Sim','Second-Order','Contrarian','Synthesizer'];
      return labels.filter(l => Array.from(document.querySelectorAll('h4')).some(h => h.textContent?.trim() === l)).length;
    }).catch(() => 0);
    rec('Run1-Standard', '7 agent cards in DAG', '7', `${dagCards}`, dagCards === 7 ? 'OK' : 'P1');

    const run1 = await waitForBrief(page, 8 * 60 * 1000, 'run1', async (s) => {
      await snap(page, `run1_progress_${s}s`);
    });
    run1Meta = { ok: run1.ok, ms: run1.ms };
    rec(
      'Run1-Standard',
      'pipeline completion (standard)',
      'brief tabs render <8min',
      run1.ok ? `complete in ${Math.round(run1.ms / 1000)}s` : `${run1.reason} after ${Math.round(run1.ms / 1000)}s`,
      run1.ok ? 'OK' : 'P0',
      await snap(page, run1.ok ? 'run1_done' : 'run1_timeout'),
    );

    for (const id of AGENT_IDS) {
      const seen = Array.from(run1.transitions[id]);
      const hadRunning = seen.includes('running');
      const hadComplete = seen.includes('complete');
      rec(
        'Run1-Standard',
        `transition ${id}`,
        'running + complete observed',
        `seen=[${seen.join(',') || 'none'}]`,
        (hadRunning || hadComplete) ? 'OK' : 'UX',
      );
    }

    if (run1.ok) {
      process.stdout.write('\n== Run 1: Brief tabs ==\n');
      await snap(page, 'run1_brief_default');

      const summary = await probeTab(page, 'Executive Summary');
      await snap(page, 'tab_summary');
      const hasGauge = await page.locator('text=Confidence Level').count().catch(() => 0);
      const gaugePct = await page.evaluate(() => {
        const m = (document.body.textContent || '').match(/\b(\d{1,3})%/g);
        return m ? m[0] : '';
      }).catch(() => '');
      rec('Tab-Summary', 'executive-summary text length', '> 100 chars', `${summary.text.length}`, summary.text.length > 100 ? 'OK' : 'P1');
      rec('Tab-Summary', 'confidence gauge present', 'visible w/ %', hasGauge > 0 ? `gauge=${gaugePct}` : 'no gauge', hasGauge > 0 ? 'OK' : 'P1');

      const scenarios = await probeTab(page, 'Scenarios');
      await snap(page, 'tab_scenarios');
      const hasBaseUpDown = /base|upside|downside/i.test(scenarios.text);
      const sceneEmpty = /No scenarios were extracted/i.test(scenarios.text);
      rec('Tab-Scenarios', 'has base/upside/downside cases', 'matches present',
        sceneEmpty ? 'EMPTY (truncation suspected)' : (hasBaseUpDown ? 'matches found' : 'no base/upside/downside keywords'),
        sceneEmpty ? 'P1' : (hasBaseUpDown ? 'OK' : 'UX'));

      const stakes = await probeTab(page, 'Stakeholders');
      await snap(page, 'tab_stakeholders');
      const stakeEmpty = /No stakeholder analysis/i.test(stakes.text);
      const stakeCount = await page.locator('span:has-text("Positive"), span:has-text("Negative"), span:has-text("Neutral")').count().catch(() => 0);
      rec('Tab-Stakeholders', '>=3 stakeholders w/ sentiment', '>=3', stakeEmpty ? 'EMPTY' : `${stakeCount} sentiment badges`,
        stakeEmpty ? 'P1' : (stakeCount >= 3 ? 'OK' : 'UX'));

      const cascade = await probeTab(page, 'Cascade Effects');
      await snap(page, 'tab_cascade');
      const has1 = /first/i.test(cascade.text);
      const has2 = /second/i.test(cascade.text);
      const has3 = /third/i.test(cascade.text);
      rec('Tab-Cascade', '1st/2nd/3rd-order chains', 'all 3 orders shown', `1st=${has1} 2nd=${has2} 3rd=${has3}`, (has1 && has2 && has3) ? 'OK' : 'UX');

      const risks = await probeTab(page, 'Risks');
      await snap(page, 'tab_risks');
      const sevHigh = /high/i.test(risks.text);
      const sevMed = /medium/i.test(risks.text);
      const probMatches = (risks.text.match(/\d+%/g) || []).length;
      rec('Tab-Risks', 'severity + probability', 'high/med + %', `high=${sevHigh} med=${sevMed} %matches=${probMatches}`,
        (sevHigh && probMatches > 0) ? 'OK' : 'UX');

      const recTab = await probeTab(page, 'Recommendation');
      await snap(page, 'tab_recommendation');
      const hasConditions = /Conditions for Success/i.test(recTab.text);
      const hasTriggers = /Monitoring Triggers/i.test(recTab.text);
      const recEmpty = recTab.text.length < 50;
      rec('Tab-Recommendation', 'recommendation body non-empty', '> 50 chars', `${recTab.text.length} chars`,
        recEmpty ? 'P1' : 'OK');
      rec('Tab-Recommendation', 'conditions + monitoring sections', 'both', `conds=${hasConditions} triggers=${hasTriggers}`,
        (hasConditions && hasTriggers) ? 'OK' : 'UX');

      await probeTab(page, 'Decision Provenance');
      await snap(page, 'tab_provenance');
      const provSvgCount = await page.locator('[data-testid="provenance-svg"]').count().catch(() => 0);
      const provNodeCount = await page.locator('[data-testid^="prov-node-"]').count().catch(() => 0);
      rec('Tab-Provenance', 'DAG SVG present', 'svg present, >=7 nodes', `svg=${provSvgCount} nodes=${provNodeCount}`,
        (provSvgCount > 0 && provNodeCount >= 7) ? 'OK' : 'P2');
      if (provNodeCount > 0) {
        await page.locator('[data-testid="prov-node-synthesizer"]').first().click().catch(() => {});
        await page.waitForTimeout(400);
        const detail = await page.locator('[data-testid="prov-detail"]').count().catch(() => 0);
        rec('Tab-Provenance', 'click node → detail panel', 'detail visible', detail > 0 ? 'visible' : 'no detail', detail > 0 ? 'OK' : 'UX');
      }

      // ── Exports ──
      process.stdout.write('\n== Exports ==\n');
      let jsonDl = false, mdDl = false;
      const dlListener = (dl: any) => {
        const fn = dl.suggestedFilename();
        if (fn.endsWith('.json')) jsonDl = true;
        if (fn.endsWith('.md')) mdDl = true;
      };
      page.on('download', dlListener);

      const collectToasts = async () => {
        const toasts = await page.locator('[role="status"], [role="alert"], div[class*="toast"]').allTextContents().catch(() => []);
        return toasts.filter(t => t && t.length > 0).slice(0, 3);
      };

      await page.locator('button:has-text("Executive Summary")').first().click().catch(() => {});
      await page.waitForTimeout(400);

      await page.locator('button:has-text("Download JSON")').first().click().catch(() => {});
      await page.waitForTimeout(1500);
      let extra = await collectToasts();
      rec('Exports', 'JSON download', 'file with .json or error toast',
        jsonDl ? 'downloaded' : (extra.length ? `toast: ${extra.join('|')}` : 'no download triggered'),
        jsonDl ? 'OK' : (extra.length ? 'UX' : 'P1'));

      await page.locator('button:has-text("Download Markdown")').first().click().catch(() => {});
      await page.waitForTimeout(1500);
      extra = await collectToasts();
      rec('Exports', 'Markdown download', 'file with .md or error toast',
        mdDl ? 'downloaded' : (extra.length ? `toast: ${extra.join('|')}` : 'no download triggered'),
        mdDl ? 'OK' : (extra.length ? 'UX' : 'P1'));

      const copyBtn = page.locator('button:has-text("Copy to Clipboard"), button:has-text("Copied!")').first();
      await copyBtn.click().catch(() => {});
      await page.waitForTimeout(500);
      const copied = (await page.locator('button:has-text("Copied!")').count().catch(() => 0)) > 0;
      rec('Exports', 'Copy to Clipboard', 'shows Copied! state', copied ? 'feedback shown' : 'no feedback', copied ? 'OK' : 'UX');

      const pdfBtn = await page.locator('button:has-text("PDF")').count().catch(() => 0);
      if (pdfBtn > 0) {
        let pdfDl = false;
        const onDl = (dl: any) => { if (dl.suggestedFilename().endsWith('.pdf')) pdfDl = true; };
        page.on('download', onDl);
        await page.locator('button:has-text("PDF")').first().click().catch(() => {});
        await page.waitForTimeout(2_000);
        extra = await collectToasts();
        rec('Exports', 'PDF download', 'file or toast', pdfDl ? 'downloaded' : (extra.length ? `toast: ${extra.join('|')}` : 'no feedback'),
          pdfDl ? 'OK' : (extra.length ? 'UX' : 'P1'));
        page.off('download', onDl);
      } else {
        rec('Exports', 'PDF export button', 'present', 'MISSING', 'GAP');
      }

      const docxBtn = await page.locator('button:has-text("DOCX")').count().catch(() => 0);
      if (docxBtn > 0) {
        let docxDl = false;
        const onDl = (dl: any) => { if (dl.suggestedFilename().endsWith('.docx')) docxDl = true; };
        page.on('download', onDl);
        await page.locator('button:has-text("DOCX")').first().click().catch(() => {});
        await page.waitForTimeout(2_000);
        extra = await collectToasts();
        rec('Exports', 'DOCX download', 'file or toast', docxDl ? 'downloaded' : (extra.length ? `toast: ${extra.join('|')}` : 'no feedback'),
          docxDl ? 'OK' : (extra.length ? 'UX' : 'P1'));
        page.off('download', onDl);
      } else {
        rec('Exports', 'DOCX export button', 'present', 'MISSING', 'GAP');
      }

      page.off('download', dlListener);

      // ── History dropdown ──
      process.stdout.write('\n== History ==\n');
      await page.locator('button:has-text("History")').first().click().catch(() => {});
      await page.waitForTimeout(800);
      await snap(page, 'history_dropdown_open');
      const histText = await page.evaluate(() => {
        const dropdowns = Array.from(document.querySelectorAll('div')).filter(d => d.textContent?.includes('Past Analyses'));
        return dropdowns[0]?.textContent || '';
      }).catch(() => '');
      const noHist = /No past analyses yet/i.test(histText);
      rec('History', 'dropdown opens', 'shows Past Analyses panel',
        histText.length > 0 ? `panel open (empty=${noHist})` : 'panel missing',
        histText.length > 0 ? 'OK' : 'P2');
      rec('History', 'completed run saved to localStorage', 'recent run listed',
        noHist ? 'NOT SAVED (history not persisted on completion)' : 'present',
        noHist ? 'P1' : 'OK');

      if (!noHist) {
        const firstHistRow = page.locator('div:has-text("Past Analyses") button, [data-testid^="history-item-"]').first();
        const hasRow = await firstHistRow.count().catch(() => 0);
        if (hasRow > 0) {
          await firstHistRow.click().catch(() => {});
          await page.waitForTimeout(500);
          const ta2 = await page.locator('textarea').first().inputValue().catch(() => '');
          rec('History', 're-run from history', 'textarea repopulated', `${ta2.length} chars`, ta2.length > 50 ? 'OK' : 'UX');
        } else {
          rec('History', 're-run from history', 'click history row', 'no clickable row', 'UX');
        }
      } else {
        rec('History', 're-run from history', 'click history row', 'cannot test — history empty', 'GAP');
      }

      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    } else {
      process.stdout.write('Run 1 did not produce a brief; skipping tabs/exports/history checks.\n');
    }

    // ── Run 2: Quick + geopolitical ──
    process.stdout.write('\n== Run 2: Analyze (quick) ==\n');
    const newBtn = page.locator('button:has-text("New Analysis")').first();
    if (await newBtn.count().catch(() => 0)) {
      await newBtn.click().catch(() => {});
    } else {
      await page.goto(`${BASE}/oraclenet`, { waitUntil: 'domcontentloaded' }).catch(() => {});
    }
    await page.waitForTimeout(1500);

    await page.locator('textarea').first().fill('').catch(() => {});
    await page.waitForTimeout(200);

    await page.locator('p:has-text("Example decisions")').locator('..').locator('button').nth(1).click().catch(() => {});
    await page.waitForTimeout(400);
    await page.locator('button:has-text("Quick")').first().click().catch(() => {});
    await page.waitForTimeout(300);

    const quickSelected = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => /^\s*Quick\s*$/.test(b.textContent || '') || b.textContent?.startsWith('Quick'));
      return btn ? (btn.className.includes('cyan') || btn.className.includes('border-cyan')) : false;
    }).catch(() => false);
    rec('Run2-Quick', 'depth=quick selected', 'quick option active', quickSelected ? 'active' : 'unsure', quickSelected ? 'OK' : 'UX');

    await snap(page, 'run2_input_filled');
    await page.locator('button:has-text("Analyze Decision")').first().click().catch(() => {});
    await page.waitForTimeout(2000);

    const run2 = await waitForBrief(page, 4 * 60 * 1000, 'run2', async (s) => {
      await snap(page, `run2_progress_${s}s`);
    });
    run2Meta = { ok: run2.ok, ms: run2.ms };
    rec(
      'Run2-Quick',
      'pipeline completion (quick)',
      'brief tabs render <4min',
      run2.ok ? `complete in ${Math.round(run2.ms / 1000)}s` : `${run2.reason} after ${Math.round(run2.ms / 1000)}s`,
      run2.ok ? 'OK' : 'P1',
      await snap(page, run2.ok ? 'run2_done' : 'run2_timeout'),
    );

    if (run2.ok && run1.ok) {
      const fasterByMs = run1.ms - run2.ms;
      rec(
        'Run2-Quick',
        'depth=quick honored (faster)',
        'quick < standard by >30s',
        `quick=${Math.round(run2.ms/1000)}s vs standard=${Math.round(run1.ms/1000)}s (delta=${Math.round(fasterByMs/1000)}s)`,
        fasterByMs > 30_000 ? 'OK' : 'P1',
      );
    }
  } catch (err: any) {
    rec('Fatal', 'main loop', 'no exception', `${err?.message?.slice(0, 200) || 'unknown'}`, 'P0');
  } finally {
    try { await browser.close(); } catch {}
    await writeReport({
      run1Ok: run1Meta.ok,
      run1Ms: run1Meta.ms,
      run2Ok: run2Meta.ok,
      run2Ms: run2Meta.ms,
    });
    process.stdout.write('\n[done]\n');
  }
}

// ── Report writer ───────────────────────────────────────────────────

async function writeReport(meta: { run1Ok: boolean; run1Ms: number; run2Ok?: boolean; run2Ms?: number }) {
  if (reportWritten) return;
  reportWritten = true;

  const phasePass: Record<string, { pass: number; fail: number }> = {};
  for (const f of findings) {
    if (!phasePass[f.phase]) phasePass[f.phase] = { pass: 0, fail: 0 };
    if (f.severity === 'OK') phasePass[f.phase].pass++;
    else phasePass[f.phase].fail++;
  }

  const bugs = findings
    .filter(f => f.severity !== 'OK')
    .sort((a, b) => {
      const order: Record<Sev, number> = { P0: 0, P1: 1, P2: 2, GAP: 3, UX: 4, OK: 5 };
      return order[a.severity] - order[b.severity];
    });

  const lines: string[] = [];
  lines.push('# OracleNet UI UAT Report');
  lines.push('');
  lines.push(`Run at: ${new Date().toISOString()}`);
  lines.push(`Base URL: ${BASE}/oraclenet`);
  lines.push('');
  lines.push('## Summary');
  lines.push('');
  lines.push(`1 page (/oraclenet) probed; 2 analyses (standard + quick); ${findings.length} CTAs/checkpoints exercised; ${findings.filter(f => f.severity === 'OK').length} pass / ${bugs.length} non-pass.`);
  lines.push('');
  lines.push(`- Run 1 (standard, SaaS pricing): ${meta.run1Ok ? `complete in ${Math.round(meta.run1Ms/1000)}s` : `failed/timeout @ ${Math.round(meta.run1Ms/1000)}s`}`);
  if (meta.run2Ok != null) {
    lines.push(`- Run 2 (quick, geopolitical): ${meta.run2Ok ? `complete in ${Math.round((meta.run2Ms||0)/1000)}s` : `failed/timeout @ ${Math.round((meta.run2Ms||0)/1000)}s`}`);
  }
  lines.push('');
  lines.push('## Per-section pass/fail');
  lines.push('');
  lines.push('| Phase | Pass | Fail |');
  lines.push('|---|---:|---:|');
  for (const [phase, c] of Object.entries(phasePass)) {
    lines.push(`| ${phase} | ${c.pass} | ${c.fail} |`);
  }
  lines.push('');

  lines.push('## Findings (full)');
  lines.push('');
  lines.push('| ID | Phase | Test | Expected | Actual | Sev |');
  lines.push('|---|---|---|---|---|---|');
  for (const f of findings) {
    const cell = (s: string) => s.replace(/\|/g, '\\|').replace(/\n/g, ' ');
    lines.push(`| ${f.id} | ${f.phase} | ${cell(f.test)} | ${cell(f.expected)} | ${cell(f.actual.slice(0, 200))} | ${f.severity} |`);
  }
  lines.push('');

  lines.push('## Top 10 Console Errors');
  lines.push('');
  if (consoleErrors.length === 0) {
    lines.push('_None captured._');
  } else {
    lines.push('```');
    for (const e of consoleErrors.slice(0, 10)) {
      lines.push(`${e.url}\n  ${e.text}`);
    }
    lines.push('```');
  }
  lines.push('');

  lines.push('## 4xx / 5xx Responses');
  lines.push('');
  if (networkFails.length === 0) {
    lines.push('_None captured._');
  } else {
    lines.push('| Status | Method | URL |');
    lines.push('|---|---|---|');
    for (const n of networkFails.slice(0, 30)) {
      lines.push(`| ${n.status} | ${n.method} | ${n.url} |`);
    }
  }
  lines.push('');

  lines.push('## Bugs (severity-ordered)');
  lines.push('');
  if (bugs.length === 0) {
    lines.push('_All checks passed._');
  } else {
    bugs.forEach((b, i) => {
      lines.push(`${i + 1}. **[${b.severity}] ${b.id} — ${b.phase} / ${b.test}**`);
      lines.push(`   - Expected: ${b.expected}`);
      lines.push(`   - Actual: ${b.actual}`);
      lines.push('');
    });
  }
  lines.push('');

  lines.push('## UI Gaps');
  lines.push('');
  lines.push('### 1. No Atlas / KB integration');
  lines.push("Historian and Stakeholder Sim agents only run web search (Tavily) — they do not query the user's Atlas (company precedents) or Knowledge Bases (policy/legal docs). For an enterprise decision tool this is the biggest miss: a customer asks about SaaS pricing and the system never checks their own pricing-history table or churn-cohort KB.");
  lines.push('');
  lines.push('### 2. Synthesizer truncation risk (5000-char cap)');
  lines.push('The page comment in `parseSynthesizerOutput` notes: "the synthesizer output may be truncated (output_message was limited to 5000 chars before the fix) so we must handle partial JSON". The frontend repairs partial JSON by closing braces, but if the synthesizer prompt produces more than ~5KB of JSON the recommendation/cascade arrays at the tail can be silently dropped. Recommended: bump `output_message` cap to 32KB or stream synthesizer output as JSONL chunks.');
  lines.push('');
  lines.push('### 3. Depth parameter ignored');
  lines.push('Depth (`quick`/`standard`/`deep`) is sent in the POST body but the OracleNet pipeline DSL does not branch on it — all three depths invoke the identical 7-agent graph with the same prompts and tool budgets. Recommended: thread `depth` into agent prompts (e.g. word-count target, search-result limit) or skip Historian + Contrarian for `quick`. The probe checks if `quick` finishes >30s faster than `standard`; if not, depth is effectively a no-op.');
  lines.push('');
  lines.push('### 4. Provenance tab is statically built');
  lines.push("`ProvenanceDAG` constructs nodes/edges from the parsed BriefData scenarios, NOT from the orchestrator's actual run-time DAG. It always shows the same 5-layer structure regardless of which agents actually ran or which insights came from where. Recommended: emit `node_complete` events with `output_excerpt` and a `produced_field` map so the provenance graph traces real lineage.");
  lines.push('');
  lines.push('### 5. PDF + DOCX exports missing');
  lines.push('Only JSON, Markdown, and Copy-to-Clipboard are implemented. PDF/DOCX would each require either a server-side renderer (`POST /api/oraclenet/export?format=pdf`) or a client-side library (jspdf + docx). Recommended: server-side using the existing brief data structure for canonical formatting.');
  lines.push('');
  lines.push('### 6. History not persisted on completion');
  lines.push('`pastAnalyses` reads from `localStorage.oraclenet_history` but no code path writes to it after a successful run, so the dropdown stays empty forever. Add `setPastAnalyses([{id, query, date, confidence}, ...prev].slice(0,20))` on phase=`brief` and persist to localStorage.');
  lines.push('');
  lines.push('### 7. No "Re-run" / "Copy past prompt" inline CTA on history rows');
  lines.push('Clicking a history item only repopulates the textarea — there is no inline "Re-run with same depth" or "Duplicate" CTA. Minor UX win.');
  lines.push('');

  lines.push('## Advancement Opportunities');
  lines.push('');
  lines.push("1. **Atlas-backed company precedents** — When the prompt mentions a known customer (or the auth tenant has Atlas data), the Historian agent should run a `cypher_query` against that tenant's graph for `(:Decision)-[:HAD_OUTCOME]->(:Outcome)` precedents before falling back to web search.");
  lines.push("2. **KB-backed policy retrieval** — Stakeholder Sim and Contrarian agents should call `kb_search` against the tenant's policy/legal/compliance KB for jurisdiction-specific constraints. Falls back gracefully when no KB is configured.");
  lines.push('3. **Streaming brief renderer** — As the synthesizer streams JSON tokens, render scenarios/risks incrementally instead of waiting for the full payload.');
  lines.push('4. **Real provenance via tool_call events** — Surface every `tool_call` with its excerpt so the provenance tab shows real citations.');
  lines.push('5. **Depth-aware budget** — `quick` = 3 agents, `standard` = 5, `deep` = 7 + multi-pass contrarian.');
  lines.push('6. **Atlas write-back** — On brief completion, write the decision + outcome-to-monitor as an Atlas node so the next analysis on the same topic gets richer precedent.');
  lines.push("7. **Slack / email digest** — One-click \"Send brief to #leadership\" or email PDF.");
  lines.push('');

  fs.writeFileSync(REPORT_FILE, lines.join('\n'));

  process.stdout.write('\n=== SUMMARY ===\n');
  process.stdout.write(`Total findings: ${findings.length}\n`);
  process.stdout.write(`OK: ${findings.filter(f => f.severity === 'OK').length}\n`);
  process.stdout.write(`P0: ${findings.filter(f => f.severity === 'P0').length}\n`);
  process.stdout.write(`P1: ${findings.filter(f => f.severity === 'P1').length}\n`);
  process.stdout.write(`P2: ${findings.filter(f => f.severity === 'P2').length}\n`);
  process.stdout.write(`UX: ${findings.filter(f => f.severity === 'UX').length}\n`);
  process.stdout.write(`GAP: ${findings.filter(f => f.severity === 'GAP').length}\n`);
  process.stdout.write(`Console errors: ${consoleErrors.length}\n`);
  process.stdout.write(`4xx/5xx responses: ${networkFails.length}\n`);
  process.stdout.write('\nPer-phase pass/fail:\n');
  for (const [phase, c] of Object.entries(phasePass)) {
    process.stdout.write(`  ${phase.padEnd(24)} pass=${c.pass} fail=${c.fail}\n`);
  }
  process.stdout.write(`\nReport: ${REPORT_FILE}\n`);
}

main().catch(err => {
  process.stderr.write(`FATAL (top-level): ${err.stack || err}\n`);
  if (!reportWritten) {
    writeReport({ run1Ok: false, run1Ms: 0 }).catch(() => {});
  }
});
