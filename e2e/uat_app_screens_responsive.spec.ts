import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// The app pages touched in the SDK and journeys pass, at desktop and phone
// width. Each one must render without an error page or sideways scrolling.
//   USE_K8S=1 npx playwright test e2e/uat_app_screens_responsive.spec.ts

const PV = process.env.PHARMAVIGIL_BASE || 'http://localhost:3007';
const WM = process.env.BASE_WM || 'http://localhost:3006';
const CIQ = process.env.CIQ_BASE || 'http://localhost:3001';
const CIQ_API = process.env.CIQ_API || 'http://localhost:8001';
const SHOTS = path.join('e2e', 'screenshots', 'app-screens');
fs.mkdirSync(SHOTS, { recursive: true });

const WIDTHS = [
  { name: '1440', width: 1440, height: 900 },
  { name: '390', width: 390, height: 844 },
];

async function ciqLogin(page: Page) {
  const r = await fetch(`${CIQ_API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: process.env.CIQ_EMAIL || 'test@contractiq.com', password: process.env.CIQ_PASSWORD || 'TestPass123!' }),
  });
  const token = (await r.json()).data.access_token;
  await page.addInitScript((t: string) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify({ email: 'test@contractiq.com', role: 'analyst' }));
    } catch { /* private mode */ }
  }, token);
}

const PAGES: Array<{ app: string; url: string; ready: RegExp; login?: boolean }> = [
  { app: 'pharmavigil-queue', url: `${PV}/`, ready: /Case queue/ },
  { app: 'pharmavigil-intake', url: `${PV}/cases/new`, ready: /New adverse event report/ },
  { app: 'pharmavigil-signals', url: `${PV}/signals`, ready: /Signal/ },
  { app: 'wingman-mispricing', url: `${WM}/mispricing`, ready: /price at risk/i },
  { app: 'wingman-approvals', url: `${WM}/approvals`, ready: /gate queue/i },
  { app: 'contractiq-chat', url: `${CIQ}/chat`, ready: /Cross-Contract Intelligence/, login: true },
  { app: 'contractiq-data-fabric', url: `${CIQ}/data-fabric`, ready: /Energy Data Fabric/, login: true },
];

for (const w of WIDTHS) {
  for (const p of PAGES) {
    test(`${p.app} at ${w.name}px`, async ({ page }) => {
      await page.setViewportSize({ width: w.width, height: w.height });
      if (p.login) await ciqLogin(page);
      const resp = await page.goto(p.url, { waitUntil: 'domcontentloaded' });
      expect(resp?.status(), `${p.url} HTTP`).toBeLessThan(400);
      await expect(page.getByRole('heading', { name: p.ready }).first()).toBeVisible({ timeout: 30_000 });
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(1200);
      const body = (await page.textContent('body')) || '';
      expect(/Application error|Internal Server Error/i.test(body), 'error page').toBeFalsy();
      await page.screenshot({ path: path.join(SHOTS, `${p.app}-${w.name}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${p.app} scrolls sideways at ${w.name}px`).toBeLessThanOrEqual(1);
    });
  }
}
