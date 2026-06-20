// Pages through /api/agents (capped at limit=100 per call) and returns every
// row. Some tenants have 150+ agents so a single ?limit=500 request silently
// 422s — callers must paginate.
//
// Usage:
//   const { agents, total } = await fetchAllAgents();
// Or with progress:
//   await fetchAllAgents({ onProgress: (loaded, total) => ... });

import { API_URL } from './api-client';

const PAGE_SIZE = 100;

interface FetchAllAgentsOptions {
  token?: string | null;
  query?: string;            // extra query string, no leading ?
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}

interface FetchAllAgentsResult<T = any> {
  agents: T[];
  total: number;
}

function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

export async function fetchAllAgents<T = any>(
  options: FetchAllAgentsOptions = {},
): Promise<FetchAllAgentsResult<T>> {
  const token = options.token ?? getStoredToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const extra = options.query ? `&${options.query.replace(/^[?&]/, '')}` : '';
  const out: T[] = [];
  let offset = 0;
  let total = 0;

  while (true) {
    const url = `${API_URL}/api/agents?limit=${PAGE_SIZE}&offset=${offset}${extra}`;
    const res = await fetch(url, { headers, signal: options.signal });
    if (!res.ok) {
      // Bubble up a sensible empty result rather than crashing the page.
      return { agents: out, total: out.length };
    }
    const body = await res.json().catch(() => ({}));
    const page: T[] = Array.isArray(body?.data) ? body.data : [];
    const metaTotal = Number(body?.meta?.total);
    if (Number.isFinite(metaTotal)) total = metaTotal;

    out.push(...page);
    options.onProgress?.(out.length, total || out.length);

    // Stop when the API gave us a short page (last page) or we've hit total.
    if (page.length < PAGE_SIZE) break;
    if (total && out.length >= total) break;
    offset += PAGE_SIZE;

    // Safety: never loop more than 50 pages (5000 agents).
    if (offset > PAGE_SIZE * 50) break;
  }

  return { agents: out, total: total || out.length };
}
