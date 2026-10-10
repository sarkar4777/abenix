import { expect, type Browser, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { openFromSidebar } from './sidebar';

// shared by the admin and sharing depth specs, the API is only used to read back and clean up

export const BASE = process.env.BASE || 'http://localhost:3100';
export const API = process.env.API || 'http://localhost:8000';
export const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };

export async function go(page: Page, route: string) {
  // the local port-forward drops for a few seconds when a service rolls, wait it out
  for (let i = 0; ; i++) {
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
      break;
    } catch (e) {
      if (i >= 8 || !/ERR_CONNECTION_REFUSED|ERR_EMPTY_RESPONSE|ERR_CONNECTION_RESET/.test(String(e))) throw e;
      await page.waitForTimeout(5_000);
    }
  }
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

export async function nav(page: Page, href: string) {
  if (!page.url().startsWith(BASE) || page.url().includes('/auth')) await go(page, '/dashboard');
  await openFromSidebar(page, href);
}

export async function signIn(page: Page, who: { email: string; password: string } = ADMIN) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

export async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const h: Record<string, string> = { Authorization: `Bearer ${tok}` };
  if (body !== undefined) h['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, { method, headers: h, data: body === undefined ? undefined : JSON.stringify(body) });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

export function shooter(dir: string) {
  const shots = path.join(dir, 'shots');
  fs.mkdirSync(shots, { recursive: true });
  return async (page: Page, name: string) => {
    await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
  };
}

// no raw traces, JSON dumps or placeholders on a page a person reads
export async function expectReadable(page: Page) {
  const text = await page.locator('main').first().innerText().catch(() => page.locator('body').innerText());
  expect(text).not.toMatch(/Traceback|File "[^"]+", line \d+|\[object Object\]|undefined undefined|\bNaN\b|lorem ipsum/i);
}

// the page fits a phone with nothing sliding sideways
export async function expectFitsPhone(page: Page, label: string) {
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(m.sw, `${label} scrolls sideways at ${m.iw}px`).toBeLessThanOrEqual(m.iw + 1);
}

export async function personContext(browser: Browser, width = 1440) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  const p = await ctx.newPage();
  p.on('dialog', (d) => d.accept());
  return { ctx, p };
}

// invite someone from Settings, Team and have them accept in their own browser
export async function inviteAndAccept(page: Page, browser: Browser, person: { email: string; name: string; password: string }) {
  await nav(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).click();
  await page.getByTestId('invite-email').fill(person.email);
  await page.getByTestId('invite-role').selectOption({ label: 'Member' });
  await page.getByTestId('invite-send').click();
  const link = (await page.getByTestId('invite-link').innerText({ timeout: 20_000 })).trim();
  const { ctx, p } = await personContext(browser);
  await p.goto(link, { waitUntil: 'domcontentloaded' });
  await expect(p.getByTestId('accept-title')).toBeVisible({ timeout: 20_000 });
  await p.locator('#accept-full-name').fill(person.name);
  await p.locator('#accept-password').fill(person.password);
  await p.getByTestId('accept-submit').click();
  await p.waitForURL(/\/dashboard/, { timeout: 30_000 });
  const me = (await api(p, 'GET', '/api/auth/me')).json.data.user;
  return { ctx, p, userId: me.id as string };
}

// a datetime-local value a few minutes ahead, rounded up to the next minute
export function minutesAhead(n: number): { input: string; at: number } {
  const d = new Date(Date.now() + n * 60_000);
  d.setSeconds(0, 0);
  d.setMinutes(d.getMinutes() + 1);
  const pad = (x: number) => String(x).padStart(2, '0');
  return { input: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`, at: d.getTime() };
}

// last assistant message once the chat is idle again
export async function lastReply(page: Page, timeoutMs = 240_000): Promise<string> {
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  await page.waitForTimeout(1000);
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const n = await replies.count();
  return n ? await replies.nth(n - 1).innerText() : '';
}
