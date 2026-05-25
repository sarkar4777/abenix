import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
  return tok;
}

test('MCP: page renders, shows registry + connect controls, drives add-from-registry', async ({ page }) => {
  const tok = await login(page);
  await page.goto(`${BASE}/mcp`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3500);

  const text = (await page.locator('body').innerText()).toLowerCase();
  expect(text).toMatch(/mcp|model context/);
  expect(text).toMatch(/registry|servers/);

  const tabs = await page.locator('[role="tab"], button', { hasText: /registry|servers|resources|prompts/i }).count();
  console.log(`MCP tabs visible: ${tabs}`);
  expect(tabs).toBeGreaterThan(2);

  const registryTab = page.locator('[role="tab"], button', { hasText: /^Registry$/i }).first();
  if (await registryTab.count()) {
    await registryTab.click();
    await page.waitForTimeout(1500);
  }
  const installBtns = await page.locator('button:has-text("Install"), button:has-text("Connect")').count();
  console.log(`MCP install buttons: ${installBtns}`);
  await page.screenshot({ path: 'test-results/uat-mcp-page.png', fullPage: true });

  expect(installBtns).toBeGreaterThan(0);
});

test('Integrations page: MCP link card + setup expand + admin badge', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/integrations`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  const text = (await page.locator('body').innerText());
  expect(text.toLowerCase()).toMatch(/mcp servers|model context|runtime tool/i);
  expect(text).toMatch(/Admin/i);

  const setupBtns = await page.locator('button', { hasText: /^Setup$/i }).count();
  console.log(`Setup buttons: ${setupBtns}`);
  expect(setupBtns).toBeGreaterThan(5);

  const firstSetup = page.locator('button', { hasText: /^Setup$/i }).first();
  await firstSetup.click();
  await page.waitForTimeout(1000);

  const expandedText = (await page.locator('body').innerText()).toLowerCase();
  expect(expandedText).toMatch(/local dev|shell export|.env file|kubernetes|helm/i);
  expect(expandedText).toMatch(/kubectl|export /);

  const copyBtns = await page.locator('button', { hasText: /^Copy$|✓ copied/i }).count();
  console.log(`Copy buttons in expanded view: ${copyBtns}`);
  expect(copyBtns).toBeGreaterThanOrEqual(3);

  await page.screenshot({ path: 'test-results/uat-integrations-setup-expanded.png', fullPage: true });
});
