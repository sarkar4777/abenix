'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, CheckCircle2, Loader2, UserRound, RefreshCw } from 'lucide-react';
import { useResolveAIFetch, resolveAIPost } from '@/lib/api';

type Citation = {
  policy_id?: string;
  version?: number;
  clause?: string;
  excerpt?: string;
  applies_because?: string;
};

type Action = {
  type?: string;
  amount_usd?: number | null;
  rationale?: string;
  approval_tier?: string;
  requires_approval?: boolean;
  cites?: string[];
};

type CaseDetail = {
  id: string;
  customer_id: string;
  customer_tier: string;
  subject: string;
  body: string;
  channel: string;
  status: string;
  deflection_score: number | null;
  resolution: string | null;
  citations: Array<Citation | string>;
  action_plan?: Action[] | Record<string, unknown>;
  cost_usd: number;
  duration_ms: number;
  created_at: string;
  events: Array<{ ts: string; type: string; summary: string }>;
};

export default function CaseDetail({ params }: { params: { caseId: string } }) {
  const { data, error, isLoading, refetch } = useResolveAIFetch<CaseDetail>(
    params.caseId ? `/api/resolveai/cases/${params.caseId}` : null,
  );
  const [taking, setTaking] = useState(false);

  const takeOver = async () => {
    setTaking(true);
    await resolveAIPost(`/api/resolveai/cases/${params.caseId}/take-over`, {
      reason: 'manual takeover from case detail',
    });
    setTaking(false);
    void refetch();
  };

  if (isLoading && !data) {
    return <div className="p-8 text-slate-500">Loading case…</div>;
  }
  if (error || !data) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <Link href="/cases" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-4">
          <ArrowLeft className="w-3 h-3" /> Back to cases
        </Link>
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-5">
          <p className="text-sm text-rose-200">
            {error ? `Couldn't load this case: ${error}` : 'Case not found.'}
          </p>
          <button
            onClick={() => void refetch()}
            className="inline-flex items-center gap-1.5 mt-3 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-200 text-xs"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      </div>
    );
  }

  const c = data;
  const citations = Array.isArray(c.citations) ? c.citations : [];
  const actions: Action[] = Array.isArray(c.action_plan) ? c.action_plan : [];
  const events = Array.isArray(c.events) ? c.events : [];

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <Link href="/cases" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-3 h-3" /> Back to cases
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            <span className="font-mono">{c.id}</span>
          </p>
          <h1 className="text-2xl font-bold text-white mt-1 flex items-center gap-2">
            <UserRound className="w-5 h-5 text-cyan-400" />
            {c.subject || '(no subject)'}
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Customer <span className="text-slate-200">{c.customer_id || '—'}</span>{' '}
            ({c.customer_tier || 'standard'}) · {c.channel || '—'} · opened{' '}
            {c.created_at ? new Date(c.created_at).toLocaleString() : '—'}
          </p>
        </div>
        {c.status !== 'human_handling' && (
          <button
            onClick={takeOver}
            disabled={taking}
            className="px-3 py-1.5 text-xs rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-300 inline-flex items-center gap-2 disabled:opacity-60"
          >
            {taking ? <Loader2 className="w-3 h-3 animate-spin" /> : <UserRound className="w-3 h-3" />}
            Take over as human
          </button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3 my-6">
        <Pill label="Status" value={(c.status || 'unknown').replace(/_/g, ' ')} />
        <Pill label="Deflection" value={c.deflection_score == null ? '—' : Number(c.deflection_score).toFixed(2)} />
        <Pill label="Spend" value={`$${Number(c.cost_usd ?? 0).toFixed(4)}`} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
          <h2 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Customer message</h2>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{c.body || '(empty body)'}</p>
        </div>
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
          <h2 className="text-xs uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" /> AI-drafted resolution
          </h2>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">
            {c.resolution || <span className="text-slate-500">(pipeline hasn&apos;t produced a resolution yet)</span>}
          </p>
          {citations.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-700/50">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Cited policies</p>
              <ul className="space-y-1 text-xs text-slate-400">
                {citations.map((cit, i) => (
                  <li key={i} className="font-mono">
                    {typeof cit === 'string'
                      ? cit
                      : `${cit.policy_id ?? 'UNKNOWN'}@v${cit.version ?? '?'}${cit.clause ? ` · ${cit.clause}` : ''}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {actions.length > 0 && (
        <div className="mt-6 rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
          <h2 className="text-xs uppercase tracking-wider text-slate-500 mb-3">Proposed actions</h2>
          <ul className="space-y-2 text-sm">
            {actions.map((a, i) => (
              <li key={i} className="flex items-start gap-3 p-2 rounded bg-slate-900/30">
                <span className="font-mono text-[10px] uppercase tracking-wider text-cyan-400 shrink-0 mt-0.5">
                  {a.type || 'action'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-slate-300 text-xs">{a.rationale || ''}</p>
                  <p className="text-[10px] text-slate-500 mt-1">
                    {a.amount_usd != null ? `$${a.amount_usd} · ` : ''}
                    tier: {a.approval_tier || 'none'}
                    {a.requires_approval ? ' · requires approval' : ''}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
        <h2 className="text-xs uppercase tracking-wider text-slate-500 mb-3">Timeline</h2>
        {events.length === 0 ? (
          <p className="text-xs text-slate-500">No events recorded yet.</p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {events.map((e, i) => (
              <li key={i} className="flex gap-3 text-slate-400">
                <span className="w-36 shrink-0 text-slate-600 font-mono">
                  {e.ts ? new Date(e.ts).toLocaleTimeString() : '—'}
                </span>
                <span className="shrink-0 text-cyan-300 font-medium uppercase tracking-wider text-[10px]">
                  {e.type || 'event'}
                </span>
                <span className="text-slate-300">{e.summary || ''}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Pill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-lg font-semibold text-white mt-1">{value}</p>
    </div>
  );
}
