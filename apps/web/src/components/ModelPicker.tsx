'use client';

import { useEffect, useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface RawModel {
  value: string;
  label: string;
  provider: string;
  is_deprecated?: boolean;
  capabilities?: Record<string, boolean>;
  status?: string;
  provider_available?: boolean;
  provider_unavailable_reason?: string | null;
  served_by?: string;
  subscription_served?: boolean;
  subscription_remapped_to?: string | null;
}

interface SubscriptionState {
  enabled: boolean;
  token_set: boolean;
  active: boolean;
  exclusive: boolean;
  default_model: string;
}

interface ProviderInfo {
  configured: boolean;
  reason?: string | null;
}

type ProviderMap = Record<string, ProviderInfo>;

interface ModelPickerProps {
  value: string;
  onChange: (model: string) => void;
  capabilities?: string[];
  label?: string;
  includeUnavailable?: boolean;
}

// Canonical group order + display names.
const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic Claude',
  azure: 'Azure OpenAI',
  google: 'Google Gemini',
  openai: 'OpenAI',
  claude_subscription: 'Claude subscription',
};
const PROVIDER_ORDER = ['anthropic', 'azure', 'google', 'openai'];

function normalizeProvider(m: RawModel): string {
  const declared = (m.provider || '').toLowerCase();
  if (declared) return declared;
  const v = (m.value || '').toLowerCase();
  if (v.startsWith('azure-')) return 'azure';
  if (v.startsWith('claude')) return 'anthropic';
  if (v.startsWith('gpt')) return 'openai';
  if (v.startsWith('gemini')) return 'google';
  return 'other';
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function fetchJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API_URL}${path}`, { headers: authHeaders() });
    if (!r.ok) return null;
    const body = await r.json();
    return (body?.data ?? body) as T;
  } catch {
    return null;
  }
}

export function ModelPicker({
  value,
  onChange,
  capabilities,
  label,
  includeUnavailable = false,
}: ModelPickerProps) {
  const [models, setModels] = useState<RawModel[] | null>(null);
  const [providers, setProviders] = useState<ProviderMap | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      fetchJSON<ProviderMap>('/api/llm/available-providers'),
      fetchJSON<{ models: RawModel[]; subscription?: SubscriptionState } | RawModel[]>(
        '/api/llm-models',
      ),
    ]).then(([prov, mods]) => {
      if (!alive) return;
      setProviders(prov || {});
      const list = Array.isArray(mods) ? mods : (mods?.models || []);
      setSubscription(Array.isArray(mods) ? null : (mods?.subscription ?? null));
      setModels(list);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const { configuredProviders, groups, flatAvailable } = useMemo(() => {
    const prov = providers || {};
    const configuredProviders = Object.entries(prov)
      .filter(([, p]) => p?.configured)
      .map(([name]) => name);

    const groups = new Map<string, RawModel[]>();
    const all = models || [];
    for (const m of all) {
      const p = normalizeProvider(m);
      // Hide models whose provider isn't configured (unless includeUnavailable).
      const provOk = prov[p]?.configured !== false; // unknown providers default to allowed
      if (!includeUnavailable && !provOk) continue;
      // Capability filter (e.g. 'tools', 'vision').
      if (capabilities && capabilities.length) {
        const caps = m.capabilities || {};
        const missing = capabilities.some((c) => !caps[c]);
        if (missing) continue;
      }
      const bucket = groups.get(p) || [];
      bucket.push(m);
      groups.set(p, bucket);
    }
    const flatAvailable: RawModel[] = [];
    for (const p of PROVIDER_ORDER) {
      const b = groups.get(p);
      if (b) flatAvailable.push(...b);
    }
    // Any extra non-canonical providers go last.
    for (const [p, b] of groups) {
      if (!PROVIDER_ORDER.includes(p)) flatAvailable.push(...b);
    }
    return { configuredProviders, groups, flatAvailable };
  }, [models, providers, capabilities, includeUnavailable]);

  const visibleProviderGroups = useMemo(() => {
    const order = [...PROVIDER_ORDER, ...[...groups.keys()].filter((p) => !PROVIDER_ORDER.includes(p))];
    return order.filter((p) => (groups.get(p)?.length || 0) > 0);
  }, [groups]);

  // 0-provider disabled state.
  if (!loading && configuredProviders.length === 0 && (providers !== null)) {
    return (
      <div data-testid="model-picker" data-provider-count="0">
        {label && (
          <label className="text-[10px] text-slate-400 mb-1 block">
            <span className="font-mono text-slate-500">{label}</span>
          </label>
        )}
        <div className="relative">
          <select
            disabled
            value=""
            className="w-full px-3 py-2 bg-slate-900/30 border border-slate-800 rounded-lg text-xs text-slate-500 cursor-not-allowed appearance-none pr-8"
          >
            <option value="">No LLM provider configured</option>
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-700 pointer-events-none" />
        </div>
        <p className="text-[10px] text-amber-400 mt-1">
          No LLM provider configured — contact your admin
        </p>
      </div>
    );
  }

  const onlyOne = visibleProviderGroups.length === 1;
  const onlyProv = onlyOne ? visibleProviderGroups[0] : null;

  // Info text: X providers available OR "Only Azure OpenAI available — Claude and Gemini are unavailable in this tenant".
  let infoText = '';
  if (!loading && providers) {
    const allCanonical = PROVIDER_ORDER.filter((p) => p in providers);
    const missing = allCanonical
      .filter((p) => providers[p]?.configured === false)
      .map((p) => PROVIDER_LABELS[p] || p);
    if (configuredProviders.length === 1) {
      const onlyName = PROVIDER_LABELS[configuredProviders[0]] || configuredProviders[0];
      if (missing.length > 0) {
        // "Claude and Gemini" / "Claude, Gemini and OpenAI"
        const others = missing.filter((m) => m !== onlyName);
        // Trim long labels for the inline note.
        const short = others.map((s) =>
          s.replace('Anthropic Claude', 'Claude').replace('Google Gemini', 'Gemini').replace('Azure OpenAI', 'Azure').replace('OpenAI', 'OpenAI'),
        );
        const joined =
          short.length <= 1
            ? short.join('')
            : short.slice(0, -1).join(', ') + ' and ' + short.slice(-1);
        infoText = `Only ${onlyName} available — ${joined} ${others.length === 1 ? 'is' : 'are'} unavailable in this tenant`;
      } else {
        infoText = '1 provider available';
      }
    } else {
      infoText = `${configuredProviders.length} providers available`;
    }
  }

  // Render option with optional unavailable badge text.
  const renderOption = (m: RawModel) => {
    const p = normalizeProvider(m);
    const provOk = providers ? providers[p]?.configured !== false : true;
    const dep = m.is_deprecated;
    // A model the subscription serves is reachable even when its own
    // provider has no API key configured.
    const unavailable = !provOk && !m.subscription_served;
    let suffix = '';
    if (dep) suffix += ' (deprecated)';
    if (m.subscription_served) {
      suffix += m.subscription_remapped_to
        ? ` — via subscription as ${m.subscription_remapped_to}`
        : ' — via subscription';
    }
    if (unavailable) suffix += ' — unavailable';
    return (
      <option key={m.value} value={m.value} disabled={unavailable}>
        {m.label}
        {suffix}
      </option>
    );
  };

  return (
    <div data-testid="model-picker" data-provider-count={configuredProviders.length}>
      {label && (
        <label className="text-[10px] text-slate-400 mb-1 block">
          <span className="font-mono text-slate-500">{label}</span>
        </label>
      )}
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={loading || flatAvailable.length === 0}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 appearance-none pr-8 disabled:opacity-60 disabled:cursor-not-allowed"
          data-testid="model-picker-select"
        >
          {loading && <option value={value || ''}>Loading models…</option>}
          {!loading && flatAvailable.length === 0 && (
            <option value="">No models match the requested capabilities</option>
          )}
          {!loading && onlyOne && onlyProv &&
            (groups.get(onlyProv) || []).map(renderOption)}
          {!loading && !onlyOne &&
            visibleProviderGroups.map((p) => (
              <optgroup key={p} label={PROVIDER_LABELS[p] || p}>
                {(groups.get(p) || []).map(renderOption)}
              </optgroup>
            ))}
        </select>
        <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
      </div>
      {subscription?.active && (
        <p
          className="text-[10px] text-emerald-400 mt-1"
          data-testid="model-picker-subscription"
        >
          Claude subscription active
          {subscription.exclusive
            ? ` — every model runs on ${subscription.default_model} at no per-token cost`
            : ' — Claude models run on the subscription at no per-token cost'}
        </p>
      )}
      {infoText && (
        <p className="text-[10px] text-slate-500 mt-1" data-testid="model-picker-info">
          {infoText}
        </p>
      )}
    </div>
  );
}

export default ModelPicker;
