'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, Loader2, RefreshCw, Play, ChevronDown, ChevronRight, Inbox, ExternalLink,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
import { adviceCode, failureTitle } from '@/components/alerts/failureAdvice';

interface DlqRow {
  id: string;
  execution_id: string;
  agent_id: string | null;
  agent_name: string | null;
  failure_code: string;
  error_message: string | null;
  original_input: Record<string, unknown>;
  runtime_pool: string;
  is_pipeline: boolean;
  replay_count: number;
  last_replay_at: string | null;
  replay_execution_id: string | null;
  resolved: boolean;
  created_at: string | null;
}

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function DlqCard({ row, onReplay, busy }: { row: DlqRow; onReplay: (id: string) => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const code = adviceCode({ failure_code: row.failure_code, sample_message: row.error_message });
  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 mb-3" data-testid="dlq-card" data-agent={row.agent_name || ''} data-execution={row.execution_id}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <h3 className="text-sm font-semibold text-white">
              {row.agent_name || row.agent_id?.slice(0, 8) || 'Unknown agent'}
            </h3>
            <span className="text-[11px] px-2 py-0.5 rounded-full border bg-rose-500/15 text-rose-300 border-rose-500/40" data-testid="dlq-reason">
              {failureTitle(code)}
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full border bg-slate-500/15 text-slate-300 border-slate-500/40 font-mono">
              pool: {row.runtime_pool || 'default'}
            </span>
            {row.is_pipeline && (
              <span className="text-[10px] px-2 py-0.5 rounded-full border bg-violet-500/15 text-violet-300 border-violet-500/40 uppercase tracking-wider">pipeline</span>
            )}
            {row.resolved && (
              <span className="text-[10px] px-2 py-0.5 rounded-full border bg-emerald-500/15 text-emerald-300 border-emerald-500/40 uppercase tracking-wider">resolved</span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
            <span>Failed {relTime(row.created_at)}</span>
            <a href={`/executions/${row.execution_id}`} className="font-mono text-slate-400 hover:text-white inline-flex items-center gap-1">
              exec {row.execution_id.slice(0, 8)} <ExternalLink className="w-2.5 h-2.5" />
            </a>
            <span>Reference <code className="font-mono text-slate-400" data-testid="dlq-code">{row.failure_code}</code></span>
            <span>Replays: {row.replay_count}</span>
            {row.last_replay_at && <span>Last replay {relTime(row.last_replay_at)}</span>}
            {row.replay_execution_id && (
              <a href={`/executions/${row.replay_execution_id}`} data-testid="dlq-replay-link" className="font-mono text-cyan-400 hover:text-cyan-200 inline-flex items-center gap-1">
                replay {row.replay_execution_id.slice(0, 8)} <ExternalLink className="w-2.5 h-2.5" />
              </a>
            )}
          </div>
          {row.error_message && (
            <pre className="mt-2 font-sans text-[12px] text-rose-200/80 whitespace-pre-wrap break-words line-clamp-2">{row.error_message}</pre>
          )}
        </div>
        <button
          onClick={() => onReplay(row.id)}
          disabled={busy}
          data-testid="dlq-replay"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 text-xs font-medium hover:bg-cyan-500/25 disabled:opacity-50"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          Replay
        </button>
      </div>
      <button
        onClick={() => setOpen(o => !o)}
        className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Original input
      </button>
      {open && (
        <pre className="mt-2 text-[11px] text-slate-300 bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words max-h-56">
          {JSON.stringify(row.original_input, null, 2)}
        </pre>
      )}
    </div>
  );
}

function AdminDlqPage() {
  const [rows, setRows] = useState<DlqRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string; href?: string } | null>(null);

  const load = useCallback(async () => {
    const res = await apiFetch<DlqRow[]>('/api/admin/dlq', { silent: true });
    if (res.error && !res.data) setError(res.error);
    else setError(null);
    setRows(res.data || []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleReplay = async (id: string) => {
    setBusyId(id);
    setNotice(null);
    const r = await apiFetch<{ new_execution_id?: string; dispatched?: boolean }>(`/api/admin/dlq/${id}/replay`, { method: 'POST', throwOnError: false });
    setBusyId(null);
    const runId = r.data?.new_execution_id;
    setNotice(r.error
      ? { ok: false, text: `Replay did not start. ${r.error}` }
      : { ok: true, text: 'Replay started with the original input. It shows on the card once it has a run.', href: runId ? `/executions/${runId}` : undefined });
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto">
      <PageHeader
        className="mb-6"
        title="Dead Letter Queue"
        purpose="Find runs that kept failing after every retry and send them again with their original input. For admins."
        icon={Inbox}
        iconClassName="text-rose-400"
        storageKey="admin-dlq"
        docSlug="02-runtime/08-queue-scaling"
        primaryAction={{ label: 'Refresh', icon: RefreshCw, onClick: load, busy: loading }}
        steps={[
          'A run lands here when it still fails after all of its automatic retries.',
          'Each card shows the agent, why it failed and a link to the failed run.',
          'Open Original input to see what it was asked, then click Replay to run it again with the same input.',
        ]}
      />

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      {notice && (
        <p role="status" data-testid="dlq-notice" className={`mb-4 text-xs rounded-lg border px-3 py-2 ${notice.ok ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5' : 'text-rose-300 border-rose-500/30 bg-rose-500/5'}`}>
          {notice.text}{notice.href && <> <a href={notice.href} className="underline" data-testid="dlq-notice-link">Open the replay</a></>}
        </p>
      )}

      {loading && rows.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading dead-letter executions
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-10 text-center">
          <Inbox className="w-8 h-8 text-emerald-400/40 mx-auto mb-2" />
          <p className="text-sm text-slate-400">Nothing here. Every run either finished or is still retrying.</p>
        </div>
      ) : (
        rows.map(r => <DlqCard key={r.id} row={r} onReplay={handleReplay} busy={busyId === r.id} />)
      )}
    </div>
  );
}

export default function AdminDlqPageGated() {
  return (
    <AccessGate
      title="Dead Letter Queue"
      purpose="Find runs that kept failing after every retry and send them again with their original input. For admins."
      icon={Inbox}
      need={{ admin: true }}
      instead={{ text: 'Failed runs of your own agents are listed on Executions, where you can run them again.', href: '/executions?status=failed', label: 'See failed runs' }}
    >
      <AdminDlqPage />
    </AccessGate>
  );
}
