/**
 * Deep UI UAT for the ClaimsIQ Vaadin app.
 *
 *   Routes:
 *     /              dashboard (hero + "Try sample claim" CTA + recent list)
 *     /fnol          first-notice-of-loss form
 *     /claims        queue grid
 *     /claims/:id    claim detail with status banner + Live DAG
 *     /review        adjuster work queue (routed_to_human)
 *     /review/:id    adjuster decision form
 *     /help          walkthrough
 *
 *   Output:
 *     logs/uat/apps/claimsiq-ui-report.md           full report
 *     logs/uat/apps/claimsiq-screens/<route>.png    one screenshot per view
 *
 *   Run:
 *     npx tsx scripts/uat-claimsiq-ui.ts
 */

import { chromium, type Browser, type BrowserContext, type Page, type ConsoleMessage, type Response } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.CLAIMSIQ_URL || 'http://localhost:3005';
const REPORT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'apps');
const SHOT_DIR = path.join(REPORT_DIR, 'claimsiq-screens');
fs.mkdirSync(SHOT_DIR, { recursive: true });

type RouteResult = { route: string; status: 'pass' | 'fail' | 'partial'; notes: string; screenshot?: string };
type DeepFlowResult = { flow: string; status: 'pass' | 'fail' | 'partial' | 'skip'; ms: number; notes: string };
type Bug = { sev: 'P0' | 'P1' | 'P2' | 'P3'; title: string; details: string };
type ConsoleErr = { route: string; type: string; text: string };
type HttpFail = { route: string; method: string; url: string; status: number };

const routes: RouteResult[] = [];
const flows: DeepFlowResult[] = [];
const bugs: Bug[] = [];
const consoleErrs: ConsoleErr[] = [];
const httpFails: HttpFail[] = [];

const log = (msg: string) => console.log(`[uat-claimsiq] ${msg}`);

async function newPage(ctx: BrowserContext, currentRoute: () => string): Promise<Page> {
  const page = await ctx.newPage();
  page.on('console', (m: ConsoleMessage) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      const raw = m.text();
      // Strip embedded data: URIs from console output (sample photo base64 leaks).
      const cleaned = raw.replace(/data:image\/[^"'\s)]+/g, '<data:img>').slice(0, 300);
      consoleErrs.push({ route: currentRoute(), type: m.type(), text: cleaned });
    }
  });
  page.on('response', (resp: Response) => {
    const s = resp.status();
    if (s >= 400) {
      const u = resp.url();
      // Many of these are base64 photo strings being mis-interpreted
      // as relative URLs — fingerprint that case so it shows up once
      // in the report, not 50 times.
      let safe = u;
      if (u.startsWith('data:')) safe = `data:URI(${u.length}b)`;
      else if (/^https?:\/\/[^/]+\/[A-Za-z0-9+/=]{60,}/.test(u)) safe = `<base64-as-relative-url ${u.length}b>`;
      else safe = u.slice(0, 200);
      httpFails.push({ route: currentRoute(), method: resp.request().method(), url: safe, status: s });
    }
    // SDK-empty-output heuristic — agent endpoint with empty output is
    // most likely the async-mode bug (SDK returned before agent done).
    if (s === 200 && /\/(execute|fnol|claim|adjudicate|pipeline|run)/i.test(resp.url())) {
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
              bugs.push({ sev: 'P0', title: 'SDK potentially returning before agent completes', details: `${resp.url().slice(0, 200)} returned 200 with empty output (mode=${mode ?? 'n/a'})` });
            }
          }
        }).catch(() => {});
      }
    }
  });
  page.on('pageerror', (err) => {
    consoleErrs.push({ route: currentRoute(), type: 'pageerror', text: String(err).slice(0, 400) });
  });
  return page;
}

async function waitVaadinReady(page: Page, timeout = 30000) {
  // Wait for the Vaadin client to bootstrap and stop loading.
  try {
    await page.waitForLoadState('domcontentloaded', { timeout });
    await page.waitForFunction(() => {
      const w: any = window as any;
      const flow = w.Vaadin && w.Vaadin.Flow;
      if (!flow) return false;
      const clients = flow.clients ? Object.values(flow.clients) : [];
      if (clients.length === 0) return true;
      return clients.every((c: any) => typeof c.isActive === 'function' ? !c.isActive() : true);
    }, undefined, { timeout });
    await page.waitForTimeout(400);
  } catch {
    // fall through; we'll still snap a screenshot
  }
}

async function shot(page: Page, name: string): Promise<string> {
  const file = path.join(SHOT_DIR, `${name}.png`);
  try { await page.screenshot({ path: file, fullPage: true }); } catch {}
  return file;
}

// Click button by visible text — pierces Vaadin's light DOM via :light selector.
async function clickByText(page: Page, text: string, timeout = 8000): Promise<boolean> {
  const candidates = [
    `vaadin-button:has-text("${text}")`,
    `button:has-text("${text}")`,
    `text="${text}"`,
  ];
  for (const sel of candidates) {
    try {
      const loc = page.locator(sel).first();
      await loc.waitFor({ state: 'visible', timeout });
      await loc.click({ timeout });
      return true;
    } catch {}
  }
  return false;
}

// ────────────────────────────────────────────────────────────────────
// Route probes
// ────────────────────────────────────────────────────────────────────

async function probeDashboard(ctx: BrowserContext): Promise<{ heroOK: boolean }> {
  let curRoute = '/';
  const page = await newPage(ctx, () => curRoute);
  let heroOK = false;
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await waitVaadinReady(page, 30000);
    const body = await page.textContent('body').catch(() => '');
    const hasHero = !!body && /Run a claim end-to-end/i.test(body);
    const hasCta = !!body && /Try it now/i.test(body);
    const hasFlow = !!body && /Six agents, one decision/i.test(body);
    heroOK = hasHero && hasCta;
    const file = await shot(page, '01-dashboard');
    routes.push({
      route: '/',
      status: heroOK && hasFlow ? 'pass' : 'partial',
      notes: `hero=${hasHero} cta=${hasCta} pipelineCard=${hasFlow}`,
      screenshot: file,
    });
    if (!hasHero) bugs.push({ sev: 'P1', title: 'Dashboard hero card missing', details: 'Expected text "Run a claim end-to-end" not found.' });
    if (!hasCta)  bugs.push({ sev: 'P1', title: 'Dashboard "Try it now" CTA missing', details: 'Expected button "Try it now — sample FNOL + live pipeline" not rendered.' });
  } catch (e: any) {
    routes.push({ route: '/', status: 'fail', notes: `nav error: ${e.message}` });
    bugs.push({ sev: 'P0', title: 'Dashboard failed to load', details: e.message });
  } finally {
    await page.close();
  }
  return { heroOK };
}

async function probeFnolPage(ctx: BrowserContext): Promise<void> {
  let curRoute = '/fnol';
  const page = await newPage(ctx, () => curRoute);
  try {
    await page.goto(`${BASE}/fnol`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const body = await page.textContent('body').catch(() => '');
    const hasForm = !!body && /Claimant name/i.test(body) && /Policy number/i.test(body) && /Describe the loss/i.test(body);
    const hasUpload = await page.locator('vaadin-upload').count() > 0;
    const hasSubmit = !!body && /Submit FNOL/i.test(body);
    const file = await shot(page, '02-fnol-empty');
    routes.push({
      route: '/fnol',
      status: hasForm && hasUpload && hasSubmit ? 'pass' : 'partial',
      notes: `form=${hasForm} upload=${hasUpload} submit=${hasSubmit}`,
      screenshot: file,
    });
    if (!hasUpload) bugs.push({ sev: 'P2', title: 'FNOL upload control missing', details: '<vaadin-upload> not present on /fnol.' });
  } catch (e: any) {
    routes.push({ route: '/fnol', status: 'fail', notes: `nav error: ${e.message}` });
  } finally {
    await page.close();
  }
}

async function probeClaimsList(ctx: BrowserContext): Promise<{ count: number; firstId?: string }> {
  let curRoute = '/claims';
  const page = await newPage(ctx, () => curRoute);
  let count = 0;
  let firstId: string | undefined;
  try {
    await page.goto(`${BASE}/claims`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const hasGrid = await page.locator('vaadin-grid').count() > 0;
    // Count rows via the grid's renderer cells — Vaadin lazy-loads.
    await page.waitForTimeout(1500);
    const rowCount = await page.locator('vaadin-grid >> vaadin-grid-cell-content').count().catch(() => 0);
    count = Math.floor(rowCount / 9); // 9 columns per row
    const file = await shot(page, '03-claims-list');
    routes.push({
      route: '/claims',
      status: hasGrid ? 'pass' : 'fail',
      notes: `grid=${hasGrid} approxRows=${count}`,
      screenshot: file,
    });
    if (!hasGrid) bugs.push({ sev: 'P0', title: '/claims grid did not render', details: '<vaadin-grid> not present on /claims.' });

    // Pull the first claim id from the API to drive the next probe deterministically.
    try {
      const resp = await page.request.get(`${BASE}/api/claimsiq/claims`);
      if (resp.ok()) {
        const j = await resp.json();
        const data = (j && j.data) || [];
        if (data.length > 0) firstId = data[0].id;
      }
    } catch {}
  } catch (e: any) {
    routes.push({ route: '/claims', status: 'fail', notes: `nav error: ${e.message}` });
  } finally {
    await page.close();
  }
  return { count, firstId };
}

async function probeReviewQueue(ctx: BrowserContext): Promise<{ routedId?: string }> {
  let curRoute = '/review';
  const page = await newPage(ctx, () => curRoute);
  let routedId: string | undefined;
  try {
    await page.goto(`${BASE}/review`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const body = await page.textContent('body').catch(() => '');
    const empty = !!body && /No claims awaiting review/i.test(body);
    const hasHeader = !!body && /Adjuster queue/i.test(body);
    const file = await shot(page, '06-review-queue');
    routes.push({
      route: '/review',
      status: hasHeader ? 'pass' : 'partial',
      notes: `header=${hasHeader} empty=${empty}`,
      screenshot: file,
    });

    // Scrape any routed_to_human claim id directly from the API.
    try {
      const resp = await page.request.get(`${BASE}/api/claimsiq/claims`);
      if (resp.ok()) {
        const j = await resp.json();
        const r = ((j && j.data) || []).find((c: any) => c.status === 'routed_to_human');
        if (r) routedId = r.id;
      }
    } catch {}
  } catch (e: any) {
    routes.push({ route: '/review', status: 'fail', notes: `nav error: ${e.message}` });
  } finally {
    await page.close();
  }
  return { routedId };
}

async function probeHelp(ctx: BrowserContext): Promise<void> {
  let curRoute = '/help';
  const page = await newPage(ctx, () => curRoute);
  try {
    await page.goto(`${BASE}/help`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const body = (await page.textContent('body').catch(() => '')) || '';
    const hasContent = body.length > 400;
    const file = await shot(page, '07-help');
    routes.push({
      route: '/help',
      status: hasContent ? 'pass' : 'partial',
      notes: `bodyLen=${body.length}`,
      screenshot: file,
    });
  } catch (e: any) {
    routes.push({ route: '/help', status: 'fail', notes: `nav error: ${e.message}` });
  } finally {
    await page.close();
  }
}

// ────────────────────────────────────────────────────────────────────
// Deep flows
// ────────────────────────────────────────────────────────────────────

async function flowTrySampleClaim(ctx: BrowserContext): Promise<{ id?: string }> {
  const t0 = Date.now();
  let curRoute = '/';
  const page = await newPage(ctx, () => curRoute);
  let id: string | undefined;
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const clicked = await clickByText(page, 'Try it now', 10000);
    if (!clicked) {
      flows.push({ flow: 'Try-Sample-Claim', status: 'fail', ms: Date.now() - t0,
        notes: '"Try it now" CTA could not be clicked' });
      bugs.push({ sev: 'P0', title: 'Dashboard sample-claim CTA dead', details: 'Could not click the "Try it now" button on /'});
      return {};
    }
    // The view navigates to /claims/<id>. Wait for the URL to match.
    try {
      await page.waitForURL(/\/claims\/[0-9a-f-]{36}/i, { timeout: 30000 });
      const url = page.url();
      const m = url.match(/claims\/([0-9a-f-]{36})/i);
      if (m) id = m[1];
      curRoute = `/claims/${id}`;
      await waitVaadinReady(page);
      await shot(page, '04-sample-claim-just-created');
      flows.push({ flow: 'Try-Sample-Claim', status: 'pass', ms: Date.now() - t0,
        notes: `created+navigated id=${id?.slice(0,8)}` });
    } catch {
      flows.push({ flow: 'Try-Sample-Claim', status: 'fail', ms: Date.now() - t0,
        notes: 'never navigated to /claims/<id> after CTA click' });
      bugs.push({ sev: 'P0', title: 'Sample-claim CTA does not navigate',
        details: 'Click fired but /claims/:id never appeared in 30s.' });
    }
  } catch (e: any) {
    flows.push({ flow: 'Try-Sample-Claim', status: 'fail', ms: Date.now() - t0, notes: e.message });
  } finally {
    await page.close();
  }
  return { id };
}

async function flowFnolSubmit(ctx: BrowserContext): Promise<{ id?: string }> {
  const t0 = Date.now();
  let curRoute = '/fnol';
  const page = await newPage(ctx, () => curRoute);
  let id: string | undefined;
  try {
    await page.goto(`${BASE}/fnol`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);

    // Fields are pre-filled with sample text, so editing is optional;
    // overwrite claimant to make sure we're in control.
    const claimant = page.locator('vaadin-text-field').filter({ hasText: 'Claimant' }).first();
    try {
      await claimant.locator('input').fill('UAT Probe Driver');
    } catch {
      // Fallback: just use whatever defaults are pre-filled.
    }

    // Click "Use all 3 sample photos" so the multimodal Damage Assessor has work to do.
    await clickByText(page, 'Use all 3 sample photos', 5000);

    const submitted = await clickByText(page, 'Submit FNOL', 8000);
    if (!submitted) {
      flows.push({ flow: 'FNOL-Submit', status: 'fail', ms: Date.now() - t0, notes: 'submit button not clickable' });
      bugs.push({ sev: 'P0', title: 'FNOL submit button dead', details: 'Could not click "Submit FNOL + run pipeline".' });
      return {};
    }
    try {
      await page.waitForURL(/\/claims\/[0-9a-f-]{36}/i, { timeout: 25000 });
      const url = page.url();
      const m = url.match(/claims\/([0-9a-f-]{36})/i);
      if (m) id = m[1];
      curRoute = `/claims/${id}`;
      await waitVaadinReady(page);
      await shot(page, '05-fnol-submitted');
      flows.push({ flow: 'FNOL-Submit', status: 'pass', ms: Date.now() - t0,
        notes: `created+navigated id=${id?.slice(0,8)}` });
    } catch {
      flows.push({ flow: 'FNOL-Submit', status: 'fail', ms: Date.now() - t0,
        notes: 'never navigated to /claims/<id> after submit' });
      bugs.push({ sev: 'P0', title: 'FNOL submit does not navigate',
        details: '"Submit FNOL" click fired but /claims/:id never loaded.' });
    }
  } catch (e: any) {
    flows.push({ flow: 'FNOL-Submit', status: 'fail', ms: Date.now() - t0, notes: e.message });
  } finally {
    await page.close();
  }
  return { id };
}

async function flowLiveDagWatch(ctx: BrowserContext, claimId: string): Promise<void> {
  // The most critical flow. Poll the API until the claim leaves
  // ingested/running, OR up to 5 minutes. Capture transitions.
  const t0 = Date.now();
  let curRoute = `/claims/${claimId}`;
  const page = await newPage(ctx, () => curRoute);
  const transitions: Array<{ status: string; t: number }> = [];
  let finalStatus = 'unknown';
  let dagRendered = false;
  let bannerSeen = false;
  let citationsSeen = false;
  let letterSeen = false;
  let notesSeen = false;
  let approvedAmt = '';
  try {
    await page.goto(`${BASE}/claims/${claimId}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    await shot(page, `08-claim-${claimId.slice(0,8)}-initial`);

    const deadline = Date.now() + 5 * 60 * 1000;
    let last = '';
    while (Date.now() < deadline) {
      try {
        const resp = await page.request.get(`${BASE}/api/claimsiq/claims/${claimId}`);
        if (resp.ok()) {
          const j = await resp.json();
          const c = (j && j.data) || {};
          const s = c.status || 'unknown';
          if (s !== last) {
            transitions.push({ status: s, t: Date.now() - t0 });
            last = s;
            log(`  claim ${claimId.slice(0,8)} → ${s} @ +${Math.round((Date.now()-t0)/1000)}s`);
          }
          if (c.draftLetter) letterSeen = true;
          if (c.adjusterNotes) notesSeen = true;
          if (c.citationsJson) citationsSeen = true;
          if (typeof c.approvedAmountUsd === 'number') approvedAmt = `$${c.approvedAmountUsd}`;
          finalStatus = s;
          if (['approved','partial','denied','routed_to_human','failed'].includes(s)) break;
        }
      } catch {}
      await page.waitForTimeout(4000);
    }

    // Banner + DAG live-view checks against the rendered DOM.
    try {
      const body = (await page.textContent('body').catch(() => '')) || '';
      bannerSeen = /Pipeline is running|Decision: |Routed to a human|Pipeline failed/i.test(body);
      dagRendered = await page.locator('text=/FNOL Intake|Policy Matcher|Damage Assessor|Fraud Screener|Valuator|Claim Decider/i').count() > 0;
    } catch {}
    await shot(page, `09-claim-${claimId.slice(0,8)}-final`);

    const ok = ['approved','partial','denied','routed_to_human'].includes(finalStatus);
    flows.push({
      flow: 'Live-DAG-Watch',
      status: ok ? 'pass' : (finalStatus === 'failed' ? 'partial' : 'fail'),
      ms: Date.now() - t0,
      notes: `final=${finalStatus} transitions=${transitions.map(t=>t.status).join('→')} letter=${letterSeen} notes=${notesSeen} citations=${citationsSeen} amt=${approvedAmt} dag=${dagRendered} banner=${bannerSeen}`,
    });

    if (transitions.length <= 1 && finalStatus === 'ingested') {
      bugs.push({ sev: 'P0', title: 'Pipeline never started',
        details: `Claim ${claimId.slice(0,8)} sat at ingested for 5 min — runtime not picking up the row.` });
    }
    // Detect the photo-CSV split bug: ClaimDetailView splits photoUrls
    // on "," but data: URIs contain a literal comma after "base64,",
    // so each URI is shredded and the browser fetches the base64 body
    // as a relative URL → 400/INVALID_URL errors in the http-fails table.
    const base64AsRelative = httpFails.filter(h => h.url.startsWith('<base64-as-relative-url')).length;
    if (base64AsRelative > 0) {
      bugs.push({
        sev: 'P1',
        title: 'photoUrls CSV split shreds data: URIs on /claims/:id',
        details: `ClaimDetailView.photoStrip() does csv.split(",") but data:image/png;base64,XXX URIs themselves contain a comma after "base64,". Result: ${base64AsRelative} broken <img src=...> requests on the detail page (status 400, ERR_INVALID_URL). Switch the join/split to a non-comma separator (e.g. "\\n" or a JSON array column).`,
      });
    }
    if (finalStatus === 'failed') {
      bugs.push({ sev: 'P1', title: 'Pipeline failed mid-run',
        details: `Claim ${claimId.slice(0,8)} ended in status=failed.` });
    }
    if (ok && !letterSeen) bugs.push({ sev: 'P1', title: 'Decided claim has no draft letter', details: `Claim ${claimId.slice(0,8)} status=${finalStatus} but draftLetter is empty.` });
    if (ok && !citationsSeen) bugs.push({ sev: 'P2', title: 'Decided claim has no citations', details: `Claim ${claimId.slice(0,8)} status=${finalStatus} but citationsJson is empty.` });
    if (!dagRendered) bugs.push({ sev: 'P2', title: 'Live DAG node labels not rendered', details: 'No node labels (FNOL Intake / Policy Matcher / …) found on detail page after pipeline run.' });

    // Update the route table for /claims/:id while we're here.
    routes.push({
      route: '/claims/:id',
      status: ok && bannerSeen ? 'pass' : (finalStatus === 'ingested' ? 'fail' : 'partial'),
      notes: `final=${finalStatus} banner=${bannerSeen} dag=${dagRendered} letter=${letterSeen}`,
      screenshot: path.join(SHOT_DIR, `09-claim-${claimId.slice(0,8)}-final.png`),
    });
  } catch (e: any) {
    flows.push({ flow: 'Live-DAG-Watch', status: 'fail', ms: Date.now() - t0, notes: e.message });
  } finally {
    await page.close();
  }
}

async function flowAdjusterReview(ctx: BrowserContext, routedId: string | undefined): Promise<void> {
  const t0 = Date.now();
  if (!routedId) {
    flows.push({ flow: 'Adjuster-Review-Decision', status: 'skip', ms: 0,
      notes: 'no routed_to_human claim available — skipped' });
    return;
  }
  let curRoute = `/review/${routedId}`;
  const page = await newPage(ctx, () => curRoute);
  try {
    await page.goto(`${BASE}/review/${routedId}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitVaadinReady(page);
    const body = (await page.textContent('body').catch(() => '')) || '';
    const hasForm = /Your decision/i.test(body) && /Approve in full/i.test(body);
    const hasSummary = /AI reasoning summary/i.test(body);
    await shot(page, `10-review-${routedId.slice(0,8)}`);

    // Fill notes and approve.
    try {
      await page.locator('vaadin-text-area textarea').first().fill('UAT auto-approve, narrative+photos consistent.');
    } catch {}
    const clicked = await clickByText(page, 'Approve in full', 5000);
    if (!clicked) {
      flows.push({ flow: 'Adjuster-Review-Decision', status: 'fail', ms: Date.now() - t0,
        notes: 'approve button not clickable' });
      bugs.push({ sev: 'P0', title: 'Adjuster decision form dead', details: '"Approve in full" not clickable.'});
      return;
    }
    // Verify backend updated.
    await page.waitForTimeout(2000);
    const resp = await page.request.get(`${BASE}/api/claimsiq/claims/${routedId}`);
    let saved = false;
    if (resp.ok()) {
      const j = await resp.json();
      const c = (j && j.data) || {};
      saved = !!c.reviewerDecision;
    }
    flows.push({
      flow: 'Adjuster-Review-Decision',
      status: saved ? 'pass' : 'fail',
      ms: Date.now() - t0,
      notes: `summary=${hasSummary} form=${hasForm} saved=${saved}`,
    });
    routes.push({ route: '/review/:id', status: saved && hasForm ? 'pass' : 'partial',
      notes: `summary=${hasSummary} form=${hasForm} decisionSaved=${saved}` });
    if (!saved) bugs.push({ sev: 'P0', title: 'Adjuster decision not persisting', details: 'POST /review went through UI but reviewerDecision stayed null.'});
  } catch (e: any) {
    flows.push({ flow: 'Adjuster-Review-Decision', status: 'fail', ms: Date.now() - t0, notes: e.message });
  } finally {
    await page.close();
  }
}

// ────────────────────────────────────────────────────────────────────
// Report writer
// ────────────────────────────────────────────────────────────────────

function severityRank(s: Bug['sev']) { return { P0: 0, P1: 1, P2: 2, P3: 3 }[s]; }

function writeReport() {
  const passes = routes.filter(r => r.status === 'pass').length + flows.filter(f => f.status === 'pass').length;
  const fails  = routes.filter(r => r.status === 'fail').length + flows.filter(f => f.status === 'fail').length;
  const broken = bugs.filter(b => b.sev === 'P0').length;

  const lines: string[] = [];
  lines.push(`# ClaimsIQ Deep UI UAT — ${new Date().toISOString()}`);
  lines.push('');
  lines.push(`**Summary:** routes=${routes.length} · CTAs+flows=${flows.length} · passes=${passes} · fails=${fails} · broken(P0)=${broken}`);
  lines.push(`**Base URL:** ${BASE}`);
  lines.push('');

  lines.push('## Routes (Vaadin views)');
  lines.push('');
  lines.push('| Route | Status | Notes |');
  lines.push('|---|---|---|');
  for (const r of routes) {
    lines.push(`| \`${r.route}\` | ${r.status} | ${r.notes.replace(/\|/g,'\\|')} |`);
  }
  lines.push('');

  lines.push('## Deep flows');
  lines.push('');
  lines.push('| Flow | Status | Duration | Notes |');
  lines.push('|---|---|---|---|');
  for (const f of flows) {
    lines.push(`| ${f.flow} | ${f.status} | ${(f.ms/1000).toFixed(1)}s | ${f.notes.replace(/\|/g,'\\|')} |`);
  }
  lines.push('');

  lines.push('### Try-Sample-Claim');
  const f1 = flows.find(f => f.flow === 'Try-Sample-Claim');
  lines.push(f1 ? `- ${f1.status} in ${(f1.ms/1000).toFixed(1)}s — ${f1.notes}` : '- not run');
  lines.push('');
  lines.push('### FNOL-Submit');
  const f2 = flows.find(f => f.flow === 'FNOL-Submit');
  lines.push(f2 ? `- ${f2.status} in ${(f2.ms/1000).toFixed(1)}s — ${f2.notes}` : '- not run');
  lines.push('');
  lines.push('### Live-DAG-Watch (most critical)');
  const f3 = flows.find(f => f.flow === 'Live-DAG-Watch');
  lines.push(f3 ? `- ${f3.status} in ${(f3.ms/1000).toFixed(1)}s — ${f3.notes}` : '- not run');
  lines.push('');
  lines.push('### Adjuster-Review-Decision');
  const f4 = flows.find(f => f.flow === 'Adjuster-Review-Decision');
  lines.push(f4 ? `- ${f4.status} in ${(f4.ms/1000).toFixed(1)}s — ${f4.notes}` : '- not run');
  lines.push('');

  lines.push('## Console errors (top 10)');
  lines.push('');
  if (consoleErrs.length === 0) {
    lines.push('_None._');
  } else {
    lines.push('| # | Route | Type | Text |');
    lines.push('|---|---|---|---|');
    consoleErrs.slice(0, 10).forEach((c, i) => {
      lines.push(`| ${i+1} | \`${c.route}\` | ${c.type} | ${c.text.replace(/\|/g,'\\|').replace(/\n/g,' ')} |`);
    });
  }
  lines.push('');

  lines.push('## 4xx / 5xx responses');
  lines.push('');
  if (httpFails.length === 0) {
    lines.push('_None._');
  } else {
    lines.push('| Route | Method | Status | URL |');
    lines.push('|---|---|---|---|');
    for (const h of httpFails.slice(0, 30)) {
      lines.push(`| \`${h.route}\` | ${h.method} | ${h.status} | ${h.url} |`);
    }
  }
  lines.push('');

  bugs.sort((a, b) => severityRank(a.sev) - severityRank(b.sev));
  lines.push('## Bugs found');
  lines.push('');
  if (bugs.length === 0) {
    lines.push('_No blocking bugs detected._');
  } else {
    bugs.forEach((b, i) => {
      lines.push(`${i+1}. **[${b.sev}] ${b.title}** — ${b.details}`);
    });
  }
  lines.push('');

  lines.push('## UI gaps (known, not bugs but missing)');
  lines.push('');
  lines.push('- **Orphan KB admin** — pipeline cites policy clauses but there is no /admin or /kb route to inspect, edit, or version the underlying policy KB.');
  lines.push('- **No pagination on /claims** — `Grid.setItems(service.listRecent())` loads the full list in memory; no page size or filter controls.');
  lines.push('- **Photos held base64 in JVM heap** — `MultiFileMemoryBuffer` + base64 data URIs persist on the Claim row; large attachments will balloon the heap and the DB row.');
  lines.push('- **No tenant isolation in UI** — `/api/claimsiq/claims` returns every row globally; no per-tenant filter, no auth guard, no `X-Tenant-Id`.');
  lines.push('- **No filters/search on /claims** — claimant name, status, date range filters absent.');
  lines.push('- **No KB citation drilldown** — `citationsJson` rendered as raw `<pre>` JSON; no clickable link back to the policy clause.');
  lines.push('- **Live DAG view is rendered but the SSE retry/reconnect path is invisible** — if the SSE stream drops, the user never sees a "reconnecting…" hint; the page just goes quiet.');
  lines.push('- **No /admin** — sample-photo set, deductible defaults, and decision thresholds are hard-coded in Java.');
  lines.push('');

  fs.writeFileSync(path.join(REPORT_DIR, 'claimsiq-ui-report.md'), lines.join('\n'));
}

// ────────────────────────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────────────────────────

(async () => {
  log(`base=${BASE}`);
  let browser: Browser | undefined;
  try {
    browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

    log('PHASE 1: dashboard');
    const { heroOK } = await probeDashboard(ctx);

    log('PHASE 2: try-sample-claim CTA');
    const { id: sampleId } = heroOK ? await flowTrySampleClaim(ctx) : { id: undefined };

    log('PHASE 3: /fnol page');
    await probeFnolPage(ctx);

    log('PHASE 4: FNOL submit');
    const { id: fnolId } = await flowFnolSubmit(ctx);

    log('PHASE 5: /claims grid');
    const { count, firstId } = await probeClaimsList(ctx);
    log(`  /claims rows ≈ ${count}, first id = ${firstId?.slice(0,8) || '—'}`);

    log('PHASE 6: live DAG watch');
    const watchId = sampleId || fnolId || firstId;
    if (watchId) {
      await flowLiveDagWatch(ctx, watchId);
    } else {
      flows.push({ flow: 'Live-DAG-Watch', status: 'skip', ms: 0, notes: 'no claim id available to watch' });
    }

    log('PHASE 7: review queue');
    const { routedId } = await probeReviewQueue(ctx);

    log('PHASE 8: adjuster decision');
    await flowAdjusterReview(ctx, routedId);

    log('PHASE 9: /help');
    await probeHelp(ctx);
  } catch (e: any) {
    log(`fatal: ${e.message}`);
    bugs.push({ sev: 'P0', title: 'UAT harness fatal error', details: e.message });
  } finally {
    if (browser) await browser.close().catch(() => {});
    writeReport();

    const passes = routes.filter(r => r.status === 'pass').length + flows.filter(f => f.status === 'pass').length;
    const fails  = routes.filter(r => r.status === 'fail').length + flows.filter(f => f.status === 'fail').length;
    console.log('');
    console.log('────────── ClaimsIQ UAT summary ──────────');
    console.log(`routes:        ${routes.length} (pass=${routes.filter(r=>r.status==='pass').length} fail=${routes.filter(r=>r.status==='fail').length})`);
    console.log(`flows:         ${flows.length} (pass=${flows.filter(f=>f.status==='pass').length} fail=${flows.filter(f=>f.status==='fail').length} skip=${flows.filter(f=>f.status==='skip').length})`);
    console.log(`bugs:          P0=${bugs.filter(b=>b.sev==='P0').length} P1=${bugs.filter(b=>b.sev==='P1').length} P2=${bugs.filter(b=>b.sev==='P2').length}`);
    console.log(`console errs:  ${consoleErrs.length}`);
    console.log(`http fails:    ${httpFails.length}`);
    console.log(`report:        ${path.join(REPORT_DIR, 'claimsiq-ui-report.md')}`);
    console.log(`screenshots:   ${SHOT_DIR}`);
    console.log('──────────────────────────────────────────');
    process.exit(fails > 0 || bugs.some(b => b.sev === 'P0') ? 1 : 0);
  }
})();
