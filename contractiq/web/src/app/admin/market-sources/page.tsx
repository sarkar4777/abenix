'use client';

import { useEffect, useState } from 'react';
import { Database, RefreshCw, Loader2 } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Source = {
  slug: string;
  name: string;
  provider: string;
  asset_class: string;
  instrument_kind: string;
  default_unit?: string;
  config_schema?: Record<string, string>;
  configured: boolean;
  enabled?: boolean;
  last_synced_at?: string | null;
  last_value?: any;
};

export default function MarketSourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const r = await fetch(`${API_URL}/api/contractiq/market/sources`, { headers: { Authorization: `Bearer ${token}` } });
    setSources((await r.json()).data || []);
  };
  useEffect(() => { load(); }, []);

  const sync = async (slug: string) => {
    setBusy(slug);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/market/sources/${slug}/snapshot?history_days=30`, { headers: { Authorization: `Bearer ${token}` } });
      await load();
    } finally { setBusy(null); }
  };

  const byClass: Record<string, Source[]> = {};
  sources.forEach(s => { (byClass[s.asset_class] ||= []).push(s); });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <div className="flex items-center gap-3 mb-6">
          <Database className="w-7 h-7 text-cyan-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Market Data Sources</h1>
            <p className="text-sm text-slate-400">Configurable feeds. Each source is a reusable adapter — same registry powers any app on the platform.</p>
          </div>
        </div>

        {Object.entries(byClass).sort().map(([cls, list]) => (
          <div key={cls} className="mb-6">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">{cls} · {list.length} sources</div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              {list.map(s => (
                <div key={s.slug} className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/80">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-white truncate">{s.name}</div>
                      <div className="text-[10px] text-slate-500 font-mono truncate">{s.slug}</div>
                    </div>
                    <button
                      onClick={() => sync(s.slug)}
                      disabled={busy === s.slug}
                      className="px-2 py-1 text-[10px] rounded bg-cyan-500/20 border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-50 flex items-center gap-1"
                    >
                      {busy === s.slug ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                      Sync
                    </button>
                  </div>
                  <div className="flex items-center gap-2 mt-2 text-[10px]">
                    <span className="px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-400">{s.instrument_kind}</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-400">{s.provider}</span>
                    {s.configured && s.enabled !== false && <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300">live</span>}
                  </div>
                  {s.last_value && (
                    <div className="mt-2 text-xs text-slate-300">
                      latest: {s.last_value.value} <span className="text-[10px] text-slate-500">{s.default_unit}</span>
                      <div className="text-[10px] text-slate-500">{s.last_synced_at}</div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
