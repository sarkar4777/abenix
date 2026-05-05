/**
 * Browser smoke for the v1.1.0 admin pages.
 *
 * Hits each new page after JWT-via-localStorage login + asserts
 * the page paints content with the expected key terms. Less strict
 * than the playwright spec — we just want "page renders, no errors,
 * recognisable copy on screen."
 */
import { chromium, type Page } from "playwright";

const BASE = process.env.BASE || "http://localhost:3000";
const API = process.env.API || "http://localhost:8000";
const EMAIL = process.env.AF_EMAIL || "admin@abenix.dev";
const PASSWORD = process.env.AF_PASSWORD || "Admin123456";

let pass = 0;
let fail = 0;

const ok = (label: string) => {
  pass++;
  console.log(`  ✓ ${label}`);
};
const ko = (label: string, reason: string) => {
  fail++;
  console.log(`  ✗ ${label} — ${reason}`);
};

async function login(page: Page) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login HTTP ${r.status}`);
  const j: any = await r.json();
  const token = j.data.access_token;
  const me = j.data.user;
  await page.addInitScript(
    ({ t, u }: { t: string; u: any }) => {
      localStorage.setItem("access_token", t);
      localStorage.setItem("token", t);
      localStorage.setItem("auth_token", t);
      localStorage.setItem("user", JSON.stringify(u));
    },
    { t: token, u: me },
  );
}

async function visit(page: Page, path: string, label: string, want: RegExp[]) {
  try {
    const r = await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    if (!r || r.status() >= 400) {
      ko(label, `HTTP ${r?.status() ?? "?"}`);
      return;
    }
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.locator("h1, h2").first().waitFor({ timeout: 8_000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const body = await page.evaluate(() => document.body.innerText);
    const missing = want.filter((re) => !re.test(body));
    if (missing.length === 0) ok(label);
    else ko(label, `missing copy: ${missing.map((re) => re.source).join(", ")} | head: ${body.slice(0, 200).replace(/\s+/g, " ")}`);
  } catch (e: any) {
    ko(label, e.message || String(e));
  }
}

async function main() {
  console.log(`v1.1.0 admin smoke against ${BASE}`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await login(page);

  await visit(page, "/admin/connectors", "/admin/connectors page", [/connector/i]);
  await visit(page, "/approvals", "/approvals page", [/approval/i]);
  await visit(page, "/admin/dlq", "/admin/dlq page", [/dlq|dead.?letter|failed/i]);
  await visit(page, "/edge", "/edge page", [/edge|gateway|bundle/i]);
  await visit(page, "/settings/integrations", "/settings/integrations page", [
    /integrations/i,
    /anthropic|llm provider/i,
  ]);

  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
