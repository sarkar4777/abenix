/**
 * The in-platform help surfaces have to work, not just exist.
 *
 * /help is the operator guide and /docs the developer guide. The developer
 * guide is a manifest-driven viewer over a copy of docs/ under public/, so it
 * can drift two ways: a nav entry whose file was never synced 404s, and a doc
 * that exists but is absent from the manifest is unreachable. Both had
 * happened — the mirror was six files behind and ten docs were missing from
 * the nav.
 *
 * Run: BASE=http://localhost:3000 npx playwright test e2e/uat_help_surfaces.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASS = process.env.AF_PASSWORD || 'Admin123456';

async function signIn(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASS },
  });
  const token = (await r.json()).data.access_token;
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
}

test('help: every topic renders body copy, none are empty shells', async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page);
  await page.goto(`${BASE}/help`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2500);

  const text = (await page.textContent('main')) || (await page.textContent('body')) || '';
  expect(text.length, '/help looks blank').toBeGreaterThan(2000);

  // The topics an operator reaches for. Each was checked against the page.
  for (const phrase of [
    /flight recorder/i,
    /tool catalog|tools reference/i,
    /knowledge base/i,
    /pipeline/i,
    /scaling/i,
    /approval/i,
  ]) {
    expect(text, `help covers ${phrase}`).toMatch(phrase);
  }
});

test('docs: the manifest and the served files agree', async ({ page, request }) => {
  test.setTimeout(240_000);

  const man = await request.get(`${BASE}/dev-docs/manifest.json`);
  expect(man.status(), 'manifest served').toBe(200);
  const sections = (await man.json()).sections as Array<{
    id: string; title: string; docs: Array<{ slug: string; title: string }>;
  }>;
  const slugs = sections.flatMap((s) => s.docs.map((d) => d.slug));
  console.log(`  ${sections.length} sections, ${slugs.length} docs`);
  expect(slugs.length, 'manifest has docs').toBeGreaterThan(20);

  // Every nav entry must resolve to a real file with real content.
  const broken: string[] = [];
  const thin: string[] = [];
  for (const slug of slugs) {
    const r = await request.get(`${BASE}/dev-docs/${slug}.md`);
    if (r.status() !== 200) {
      broken.push(`${slug} -> HTTP ${r.status()}`);
      continue;
    }
    const body = await r.text();
    if (body.trim().length < 200) thin.push(`${slug} (${body.trim().length} chars)`);
  }
  if (broken.length) console.log(`  broken:\n    ${broken.join('\n    ')}`);
  if (thin.length) console.log(`  thin:\n    ${thin.join('\n    ')}`);
  expect(broken, 'nav entries with no served file').toEqual([]);
  expect(thin, 'nav entries served as near-empty files').toEqual([]);
});

test('docs: the viewer renders a doc body, not just the nav', async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page);
  await page.goto(`${BASE}/docs?slug=09-reference/04-platform-settings`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(3000);

  const text = (await page.textContent('body')) || '';
  expect(text, 'the requested doc rendered').toMatch(/platform settings/i);
  expect(text, 'its body rendered, not just the title').toMatch(
    /pipeline\.timeout_seconds/i,
  );
  expect(text.length, 'doc page looks blank').toBeGreaterThan(1500);
});

test('docs: /dev-docs forwards to /docs rather than dead-ending', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await page.goto(`${BASE}/dev-docs`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  expect(page.url(), 'redirected to /docs').toMatch(/\/docs/);
});
