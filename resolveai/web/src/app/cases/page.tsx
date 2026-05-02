'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Plus, Loader2, RefreshCw, AlertCircle } from 'lucide-react';
import { useResolveAIFetch, resolveAIPost, fetchSampleTickets, type SampleTicket } from '@/lib/api';
import { toastError, toastSuccess } from '@/stores/toastStore';

type Case = {
  id: string;
  customer_id: string;
  customer_tier: string;
  subject: string;
  status: string;
  channel: string;
  deflection_score: number | null;
  cost_usd: number;
  duration_ms: number;
  created_at: string;
};

const STATUS_COLOR: Record<string, string> = {
  auto_resolved:  'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  handed_to_human:'text-amber-400 bg-amber-500/10 border-amber-500/30',
  human_handling: 'text-violet-400 bg-violet-500/10 border-violet-500/30',
  pipeline_error: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  ingested:       'text-slate-300 bg-slate-500/10 border-slate-500/30',
};

// Server-controlled now — fetched from /api/resolveai/admin/sample-tickets
// so we can vary fixtures per tenant and keep them out of the prod bundle.
// `NEXT_PUBLIC_SHOW_SAMPLES=true` is the gate; in prod we hide the button.
const SHOW_SAMPLES = process.env.NEXT_PUBLIC_SHOW_SAMPLES === 'true';

export default function CasesPage() {
  const { data, error, isLoading, refetch } = useResolveAIFetch<Case[]>('/api/resolveai/cases?limit=200');
  const cases = Array.isArray(data) ? data : [];
  const [creating, setCreating] = useState(false);
  const [postErr, setPostErr] = useState<string | null>(null);

  const createSynthetic = async () => {
    setCreating(true);
    setPostErr(null);
    const samples = await fetchSampleTickets();
    if (samples.length === 0) {
      const msg = 'Could not load sample tickets — admin endpoint unreachable.';
      setPostErr(msg);
      toastError(msg);
      setCreating(false);
      return;
    }
    const pick: SampleTicket = samples[Math.floor(Math.random() * samples.length)];
    const { error: err } = await resolveAIPost('/api/resolveai/cases', {
      ...pick,
      channel: 'chat',
      jurisdiction: 'US',
      locale: 'en',
    });
    if (err) {
      setPostErr(err);
      toastError(`Pipeline call failed: ${err}`);
    } else {
      toastSuccess('Sample ticket queued — running through Inbound Resolution.');
    }
    setCreating(false);
    void refetch();
  };

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6 gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI</p>
          <h1 className="text-2xl font-bold text-white">Cases</h1>
          <p className="text-sm text-slate-400 mt-1">
            Every ticket that entered the resolution pipeline.{' '}
            <span className="text-slate-500">Tap the green button to run one through end-to-end — it takes ~30s.</span>
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => void refetch()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-300 text-xs disabled:opacity-60"
            title="Refresh case list"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          {SHOW_SAMPLES && (
            <button
              onClick={createSynthetic}
              disabled={creating}
              data-testid="create-synthetic"
              className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-60"
            >
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              {creating ? 'Running pipeline…' : 'Simulate a ticket'}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Couldn&apos;t load cases: {error}. Refresh to retry.</span>
        </div>
      )}
      {postErr && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          Pipeline call failed: {postErr}
        </div>
      )}

      {isLoading && cases.length === 0 && !error ? (
        <p className="text-slate-500 text-sm">Loading cases…</p>
      ) : cases.length === 0 ? (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-10 text-center">
          <p className="text-slate-400 text-sm">
            No cases yet. Click <strong>Simulate a ticket</strong> to trigger the Inbound Resolution pipeline — it runs Triage → Policy Research → Resolution Planner end-to-end.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-slate-700/50 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-[#0F172A]">
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Subject</th>
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Deflection</th>
                <th className="px-3 py-2 text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} className="border-t border-slate-800/70 hover:bg-slate-800/30">
                  <td className="px-3 py-2 font-mono text-[10px] text-slate-500">
                    <Link href={`/cases/${c.id}`} className="hover:text-cyan-400">
                      {(c.id || '').slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-white">{c.customer_id || '—'}</span>
                    <span className="text-[9px] text-slate-500 ml-1.5 uppercase">{c.customer_tier || ''}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-200 truncate max-w-[260px]">{c.subject || '(no subject)'}</td>
                  <td className="px-3 py-2 text-slate-400">{c.channel || '—'}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded border text-[10px] ${STATUS_COLOR[c.status] || STATUS_COLOR.ingested}`}>
                      {(c.status || 'unknown').replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300 tabular-nums">
                    {c.deflection_score == null ? '—' : Number(c.deflection_score).toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300 tabular-nums">
                    ${Number(c.cost_usd ?? 0).toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
