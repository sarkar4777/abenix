'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, Loader2, RefreshCw, Play, ChevronDown, ChevronRight, Inbox,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface DlqRow {
  id: string;
  execution_id: string;
  agent_id: string | null;
  agent_name: string | null;
  failure_code: string;
  error_message: string | null;
  original_input: Record<string, unknown>;
  replay_count: number;
  last_replay_at: string | null;
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
  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 mb-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <h3 className="text-sm font-semibold text-white">
              {row.agent_name || row.agent_id?.slice(0, 8) || 'Unknown agent'}
            </h3>
            <span className="text-[10px] px-2 py-0.5 rounded-full border bg-rose-500/15 text-rose-300 border-rose-500/40 uppercase tracking-wider">
              {row.failure_code}
            </span>
            {row.resolved && (
              <span className="text-[10px] px-2 py-0.5 rounded-full border bg-emerald-500/15 text-emerald-300 border-emerald-500/40 uppercase tracking-wider">resolved</span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
            <span>Failed {relTime(row.created_at)}</span>
            <span className="font-mono text-slate-600">exec {row.execution_id.slice(0, 8)}</span>
            <span>Replays: {row.replay_count}</span>
            {row.last_replay_at && <span>Last replay {relTime(row.last_replay_at)}</span>}
          </div>
          {row.error_message && (
            <p className="mt-2 text-[12px] text-rose-200/80 line-clamp-2">{row.error_message}</p>
          )}
        </div>
        <button
          onClick={() => onReplay(row.id)}
          disabled={busy}
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

export default function AdminDlqPage() {
  const [rows, setRows] = useState<DlqRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

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
    await apiFetch(`/api/admin/dlq/${id}/replay`, { method: 'POST' });
    setBusyId(null);
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto">
      <header className="flex flex-wrap items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center">
          <Inbox className="w-5 h-5 text-rose-400" />
        </div>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold text-white">Dead Letter Queue</h1>
          <p className="text-sm text-slate-500">Executions that failed past the retry budget. Replay re-fires the request with the original input.</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-300 hover:text-white"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      {loading && rows.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading dead-letter executions
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-10 text-center">
          <Inbox className="w-8 h-8 text-emerald-400/40 mx-auto mb-2" />
          <p className="text-sm text-slate-400">DLQ is empty. Healthy.</p>
        </div>
      ) : (
        rows.map(r => <DlqCard key={r.id} row={r} onReplay={handleReplay} busy={busyId === r.id} />)
      )}
    </div>
  );
}
