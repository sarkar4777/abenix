/**
 * Deep UI UAT for the Industrial-IoT showcase.
 *
 *   web : http://localhost:3003
 *   api : http://localhost:8003
 *
 * Drives the live UI through:
 *   - Pump tab        → deploy DSP + RUL + start stream of 10 windows
 *   - Cold Chain tab  → deploy corrector + start shipment + claim draft
 *   - Architecture    → static doc check + /executions external link
 *
 * Records console errors, 4xx/5xx network responses, takes screenshots,
 * and writes logs/uat/apps/industrial-iot-ui-report.md.
 *
 * Run:  npx tsx scripts/uat-industrial-iot-ui.ts
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const WEB = process.env.IIOT_WEB || 'http://localhost:3003';
const API = process.env.IIOT_API || 'http://localhost:8003';

const LOG_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'apps');
const SHOTS_DIR = path.join(LOG_DIR, 'industrial-iot-screens');
fs.mkdirSync(SHOTS_DIR, { recursive: true });

const REPORT_PATH = path.join(LOG_DIR, 'industrial-iot-ui-report.md');

// ── observability ──────────────────────────────────────────────────
interface ConsoleErr { url: string; text: string; tab: string }
interface NetFail    { url: string; status: number; tab: string }
const consoleErrors: ConsoleErr[] = [];
const networkFails:  NetFail[]    = [];

interface Bug { id: number; severity: 'P0'|'P1'|'P2'|'GAP'|'UX'; tab: string; summary: string }
const bugs: Bug[] = [];
let nextBug = 1;
function flag(severity: Bug['severity'], tab: string, summary: string) {
  bugs.push({ id: nextBug++, severity, tab, summary });
  process.stdout.write(`  ! [${severity}] ${tab}: ${summary}\n`);
}

interface Result {
  pump:   { deployDsp: 'pass'|'fail'|'skip'; deployRul: 'pass'|'fail'|'skip'; stream: 'pass'|'fail'|'skip'; severities: Record<string, number>; rulSeen: boolean; workOrderSeen: boolean; windows: number; details: string[] };
  cold:   { deploy: 'pass'|'fail'|'skip'; shipment: 'pass'|'fail'|'skip'; excursionsSeen: boolean; adjudication: boolean; claim: boolean; claimExcerpt: string; details: string[] };
  arch:   { docs: 'pass'|'fail'; executionsLink: string };
  summary: { ctas: number; tabs: number };
}

const result: Result = {
  pump:   { deployDsp: 'skip', deployRul: 'skip', stream: 'skip', severities: {}, rulSeen: false, workOrderSeen: false, windows: 0, details: [] },
  cold:   { deploy: 'skip', shipment: 'skip', excursionsSeen: false, adjudication: false, claim: false, claimExcerpt: '', details: [] },
  arch:   { docs: 'fail', executionsLink: '' },
  summary:{ ctas: 0, tabs: 3 },
};

function attach(page: Page, tab: string) {
  page.on('console', m => {
    if (m.type() === 'error') {
      consoleErrors.push({ url: page.url(), text: m.text().slice(0, 240), tab });
    }
  });
  page.on('response', r => {
    const u = r.url();
    if (r.status() >= 400 && !u.includes('favicon') && !u.startsWith('data:') && !u.startsWith('chrome-extension:')) {
      networkFails.push({ url: u.slice(0, 220), status: r.status(), tab });
    }
    // SDK-empty-output heuristic — flag P0 if an agent endpoint returned
    // 200 with no output (suggests SDK or server fell back to async-mode
    // without polling / waiting; the bug we fixed in Phase A-DEEP).
    if (r.status() === 200 && /\/(execute|run|diagnose|adjudicate|stream)/i.test(u)) {
      const ct = r.headers()['content-type'] || '';
      if (ct.includes('application/json')) {
        r.text().then(t => {
          if (!t || t.length < 4) return;
          let body: any = null;
          try { body = JSON.parse(t); } catch { return; }
          const data = body?.data ?? body;
          if (data && typeof data === 'object') {
            const out = data.output ?? data.output_message ?? data.result;
            const mode = data.mode;
            if ((out === '' || out === null) && (mode === 'async' || data.execution_id)) {
              flag('P0', tab, `SDK potentially returning before agent completes: ${u.slice(0, 140)} (mode=${mode ?? 'n/a'})`);
            }
          }
        }).catch(() => {});
      }
    }
  });
}

async function snap(page: Page, name: string): Promise<string> {
  const f = path.join(SHOTS_DIR, name + '.png');
  await page.screenshot({ path: f, fullPage: true }).catch(() => {});
  return f;
}

// ── core button helpers ────────────────────────────────────────────

async function clickButtonByText(page: Page, text: string|RegExp): Promise<boolean> {
  const btn = page.locator('button', { hasText: text }).first();
  if (await btn.count() === 0) return false;
  await btn.scrollIntoViewIfNeeded().catch(() => {});
  await btn.click({ timeout: 5000 }).catch(async () => { await btn.click({ force: true }).catch(() => {}); });
  return true;
}

/** Wait for a button-with-text to settle into one of the desired
 *  states. We check via textContent. Returns the final text seen. */
async function waitForButtonText(
  page: Page,
  containerLocator: ReturnType<Page['locator']>,
  desired: RegExp,
  timeoutMs: number,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = (await containerLocator.first().textContent().catch(() => '')) ?? '';
    if (desired.test(last)) return last;
    await page.waitForTimeout(2000);
  }
  return last;
}

// ── PUMP tab ───────────────────────────────────────────────────────

async function runPumpTab(page: Page) {
  process.stdout.write('\n[PUMP] starting\n');
  // ensure pump tab is selected — it's the default, but click anyway.
  await clickButtonByText(page, 'Pump Vibration');
  await page.waitForTimeout(800);
  result.summary.ctas++; // tab click

  await snap(page, 'pump-01-pre-deploy');

  // STEP 1 — Deploy Go DSP Asset
  // Anchor on the title <p> (unique), walk up to the flex row that holds the Deploy button.
  // DOM: <div .flex.items-start.gap-2> <p>title</p> <button>Deploy</button> </div>
  const dspBtn = page.locator(
    'p:has-text("Step 1 · Deploy Go DSP Asset") + button, ' +
    'p:has-text("Step 1 · Deploy Go DSP Asset") ~ button'
  ).first();
  const dspInitial = (await dspBtn.textContent().catch(() => '')) ?? '';
  result.pump.details.push(`DSP card initial button: "${dspInitial.trim()}"`);

  if (/Deployed/i.test(dspInitial)) {
    result.pump.deployDsp = 'pass';
    result.pump.details.push('DSP already deployed (existing asset reused).');
  } else {
    result.summary.ctas++;
    await dspBtn.click({ timeout: 5000 }).catch(() => {});
    process.stdout.write('  → clicked DSP Deploy, waiting up to 90s for ready…\n');
    const final = await waitForButtonText(page, dspBtn, /Deployed/i, 90_000);
    if (/Deployed/i.test(final)) {
      result.pump.deployDsp = 'pass';
      result.pump.details.push('DSP deploy reached "Deployed" state.');
    } else {
      result.pump.deployDsp = 'fail';
      result.pump.details.push(`DSP deploy did NOT reach Deployed within 90s — last button text: "${final.trim()}"`);
      flag('P1', 'Pump', 'Go DSP asset did not reach deployed state within 90s (cluster may be slow / probe continued)');
    }
  }

  // STEP 2 — Deploy RUL Estimator
  const rulBtn = page.locator(
    'p:has-text("Step 2 · Deploy RUL Estimator") + button, ' +
    'p:has-text("Step 2 · Deploy RUL Estimator") ~ button'
  ).first();
  const rulInitial = (await rulBtn.textContent().catch(() => '')) ?? '';
  result.pump.details.push(`RUL card initial button: "${rulInitial.trim()}"`);

  if (/Deployed/i.test(rulInitial)) {
    result.pump.deployRul = 'pass';
  } else {
    result.summary.ctas++;
    await rulBtn.click({ timeout: 5000 }).catch(() => {});
    process.stdout.write('  → clicked RUL Deploy, waiting up to 90s…\n');
    const final = await waitForButtonText(page, rulBtn, /Deployed/i, 90_000);
    if (/Deployed/i.test(final)) {
      result.pump.deployRul = 'pass';
      result.pump.details.push('RUL deploy reached "Deployed".');
    } else {
      result.pump.deployRul = 'fail';
      result.pump.details.push(`RUL deploy did NOT reach Deployed within 90s — last "${final.trim()}"`);
      flag('P1', 'Pump', 'RUL estimator asset did not reach deployed state within 90s (probe continued)');
    }
  }

  await snap(page, 'pump-02-post-deploy-both');

  // STEP 3 — Start Stream
  const streamBtn = page.locator('button', { hasText: 'Start Stream' }).first();
  if (await streamBtn.count() === 0) {
    flag('P1', 'Pump', 'Start Stream button not found (deploy probably did not complete; probe continued)');
    result.pump.stream = 'fail';
    return;
  }
  const disabled = await streamBtn.isDisabled().catch(() => false);
  if (disabled) {
    flag('P1', 'Pump', 'Start Stream button is disabled (deploy not ready); skipping stream phase');
    result.pump.stream = 'skip';
    return;
  }
  result.summary.ctas++;
  await streamBtn.click({ timeout: 5000 }).catch(() => {});
  process.stdout.write('  → Stream started, watching window count (10 windows, up to 3 min)…\n');

  // Poll the diagnosis list — each window adds a row with #01..#10.
  const diagSection = page.locator('h4', { hasText: 'Per-window diagnosis' }).locator('..');
  const deadline = Date.now() + 3 * 60 * 1000; // 3 min budget (was 6)
  let windowsSeen = 0;
  let didMidShot = false;
  const seenSeverities = new Set<string>();
  while (Date.now() < deadline) {
    const text = (await diagSection.first().textContent().catch(() => '')) ?? '';
    // Count #NN rows.
    const m = text.match(/#\d{2}/g) ?? [];
    windowsSeen = new Set(m).size;
    // detect severities (NORMAL/WARN/CRITICAL/OK/WATCH)
    for (const s of ['CRITICAL', 'WARN', 'WATCH', 'OK', 'ERR']) {
      if (text.includes(s)) seenSeverities.add(s);
    }
    if (windowsSeen >= 5 && !didMidShot) {
      await snap(page, 'pump-03-mid-stream');
      didMidShot = true;
      process.stdout.write(`  · midstream snapshot taken at ${windowsSeen}/10\n`);
    }
    if (windowsSeen >= 10) break;
    await page.waitForTimeout(3000);
  }

  result.pump.windows = windowsSeen;
  if (windowsSeen >= 10) {
    result.pump.stream = 'pass';
  } else if (windowsSeen > 0) {
    result.pump.stream = 'fail';
    flag('P1', 'Pump', `Stream stalled at ${windowsSeen}/10 windows`);
  } else {
    result.pump.stream = 'fail';
    flag('P0', 'Pump', 'Stream produced 0 windows — pipeline likely failed');
  }

  // collect severity counts by re-reading diagnosis section
  const fullText = (await diagSection.first().textContent().catch(() => '')) ?? '';
  for (const sev of ['NORMAL', 'OK', 'WATCH', 'WARN', 'CRITICAL', 'ERR']) {
    const matches = fullText.match(new RegExp('\\b' + sev + '\\b', 'g'));
    if (matches) result.pump.severities[sev] = matches.length;
  }
  result.pump.rulSeen = /RUL\s*~/.test(fullText);

  // Expand each row briefly to surface work orders
  const rowButtons = await diagSection.locator('button:has-text("#")').all();
  let workOrderHits = 0;
  for (const rb of rowButtons.slice(0, 10)) {
    await rb.click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(150);
    const expandedText = (await diagSection.first().textContent().catch(() => '')) ?? '';
    if (/Work Order Drafted/.test(expandedText)) workOrderHits++;
  }
  result.pump.workOrderSeen = workOrderHits > 0;
  result.pump.details.push(`Work Order rows visible after expansion: ${workOrderHits}`);

  await snap(page, 'pump-04-end-of-stream');
  process.stdout.write(`  ✓ Pump tab finished (windows=${windowsSeen}, severities=${JSON.stringify(result.pump.severities)})\n`);
}

// ── COLD CHAIN tab ─────────────────────────────────────────────────

async function runColdChainTab(page: Page) {
  process.stdout.write('\n[COLD CHAIN] starting\n');
  await clickButtonByText(page, 'Cold Chain');
  result.summary.ctas++;
  await page.waitForTimeout(1500);

  await snap(page, 'cold-01-pre-deploy');

  const deployBtn = page.locator(
    'p:has-text("Step 1 · Deploy Go Cold-Chain Corrector") + button, ' +
    'p:has-text("Step 1 · Deploy Go Cold-Chain Corrector") ~ button'
  ).first();
  const initial = (await deployBtn.textContent().catch(() => '')) ?? '';
  result.cold.details.push(`Corrector card initial: "${initial.trim()}"`);

  if (/Deployed/i.test(initial)) {
    result.cold.deploy = 'pass';
    result.cold.details.push('Cold-chain corrector already deployed.');
  } else {
    result.summary.ctas++;
    await deployBtn.click({ timeout: 5000 }).catch(() => {});
    process.stdout.write('  → clicked Deploy Go Corrector, waiting up to 90s…\n');
    const final = await waitForButtonText(page, deployBtn, /Deployed/i, 90_000);
    if (/Deployed/i.test(final)) {
      result.cold.deploy = 'pass';
    } else {
      result.cold.deploy = 'fail';
      result.cold.details.push(`Corrector did NOT reach Deployed within 90s — last "${final.trim()}"`);
      flag('P1', 'ColdChain', 'Cold-chain corrector did not reach deployed state within 90s (probe continued)');
    }
  }
  await snap(page, 'cold-02-post-deploy');

  const startBtn = page.locator('button', { hasText: 'Start Shipment' }).first();
  if (await startBtn.count() === 0) {
    flag('P1', 'ColdChain', 'Start Shipment button not found (deploy likely not ready); skipping shipment phase');
    result.cold.shipment = 'skip';
    return;
  }
  if (await startBtn.isDisabled().catch(() => false)) {
    flag('P1', 'ColdChain', 'Start Shipment is disabled (deploy not ready); skipping shipment phase');
    result.cold.shipment = 'skip';
    return;
  }
  result.summary.ctas++;
  await startBtn.click({ timeout: 5000 }).catch(() => {});
  process.stdout.write('  → Shipment started, animating waypoints (~4s) then pipeline (up to 2 min)…\n');

  // Mid-shipment screenshot ~5s in (after the raw animation has played a bit).
  await page.waitForTimeout(5000);
  await snap(page, 'cold-03-mid-shipment');

  // Now poll until adjudication card or claim card appears, or budget expires.
  const deadline = Date.now() + 2 * 60 * 1000; // 2 min (was 5)
  let adjuFound = false;
  let claimFound = false;
  let excursionsFound = false;
  let claimText = '';
  while (Date.now() < deadline) {
    const allText = (await page.textContent('body').catch(() => '')) ?? '';
    if (/LLM Adjudication/.test(allText)) adjuFound = true;
    if (/Draft Insurance Claim/.test(allText)) {
      claimFound = true;
      const claimBlock = page.locator('div', { hasText: 'Draft Insurance Claim' }).first();
      claimText = (await claimBlock.textContent().catch(() => '')) ?? '';
    }
    if (/Excursion #/.test(allText)) excursionsFound = true;
    if (claimFound && adjuFound) break;
    await page.waitForTimeout(3000);
  }
  result.cold.adjudication = adjuFound;
  result.cold.claim = claimFound;
  result.cold.excursionsSeen = excursionsFound;
  result.cold.claimExcerpt = claimText.slice(0, 1200);
  result.cold.shipment = (adjuFound || claimFound) ? 'pass' : 'fail';

  if (!adjuFound) flag('P1', 'ColdChain', 'No LLM Adjudication card rendered after waypoint stream');
  if (!claimFound) flag('P1', 'ColdChain', 'No Draft Insurance Claim card rendered (severity may have been LOW/OK)');
  if (!excursionsFound) flag('P2', 'ColdChain', 'No excursion chips rendered — monitor.excursions empty?');

  await snap(page, 'cold-04-end-with-claim');
  process.stdout.write(`  ✓ Cold Chain finished (adju=${adjuFound}, claim=${claimFound}, exc=${excursionsFound})\n`);
}

// ── ARCHITECTURE tab ───────────────────────────────────────────────

async function runArchitectureTab(page: Page) {
  process.stdout.write('\n[ARCH] starting\n');
  await clickButtonByText(page, 'Architecture');
  result.summary.ctas++;
  await page.waitForTimeout(1200);

  const text = (await page.textContent('body').catch(() => '')) ?? '';
  const expectedStages = [
    'Browser', 'API', 'Sandbox (k8s Job)', 'Pipeline', 'LLM', 'Persistence',
  ];
  const missing = expectedStages.filter(s => !text.includes(s));
  if (missing.length === 0) {
    result.arch.docs = 'pass';
  } else {
    flag('P2', 'Architecture', 'Missing stages: ' + missing.join(', '));
  }

  // Check the /executions link rendered in this tab.
  const link = page.locator('a[href="/executions"]').first();
  if (await link.count() > 0) {
    const href = await link.getAttribute('href');
    result.arch.executionsLink = href ?? '';
    // Note: this is a relative link — on the standalone industrial-iot
    // origin (3003), it's a dead link unless routed back to AgentForge.
    flag('GAP', 'Architecture', '/executions link is a relative path and dead-links on the standalone industrial-iot origin (3003) — should point to AgentForge web origin (3000)');
  } else {
    flag('P2', 'Architecture', '/executions link not found');
  }

  await snap(page, 'arch-01-static');
  process.stdout.write(`  ✓ Arch finished (missing stages: ${missing.length})\n`);
}

// ── REPORT WRITER ──────────────────────────────────────────────────

function topConsoleErrors(): ConsoleErr[] {
  // De-dup by text first 120 chars, keep first 10.
  const seen = new Set<string>();
  const out: ConsoleErr[] = [];
  for (const e of consoleErrors) {
    const k = e.text.slice(0, 120);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(e);
    if (out.length >= 10) break;
  }
  return out;
}

function writeReport() {
  const passes = [
    result.pump.deployDsp === 'pass',
    result.pump.deployRul === 'pass',
    result.pump.stream === 'pass',
    result.cold.deploy === 'pass',
    result.cold.shipment === 'pass',
    result.arch.docs === 'pass',
  ];
  const passCount = passes.filter(Boolean).length;
  const totalChecks = passes.length;

  const md: string[] = [];
  md.push('# Industrial IoT — Deep UI UAT Report');
  md.push('');
  md.push(`Run: ${new Date().toISOString()}  ·  WEB=${WEB}  API=${API}`);
  md.push('');
  md.push('## Summary');
  md.push('');
  md.push(`- **Tabs probed**: ${result.summary.tabs} (Pump, Cold Chain, Architecture)`);
  md.push(`- **CTAs exercised**: ${result.summary.ctas}`);
  md.push(`- **Deep flows**: 2 (Pump 10-window stream · Cold-chain SFO→LAX shipment)`);
  md.push(`- **Pass / Fail**: **${passCount} / ${totalChecks}** core checks passed`);
  md.push(`- **Bugs surfaced**: ${bugs.length}`);
  md.push(`- **Console errors**: ${consoleErrors.length} (top 10 below)`);
  md.push(`- **4xx/5xx network failures**: ${networkFails.length}`);
  md.push('');
  md.push('## Per-tab results');
  md.push('');

  // PUMP
  md.push('### Pump Vibration');
  md.push('');
  md.push(`- Deploy Go DSP Asset: **${result.pump.deployDsp.toUpperCase()}**`);
  md.push(`- Deploy RUL Estimator: **${result.pump.deployRul.toUpperCase()}**`);
  md.push(`- Stream 10 windows: **${result.pump.stream.toUpperCase()}** (${result.pump.windows}/10 windows)`);
  md.push(`- Severity counts seen: \`${JSON.stringify(result.pump.severities)}\``);
  md.push(`- RUL estimate rendered: ${result.pump.rulSeen ? 'yes' : 'no'}`);
  md.push(`- Work order drafted: ${result.pump.workOrderSeen ? 'yes' : 'no'}`);
  md.push('');
  md.push('Detail log:');
  for (const d of result.pump.details) md.push(`- ${d}`);
  md.push('');
  md.push('Screenshots:');
  for (const name of ['pump-01-pre-deploy', 'pump-02-post-deploy-both', 'pump-03-mid-stream', 'pump-04-end-of-stream']) {
    const exists = fs.existsSync(path.join(SHOTS_DIR, name + '.png'));
    md.push(`- ${exists ? '' : '_(not captured)_ '}\`industrial-iot-screens/${name}.png\``);
  }
  md.push('');

  // COLD
  md.push('### Cold Chain');
  md.push('');
  md.push(`- Deploy Go Corrector: **${result.cold.deploy.toUpperCase()}**`);
  md.push(`- Shipment SFO→LAX (20 waypoints + pipeline): **${result.cold.shipment.toUpperCase()}**`);
  md.push(`- Excursion chips visible: ${result.cold.excursionsSeen ? 'yes' : 'no'}`);
  md.push(`- LLM Adjudication card: ${result.cold.adjudication ? 'yes' : 'no'}`);
  md.push(`- Insurance claim drafted: ${result.cold.claim ? 'yes' : 'no'}`);
  if (result.cold.claimExcerpt) {
    md.push('');
    md.push('Claim excerpt:');
    md.push('```');
    md.push(result.cold.claimExcerpt);
    md.push('```');
  }
  md.push('');
  md.push('Detail log:');
  for (const d of result.cold.details) md.push(`- ${d}`);
  md.push('');
  md.push('Screenshots:');
  for (const name of ['cold-01-pre-deploy', 'cold-02-post-deploy', 'cold-03-mid-shipment', 'cold-04-end-with-claim']) {
    const exists = fs.existsSync(path.join(SHOTS_DIR, name + '.png'));
    md.push(`- ${exists ? '' : '_(not captured)_ '}\`industrial-iot-screens/${name}.png\``);
  }
  md.push('');

  // ARCH
  md.push('### Architecture');
  md.push('');
  md.push(`- Static stages render: **${result.arch.docs.toUpperCase()}**`);
  md.push(`- /executions link: \`${result.arch.executionsLink || '(missing)'}\` (relative — dead-links on origin 3003 unless routed)`);
  md.push('');
  md.push('Screenshot: `industrial-iot-screens/arch-01-static.png`');
  md.push('');

  md.push('## Top 10 console errors');
  md.push('');
  const top = topConsoleErrors();
  if (top.length === 0) md.push('_No console errors captured._');
  else {
    md.push('| # | Tab | Text | URL |');
    md.push('|---|-----|------|-----|');
    top.forEach((e, i) =>
      md.push(`| ${i + 1} | ${e.tab} | ${e.text.replace(/\|/g, '\\|').slice(0, 140)} | \`${e.url.slice(0, 80)}\` |`));
  }
  md.push('');

  md.push('## 4xx / 5xx network failures');
  md.push('');
  if (networkFails.length === 0) md.push('_No network failures captured._');
  else {
    md.push('| Status | Tab | URL |');
    md.push('|--------|-----|-----|');
    const seen = new Set<string>();
    for (const n of networkFails) {
      const k = `${n.status}|${n.url}`;
      if (seen.has(k)) continue;
      seen.add(k);
      md.push(`| ${n.status} | ${n.tab} | \`${n.url}\` |`);
    }
  }
  md.push('');

  md.push('## Bugs found');
  md.push('');
  if (bugs.length === 0) md.push('_No bugs surfaced._');
  else {
    bugs.forEach(b => md.push(`${b.id}. **[${b.severity}]** _${b.tab}_ — ${b.summary}`));
  }
  md.push('');

  md.push('## UI gaps & advancement opportunities');
  md.push('');
  md.push('- **No KB-availability indicator.** Docs note that without a KB, the claim-draft falls back to "standard terms." The UI surfaces zero signal about whether `knowledge_search` returned hits or fell through. Add a small badge ("KB cited: ISO 10816-3" / "KB unavailable — fallback to standard terms") on both the diagnosis and claim cards so the operator knows whether retrieval grounded the LLM.');
  md.push('- **No pump fleet picker.** Pump tab is pinned to a single synthetic sensor (`Plant 3 / Cooling A`). For a real demo you would expect a drop-down of pump assets, RPM, sample-rate; currently the operator can\'t pivot scenarios without code changes.');
  md.push('- **No product-spec selection for cold chain.** Hard-wired to insulin 2–8°C. Adding a spec picker (vaccine 2–8°C, frozen plasma –30 to –20°C, fresh produce 0–4°C) would showcase the platform\'s "change one prompt, repurpose" claim from the right-rail explainer.');
  md.push('- **`/executions` is a relative link.** On the standalone industrial-iot origin (port 3003) it 404s — should be an absolute link to the AgentForge web origin (3000) or open in a new tab with the right origin baked in.');
  md.push('- **No reset / re-run button.** After a stream finishes, there is no way to clear the diagnosis list and re-run without a full page refresh.');
  md.push('- **Stream Stop is the only mid-flight control.** No skip / pause / step-through. Useful for demos; today the user must wait or abort completely.');
  md.push('- **No exec ID surfaced inline.** The deep-flow log shows window numbers but never links out to `/executions/<id>` for the underlying pipeline runs — defeats the audit-trail story called out in the explainer.');
  md.push('- **Per-window details are buried behind a click.** All RMS/peak/crest/kurtosis/fault-scores live inside an expander; a "show all metrics" toggle or sparkline-per-row would convey the trajectory at a glance.');
  md.push('- **Cold-chain "raw vs smoothed" chart is missing units on Y-axis on initial render** until smoothing arrives — minor polish gap.');
  md.push('- **Asset list is global, not tagged.** Re-deploys produce `pump-dsp-correction-2`/`-3` over time; the UI does not surface a "newer version available" hint.');
  md.push('');

  fs.writeFileSync(REPORT_PATH, md.join('\n'));
}

// ── MAIN ───────────────────────────────────────────────────────────

async function main() {
  process.stdout.write(`Industrial-IoT UAT — web=${WEB}\n`);
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx: BrowserContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  attach(page, 'init');
  page.setDefaultTimeout(15_000);

  try {
    const resp = await page.goto(WEB + '/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    if (!resp || !resp.ok()) {
      flag('P0', 'init', `Landing page returned ${resp?.status() ?? '(no resp)'} — aborting`);
      throw new Error('landing failed');
    }
    // Brief settle.
    await page.waitForTimeout(1500);
    // No login is required on the standalone industrial-iot app —
    // verified from page.tsx (no auth gate).

    // Re-tag listener per-tab so report attributes errors correctly.
    const setTab = (t: string) => {
      page.removeAllListeners('console');
      page.removeAllListeners('response');
      attach(page, t);
    };

    setTab('pump');
    await runPumpTab(page);

    setTab('cold');
    await runColdChainTab(page);

    setTab('arch');
    await runArchitectureTab(page);
  } catch (err) {
    process.stdout.write(`FATAL: ${(err as Error).message}\n`);
    flag('P0', 'init', `fatal in run: ${(err as Error).message}`);
  } finally {
    writeReport();
    await ctx.close().catch(() => {});
    await browser.close().catch(() => {});
  }

  // Stdout summary
  process.stdout.write('\n========== SUMMARY ==========\n');
  process.stdout.write(`Pump:   deployDsp=${result.pump.deployDsp}, deployRul=${result.pump.deployRul}, stream=${result.pump.stream} (${result.pump.windows}/10), severities=${JSON.stringify(result.pump.severities)}, rul=${result.pump.rulSeen}, workOrder=${result.pump.workOrderSeen}\n`);
  process.stdout.write(`Cold:   deploy=${result.cold.deploy}, shipment=${result.cold.shipment}, excursions=${result.cold.excursionsSeen}, adju=${result.cold.adjudication}, claim=${result.cold.claim}\n`);
  process.stdout.write(`Arch:   docs=${result.arch.docs}, executionsLink=${result.arch.executionsLink}\n`);
  process.stdout.write(`Bugs: ${bugs.length}, console errors: ${consoleErrors.length}, network 4xx/5xx: ${networkFails.length}\n`);
  process.stdout.write(`Report: ${REPORT_PATH}\n`);
  process.stdout.write(`Screens: ${SHOTS_DIR}\n`);
}

main().catch(e => { process.stderr.write(String(e) + '\n'); process.exit(1); });
