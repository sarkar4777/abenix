/**
 * Capture the README's use-case screenshots into docs/screenshots/usecases/.
 *
 * The other shots in that folder were taken by hand, so when ContractIQ and
 * Wingman were written up nobody produced one and those two sections shipped
 * as prose alone. This puts the capture beside the rest of the suite, so the
 * next app has an obvious place to add its own.
 *
 * Each target asserts it is on the page the README paragraph describes. A size
 * floor alone is not enough: the first ContractIQ run bounced to the public
 * marketing page because it was unauthenticated, and produced a perfectly
 * large screenshot of the wrong thing.
 *
 *   npx playwright test e2e/capture_readme_shots.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const OUT = path.join(process.cwd(), 'docs', 'screenshots', 'usecases');
fs.mkdirSync(OUT, { recursive: true });

// The README embeds these at full width, so a wide viewport keeps the text in
// the picture legible rather than reflowed into a narrow layout.
const VIEWPORT = { width: 1680, height: 1050 };

type Target = {
  name: string;
  base: string;
  path: string;
  /** Seed auth before the first navigation, for apps that gate their pages. */
  auth?: (page: Page, base: string) => Promise<void>;
  /** Text that only appears on the intended page. */
  expect: RegExp;
};

async function contractiqAuth(page: Page, base: string) {
  const api = process.env.CIQ_API || 'http://localhost:8001';
  const res = await page.request.post(`${api}/api/contractiq/auth/login`, {
    data: {
      email: process.env.CIQ_EMAIL || 'test@contractiq.com',
      password: process.env.CIQ_PASSWORD || 'TestPass123!',
    },
  });
  expect(res.ok(), 'ContractIQ login failed').toBeTruthy();
  const token = (await res.json())?.data?.access_token;
  expect(token, 'ContractIQ login returned no token').toBeTruthy();

  // Seed the key the app reads before any page script runs.
  await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
}

const TARGETS: Target[] = [
  {
    // "19 agents behind an Insights Hub" — the hub is the claim being made.
    name: 'contractiq-insights',
    base: process.env.CIQ_BASE || 'http://localhost:3001',
    path: '/insights',
    auth: contractiqAuth,
    expect: /insight/i,
  },
  {
    // "pairs a BayesianRidge fair-value model with an IsolationForest anomaly
    // score ... then raises a trade card."
    name: 'wingman-mispricing',
    base: process.env.WM_BASE || 'http://localhost:3006',
    path: '/mispricing',
    expect: /bayesian|isolation forest|price at risk/i,
  },
];

for (const t of TARGETS) {
  test(`capture ${t.name}`, async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    if (t.auth) await t.auth(page, t.base);

    await page.goto(`${t.base}${t.path}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    // These pages fetch through the SDK on mount, so give the agent-backed
    // panels a moment to replace their skeletons before the shutter.
    await page.waitForTimeout(6000);

    const body = (await page.locator('body').innerText()).slice(0, 8000);
    expect(body, `${t.name} is not the page the README describes`).toMatch(t.expect);
    expect(
      page.url(),
      `${t.name} redirected away from ${t.path} — probably unauthenticated`,
    ).toContain(t.path);

    const file = path.join(OUT, `${t.name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(`${t.name}: ${fs.statSync(file).size} bytes  <- ${page.url()}`);
  });
}
