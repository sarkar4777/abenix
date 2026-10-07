'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ChevronDown } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface RawModel {
  value: string;
  label: string;
  provider: string;
  is_deprecated?: boolean;
  capabilities?: Record<string, boolean>;
  provider_available?: boolean;
  subscription_served?: boolean;
  subscription_remapped_to?: string | null;
}

interface SubscriptionState {
  active: boolean;
  exclusive: boolean;
  default_model: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic Claude',
  google: 'Google Gemini',
  openai: 'OpenAI',
  azure: 'Azure OpenAI',
};
const PROVIDER_ORDER = ['anthropic', 'google', 'openai', 'azure'];

function providerOf(m: RawModel): string {
  const declared = (m.provider || '').toLowerCase();
  if (declared) return declared;
  const v = m.value.toLowerCase();
  if (v.startsWith('claude')) return 'anthropic';
  if (v.startsWith('gemini')) return 'google';
  if (v.startsWith('gpt')) return 'openai';
  if (v.startsWith('azure-')) return 'azure';
  return 'other';
}

// dated ids and their short aliases share a label, keep one per label
export function dedupeAliases(models: RawModel[], current: string): RawModel[] {
  const byKey = new Map<string, RawModel>();
  for (const m of models) {
    const key = `${providerOf(m)}|${(m.label || m.value.replace(/-\d{8}$/, '')).toLowerCase()}`;
    const prev = byKey.get(key);
    if (!prev) { byKey.set(key, m); continue; }
    if (m.value === current) { byKey.set(key, m); continue; }
    if (prev.value === current) continue;
    // prefer the short alias over the dated snapshot
    if (/-\d{8}$/.test(prev.value) && !/-\d{8}$/.test(m.value)) byKey.set(key, m);
  }
  return [...byKey.values()];
}

export default function VisionModelPicker({
  value, onChange, isAdmin,
}: {
  value: string;
  onChange: (model: string) => void;
  isAdmin: boolean;
}) {
  const [models, setModels] = useState<RawModel[] | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionState | null>(null);

  useEffect(() => {
    let alive = true;
    void apiFetch<{ models: RawModel[]; subscription?: SubscriptionState }>('/api/llm-models', { silent: true })
      .then(r => {
        if (!alive) return;
        setModels(r.data?.models || []);
        setSubscription(r.data?.subscription ?? null);
      });
    return () => { alive = false; };
  }, []);

  const groups = useMemo(() => {
    const usable = (models || []).filter(m =>
      m.capabilities?.vision
      && !m.is_deprecated
      && (m.provider_available !== false || m.subscription_served),
    );
    const deduped = dedupeAliases(usable, value);
    const out = new Map<string, RawModel[]>();
    for (const m of deduped) {
      const p = providerOf(m);
      out.set(p, [...(out.get(p) || []), m]);
    }
    return [...PROVIDER_ORDER, ...[...out.keys()].filter(p => !PROVIDER_ORDER.includes(p))]
      .filter(p => out.has(p))
      .map(p => ({ provider: p, models: out.get(p) || [] }));
  }, [models, value]);

  const known = groups.some(g => g.models.some(m => m.value === value));
  const loading = models === null;

  // a default this server cannot reach would only fail later, pick one it can
  useEffect(() => {
    if (!loading && value && !known && groups.length > 0) onChange(groups[0].models[0].value);
  }, [loading, value, known, groups, onChange]);

  const optionText = (m: RawModel) => {
    if (!m.subscription_served) return m.label;
    return m.subscription_remapped_to
      ? `${m.label} (runs as ${m.subscription_remapped_to} on the subscription)`
      : `${m.label} (subscription)`;
  };

  return (
    <div data-testid="model-picker">
      <div className="relative">
        <select
          value={value}
          onChange={e => onChange(e.target.value)}
          disabled={loading || groups.length === 0}
          aria-label="Vision model"
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 appearance-none pr-8 disabled:opacity-60"
          data-testid="model-picker-select"
        >
          {loading && <option value={value}>Loading models…</option>}
          {!loading && groups.length === 0 && <option value="">No vision model is available</option>}
          {!loading && !known && value && <option value={value}>{value}</option>}
          {!loading && groups.map(g => (
            <optgroup key={g.provider} label={PROVIDER_LABELS[g.provider] || g.provider}>
              {g.models.map(m => <option key={m.value} value={m.value}>{optionText(m)}</option>)}
            </optgroup>
          ))}
        </select>
        <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
      </div>
      {subscription?.active && (
        <p className="text-[10px] text-emerald-400 mt-1" data-testid="model-picker-subscription">
          {subscription.exclusive
            ? `Claude subscription active. Every model runs on ${subscription.default_model} at no per-token cost`
            : 'Claude subscription active. Claude models run on it at no per-token cost'}
        </p>
      )}
      <p className="text-[10px] text-slate-500 mt-1">
        {isAdmin
          ? <Link href="/admin/llm-settings" className="text-violet-300 hover:text-violet-200 underline underline-offset-2">Manage models in LLM Settings</Link>
          : 'Your admin manages this list'}
      </p>
    </div>
  );
}
