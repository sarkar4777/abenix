'use client';


import { useCallback, useEffect, useRef, useState } from 'react';

export interface ApiResult<T, M = Record<string, unknown>> {
  data: T | null;
  meta: M | null;
  error: string | null;
  isLoading: boolean;
  refetch: () => Promise<void>;
}

type Envelope<T, M> = {
  data?: T;
  meta?: M;
  error?: string | { message?: string } | null;
  detail?: string;
};

async function fetchOnce<T, M>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T | null; meta: M | null; error: string | null }> {
  try {
    const res = await fetch(path, { ...init, cache: 'no-store' });
    let body: Envelope<T, M> = {};
    try {
      body = (await res.json()) as Envelope<T, M>;
    } catch {
      // non-JSON responses (rare) — fall through with an empty body
    }
    if (!res.ok) {
      const errMsg =
        (typeof body.error === 'string' ? body.error : body.error?.message) ||
        body.detail ||
        `HTTP ${res.status}`;
      return { data: null, meta: null, error: errMsg };
    }
    // Some endpoints (POST /cases, /cases/{id}/take-over, …) return the
    // raw payload without the {data, meta} envelope. Treat any 2xx
    // body that doesn't carry an explicit `data` field as the payload
    // itself so callers like `Try It Now` can read `data.id`.
    const hasEnvelope =
      body && typeof body === 'object' &&
      ('data' in body || 'meta' in body || 'error' in body);
    return {
      data: (hasEnvelope ? (body.data ?? null) : (body as unknown)) as T | null,
      meta: (body.meta ?? null) as M | null,
      error: null,
    };
  } catch (e) {
    return { data: null, meta: null, error: (e as Error).message || 'Network error' };
  }
}

export function useResolveAIFetch<T, M = Record<string, unknown>>(
  path: string | null,
  options?: { autoRefresh?: number },
): ApiResult<T, M> {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<M | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setLoading] = useState<boolean>(Boolean(path));
  const inflightRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    if (!path) {
      setLoading(false);
      return;
    }
    // Guard against StrictMode double-invoke + parallel refetches on
    // the same path. If the same path is already in flight, don't
    // kick off another fetch — the in-flight one will update state.
    if (inflightRef.current === path) return;
    inflightRef.current = path;
    setLoading(true);
    let res = await fetchOnce<T, M>(path);
    // One retry on 5xx / transient network — these show up during
    // rolling deploys and when port-forwards bounce.
    if (res.error && /HTTP 5\d\d|Network error|Failed to fetch/i.test(res.error)) {
      await new Promise((r) => setTimeout(r, 400));
      res = await fetchOnce<T, M>(path);
    }
    inflightRef.current = null;
    setData(res.data);
    setMeta(res.meta);
    setError(res.error);
    setLoading(false);
  }, [path]);

  useEffect(() => {
    void load();
    if (options?.autoRefresh && options.autoRefresh > 0) {
      const id = setInterval(() => void load(), options.autoRefresh);
      return () => clearInterval(id);
    }
    return undefined;
  }, [load, options?.autoRefresh]);

  return { data, meta, error, isLoading, refetch: load };
}

/**
 * Fire-and-forget POST helper with the same envelope handling and a
 * one-retry on transient failure. Returns `{data, error}` so callers
 * can surface the error inline without throwing.
 */
export async function resolveAIPost<T = unknown>(
  path: string,
  body?: unknown,
): Promise<{ data: T | null; error: string | null }> {
  const init: RequestInit = {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  };
  let res = await fetchOnce<T, Record<string, unknown>>(path, init);
  if (res.error && /HTTP 5\d\d|Network error|Failed to fetch/i.test(res.error)) {
    await new Promise((r) => setTimeout(r, 400));
    res = await fetchOnce<T, Record<string, unknown>>(path, init);
  }
  return { data: res.data, error: res.error };
}
