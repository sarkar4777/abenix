import { chromium, type Browser, type Page } from 'playwright';
import path from 'path';
import fs from 'fs';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';
const EMAIL = process.env.ABENIX_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.ABENIX_PASSWORD || 'Admin123456';
const OUT_DIR = path.resolve(__dirname, '..', 'docs', 'screenshots', 'deep-uat');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

interface StepResult { name: string; ok: boolean; detail: string; ms: number; }
const results: StepResult[] = [];
const consoleErrors: string[] = [];

async function step<T>(name: string, fn: () => Promise<T>): Promise<T | undefined> {
  const start = Date.now();
  try {
    const out = await fn();
    const ms = Date.now() - start;
    results.push({ name, ok: true, detail: '', ms });
    console.log(`  PASS  ${name}  (${ms} ms)`);
    return out;
  } catch (e: any) {
    const ms = Date.now() - start;
    const detail = (e?.message || String(e)).split('\n')[0].slice(0, 240);
    results.push({ name, ok: false, detail, ms });
    console.log(`  FAIL  ${name}  (${ms} ms)  ${detail}`);
    return undefined;
  }
}

async function snap(page: Page, name: string) {
  try {
    await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: false });
  } catch {}
}

async function login(page: Page) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  // Auth card hydrates a moment after first paint.
  await page.locator('#auth-email').waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2_000);

  // Synthetic clicks get swallowed by framer-motion on the auth card.
  // The Admin Demo button's React onClick fires the demo login directly.
  const fired = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button')) as HTMLButtonElement[];
    const btn = btns.find(b => b.textContent?.trim() === 'Admin Demo');
    if (!btn) return 'no Admin Demo button';
    const key = Object.keys(btn).find(k => k.startsWith('__reactProps$'));
    if (!key) return 'no __reactProps key';
    const onClick = (btn as any)[key].onClick;
    if (typeof onClick !== 'function') return 'no onClick';
    onClick();
    return 'fired';
  });
  if (fired !== 'fired') {
    // Fallback: form-based login
    await page.fill('#auth-email', EMAIL);
    await page.fill('#auth-password', PASSWORD);
    await page.locator('button[type="submit"]').first().click().catch(() => {});
  }
  await page.waitForURL((url) => /\/dashboard|\/atlas|\/agents|\/home/.test(url.pathname), { timeout: 45_000 });
  await page.waitForTimeout(1_500);
}

async function gotoAndSettle(page: Page, route: string, sentinel?: string | RegExp) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  if (sentinel) {
    await page.locator(typeof sentinel === 'string' ? `text=${sentinel}` : `text=${sentinel.source}`)
      .first().waitFor({ timeout: 30_000 }).catch(() => {});
  }
  await page.waitForTimeout(1_000);
}

async function run() {
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: 'dark',
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const t = msg.text();
      if (
        !t.includes('favicon') &&
        !t.includes('Download the React DevTools') &&
        !t.includes('chrome-extension')
      ) consoleErrors.push(t.slice(0, 240));
    }
  });
  page.on('pageerror', err => consoleErrors.push(`pageerror: ${err.message}`.slice(0, 240)));

  console.log(`\n🧪  Abenix Deep UAT against ${BASE}\n`);

  await step('login as admin', () => login(page));
  await snap(page, '01-after-login');

  // 1. Dashboard
  await step('dashboard renders', async () => {
    await gotoAndSettle(page, '/dashboard');
    if (!(await page.locator('text=/Dashboard|Overview|Welcome|Agents/i').first().count()))
      throw new Error('no dashboard heading visible');
  });
  await snap(page, '02-dashboard');

  // 2. Sidebar groups — Agents is in the always-open PINNED group; Atlas and
  // Knowledge live under BUILD which collapses by default.  Expand BUILD,
  // then assert the link hrefs.
  await step('sidebar shows Agents + Atlas + Knowledge links', async () => {
    const haveAgents = await page.locator('a[href="/agents"]').count();
    if (!haveAgents) throw new Error('no /agents nav link');
    // Expand the BUILD group if it's collapsed.
    if (!(await page.locator('a[href="/atlas"]').count())) {
      await page.getByRole('button', { name: /^BUILD/ }).first().click({ force: true }).catch(() => {});
      await page.waitForTimeout(400);
    }
    if (!(await page.locator('a[href="/atlas"]').count()))     throw new Error('no /atlas nav link after expanding BUILD');
    if (!(await page.locator('a[href="/knowledge"]').count())) throw new Error('no /knowledge nav link after expanding BUILD');
  });

  // 3. Agents list — verify the page renders cards, then look up an OOB
  // agent via the API.  The grouped UI buries the "built-in" badge inside
  // nested spans; the API gives us a clean agent_type filter.
  let firstOobHref: string | null = null;
  let agentName: string | null = null;
  await step('agents list — at least one OOB agent visible', async () => {
    await gotoAndSettle(page, '/agents');
    await page.locator('a[href*="/agents/"][href*="/info"]').first().waitFor({ timeout: 30_000 });
    // Pull an OOB agent from the API directly (port 8000).  Filter client-side.
    // Skip agents that define required input_variables — those block sending
    // until parameters are filled in.
    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token');
      if (!token) return { error: 'no token' };
      const r = await fetch('http://localhost:8000/api/agents', { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) return { error: `status ${r.status}` };
      const j = await r.json();
      const list: any[] = Array.isArray(j.data) ? j.data : (j.data?.items ?? []);
      const oob = list.find((a) => {
        if (a.agent_type !== 'oob') return false;
        const ivs = (a.model_config || {}).input_variables || [];
        return !ivs.some((v: any) => v.required);
      });
      return oob ? { id: oob.id as string, name: oob.name as string } : { error: `no oob agent without required input_vars in ${list.length} agents` };
    });
    if ('error' in result && result.error) throw new Error(`API: ${result.error}`);
    firstOobHref = `/agents/${(result as any).id}/info`;
    agentName = (result as any).name;
  });
  await snap(page, '03-agents-list');

  // 4. Chat with first OOB agent — assert a NEW assistant bubble appears
  // after we send.  Bubble count is the most reliable signal because it
  // can't be satisfied by static page text.
  await step(`chat with "${agentName ?? 'agent'}"`, async () => {
    if (!firstOobHref) throw new Error('no agent href captured');
    const chatHref = firstOobHref.replace('/info', '/chat');
    await gotoAndSettle(page, chatHref);
    const ta = page.locator('textarea[placeholder*="Message"]').first();
    await ta.waitFor({ timeout: 20_000 });
    let executeRequested = false;
    let executeStatus = 0;
    page.on('request', (req) => {
      if (req.url().includes('/execute') && req.method() === 'POST') executeRequested = true;
    });
    page.on('response', (res) => {
      if (res.url().includes('/execute')) executeStatus = res.status();
    });
    const SENTINEL = 'Reply with the single word OK and nothing else.';
    await ta.click({ force: true });
    await ta.focus();
    await page.keyboard.type(SENTINEL, { delay: 8 });
    await page.waitForTimeout(300);
    const taValue = await ta.inputValue();
    if (!taValue.includes('Reply')) throw new Error(`textarea did not capture text — value="${taValue}"`);
    await ta.press('Enter');
    // Wait for the user message bubble (echoes our sentinel) AND the empty-state
    // to be replaced by ChatMessage components.  After the SSE 'done' event
    // arrives, an assistant ChatMessage is appended.
    try {
      await page.waitForFunction(
        (sentinel) => {
          const txt = (document.body.innerText || '');
          if (!txt.includes(sentinel)) return false;
          // ChatMessage assistant bubbles use bg-slate-800/50; user bubbles use bg-cyan-600/20.
          // After the SSE 'done' event, both should be present.
          const userBubble = !!document.querySelector('.bg-cyan-600\\/20');
          const assistantBubble = !!document.querySelector('.bg-slate-800\\/50.rounded-2xl');
          return userBubble && assistantBubble;
        },
        SENTINEL,
        { timeout: 120_000 }
      );
    } catch (e) {
      await snap(page, '04b-chat-timeout');
      const dom = await page.evaluate((sentinel) => ({
        sawSentinel: (document.body.innerText || '').includes(sentinel),
        userBubble: !!document.querySelector('.bg-cyan-600\\/20'),
        assistantBubble: !!document.querySelector('.bg-slate-800\\/50.rounded-2xl'),
        bodyLen: (document.body.innerText || '').length,
        snippet: (document.body.innerText || '').slice(-300),
      }), SENTINEL);
      throw new Error(`chat timeout exec=${executeRequested} status=${executeStatus} sawSentinel=${dom.sawSentinel} user=${dom.userBubble} assistant=${dom.assistantBubble} tail=${dom.snippet.replace(/\s+/g, ' ')}`);
    }
  });
  await snap(page, '04-chat-reply');

  // 5. Fork & Edit (clone) — only valid for OOB agents.  We navigate to /info,
  // click Fork & Edit, and assert we land in /builder?agent=<id>.
  let clonedAgentId: string | null = null;
  await step('fork & edit (clone) an OOB agent', async () => {
    if (!firstOobHref) throw new Error('no agent href');
    await gotoAndSettle(page, firstOobHref);
    const fork = page.getByRole('button', { name: /Fork & Edit/i }).first();
    await fork.waitFor({ timeout: 15_000 });
    await fork.click({ force: true });
    await page.waitForURL(/\/builder\?agent=/, { timeout: 30_000 });
    const url = new URL(page.url());
    clonedAgentId = url.searchParams.get('agent');
    if (!clonedAgentId) throw new Error('no agent= query param after fork');
  });
  await snap(page, '05-after-fork');

  // 6. Knowledge collections list
  await step('knowledge collections list renders', async () => {
    await gotoAndSettle(page, '/knowledge');
    if (!(await page.getByText(/knowledge/i).count())) throw new Error('no knowledge heading');
  });
  await snap(page, '06-knowledge');

  // 7. Knowledge projects — create one via modal
  let createdProjectName: string | null = null;
  await step('create knowledge project via modal', async () => {
    await gotoAndSettle(page, '/knowledge/projects');
    const newBtn = page.getByRole('button', { name: /New Project/i }).first();
    await newBtn.waitFor({ timeout: 15_000 });
    await newBtn.click({ force: true });
    await page.waitForTimeout(700);
    const nameInput = page.locator('input[placeholder*="Legal Knowledge"]').first();
    await nameInput.waitFor({ timeout: 10_000 });
    createdProjectName = `UAT Project ${Date.now()}`;
    await nameInput.fill(createdProjectName);
    await page.getByRole('button', { name: /^Create Project$/i }).first().click({ force: true });
    await page.waitForTimeout(2_500);
    // The new project should appear in the list.
    if (!(await page.getByText(createdProjectName).count()))
      throw new Error(`project "${createdProjectName}" did not appear in list`);
  });
  await snap(page, '07-knowledge-project-created');

  // 8. Atlas page renders
  await step('atlas page renders', async () => {
    await gotoAndSettle(page, '/atlas');
    await page.waitForTimeout(2_000);
    if (!(await page.getByRole('button', { name: /New atlas/i }).count()))
      throw new Error('"New atlas" CTA missing');
  });
  await snap(page, '08-atlas');

  // 9. Top-level /chat
  await step('multi-agent /chat page renders', async () => {
    await gotoAndSettle(page, '/chat');
    await page.waitForTimeout(1_500);
    // Either a thread sidebar or an empty-state — anything but a router error.
    const body = (await page.locator('body').textContent()) || '';
    if (/error|404|not found/i.test(body) && !/conversations|chat|select an agent/i.test(body))
      throw new Error('chat page seems broken');
  });
  await snap(page, '09-chat');

  // 10. Builder loads
  await step('builder page renders', async () => {
    await gotoAndSettle(page, '/builder');
    await page.waitForTimeout(2_500);
    const body = (await page.locator('body').textContent()) || '';
    if (!/agent|builder|model|prompt|tool/i.test(body))
      throw new Error('builder body lacks expected content');
  });
  await snap(page, '10-builder');

  // 11. Settings → Security renders + activity log clean
  await step('settings/security renders without raw null leaks', async () => {
    await gotoAndSettle(page, '/settings/security');
    await page.waitForTimeout(2_000);
    const body = (await page.locator('body').textContent()) || '';
    if (/integrity_hash|"new_value":\s*null|"old_value":\s*null/.test(body))
      throw new Error('raw audit field leaked into UI');
  });
  await snap(page, '11-settings-security');

  // 12. Cleanup the cloned agent (if any) via API to keep state tidy.
  if (clonedAgentId) {
    await step('cleanup cloned agent', async () => {
      const token = await page.evaluate(() => localStorage.getItem('access_token'));
      if (!token) return;
      await fetch(`http://localhost:8000/api/agents/${clonedAgentId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    });
  }

  await browser.close();

  // ── Report ──────────────────────────────────────────────────────────
  const passed = results.filter(r => r.ok).length;
  const failed = results.filter(r => !r.ok).length;
  console.log(`\n────────────────────────────────────────`);
  console.log(`  ${passed} passed · ${failed} failed`);
  if (consoleErrors.length) console.log(`  ${consoleErrors.length} JS console errors`);
  console.log(`────────────────────────────────────────\n`);

  if (failed) {
    console.log('Failures:');
    for (const r of results.filter(r => !r.ok)) console.log(`  • ${r.name} — ${r.detail}`);
  }
  if (consoleErrors.length) {
    console.log('\nFirst 10 console errors:');
    for (const e of consoleErrors.slice(0, 10)) console.log(`  • ${e}`);
  }

  const md = [
    `# Abenix Deep UAT results`,
    ``,
    `**${passed} passed · ${failed} failed**` + (consoleErrors.length ? ` · ${consoleErrors.length} console errors` : ''),
    ``,
    `Run against \`${BASE}\` on ${new Date().toISOString()}.`,
    ``,
    `| # | Step | Result | ms | Detail |`,
    `|---|------|--------|----|--------|`,
    ...results.map((r, i) => `| ${i + 1} | ${r.name} | ${r.ok ? '✅' : '❌'} | ${r.ms} | ${r.detail || ''} |`),
    ``,
    consoleErrors.length ? '## Console errors\n' + consoleErrors.map(e => `- ${e}`).join('\n') : '',
  ].join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'report.md'), md);

  process.exit(failed === 0 ? 0 : 1);
}

run().catch(err => {
  console.error('Deep UAT crashed:', err);
  process.exit(2);
});
