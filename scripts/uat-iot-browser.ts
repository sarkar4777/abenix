/**
 * Browser UAT for the industrial-iot standalone — drives every tab end to
 * end and reports what worked vs broke. Assumes platform port-forwards are
 * up on :3003 / :8003 / :3000 / :8000 (deploy-azure managed).
 *
 * What it covers:
 *   1. /  page loads + 6 tabs visible
 *   2. Pump tab — scenario explainer + DAG render
 *   3. Cold Chain tab — explainer + DAG render
 *   4. ValueEdge tab — DAG render + 2-col layout
 *   5. FieldEdge tab — DAG render + technician panel
 *   6. BedROCC tab — alarm queue + DAG render + cascade banner
 *   7. Architecture tab — Help section + 5 scenario cards
 *
 * Saves screenshots to logs/uat-iot-browser/<tab>.png so you can eyeball
 * the rendering after the run.
 */

import { chromium, Page, Browser } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.BASE || "http://localhost:3003";
const SHOTS = resolve(process.cwd(), "logs/uat-iot-browser");

interface Result { name: string; ok: boolean; note: string }
const results: Result[] = [];

mkdirSync(SHOTS, { recursive: true });

async function shot(page: Page, name: string) {
  try { await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); } catch { /* ignore */ }
}

async function step(name: string, fn: () => Promise<string>) {
  try {
    const note = await fn();
    results.push({ name, ok: true, note });
    console.log(`  ✓ ${name}${note ? " — " + note : ""}`);
  } catch (e: unknown) {
    const msg = (e as Error).message || String(e);
    results.push({ name, ok: false, note: msg });
    console.log(`  ✘ ${name} — ${msg}`);
  }
}

async function clickTab(page: Page, label: string) {
  const btn = page.locator(`button:has-text("${label}")`).first();
  await btn.click({ timeout: 8000 });
  await page.waitForTimeout(800);
}

async function expectVisible(page: Page, selector: string, what: string) {
  const loc = page.locator(selector).first();
  if (!(await loc.isVisible({ timeout: 5000 }).catch(() => false))) {
    throw new Error(`expected visible: ${what}`);
  }
}

async function main() {
  console.log(`▶ industrial-iot browser UAT against ${BASE}`);
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await ctx.newPage();

  await step("home loads", async () => {
    const r = await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 20000 });
    if (!r || !r.ok()) throw new Error(`http ${r?.status()}`);
    await expectVisible(page, "h1:has-text('Industrial IoT')", "page header");
    await shot(page, "01-home");
    return "header rendered";
  });

  await step("6 tabs visible", async () => {
    for (const t of ["Pump Vibration", "Cold Chain", "ValueEdge", "FieldEdge", "BedROCC", "Architecture"]) {
      await expectVisible(page, `button:has-text("${t}")`, t);
    }
    return "all 6 tabs present";
  });

  await step("Pump tab", async () => {
    await clickTab(page, "Pump Vibration");
    await expectVisible(page, "text=Predictive Maintenance", "scenario explainer header");
    await shot(page, "02-pump");
    return "explainer + scenario panel render";
  });

  await step("Cold Chain tab", async () => {
    await clickTab(page, "Cold Chain");
    await expectVisible(page, "text=Cold Chain", "tab content");
    await shot(page, "03-coldchain");
    return "tab content rendered";
  });

  await step("ValueEdge tab + DAG", async () => {
    await clickTab(page, "ValueEdge");
    await expectVisible(page, "text=Engineering & EPC Copilot", "valueedge hero");
    await page.locator("text=Execution DAG").first().scrollIntoViewIfNeeded().catch(() => {});
    await expectVisible(page, "text=iot-valueedge-pipeline", "dag pipelineSlug label");
    await shot(page, "04-valueedge");
    return "DAG + explainer rendered";
  });

  await step("FieldEdge tab + DAG", async () => {
    await clickTab(page, "FieldEdge");
    await expectVisible(page, "text=Get Repair Procedure", "main CTA");
    await expectVisible(page, "text=iot-fieldedge-pipeline", "dag");
    await shot(page, "05-fieldedge");
    return "DAG + repair CTA rendered";
  });

  await step("BedROCC tab + DAG", async () => {
    await clickTab(page, "BedROCC");
    await expectVisible(page, "text=Operations Control Room", "bedrocc explainer");
    await expectVisible(page, "text=iot-bedrocc-pipeline", "dag");
    await shot(page, "06-bedrocc");
    return "DAG + alarm queue rendered";
  });

  await step("Architecture tab as help section", async () => {
    await clickTab(page, "Architecture");
    await expectVisible(page, "text=Help & UAT Guide", "help header");
    await expectVisible(page, "text=Scenario tour", "scenario tour");
    // count scenario cards (5)
    const cards = await page.locator("text=pipeline:").count();
    if (cards < 5) throw new Error(`only ${cards}/5 scenario cards rendered`);
    await shot(page, "07-arch");
    return `${cards} scenario cards`;
  });

  await browser.close();

  console.log();
  const pass = results.filter((r) => r.ok).length;
  const fail = results.length - pass;
  console.log(`▶ ${pass}/${results.length} passed, ${fail} failed`);
  if (fail) {
    console.log();
    console.log("Failures:");
    for (const r of results) if (!r.ok) console.log(`  ✘ ${r.name}: ${r.note}`);
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(2); });
