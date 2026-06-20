'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, AlertOctagon, ArrowRight } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ResolveResult {
  requested: string;
  effective: string;
  chain: string[];
  reason: string;
  swap: boolean;
  requested_status: string;
  requested_is_deprecated: boolean;
  requested_last_error: string | null;
  migration_hint: string | null;
}

const _cache = new Map<string, { at: number; value: ResolveResult | null }>();
const TTL_MS = 30_000;
const _inflight = new Map<string, Promise<ResolveResult | null>>();

async function fetchResolve(model: string, needsTools: boolean): Promise<ResolveResult | null> {
  if (!model) return null;
  const key = `${model}|${needsTools ? 1 : 0}`;
  const now = Date.now();
  const cached = _cache.get(key);
  if (cached && now - cached.at < TTL_MS) return cached.value;
  if (_inflight.has(key)) return _inflight.get(key)!;
  const promise = (async () => {
    try {
      const token = typeof window !== 'undefined' ? window.localStorage.getItem('access_token') : null;
      const qs = `model=${encodeURIComponent(model)}${needsTools ? '&needs_tools=true' : ''}`;
      const resp = await fetch(`${API_URL}/api/llm-models/resolve?${qs}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) return null;
      const body = await resp.json();
      const v: ResolveResult = body?.data || body;
      _cache.set(key, { at: now, value: v });
      return v;
    } catch {
      return null;
    } finally {
      _inflight.delete(key);
    }
  })();
  _inflight.set(key, promise);
  return promise;
}

interface Props {
  model: string;
  needsTools?: boolean;
  compact?: boolean;
}

export function ModelStatusBanner({ model, needsTools = false, compact = false }: Props) {
  const [r, setR] = useState<ResolveResult | null>(null);
  useEffect(() => {
    let alive = true;
    setR(null);
    fetchResolve(model, needsTools).then((v) => { if (alive) setR(v); });
    return () => { alive = false; };
  }, [model, needsTools]);

  if (!r) return null;

  const isDeprecated = r.requested_is_deprecated;
  const isDown = r.requested_status !== 'available' && !isDeprecated;
  const swap = r.swap && r.effective !== r.requested;

  if (!isDeprecated && !isDown && !swap) return null;

  const tone = isDeprecated
    ? 'bg-red-950/40 border-red-700/60 text-red-200'
    : 'bg-amber-950/40 border-amber-700/60 text-amber-200';
  const Icon = isDeprecated ? AlertOctagon : AlertTriangle;
  const title = isDeprecated
    ? `${r.requested} is deprecated`
    : isDown
      ? `${r.requested} is ${r.requested_status}`
      : `Will not run as ${r.requested}`;

  return (
    <div className={`mt-2 px-3 py-2 rounded-md border text-[11px] flex items-start gap-2 ${tone}`}>
      <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="font-medium">{title}</div>
        {!compact && (
          <div className="mt-0.5 opacity-90">
            {swap ? (
              <span className="inline-flex items-center gap-1">
                Runs will use <span className="font-mono">{r.requested}</span>
                <ArrowRight className="w-3 h-3" />
                <span className="font-mono">{r.effective}</span>
                {r.reason !== 'primary' && (
                  <span className="opacity-70"> ({r.reason.replace(/_/g, ' ')})</span>
                )}
              </span>
            ) : isDeprecated && r.migration_hint ? (
              <span>Migration hint: {r.migration_hint}</span>
            ) : r.requested_last_error ? (
              <span className="opacity-80">Last error: {r.requested_last_error.slice(0, 120)}</span>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default ModelStatusBanner;
