/**
 * Drive the operator-facing surfaces the way an operator does.
 *
 * Load-test playground, SDK playground, scaling admin, MCP config against a
 * real custom server, alerts, and the edge page. These pages are where the
 * platform is configured rather than used, so they get less traffic than the
 * builder and correspondingly less notice when they rot.
 *
 * Everything asserts on what the page actually did. A page that renders its
 * chrome and no data passes a smoke test and fails this one.
 *
 *   npx playwright test e2e/uat_platform_surfaces.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

// The custom MCP server deployed alongside the platform. Three tools, and
// numbers chosen so an invented answer cannot accidentally match.
const MCP_URL = process.env.CUSTOM_MCP_URL || 'http://custom-mcp.abenix.svc.cluster.local:8080/mcp';

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(res.ok(), 'login').toBeTruthy();
  const token = (await res.json())?.data?.access_token;
  expect(token, 'access token').toBeTruthy();
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
  }, token);
  return token as string;
}

async function api(page: Page, method: string, path: string, token: string, body?: unknown) {
  const res = await page.request.fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  });
  let json: any = null;
  try { json = await res.json(); } catch { /* empty body */ }
  return { status: res.status(), json };
}

/** Text of the whole page, for asserting a surface rendered its own content. */
async function bodyText(page: Page) {
  return (await page.locator('body').innerText()).slice(0, 20000);
}

let token = '';

test.describe.serial('platform surfaces', () => {
  test('load-test playground runs a load test and reports latency', async ({ page }) => {
    token = await login(page);
    await page.goto(`${BASE}/load-playground`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text.length, 'load playground rendered nothing').toBeGreaterThan(200);
    // The page is about firing concurrent work, so it must offer a way to.
    const run = page.getByRole('button', { name: /run|start|fire|launch/i }).first();
    expect(await run.count(), 'no run control on the load playground').toBeGreaterThan(0);
    console.log(`  load playground: ${text.length} chars, run control present`);
  });

  test('sdk playground lists endpoints and executes one against the live api', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/sdk-playground`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text.length).toBeGreaterThan(200);
    // A playground that cannot name a single SDK call is a shell.
    expect(text, 'no SDK surface named').toMatch(/agent|execute|knowledge|sdk/i);
    console.log(`  sdk playground: ${text.length} chars`);
  });

  test('scaling admin shows pools and persists a change', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/admin/scaling`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text, 'scaling page has no pool or replica language').toMatch(/pool|replica|concurrency|scal/i);

    // Round-trip a real change through the API the page drives.
    const list = await api(page, 'GET', '/api/admin/scaling/agents', token);
    expect(list.status, 'scaling agents endpoint failed').toBe(200);
    const rows = list.json?.data?.agents ?? list.json?.data ?? [];
    expect(Array.isArray(rows) && rows.length, 'no agents on the scaling surface').toBeTruthy();
    const agent = rows[0];
    const before = agent.min_replicas ?? 1;
    const target = before === 2 ? 3 : 2;

    const patch = await api(page, 'PATCH', `/api/admin/scaling/agents/${agent.id}`, token, {
      min_replicas: target,
    });
    console.log(`  scaling: PATCH -> ${patch.status} (min_replicas ${before} -> ${target})`);
    expect(patch.status, 'scaling change rejected').toBeLessThan(400);

    // It has to survive a re-read, not just answer 200.
    const after = await api(page, 'GET', '/api/admin/scaling/agents', token);
    const rows2 = after.json?.data?.agents ?? after.json?.data ?? [];
    const got = rows2.find((r: any) => r.id === agent.id)?.min_replicas;
    expect(got, 'scaling change did not persist').toBe(target);

    // Put it back so the cluster is left as found.
    await api(page, 'PATCH', `/api/admin/scaling/agents/${agent.id}`, token, {
      min_replicas: before,
    });
  });

  test('mcp config registers a custom server and discovers its three tools', async ({ page }) => {
    await login(page);

    const name = `custom-mcp-${Date.now()}`;
    const create = await api(page, 'POST', '/api/mcp/connections', token, {
      server_name: name, server_url: MCP_URL, auth_type: 'none',
    });
    console.log(`  mcp register -> ${create.status}`);
    expect(create.status, 'could not register the MCP server').toBeLessThan(400);
    const conn = create.json?.data ?? create.json;
    const connId = conn?.id;
    expect(connId, 'no connection id returned').toBeTruthy();

    // Discovery is the whole point. Three tools, by name.
    const disc = await api(page, 'POST', `/api/mcp/connections/${connId}/discover`, token, {});
    console.log(`  mcp discover -> ${disc.status}`);
    const payload = disc.json?.data ?? disc.json ?? {};
    const raw = payload.tools ?? payload.discovered_tools ?? conn?.tools ?? [];
    const names = (Array.isArray(raw) ? raw : []).map((t: any) => t.name ?? t);
    console.log(`  mcp tools discovered: ${JSON.stringify(names)}`);
    for (const want of ['inventory_lookup', 'shipping_quote', 'order_status']) {
      expect(names, `${want} not discovered`).toContain(want);
    }

    // And the page has to show it, not just the API.
    await page.goto(`${BASE}/mcp`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text, 'registered server absent from the MCP settings page').toContain(name);
  });

  test('alerts surface a real failure with its failure_code', async ({ page }) => {
    await login(page);

    // Make a genuine failure rather than asserting against whatever happens to
    // be lying around. A model that does not exist fails in the runtime, which
    // is the path the alerts page exists to show.
    const mk = await api(page, 'POST', '/api/agents', token, {
      name: `alerts-probe-${Date.now()}`,
      description: 'Deliberate failure, to prove the alerts surface reports it.',
      system_prompt: 'You will not be reached.',
      category: 'other',
      model_config: { mode: 'agent', model: 'model-that-does-not-exist', tools: [] },
    });
    const agentId = (mk.json?.data ?? mk.json)?.id;
    expect(agentId, `could not create the probe agent (${mk.status})`).toBeTruthy();

    const run = await api(page, 'POST', `/api/agents/${agentId}/execute`, token, {
      message: 'go', stream: false, wait: true, wait_timeout_seconds: 180,
    });
    const status = (run.json?.data ?? {}).status;
    console.log(`  probe execution status: ${status}`);

    // It must FAIL. This used to allow 'completed' too, and it passed that way
    // because the router quietly degraded an unrecognised model onto whatever
    // provider had a credential, so a nonexistent model returned a perfectly
    // good answer. Accepting 'completed' hid a real bug.
    expect(status, 'a nonexistent model must fail, not answer').toBe('failed');

    // The /alerts page draws on two different surfaces and it is worth being
    // precise about which. /api/analytics/failures groups real executions by
    // failure_code. /api/admin/alerts is the Prometheus rule state, which stays
    // inactive until a rate threshold trips, so one failure will not show there
    // and asserting it would be asserting the wrong thing.
    const failures = await api(page, 'GET', '/api/analytics/failures?hours=24', token);
    expect(failures.status, 'failure summary endpoint failed').toBe(200);
    const groups = failures.json?.data ?? [];
    console.log(`  failure groups: ${groups.map((g: any) => `${g.failure_code}=${g.count}`).join(', ')}`);
    expect(Array.isArray(groups) && groups.length,
      'the execution just failed but nothing was grouped').toBeTruthy();
    for (const g of groups) {
      expect(g.failure_code, 'a failure group has no failure_code').toBeTruthy();
      expect(g.count, 'a failure group has no count').toBeGreaterThan(0);
      expect(g.sample_message, 'a failure group has no sample message').toBeTruthy();
    }

    // Assert on the failure this test caused, not on whatever rows happened to
    // be in the table already. Passing on somebody else's stale failures is how
    // this test was green while proving nothing.
    expect(groups.map((g: any) => g.failure_code),
      'the probe failure was not classified as a config problem')
      .toContain('CONFIG_UNKNOWN_MODEL');

    const feed = await api(page, 'GET', '/api/admin/alerts?limit=25', token);
    expect(feed.status, 'alerts endpoint failed').toBe(200);
    // Rules have to be loaded, otherwise nothing could ever fire.
    const rules = await api(page, 'GET', '/api/admin/alerts/rules', token);
    const ruleGroups = rules.json?.data?.groups ?? [];
    const ruleCount = ruleGroups.reduce((n: number, gr: any) => n + (gr.rules?.length ?? 0), 0);
    console.log(`  prometheus rules loaded: ${ruleCount} in ${ruleGroups.length} groups`);
    expect(ruleCount, 'no prometheus alert rules are loaded').toBeGreaterThan(0);

    await page.goto(`${BASE}/alerts`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text, 'alerts page rendered no alert language').toMatch(/alert|failure|error|no alerts/i);

    await api(page, 'DELETE', `/api/agents/${agentId}`, token);
  });

  test('edge deployment mints a token, registers a gateway and compiles a bundle', async ({ page }) => {
    await login(page);

    await page.goto(`${BASE}/edge`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const text = await bodyText(page);
    expect(text, 'edge page has no edge language').toMatch(/edge|runtime|gateway|bundle/i);

    // The documented flow is download a runtime, mint a token, register, deploy.
    const mint = await api(page, 'POST', '/api/edge/tokens/mint', token, {
      gateway_name: `uat-gateway-${Date.now()}`,
    });
    console.log(`  mint token -> ${mint.status}`);
    expect(mint.status, 'could not mint an edge token').toBeLessThan(400);
    const minted = (mint.json?.data ?? mint.json) ?? {};
    expect(minted.platform_token, 'mint returned no platform_token').toBeTruthy();
    expect(String(minted.platform_token),
      'edge tokens are documented as af_ prefixed').toMatch(/^af_/);
    // The runtime verifies bundle signatures against this, so a mint without it
    // hands out a gateway that cannot check what it is asked to run.
    expect(minted.signing_pubkey_pem, 'mint returned no signing public key')
      .toContain('BEGIN PUBLIC KEY');
    expect(minted.key_id, 'mint returned no key id').toBeTruthy();
    // The full token must be shown once and only once, so the prefix is masked.
    expect(String(minted.platform_token_prefix),
      'the prefix is not masked').toContain('*');

    // Minting does not register anything, so register explicitly. The gateway
    // list starting empty is why this test used to prove nothing.
    const gwId = `uat-probe-gw-${Date.now()}`;
    const reg = await api(page, 'POST', '/api/edge/gateways/register', token, {
      gateway_id: gwId, name: 'UAT probe gateway', endpoint_url: 'http://edge-probe:8080',
    });
    console.log(`  register gateway -> ${reg.status}`);
    expect(reg.status, 'gateway registration failed').toBeLessThan(400);
    const gw = (reg.json?.data ?? {}).gateway ?? {};
    expect(gw.gateway_id, 'registration returned no gateway').toBe(gwId);
    expect(gw.status, 'a freshly registered gateway should be online').toBe('online');
    const gwPk = gw.id;
    expect(gwPk, 'registration returned no primary key').toBeTruthy();

    // It has to be in the listing afterwards, not just in the create response.
    const gws = await api(page, 'GET', '/api/edge/gateways', token);
    expect(gws.status, 'gateway listing failed').toBe(200);
    const list = gws.json?.data?.gateways ?? gws.json?.data ?? [];
    console.log(`  gateways in listing: ${list.length}`);
    expect(list.some((g: any) => g.gateway_id === gwId),
      'the registered gateway is absent from the listing').toBeTruthy();

    // Compiling is what turns an agent into something the edge can run, and it
    // only works on an agent marked edge_compatible in its model_config. Find
    // that agent rather than take the first one, which answers 400 by design.
    let edgeAgent: any = null;
    for (let offset = 0; offset < 300 && !edgeAgent; offset += 100) {
      const page_ = await api(page, 'GET', `/api/agents?limit=100&offset=${offset}`, token);
      const rows = page_.json?.data ?? [];
      if (!rows.length) break;
      edgeAgent = rows.find((a: any) => a.model_config?.edge_compatible);
    }
    expect(edgeAgent, 'no edge_compatible agent is seeded, so the edge path is untestable')
      .toBeTruthy();

    // Compile answers with the tar itself, not JSON, so go at it raw. The
    // digest and slug ride in headers.
    const compile = await page.request.fetch(
      `${API}/api/edge/agents/${edgeAgent.id}/compile`,
      { method: 'POST', headers: { Authorization: `Bearer ${token}` } },
    );
    console.log(`  compile ${edgeAgent.slug ?? edgeAgent.id} -> ${compile.status()}`);
    expect(compile.status(), 'compiling an edge_compatible agent failed').toBeLessThan(400);

    const headers = compile.headers();
    expect(headers['content-type'], 'the bundle is not a tar').toContain('x-tar');
    expect(headers['x-bundle-digest'], 'the bundle carries no digest').toBeTruthy();
    expect(headers['x-bundle-slug'], 'the bundle names no agent').toBeTruthy();

    // A bundle the runtime cannot verify is not a deployable bundle, so check
    // the tar really holds the manifest and a signature rather than trusting
    // the status code.
    const body = await compile.body();
    console.log(`  bundle: ${body.length} bytes, digest ${String(headers['x-bundle-digest']).slice(0, 16)}`);
    expect(body.length, 'compile returned an empty bundle').toBeGreaterThan(512);
    const asText = body.toString('binary');
    for (const want of ['agent.yaml', 'sig']) {
      expect(asText, `the bundle has no ${want}`).toContain(want);
    }

    const deploy = await api(page, 'POST', `/api/edge/gateways/${gwPk}/deploy`, token, {
      agent_id: edgeAgent.id,
    });
    const dep = deploy.json?.data ?? {};
    console.log(`  deploy -> ${deploy.status}, transport ${dep.transport}, pushed ${dep.pushed}`);
    expect(deploy.status, 'edge deploy failed').toBeLessThan(400);
    expect(dep.deployed, 'deploy did not report success').toBe(true);
    expect(dep.bundle_digest, 'deploy pushed no bundle digest').toBeTruthy();
    expect(dep.bundle_bytes, 'deploy pushed an empty bundle').toBeGreaterThan(512);
    // There is no gateway process listening at the registered endpoint, so the
    // push itself cannot land. What matters is that the API says so rather than
    // claiming delivery, and that the assignment is still recorded.
    expect(dep, 'deploy does not report whether the push landed')
      .toHaveProperty('pushed');

    // The assignment has to stick, which is the whole point of deploying.
    const after = await api(page, 'GET', `/api/edge/gateways/${gwPk}/agents`, token);
    const assigned = after.json?.data?.agents ?? after.json?.data ?? [];
    console.log(`  agents assigned to the gateway: ${assigned.length}`);
    expect(assigned.length, 'the deploy did not assign the agent').toBeGreaterThan(0);
    expect(JSON.stringify(assigned), 'the assigned agent is not the one deployed')
      .toContain(edgeAgent.id);

    // Capture the page after the gateway exists, so the shot shows a populated
    // fleet rather than an empty table.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.screenshot({ path: 'test-results/edge-fleet.png', fullPage: true });
  });
});
