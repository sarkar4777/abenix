'use client';

/**
 * /trends — VoC (Voice of Customer) dashboard. Surfaces clusters the
 * Trend Mining pipeline filed: SKU/carrier/policy anomalies across the
 * last 72h of cases.
 */
import { useState } from 'react';
import { Loader2, TrendingUp, PlayCircle, RefreshCw } from 'lucide-react';
import { useResolveAIFetch, resolveAIPost } from '@/lib/api';

type Insight = {
  id?: string;
  cluster_id?: string;
  signal?: string;
  case_count?: number;
  anomaly_score?: number;
  example_case_ids?: string[];
  suggested_action?: string;
  status?: 'open' | 'acknowledged' | 'resolved';
  created_at?: string;
};

export default function TrendsPage() {
  const { data, error, isLoading, refetch } = useResolveAIFetch<Insight[]>(
    '/api/resolveai/trends/insights',
  );
  const insights = Array.isArray(data) ? data : [];
  const [mining, setMining] = useState(false);
  const [mineErr, setMineErr] = useState<string | null>(null);

  async function mine() {
    setMining(true);
    setMineErr(null);
    const { error: err } = await resolveAIPost('/api/resolveai/trends/mine');
    if (err) setMineErr(err);
    setMining(false);
    void refetch();
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · VoC</p>
          <h1 className="text-2xl font-bold text-white">Voice of Customer — Trend Mining</h1>
          <p className="text-sm text-slate-400 mt-1">
            Nightly job clusters the last 72h of cases and files insights when an
            SKU/carrier/policy spikes. Click below to run it now.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => void refetch()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-300 text-xs disabled:opacity-60"
            title="Refresh insights"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          <button
            onClick={() => void mine()}
            disabled={mining}
            data-testid="run-trend-mining"
            className="inline-flex items-center gap-2 px-4 py-2 bg-violet-500 hover:bg-violet-400 text-slate-950 text-sm font-semibold rounded-lg disabled:opacity-60"
          >
            {mining ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
            Mine now
          </button>
        </div>
      </div>

      {(error || mineErr) && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          {error ? `Couldn't load insights: ${error}` : `Mining run failed: ${mineErr}`}. Click Refresh to retry.
        </div>
      )}

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" data-testid="insights-list">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-violet-400" /> Open insights ({insights.length})
        </h2>
        {isLoading && insights.length === 0 ? (
          <p className="text-xs text-slate-500">Loading insights…</p>
        ) : insights.length === 0 ? (
          <div className="py-8 text-center">
            <p className="text-sm text-slate-400">No VoC insights yet.</p>
            <p className="text-xs text-slate-500 mt-2">
              Close a few cases first (the miner needs at least a handful of cases
              in the last 72h to cluster) — then click <strong>Mine now</strong>.
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {insights.map((i, idx) => (
              <li
                key={i.id || `insight-${idx}`}
                className="rounded-lg border border-slate-700/40 bg-slate-900/30 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-white font-medium">{i.signal || '(unnamed signal)'}</p>
                    <p className="text-xs text-slate-400 mt-1">{i.suggested_action || ''}</p>
                    <p className="text-[10px] text-slate-500 mt-2 font-mono">
                      {Number(i.case_count ?? 0)} cases · anomaly{' '}
                      {Number(i.anomaly_score ?? 0).toFixed(2)} · cluster{' '}
                      {i.cluster_id ?? '—'}
                    </p>
                  </div>
                  {i.status && (
                    <span
                      className={`shrink-0 px-2 py-0.5 rounded border text-[10px] ${
                        i.status === 'open'
                          ? 'bg-violet-500/10 border-violet-500/40 text-violet-300'
                          : i.status === 'acknowledged'
                          ? 'bg-slate-500/10 border-slate-500/40 text-slate-300'
                          : 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                      }`}
                    >
                      {i.status}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
