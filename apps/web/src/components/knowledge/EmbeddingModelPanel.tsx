'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Wand2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';

interface ReembedJob {
  job_id?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'skipped';
  from_model?: string | null;
  to_model?: string | null;
  documents_total?: number;
  documents_done?: number;
  chunks?: number;
  error?: string | null;
  warning?: string | null;
  finished_at?: string;
}

interface ReembedState {
  embedding_model: string;
  supported_models: string[];
  job: ReembedJob | null;
}

interface Estimate {
  chunks_to_reembed: number;
  estimated_usd: number;
  estimated_seconds: number;
}

const MODEL_NOTES: Record<string, string> = {
  'text-embedding-3-small': 'OpenAI, semantic, the default',
  'text-embedding-3-large': 'OpenAI, semantic, higher quality at 1536 dimensions',
  'text-embedding-ada-002': 'OpenAI, older semantic model',
  'local-hashing-v1': 'Offline, lexical (matches words, not meaning), no API key',
};

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function EmbeddingModelPanel({ kbId }: { kbId: string }) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [state, setState] = useState<ReembedState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [target, setTarget] = useState('');
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await apiFetch<ReembedState>(`/api/knowledge/${kbId}/reembed`, { silent: true });
    if (r.data) {
      setState(r.data);
      setLoadError(null);
    } else {
      setLoadError(r.error || 'Could not load the embedding model');
    }
  }, [kbId]);

  useEffect(() => { load(); }, [load]);

  const active = state?.job?.status === 'queued' || state?.job?.status === 'running';
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [active, load]);

  const choose = (m: string) => {
    setTarget(m);
    setEstimate(null);
    setActionError(null);
  };

  const runEstimate = async () => {
    if (!target) return;
    setBusy(true);
    setActionError(null);
    try {
      const r = await apiFetch<Estimate>(`/api/knowledge/${kbId}/reembed`, {
        method: 'POST',
        body: JSON.stringify({ embedding_model: target, dry_run: true }),
      });
      setEstimate(r.data);
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await apiFetch(`/api/knowledge/${kbId}/reembed`, {
        method: 'POST',
        body: JSON.stringify({ embedding_model: target }),
      });
      setEstimate(null);
      setTarget('');
      await load();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 text-xs text-red-400">
        {loadError}
      </div>
    );
  }
  if (!state) {
    return (
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 text-xs text-slate-400 flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading embedding model…
      </div>
    );
  }

  const job = state.job;
  const done = job?.documents_done ?? 0;
  const total = job?.documents_total ?? 0;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3" data-testid="embedding-model-panel">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <Wand2 className="w-4 h-4 text-cyan-400" />
        Embedding model
      </h3>
      <p className="text-xs text-slate-400">
        Indexed with <span className="font-mono text-slate-200">{state.embedding_model}</span>
        {MODEL_NOTES[state.embedding_model] ? ` (${MODEL_NOTES[state.embedding_model]})` : ''}.
        Search always embeds the question with this same model.
      </p>

      {job && (
        <div className="rounded-lg bg-slate-900/50 p-3 text-xs space-y-2">
          {active && (
            <>
              <p className="text-slate-300 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />
                Re-embedding to <span className="font-mono">{job.to_model}</span>
                {job.status === 'queued' ? ', waiting for a worker' : `, ${done} of ${total} documents`}
              </p>
              {job.status === 'running' && (
                <div className="h-1.5 bg-slate-800 rounded">
                  <div className="h-1.5 bg-cyan-500 rounded" style={{ width: `${pct}%` }} />
                </div>
              )}
              <p className="text-slate-500">Search keeps using the current vectors until every document is done.</p>
            </>
          )}
          {job.status === 'completed' && (
            <p className="text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Re-embedded {total} documents ({job.chunks ?? 0} chunks) with {job.to_model}.
            </p>
          )}
          {(job.status === 'failed' || job.status === 'skipped') && (
            <p className="text-red-400 flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>Re-embed to {job.to_model} did not run to the end: {job.error || job.status}. Nothing was changed.</span>
            </p>
          )}
          {job.warning && <p className="text-amber-300">{job.warning}</p>}
        </div>
      )}

      {isAdmin ? (
        <div className="space-y-2">
          <label className="block text-xs text-slate-400">
            Switch to
            <select
              value={target}
              onChange={(e) => choose(e.target.value)}
              disabled={busy || active}
              className="mt-1 block w-full max-w-md rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm"
            >
              <option value="">Choose a model…</option>
              {state.supported_models.map((m) => (
                <option key={m} value={m}>
                  {m === state.embedding_model ? `${m} (current, re-index)` : m}
                  {MODEL_NOTES[m] ? ` — ${MODEL_NOTES[m]}` : ''}
                </option>
              ))}
            </select>
          </label>
          {target && !estimate && (
            <button
              onClick={runEstimate}
              disabled={busy}
              className="rounded-md bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              {busy ? 'Estimating…' : 'Estimate cost'}
            </button>
          )}
          {estimate && (
            <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 text-xs text-slate-300 space-y-2">
              <p>
                Re-embeds {estimate.chunks_to_reembed.toLocaleString()} chunks, about $
                {estimate.estimated_usd.toFixed(2)} and {Math.ceil(estimate.estimated_seconds / 60)} min.
                Every document is re-read and re-chunked, then the collection switches over in one step.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={start}
                  disabled={busy}
                  className="rounded-md bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  {busy ? 'Queuing…' : `Re-embed with ${target}`}
                </button>
                <button
                  onClick={() => setEstimate(null)}
                  disabled={busy}
                  className="rounded-md bg-slate-800 hover:bg-slate-700 px-3 py-1.5 text-xs text-slate-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {actionError && <p className="text-xs text-red-400">{actionError}</p>}
        </div>
      ) : (
        <p className="text-[11px] text-slate-500">Only workspace admins can change the embedding model.</p>
      )}
    </div>
  );
}

export default EmbeddingModelPanel;
