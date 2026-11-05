import type { APIRequestContext } from '@playwright/test';

// why this stack cannot prove a fallback to Azure, null when it can
export async function fallbackBlocker(request: APIRequestContext, api: string, token: string): Promise<string | null> {
  const headers = { Authorization: `Bearer ${token}` };
  const providers = (await (await request.get(`${api}/api/llm/available-providers`, { headers })).json())?.data ?? {};
  if (!providers.azure?.configured) {
    return `Azure OpenAI is not configured here (${providers.azure?.reason || 'no key'}), so there is nothing to fall back to`;
  }
  const sub = (await (await request.get(`${api}/api/admin/settings/subscription`, { headers })).json())?.data;
  if (sub?.active) {
    return `the Claude subscription is on (exclusive ${sub.exclusive}), it serves Claude models whatever their status, so no fallback runs`;
  }
  return null;
}
