import { test, expect } from '@playwright/test';
import { fallbackBlocker } from './uat_helpers/llm_env';

const API = process.env.API_URL || 'http://localhost:8000';
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@abenix.dev';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Admin123456';

async function loginAdmin(request: any): Promise<string> {
  const r = await request.post(`${API}/api/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  expect(r.status()).toBeLessThan(300);
  const body = await r.json();
  const token = body?.data?.access_token || body?.access_token;
  expect(token, 'admin login token').toBeTruthy();
  return token;
}

test.describe.serial('Model fallback — Claude → Azure GPT-4o', () => {
  const WM_API = process.env.WM_API || 'http://localhost:8006';
  const CORRIDOR = process.env.WM_CORRIDOR || 'USGC-NWE';
  const AGENT = 'wingman-arb-analyzer';
  let token: string;
  let blocker: string | null = null;
  let agentModel = '';
  let forced = false;
  const auth = () => ({ Authorization: `Bearer ${token}` });
  const setStatus = (request: any, status: string) =>
    request.post(`${API}/api/admin/model-availability/force-status`, { headers: auth(), data: { model: agentModel, status } });

  test.beforeAll(async ({ request }) => {
    token = await loginAdmin(request);
    blocker = await fallbackBlocker(request, API, token);
  });

  test.beforeEach(() => {
    test.skip(!!blocker, blocker ?? '');
  });

  // a failed step skips the rest of a serial run, the model must not stay forced off
  test.afterAll(async ({ request }) => {
    if (forced) await setStatus(request, 'available');
  });

  test('1. admin can list models, Azure deployments are surfaced', async ({ request }) => {
    const r = await request.get(`${API}/api/llm-models`, { headers: auth() });
    expect(r.status()).toBeLessThan(300);
    const body = await r.json();
    const models: any[] = body?.data?.models || body?.models || [];
    expect(models.length).toBeGreaterThan(5);
    const providers = new Set(models.map((m) => m.provider));
    expect(providers.has('anthropic')).toBeTruthy();
    expect(providers.has('azure'), 'azure provider must appear in model list').toBeTruthy();
    const azureModels = models.filter((m) => m.provider === 'azure').map((m) => m.value);
    console.log('  azure models surfaced:', azureModels);
    expect(azureModels).toContain('azure-gpt-4o');
  });

  test('2. force the Claude model the Wingman agent uses unavailable', async ({ request }) => {
    const health = await request.get(`${WM_API}/health`, { timeout: 10_000 }).catch(() => null);
    test.skip(!health?.ok(), `Wingman API is not reachable at ${WM_API}`);
    const found = await request.get(`${API}/api/agents?slug=${AGENT}`, { headers: auth() });
    const agent = ((await found.json())?.data || [])[0];
    test.skip(!agent, `${AGENT} is not seeded in this tenant`);
    agentModel = agent.model_config?.model || '';
    expect(agentModel, 'the seeded agent runs on Claude').toMatch(/^claude/);

    await request.patch(`${API}/api/admin/llm-pricing/_by-model/${agentModel}`, {
      headers: auth(),
      data: { fallback_to: ['azure-gpt-4o', 'gpt-4o'] },
    }).catch(() => null);
    const r2 = await setStatus(request, 'unavailable');
    expect(r2.status()).toBeLessThan(400);
    forced = true;
  });

  test('3. Wingman arb analysis runs on Azure, not Claude', async ({ request }) => {
    test.setTimeout(6 * 60_000);
    test.skip(!forced, 'step 2 could not force the Wingman agent model off');
    const r = await request.post(`${WM_API}/api/wingman/corridors/${CORRIDOR}/analyze`, { data: { methodology: 'quick' } });
    expect(r.status(), await r.text()).toBeLessThan(400);
    const executionId = (await r.json()).data.execution_id;
    expect(executionId).toBeTruthy();

    let row: any = null;
    await expect.poll(async () => {
      const got = await request.get(`${WM_API}/api/wingman/executions/${executionId}`);
      row = got.ok() ? (await got.json()).data : null;
      return row?.status;
    }, { timeout: 5 * 60_000, intervals: [5_000] }).toMatch(/^(completed|failed)$/);
    const modelUsed = row.model_used;
    console.log('  Wingman ran with model:', modelUsed, row.status);
    expect(row.status, row.error_message || '').toBe('completed');
    expect(modelUsed).toMatch(/^(azure-)?gpt-/);
  });

  test('4. restore claude availability so the cluster goes back to normal', async ({ request }) => {
    test.skip(!forced, 'nothing was forced off');
    const r = await setStatus(request, 'available');
    expect(r.status()).toBeLessThan(400);
    forced = false;
  });
});
