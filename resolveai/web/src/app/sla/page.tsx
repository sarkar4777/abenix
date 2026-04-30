'use client';

/**
 * /sla — SLA board. Lets ops manually trigger the sweep, lists recent
 * breaches. In production the sweep fires on a cron via Abenix
 * triggers — this UI is the human-visible side of that cycle.
 */
import { useEffect, useState } from 'react';
import { Loader2, PlayCircle, AlertTriangle } from 'lucide-react';
import { resolveAIPost } from '@/lib/api';

type SweepResult = {
  swept?: number;
  breached?: number;
  escalated?: number;
  breaches?: Array<{
    case_id?: string;
    sla_type?: string;
    minutes_overdue?: number;
    subject?: string;
  }>;
};

export default function SLABoard() {
  const [result, setResult] = useState<SweepResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function sweep() {
    setLoading(true);
    setErr(null);
    const { data, error } = await resolveAIPost<SweepResult>('/api/resolveai/sla/sweep');
    if (error) {
      setErr(error);
    } else {
      setResult(data ?? {});
    }
    setLoading(false);
  }

  useEffect(() => {
    void sweep();
  }, []);

  const breaches = Array.isArray(result?.breaches) ? result!.breaches! : [];

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · SLA</p>
          <h1 className="text-2xl font-bold text-white">SLA Board</h1>
          <p className="text-sm text-slate-400 mt-1">
            Manual sweep trigger + recent breaches. In prod this fires on a 5-minute cron.
          </p>
        </div>
        <button
          onClick={() => void sweep()}
          disabled={loading}
          data-testid="run-sla-sweep"
          className="inline-flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-sm font-semibold rounded-lg disabled:opacity-60"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
          Run sweep now
        </button>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          Sweep failed: {err}. The rest of ResolveAI is still reachable — click{' '}
          <button className="underline" onClick={() => void sweep()}>
            Run sweep now
          </button>{' '}
          to retry.
        </div>
      )}

      {result && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Open cases swept" value={Number(result.swept ?? 0)} />
          <Stat label="Breaches detected" value={Number(result.breached ?? 0)} accent="amber" />
          <Stat label="Escalated" value={Number(result.escalated ?? 0)} accent="rose" />
        </div>
      )}

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" /> Recent breaches
        </h2>
        {breaches.length === 0 ? (
          <p className="text-xs text-slate-500">No SLA breaches in the current window.</p>
        ) : (
          <ul className="space-y-2 text-sm" data-testid="breach-list">
            {breaches.map((b, i) => (
              <li key={i} className="flex gap-3 items-center">
                <span className="font-mono text-xs text-slate-500">
                  {(b.case_id || '').slice(0, 8) || '—'}
                </span>
                <span className="px-2 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300 text-[10px]">
                  {b.sla_type || 'sla'}
                </span>
                <span className="text-slate-200 truncate max-w-[260px]">
                  {b.subject || '(no subject)'}
                </span>
                <span className="ml-auto text-xs text-rose-300 tabular-nums">
                  {Number(b.minutes_overdue ?? 0)}m overdue
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, accent = 'cyan' }: { label: string; value: number; accent?: 'cyan' | 'amber' | 'rose' }) {
  const colors = {
    cyan:  'text-cyan-400',
    amber: 'text-amber-400',
    rose:  'text-rose-400',
  }[accent];
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-2xl font-bold ${colors} mt-1`}>{value}</p>
    </div>
  );
}
