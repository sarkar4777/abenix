'use client';

import { Star, ShieldAlert, RefreshCw } from 'lucide-react';
import { useResolveAIFetch } from '@/lib/api';

type QAScore = {
  case_id: string;
  predicted_csat: number;
  source: string;
  predicted_nps_bucket: 'detractor' | 'passive' | 'promoter' | null;
  red_flags: string[];
  created_at: string;
  subject?: string;
};

type QAMeta = {
  total?: number;
  predicted_avg?: number;
  survey_avg?: number;
  agent_rating_avg?: number;
  nps_buckets?: { detractor?: number; passive?: number; promoter?: number };
};

export default function QAPage() {
  const { data, meta, error, isLoading, refetch } = useResolveAIFetch<QAScore[], QAMeta>(
    '/api/resolveai/qa/scores',
  );
  const scores = Array.isArray(data) ? data : [];
  const total = meta?.total ?? scores.length;
  const predictedAvg = meta?.predicted_avg ?? 0;
  const promoters = meta?.nps_buckets?.promoter ?? 0;
  const detractors = meta?.nps_buckets?.detractor ?? 0;

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · QA</p>
          <h1 className="text-2xl font-bold text-white">CSAT Prediction & QA Review</h1>
          <p className="text-sm text-slate-400 mt-1">
            Every closed case passes through the Post-Resolution QA pipeline. Predicted
            detractors get proactive outreach instead of an NPS email.
          </p>
        </div>
        <button
          onClick={() => void refetch()}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-300 text-xs disabled:opacity-60"
          title="Refresh scores"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          Couldn&apos;t load QA scores: {error}. The rest of ResolveAI is still
          reachable — try <button className="underline" onClick={() => void refetch()}>refresh</button>.
        </div>
      )}

      {isLoading && !error ? (
        <p className="text-xs text-slate-500">Loading QA scores…</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-3">
            <Stat label="Cases scored" value={total} />
            <Stat label="Avg predicted CSAT" value={Number(predictedAvg).toFixed(2)} accent="emerald" />
            <Stat label="Promoters" value={promoters} accent="emerald" />
            <Stat label="Detractors" value={detractors} accent="rose" />
          </div>

          <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" data-testid="qa-scores">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <Star className="w-4 h-4 text-amber-400" /> Recent QA scores
            </h2>
            {scores.length === 0 ? (
              <div className="py-10 text-center">
                <p className="text-sm text-slate-400">No cases have been QA-scored yet.</p>
                <p className="text-xs text-slate-500 mt-2">
                  The Post-Resolution QA pipeline runs when a case closes.{' '}
                  <a href="/cases" className="text-cyan-400 hover:underline">
                    Simulate a ticket
                  </a>
                  , then close it — its CSAT prediction will show up here.
                </p>
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="text-left py-2">Case</th>
                    <th className="text-left py-2">Subject</th>
                    <th className="text-right py-2">CSAT</th>
                    <th className="text-left py-2">Bucket</th>
                    <th className="text-left py-2">Red flags</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.map((s) => (
                    <tr key={s.case_id} className="border-t border-slate-800/70">
                      <td className="py-2 font-mono text-slate-500">{(s.case_id || '').slice(0, 8)}</td>
                      <td className="py-2 text-slate-200 truncate max-w-[240px]">{s.subject || '—'}</td>
                      <td className="py-2 text-right tabular-nums text-slate-200">
                        {typeof s.predicted_csat === 'number' ? s.predicted_csat.toFixed(1) : '—'}
                      </td>
                      <td className="py-2">
                        {s.predicted_nps_bucket ? (
                          <span className={`px-2 py-0.5 rounded border text-[10px] ${
                            s.predicted_nps_bucket === 'promoter' ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300' :
                            s.predicted_nps_bucket === 'detractor' ? 'bg-rose-500/10 border-rose-500/40 text-rose-300' :
                            'bg-slate-500/10 border-slate-500/40 text-slate-300'
                          }`}>{s.predicted_nps_bucket}</span>
                        ) : '—'}
                      </td>
                      <td className="py-2">
                        {Array.isArray(s.red_flags) && s.red_flags.length > 0 && (
                          <span className="inline-flex items-center gap-1 text-rose-300 text-[10px]">
                            <ShieldAlert className="w-3 h-3" /> {s.red_flags.join(', ')}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, accent = 'cyan' }: { label: string; value: number | string; accent?: 'cyan' | 'emerald' | 'rose' }) {
  const colors = {
    cyan:    'text-cyan-400',
    emerald: 'text-emerald-400',
    rose:    'text-rose-400',
  }[accent];
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-2xl font-bold ${colors} mt-1`}>{value}</p>
    </div>
  );
}
