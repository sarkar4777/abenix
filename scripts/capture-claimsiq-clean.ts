/**
 * Capture a clean ClaimsIQ screenshot for the README.
 *
 * Files a fresh sample claim via the dashboard "Try sample claim" CTA, waits
 * for the pipeline to reach a terminal non-failed state (`approved` or
 * `routed_to_human`), then takes a full-page screenshot of the claim detail
 * page where:
 *   - photos render (post-fix codec stores them as JSON array)
 *   - decision pills are populated
 *   - draft letter + adjuster notes are non-empty
 *   - live DAG has paint
 *
 * Saves to docs/screenshots/usecases/claimsiq-final.png (overwrites).
 *
 * Run:  npx tsx scripts/capture-claimsiq-clean.ts
 */

import { chromium } from "playwright";
import path from "path";

const BASE = process.env.CLAIMSIQ_WEB || "http://localhost:3005";
const OUT = path.resolve(
  __dirname,
  "..",
  "docs",
  "screenshots",
  "usecases",
  "claimsiq-final.png",
);
const MAX_WAIT_MS = 5 * 60 * 1000; // 5 min for pipeline to complete

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1800 } });
  const page = await ctx.newPage();

  console.log(`[capture] goto ${BASE}/`);
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  // Click "Try sample claim" — the dashboard hero button.
  console.log(`[capture] click Try sample claim`);
  const tryBtn = page.locator('vaadin-button:has-text("Try it now")').first();
  await tryBtn.click({ timeout: 30_000 });

  // Wait for navigation into /claims/<id>
  await page.waitForURL(/\/claims\/[a-f0-9-]+/i, { timeout: 30_000 });
  const url = page.url();
  const claimId = url.split("/").pop()!;
  console.log(`[capture] navigated to claim ${claimId}`);

  // Poll the page text for a terminal state.
  console.log(`[capture] polling for terminal state (max ${MAX_WAIT_MS / 1000}s)`);
  const start = Date.now();
  let terminal: string | null = null;
  while (Date.now() - start < MAX_WAIT_MS) {
    const txt = await page.locator("body").innerText();
    // Vaadin renders status pills with these labels
    if (/\bapproved\b/i.test(txt) && /\bcomplete\b/i.test(txt)) {
      terminal = "approved";
      break;
    }
    if (/routed[_ ]to[_ ]human/i.test(txt)) {
      terminal = "routed_to_human";
      break;
    }
    if (/\bfailed\b/i.test(txt) && /pipeline tripped/i.test(txt)) {
      terminal = "failed";
      break;
    }
    await page.waitForTimeout(4000);
  }

  if (!terminal) {
    console.error(`[capture] timeout waiting for terminal state`);
    await page.screenshot({ path: OUT, fullPage: true });
    console.log(`[capture] saved partial-state screenshot to ${OUT}`);
    await browser.close();
    process.exit(2);
  }

  console.log(`[capture] terminal state = ${terminal}`);

  // If we got a "failed" claim, retry once with a fresh sample.
  if (terminal === "failed") {
    console.log(`[capture] failed claim — re-trying`);
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    await page.locator('vaadin-button:has-text("Try it now")').first().click();
    await page.waitForURL(/\/claims\/[a-f0-9-]+/i, { timeout: 30_000 });
    const start2 = Date.now();
    while (Date.now() - start2 < MAX_WAIT_MS) {
      const txt = await page.locator("body").innerText();
      if (/\bapproved\b/i.test(txt) && /\bcomplete\b/i.test(txt)) {
        terminal = "approved";
        break;
      }
      if (/routed[_ ]to[_ ]human/i.test(txt)) {
        terminal = "routed_to_human";
        break;
      }
      await page.waitForTimeout(4000);
    }
    console.log(`[capture] retry terminal = ${terminal}`);
  }

  // Settle then full-page shot.
  await page.waitForTimeout(2000);
  await page.screenshot({ path: OUT, fullPage: true });
  console.log(`[capture] saved screenshot (${terminal}) to ${OUT}`);

  await browser.close();
})();
