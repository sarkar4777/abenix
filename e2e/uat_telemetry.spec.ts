/**
 * Telemetry through the UI, as an admin and as a Member.
 *
 *   - a first-time admin opens Get started, picks a webhook, gets an address and token, sends a test message, maps it,
 *     sees it in the inspector, makes a device key, sends with it, and revokes it
 *   - admin adds an MQTT source in the add-source flow (bad address first), tests it, turns it on, then off
 *   - a Sparkplug B edge node comes online (this spec plays one through a small MQTT client, or uses the Groundwork PCs
 *     when the broker port is not reachable) and its card appears on the Devices tab
 *   - the device page shows values moving live, a sparkline and the history chart
 *   - the Frames tab shows a decoded J1939 frame, pause works
 *   - a safety hold is sent with a reason, the preview names the exact DCMD, and the edge node receives it
 *   - the edge node drops off the broker, its last will fires and the page says it is offline
 *   - a fresh Member sees the page view only, with no command or broker controls
 * Screens are saved at 1440 and 390 px in e2e/uat_telemetry/.
 *
 *   MQTT_URL=mqtt://localhost:1883 BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_telemetry.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { DT, EdgeNode, MiniMqtt, type SpMetric } from './helpers/sparkplug';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const MQTT_URL = process.env.MQTT_URL || 'mqtt://127.0.0.1:1883';
const IN_CLUSTER_BROKER = process.env.TEL_BROKER || 'mqtt://abenix-mosquitto.abenix.svc.cluster.local:1883';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const GROUP = 'abenix-uat';
const NODE = 'uat-ex1';
const RAW_TOPIC = `${GROUP}/${NODE}/can/raw`;
const CONN = `UAT broker ${RUN}`;
const PUSH = `UAT push ${RUN}`;
const MEMBER = { email: `tel-member-${RUN}@example.com`, password: `Member-${RUN}-9x`, name: `Tess Viewer ${RUN}` };
const OUT = path.join(__dirname, 'uat_telemetry');
const WIDTHS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

// in order on one worker, but a failure does not stop the rest
test.describe.configure({ mode: 'default' });
test.setTimeout(240_000);

let edge: EdgeNode | null = null;
let useGroundwork = false;
let target = { group: GROUP, node: NODE, engine: 'engine', safety: 'safety' };
const commands: Array<{ topic: string; metrics: Array<{ name?: string; value?: unknown }> }> = [];
let ticker: NodeJS.Timeout | null = null;
let rpm = 900;

fs.mkdirSync(OUT, { recursive: true });

async function shot(page: Page, name: string) {
  const size = page.viewportSize();
  for (const w of WIDTHS) {
    await page.setViewportSize(w);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `${name}-${w.width}.png`), fullPage: true });
  }
  if (size) await page.setViewportSize(size);
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
}

async function signIn(page: Page, who: { email: string; password: string }) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function inviteMember(page: Page, browser: Browser) {
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).first().click();
  await page.getByPlaceholder('email@example.com').fill(MEMBER.email);
  await page.getByTestId('invite-role').selectOption('user');
  await page.getByTestId('invite-send').click();
  const link = page.getByTestId('invite-link');
  await expect(link).toBeVisible({ timeout: 20_000 });
  const raw = ((await link.innerText()) || (await link.inputValue().catch(() => ''))).trim();
  const url = raw.startsWith('http') ? raw.replace(/^https?:\/\/[^/]+/, BASE) : `${BASE}${raw}`;
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p2 = await ctx.newPage();
  await p2.goto(url, { waitUntil: 'domcontentloaded' });
  await p2.locator('#accept-full-name').fill(MEMBER.name);
  await p2.locator('#accept-password').fill(MEMBER.password);
  await p2.getByTestId('accept-submit').click();
  await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
}

function engineMetrics(): SpMetric[] {
  rpm = 900 + Math.round(Math.random() * 600);
  return [
    { name: 'Engine/Speed_rpm', datatype: DT.Double, value: rpm },
    { name: 'Engine/Coolant_c', datatype: DT.Double, value: 80 + Math.random() * 6 },
    { name: 'Engine/Load_pct', datatype: DT.Double, value: 30 + Math.random() * 40 },
  ];
}

// an EEC1 frame for the current speed, packed as the J1939-71 layout
function eec1(): { t: number; id: number; data: string; dlc: number } {
  const raw = Math.round(rpm / 0.125);
  const bytes = [0xf1, 0xa5, 0xa7, raw & 0xff, (raw >> 8) & 0xff, 0x00, 0xf0, 0xaa];
  return { t: Date.now(), id: 0x0cf00400, data: Buffer.from(bytes).toString('hex'), dlc: 8 };
}

async function startEdge() {
  edge = new EdgeNode(MQTT_URL, GROUP, NODE);
  await edge.start([{ name: 'Machine/Name', datatype: DT.String, value: 'UAT excavator' }]);
  edge.birthDevice('engine', engineMetrics());
  edge.birthDevice('safety', [
    { name: 'Safety/Hold', datatype: DT.Boolean, value: false },
    { name: 'Mode/Set', datatype: DT.String, value: 'auto' },
  ]);
  edge.onCommand((topic, p) => {
    commands.push({ topic, metrics: p.metrics });
    const hold = p.metrics.find((m) => m.name === 'Safety/Hold');
    // a real controller reports the new state back
    if (hold) edge?.data('safety', [{ name: 'Safety/Hold', datatype: DT.Boolean, value: !!hold.value }]);
  });
  ticker = setInterval(() => {
    edge?.data('engine', engineMetrics());
    edge?.frames(RAW_TOPIC, [eec1(), { t: Date.now(), id: 0x18feee00, data: '8051502effff5fff', dlc: 8 }]);
  }, 100);
}

async function brokerReachable(): Promise<boolean> {
  const c = MiniMqtt.fromUrl(MQTT_URL, `abenix-uat-probe-${RUN}`);
  try {
    await c.connect(undefined, 3000);
    c.end();
    return true;
  } catch {
    return false;
  }
}

test.afterAll(async () => {
  if (ticker) clearInterval(ticker);
  edge?.stop();
});

async function apiToken(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  return (await r.json()).data.access_token;
}

async function hasCatalogue(page: Page): Promise<boolean> {
  const t = await apiToken(page);
  const r = await page.request.get(`${API}/api/telemetry/transports`, { headers: { Authorization: `Bearer ${t}` } });
  return r.ok();
}

test('a first-time admin is guided to a live stream over HTTP, with device keys', async ({ page }) => {
  test.skip(!(await hasCatalogue(page)), 'this server has no source catalogue yet (GET /api/telemetry/transports)');
  await signIn(page, ADMIN);
  await go(page, '/telemetry');
  await expect(page.getByTestId('page-header')).toContainText('Telemetry');
  await page.getByTestId('tel-get-started').click();
  await expect(page.getByTestId('tel-guide')).toContainText('What do you want to connect?');
  await shot(page, '01-guide');
  await page.getByTestId('tel-guide-vehicles').click();
  await expect(page.getByTestId('tel-guide-code').first()).toContainText('Abenix Edge');
  await shot(page, '02-guide-vehicles');
  await page.getByTestId('tel-guide-back').click();
  await page.getByTestId('tel-guide-software').click();
  await page.locator('[data-testid="tel-guide-path"][data-path="webhook"] [data-testid="tel-guide-start"]').click();

  const wiz = page.getByTestId('tel-wizard');
  await expect(wiz).toHaveAttribute('data-step', 'settings');
  await page.getByTestId('tel-src-name').fill('');
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz).toContainText('Give the connection a name');
  await page.getByTestId('tel-src-name').fill(PUSH);
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz).toHaveAttribute('data-step', 'decoder');
  await shot(page, '03-wizard-format');
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz).toHaveAttribute('data-step', 'finish', { timeout: 15_000 });
  await expect(page.getByTestId('tel-push-token')).toBeVisible();
  await expect(page.getByTestId('tel-push-snippet')).toContainText('Idempotency-Key');
  await page.getByTestId('tel-push-test').click();
  await expect(page.getByTestId('tel-push-result')).toContainText('Accepted', { timeout: 15_000 });
  await shot(page, '04-push-endpoint');
  await page.getByTestId('tel-push-map').click();
  await expect(wiz).toHaveAttribute('data-step', 'mapping');
  await expect(page.getByTestId('tel-map-record').first()).toBeVisible({ timeout: 15_000 });
  await shot(page, '05-mapping-preview');
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz).toHaveCount(0, { timeout: 15_000 });

  // the message is in the inspector for that source
  await go(page, '/telemetry?tab=sources');
  const row = page.getByTestId('tel-conn-row').filter({ hasText: PUSH });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByTestId('tel-conn-messages').click();
  await expect(page.getByTestId('tel-msg-row').first()).toBeVisible({ timeout: 20_000 });
  await shot(page, '06-messages');

  // a device key, shown once, that writes as its own device
  await go(page, '/telemetry?tab=sources');
  await page.getByTestId('tel-conn-row').filter({ hasText: PUSH }).getByTestId('tel-conn-keys').click();
  await page.getByTestId('tel-keys-one').click();
  await page.getByTestId('tel-key-create').click();
  await expect(page.getByTestId('tel-keys')).toContainText('Give the device id');
  await page.getByTestId('tel-key-device').fill(`van-${RUN}`);
  await page.getByTestId('tel-key-create').click();
  const key = (await page.getByTestId('tel-key-value').innerText({ timeout: 15_000 })).trim();
  await expect(page.getByTestId('tel-key-made')).toContainText('You will not see it again');
  await shot(page, '07-device-key');
  const src = await (await page.request.get(`${API}/api/telemetry/connections`, { headers: { Authorization: `Bearer ${await apiToken(page)}` } })).json();
  const pushId = (src.data as Array<{ id: string; name: string }>).find((c) => c.name === PUSH)!.id;
  const sent = await page.request.post(`${API}/api/telemetry/ingest/${pushId}`, { headers: { Authorization: `Bearer ${key}`, 'Idempotency-Key': `${RUN}-1` }, data: { ts: Date.now(), speed_kmh: 48 } });
  expect(sent.status(), 'a device key is accepted').toBeLessThan(300);
  await page.getByRole('button', { name: 'I have copied it' }).click();
  await page.getByTestId('tel-key-row').filter({ hasText: `van-${RUN}` }).getByTestId('tel-key-revoke').click();
  await expect(page.getByRole('dialog').last()).toContainText('stops working at once');
  await page.getByTestId('tel-key-revoke-confirm').click();
  await expect(page.getByTestId('tel-key-row').filter({ hasText: `van-${RUN}` })).toHaveCount(0, { timeout: 15_000 });
  await expect.poll(async () => (await page.request.post(`${API}/api/telemetry/ingest/${pushId}`, { headers: { Authorization: `Bearer ${key}` }, data: { ts: Date.now(), speed_kmh: 49 } })).status(), { message: 'a revoked key is refused', timeout: 15_000 }).toBe(401);
});

test('admin adds an MQTT source, tests it and turns it off and on', async ({ page }) => {
  test.skip(!(await hasCatalogue(page)), 'this server has no source catalogue yet (GET /api/telemetry/transports)');
  await signIn(page, ADMIN);
  await go(page, '/telemetry?tab=sources');
  await expect(page.getByTestId('tel-tab-sources')).toHaveAttribute('aria-selected', 'true');
  await shot(page, '08-sources');
  await page.getByTestId('tel-primary').click();
  const wiz = page.getByTestId('tel-wizard');
  await page.getByTestId('tel-transport-mqtt').click();
  await page.getByTestId('tel-wiz-next').click();
  await page.getByTestId('tel-src-name').fill(CONN);
  const url = page.locator('[data-testid="tel-cfg-broker_url"], [data-testid="tel-cfg-url"]').first();
  await url.fill('broker.local');
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz.locator('[data-testid$="-problem"]').first()).toBeVisible();
  await shot(page, '09-wizard-invalid');
  await url.fill(IN_CLUSTER_BROKER);
  const topics = page.locator('[data-testid="tel-cfg-subjects"], [data-testid="tel-cfg-topics"]').first();
  if (await topics.count()) await topics.fill(`spBv1.0/${GROUP}/#`);
  await page.getByTestId('tel-src-test').click();
  await expect(page.getByTestId('tel-src-test-result')).toHaveAttribute('data-ok', 'true', { timeout: 20_000 });
  await shot(page, '10-wizard-tested');
  await page.getByTestId('tel-wiz-next').click();
  await page.getByTestId('tel-decoder-sparkplug_b').click();
  await page.getByTestId('tel-wiz-next').click();
  await expect(wiz).toHaveAttribute('data-step', 'finish', { timeout: 15_000 });
  await page.getByTestId('tel-wiz-turn-on').click();
  await expect(wiz).toHaveCount(0, { timeout: 15_000 });

  const row = page.getByTestId('tel-conn-row').filter({ hasText: CONN });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByTestId('tel-conn-test').click();
  await expect(row.getByTestId('tel-conn-test-result')).toBeVisible({ timeout: 20_000 });
  // a second source on the same broker would store everything twice, so it goes off again
  await row.getByTestId('tel-conn-disable').click();
  await expect(page.getByRole('dialog')).toContainText('within 5 seconds');
  await page.getByTestId('tel-conn-disable-confirm').click();
  await expect(row.getByTestId('tel-conn-enable')).toBeVisible({ timeout: 15_000 });
});

// a failed test restarts the worker, so every test that needs the edge node makes sure it runs
async function ensureEdge(page: Page) {
  if (edge || useGroundwork) return;
  if (await brokerReachable()) {
    await startEdge();
    await page.waitForTimeout(3000);
    return;
  }
  // no local broker port, fall back to Groundwork's PCs if they are publishing
  const r = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const token = (await r.json()).data.access_token;
  const d = await page.request.get(`${API}/api/telemetry/devices`, { headers: { Authorization: `Bearer ${token}` } });
  const rows = ((await d.json()).data || []) as Array<{ group: string; node: string; online: boolean }>;
  const pc = rows.find((x) => x.group === 'groundwork' && x.node === 'ipc-ex1' && x.online);
  test.skip(!pc, `No broker at ${MQTT_URL} and the Groundwork PCs are not publishing. Add the mosquitto forward or start groundwork-edge.`);
  useGroundwork = true;
  target = { group: 'groundwork', node: 'ipc-ex1', engine: 'engine', safety: 'safety' };
}

test('a machine comes online and its values move live', async ({ page }) => {
  await ensureEdge(page);

  await signIn(page, ADMIN);
  await go(page, '/telemetry');
  await page.getByTestId('tel-search').fill(target.node);
  const card = page.locator(`[data-testid="tel-node-card"][data-node="${target.node}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId('tel-node-status')).toHaveAttribute('data-status', 'online', { timeout: 15_000 });
  await expect(page).toHaveURL(new RegExp(`q=${target.node}`));
  await expect(page.getByTestId('tel-health')).toBeVisible();
  await shot(page, '05-devices');

  await card.locator(`[data-testid="tel-device-chip"][data-device="${target.engine}"]`).click();
  await expect(page.getByTestId('tel-device-title')).toHaveText(`${target.node} / ${target.engine}`);
  await expect(page).toHaveURL(new RegExp(`node=${target.node}.*device=${target.engine}|device=${target.engine}.*node=${target.node}`));
  const speed = page.locator('[data-testid="tel-metric-row"][data-metric="Engine/Speed_rpm"] [data-testid="tel-metric-value"]');
  await expect(speed).toBeVisible({ timeout: 20_000 });
  const seen = new Set<string>();
  for (let i = 0; i < 12 && seen.size < 3; i++) {
    seen.add((await speed.innerText()).trim());
    await page.waitForTimeout(300);
  }
  expect(seen.size, 'engine speed changes on screen while the node publishes').toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId('tel-chart').first()).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => Number(await page.getByTestId('tel-chart').first().getAttribute('data-points')), { timeout: 15_000 }).toBeGreaterThan(5);
  await shot(page, '06-device-live');

  // a deep link opens the same view, for film scripts and shared links
  await go(page, `/telemetry?node=${target.node}&device=${target.engine}&range=15m`);
  await expect(page.getByTestId('tel-device-title')).toHaveText(`${target.node} / ${target.engine}`);
  await expect(page.getByTestId('tel-range-15m')).toHaveAttribute('aria-pressed', 'true');
});

test('a J1939 frame is decoded on the Frames tab', async ({ page }) => {
  await ensureEdge(page);
  await signIn(page, ADMIN);
  await go(page, `/telemetry?node=${target.node}&group=${target.group}`);
  await page.getByTestId('tel-open-frames').click();
  await expect(page.getByTestId('tel-tab-messages')).toHaveAttribute('aria-selected', 'true');
  const row = page.locator('[data-testid="tel-frame-row"][data-pgn="EEC1"]').last();
  await expect(row).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('tel-frames-rate')).toContainText('frames/s');
  await page.getByTestId('tel-pgn-EEC1').click();
  await page.locator('[data-testid="tel-frame-row"][data-pgn="EEC1"]').last().click();
  await expect(page.getByTestId('tel-frame-detail')).toContainText('Engine speed');
  await expect(page.getByTestId('tel-frame-detail')).toContainText('rpm');
  await page.getByTestId('tel-frames-pause').click();
  await expect(page.getByTestId('tel-frames-rate')).toContainText('Paused');
  await shot(page, '07-frames');
  await page.getByTestId('tel-frames-pause').click();
});

test('a safety hold is sent with a reason and reaches the machine', async ({ page }) => {
  await ensureEdge(page);
  await signIn(page, ADMIN);
  await go(page, `/telemetry?group=${target.group}&node=${target.node}&device=${target.safety}`);
  await page.getByTestId('tel-send-command').click();
  const dlg = page.getByTestId('tel-command-dialog');
  await expect(dlg).toBeVisible();
  await page.getByTestId('tel-cmd-metric').selectOption('Safety/Hold');
  await page.getByTestId(useGroundwork ? 'tel-cmd-bool-false' : 'tel-cmd-bool-true').click();
  await expect(page.getByTestId('tel-cmd-topic')).toHaveText(`spBv1.0/${target.group}/DCMD/${target.node}/${target.safety}`);
  await expect(page.getByTestId('tel-cmd-payload')).toContainText('"name": "Safety/Hold"');
  await page.getByTestId('tel-cmd-review').click();
  await expect(page.getByTestId('tel-cmd-reason-problem')).toContainText('at least 5 characters');
  await page.getByTestId('tel-cmd-reason').fill(`UAT ${RUN}: worker reported near the swing zone`);
  await shot(page, '08-command-form');
  await page.getByTestId('tel-cmd-review').click();
  await expect(page.getByTestId('tel-cmd-confirm-title')).toContainText(`on ${target.node} / ${target.safety}`);
  await expect(dlg).toContainText('does not wait for an approval');
  await shot(page, '09-command-confirm');
  await page.getByTestId('tel-cmd-send').click();
  await expect(page.getByTestId('tel-cmd-sent')).toBeVisible({ timeout: 15_000 });
  if (!useGroundwork) {
    await expect.poll(() => commands.find((c) => c.metrics.some((m) => m.name === 'Safety/Hold'))?.topic, { timeout: 10_000 }).toBe(`spBv1.0/${GROUP}/DCMD/${NODE}/safety`);
    expect(commands.find((c) => c.metrics.some((m) => m.name === 'Safety/Hold'))!.metrics.find((m) => m.name === 'Safety/Hold')!.value).toBe(true);
    await expect(page.getByTestId('tel-cmd-echo')).toContainText('now reports Safety hold as On', { timeout: 10_000 });
  }
  await shot(page, '10-command-sent');
  await page.getByTestId('tel-cmd-close').click();
});

test('the page says when the machine goes offline', async ({ page }) => {
  await ensureEdge(page);
  test.skip(useGroundwork, 'the Groundwork PCs are left running');
  await signIn(page, ADMIN);
  await go(page, `/telemetry?group=${GROUP}&node=${NODE}&device=engine`);
  await expect(page.getByTestId('tel-device-status')).toHaveAttribute('data-status', 'online', { timeout: 15_000 });
  if (ticker) clearInterval(ticker);
  ticker = null;
  edge?.client.drop();
  await expect(page.getByTestId('tel-device-offline')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('tel-device-offline')).toContainText('went offline at');
  await expect(page.getByTestId('tel-command-offline-note').or(page.getByTestId('tel-send-command'))).toBeVisible();
  await shot(page, '11-device-offline');
  await go(page, `/telemetry?q=${NODE}`);
  await expect(page.getByTestId('tel-offline-banner')).toContainText(NODE);
  await expect(page.getByTestId('tel-offline-alerts')).toHaveAttribute('href', '/alerts');
  await shot(page, '12-devices-offline');
});

test('a Member sees telemetry view only', async ({ page, browser }) => {
  await ensureEdge(page);
  await signIn(page, ADMIN);
  await inviteMember(page, browser);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const mp = await ctx.newPage();
  await signIn(mp, MEMBER);
  await go(mp, '/telemetry');
  await expect(mp.getByTestId('tel-view-only')).toContainText('View only.');
  await expect(mp.getByTestId('tel-primary')).toHaveCount(0);
  await shot(mp, '13-member-devices');
  await go(mp, `/telemetry?group=${target.group}&node=${target.node}&device=${target.safety}`);
  await expect(mp.getByTestId('tel-device-title')).toBeVisible({ timeout: 20_000 });
  await expect(mp.getByTestId('tel-send-command')).toHaveCount(0);
  await expect(mp.getByTestId('tel-command-needs')).toContainText('Admin, Permissions');
  await go(mp, '/telemetry?tab=sources');
  await expect(mp.getByTestId('tel-connections-view-only')).toBeVisible();
  for (const id of ['tel-primary', 'tel-conn-test', 'tel-conn-edit', 'tel-conn-delete', 'tel-conn-disable', 'tel-conn-share-open', 'tel-conn-keys', 'tel-conn-mapping']) {
    await expect(mp.getByTestId(id)).toHaveCount(0);
  }
  await shot(mp, '14-member-sources');
  await mp.getByTestId('tel-get-started').click();
  await mp.getByTestId('tel-guide-sensors').click();
  await expect(mp.getByTestId('tel-guide-start')).toHaveCount(0);
  await expect(mp.getByTestId('tel-guide')).toContainText('An admin sets this up');
  await ctx.close();
});

test('admin deletes the UAT sources after a confirmation', async ({ page }) => {
  await signIn(page, ADMIN);
  await go(page, '/telemetry?tab=sources');
  // this run's sources, and any a restarted worker or an earlier run left behind
  for (let i = 0; i < 10; i++) {
    const row = page.locator('[data-testid="tel-conn-row"][data-name^="UAT broker "], [data-testid="tel-conn-row"][data-name^="UAT push "]').first();
    if (!(await row.count())) break;
    const name = (await row.getAttribute('data-name')) || '';
    await row.getByTestId('tel-conn-delete').click();
    await expect(page.getByRole('dialog')).toContainText('This cannot be undone');
    if (i === 0) await shot(page, '15-delete-confirm');
    await page.getByTestId('tel-conn-delete-confirm').click();
    await expect(page.locator(`[data-testid="tel-conn-row"][data-name="${name}"]`)).toHaveCount(0, { timeout: 15_000 });
  }
});

test('admin forgets the UAT assets, one from its page and the rest in bulk', async ({ page }) => {
  test.skip(useGroundwork, 'the Groundwork PCs are not test assets');
  await signIn(page, ADMIN);
  edge?.stop();
  edge = null;
  // the test asset from its own page, a second confirm if it still looks online
  await go(page, `/telemetry?group=${GROUP}&node=${NODE}`);
  const forget = page.getByTestId('tel-forget');
  if (await forget.count()) {
    await forget.click();
    await expect(page.getByRole('dialog')).toContainText('history is kept');
    await shot(page, '16-forget-confirm');
    await page.getByTestId('tel-forget-confirm').click();
    const force = page.getByTestId('tel-forget-force');
    if (await force.isVisible({ timeout: 5_000 }).catch(() => false)) await force.click();
    await expect(page).toHaveURL(/\/telemetry(\?|$)/, { timeout: 15_000 });
    await expect(page.getByTestId('tel-device-title')).toHaveCount(0);
  }
  // anything an earlier run left behind in the test group, with a dry run first
  await go(page, '/telemetry');
  await page.getByTestId('tel-bulk-forget-open').click();
  await page.getByTestId('tel-forget-offline-for').selectOption('60');
  const groupSelect = page.getByTestId('tel-forget-group');
  if (await groupSelect.locator(`option[value="${GROUP}"]`).count()) await groupSelect.selectOption(GROUP);
  await page.getByTestId('tel-forget-glob').fill('uat-*');
  await page.getByTestId('tel-forget-preview-run').click();
  const preview = page.getByTestId('tel-forget-preview');
  await expect(preview).toBeVisible({ timeout: 15_000 });
  await shot(page, '17-bulk-forget-preview');
  if (Number(await preview.getAttribute('data-matched')) > 0) {
    await page.getByTestId('tel-forget-next').click();
    await expect(page.getByTestId('tel-forget-confirm-text')).toContainText('History is kept');
    await page.getByTestId('tel-forget-run').click();
    await expect(page.getByTestId('tel-forget-progress')).toContainText('Done.', { timeout: 60_000 });
    await page.getByTestId('tel-forget-close').click();
  }
});
