'use client';

import { useEffect, useRef, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ModelOption {
  value: string;
  label: string;
  provider: string;
  is_deprecated: boolean;
  deprecated_at: string | null;
  migration_hint: string | null;
  input_per_m: number;
  output_per_m: number;
  capabilities: Record<string, boolean>;
  fallback_to: string[];
  status: 'available' | 'unavailable' | 'degraded' | string;
  last_checked_at: string | null;
  last_error: string | null;
}

export const FALLBACK_MODELS: ModelOption[] = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5', provider: 'anthropic', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 3, output_per_m: 15, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5', provider: 'anthropic', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 0.8, output_per_m: 4, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
  { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 2.5, output_per_m: 10, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 0.15, output_per_m: 0.6, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
  { value: 'azure-gpt-4o', label: 'Azure GPT-4o', provider: 'azure', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 2.5, output_per_m: 10, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', provider: 'google', is_deprecated: false, deprecated_at: null, migration_hint: null, input_per_m: 0.1, output_per_m: 0.4, capabilities: { tools: true }, fallback_to: [], status: 'available', last_checked_at: null, last_error: null },
];

let _cache: ModelOption[] | null = null;
let _cacheAt = 0;
const TTL_MS = 60_000;
let _inflight: Promise<ModelOption[]> | null = null;

async function fetchModels(): Promise<ModelOption[]> {
  const now = Date.now();
  if (_cache && now - _cacheAt < TTL_MS) return _cache;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const token = typeof window !== 'undefined' ? window.localStorage.getItem('access_token') : null;
      const resp = await fetch(`${API_URL}/api/llm-models`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error('llm-models fetch failed');
      const body = await resp.json();
      const models = (body?.data?.models || body?.models) as ModelOption[];
      if (!Array.isArray(models) || models.length === 0) throw new Error('empty model list');
      _cache = models;
      _cacheAt = now;
      return models;
    } catch {
      return FALLBACK_MODELS;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

export function useModels(): { models: ModelOption[]; loading: boolean } {
  const [models, setModels] = useState<ModelOption[]>(_cache || FALLBACK_MODELS);
  const [loading, setLoading] = useState(!_cache);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    fetchModels().then((m) => {
      if (mounted.current) {
        setModels(m);
        setLoading(false);
      }
    });
    return () => { mounted.current = false; };
  }, []);
  return { models, loading };
}

export function useSelectableModels(includeDeprecated = false): ModelOption[] {
  const { models } = useModels();
  const visible = models.filter((m) => includeDeprecated || !m.is_deprecated);
  // Always expose the Azure fallback model so the builder can pin to Azure
  // even when the registry doesn't ship it (e.g. local-only or partial seed).
  if (!visible.some((m) => m.value === 'azure-gpt-4o')) {
    const az = FALLBACK_MODELS.find((m) => m.value === 'azure-gpt-4o');
    if (az) visible.push(az);
  }
  return visible;
}
