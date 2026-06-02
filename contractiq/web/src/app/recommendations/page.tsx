'use client';

import { useEffect, useState } from 'react';
import { BellRing, ArrowUpRight, ShieldCheck, FileText, Sparkles, Loader2, AlertTriangle } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type Evidence = { kind: string; source: string; value: any };
type Rec = {
  id: string;
  category: 'trade' | 'hedge' | 'monitor';
  title: string;
  rationale: string;
  impact_eur: number;
  counterparty_id: string | null;
  hub: string | null;
  evidence: Evidence[];
  confidence: number;
};

type EngineOut = {
  recommendations?: Rec[];
  summary?: { live_sources?: string[]; needs_configuration?: string[]; warnings?: string[] };
  error?: string;
};

export default function RecommendationsPage() {
  const [out, setOut] = useState<EngineOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<'all' | Rec['category']>('all');

  const run = async () => {
    setLoading(true);
    try {
      const me = await authFetch('/api/contractiq/auth/me').then(r => r.json()).catch(() => null);
      const meData = me?.data ?? me ?? {};
      const tenant_id = meData?.tenant_id || meData?.user?.tenant_id || '';
      const res = await authFetch('/api/contractiq/recommendations/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id }),
      });
      setOut(await res.json());
    } catch (e: any) {
      setOut({ error: String(e), summary: { warnings: [String(e)] } });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { run(); }, []);

  const recs = (out?.recommendations ?? []).filter(r => filter === 'all' || r.category === filter);
  const needsConfig = (out?.summary?.needs_configuration ?? []).length > 0;
  const warnings = out?.summary?.warnings ?? [];

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <Sparkles className="w-7 h-7 text-amber-400" />
            <h1 className="text-3xl font-bold text-white">Recommendations</h1>
          </div>
          <p className="text-slate-400 max-w-3xl">
            Cross-signal recommendations from <span className="font-mono">ciq-recommendation-engine</span>. Pulls live counterparty tiers,
            calls <span className="font-mono">ciq-offtake-forecaster</span> + <span className="font-mono">ciq-price-engine</span>, mixes in
            unacknowledged compliance alerts, and ranks by impact_eur. Every card cites the source signals — no synthesis.
          </p>
        </div>
        <button onClick={run} disabled={loading} className="px-4 py-2 text-sm bg-amber-600/80 hover:bg-amber-600 disabled:bg-slate-700 text-white rounded-md inline-flex items-center gap-2">
          {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Running</> : 'Re-run engine'}
        </button>
      </header>

      <div className="flex gap-2 mb-6">
        {(['all', 'trade', 'hedge', 'monitor'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-md text-xs border ${filter === f ? 'bg-amber-500/15 text-amber-200 border-amber-500/40' : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:text-white'}`}
          >
            {f}
          </button>
        ))}
      </div>

      {needsConfig && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 p-4 mb-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-amber-200">Upstream agents need configuration</p>
            <p className="text-amber-300/80 text-xs mt-1">Missing: <span className="font-mono">{out?.summary?.needs_configuration?.join(', ')}</span>. The engine only shows recs whose dependencies are live.</p>
          </div>
        </div>
      )}
      {warnings.length > 0 && !needsConfig && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-6 text-xs text-amber-300/90">
          {warnings.map((w, i) => <div key={i}>• {w}</div>)}
        </div>
      )}

      {loading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center">
          <Loader2 className="w-6 h-6 animate-spin text-amber-400 mx-auto mb-2" />
          <p className="text-sm text-slate-400">Running multi-agent recommendation engine...</p>
        </div>
      )}

      {!loading && recs.length === 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center">
          <BellRing className="w-6 h-6 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-400">No recommendations from the engine right now.</p>
          <p className="text-xs text-slate-600 mt-1">The engine only emits cards when live signals (tier, fair-value z, alerts) cross threshold.</p>
        </div>
      )}

      <div className="space-y-3">
        {recs.map(r => (
          <div key={r.id} className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
            <div className="flex items-baseline justify-between mb-2">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${
                  r.category === 'trade' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' :
                  r.category === 'hedge' ? 'bg-violet-500/10 text-violet-300 border-violet-500/30' :
                                            'bg-cyan-500/10 text-cyan-300 border-cyan-500/30'
                }`}>{r.category}</span>
                {r.title}
              </h3>
              <span className="text-xs font-mono text-slate-500">conf {(r.confidence * 100).toFixed(0)}%</span>
            </div>
            <p className="text-sm text-slate-300 mb-3">{r.rationale}</p>
            <div className="flex flex-wrap gap-2 mb-3">
              {r.evidence.map((ev, i) => (
                <span key={i} className="text-[10px] font-mono px-2 py-0.5 rounded border border-slate-800 bg-slate-950/60 text-slate-400">
                  {ev.kind}:{ev.source}
                </span>
              ))}
            </div>
            <div className="flex items-baseline justify-between pt-3 border-t border-slate-800/60">
              <p className="text-xs text-slate-500">Impact <span className="font-mono text-white text-sm">€{r.impact_eur.toLocaleString()}</span></p>
              <button className="text-xs text-amber-300 inline-flex items-center gap-1 hover:text-amber-200">
                Open <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
