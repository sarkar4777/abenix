'use client';

import { toastError, toastSuccess } from '@/stores/toastStore';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import ConfirmModal from '@/components/ui/ConfirmModal';
import Link from 'next/link';
import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, Clock, ExternalLink, GitBranch, Loader2, RotateCcw, X } from 'lucide-react';
import { proofLink, sourceBadge } from './revisionSource';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Revision {
  id: string;
  revision_number: number;
  change_type: string;
  source?: string | null;
  proposal_id?: string | null;
  diff_summary: string;
  created_at: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  agentId: string;
  agentName: string;
  onReverted?: () => void;
}

type Pending = { rev: Revision; which: 'after' | 'before' };

export default function VersionHistoryDialog({ open, onClose, agentId, agentName, onReverted }: Props) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reverting, setReverting] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : '';

  const load = useCallback(() => {
    if (!agentId) return;
    setLoading(true);
    setLoadError(null);
    fetch(`${API_URL}/api/agents/${agentId}/revisions`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async r => {
        const b = await r.json().catch(() => null);
        if (!r.ok) throw new Error(b?.error?.message || `HTTP ${r.status}`);
        setRevisions(b?.data || []);
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : 'Could not load the history.'))
      .finally(() => setLoading(false));
  }, [agentId, token]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  useEscapeToClose(open && !pending, onClose);
  if (!open) return null;

  const revert = async ({ rev, which }: Pending) => {
    setReverting(rev.id);
    try {
      const r = await fetch(`${API_URL}/api/agents/${agentId}/revisions/${rev.id}/revert?which=${which}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) {
        const b = await r.json().catch(() => null);
        toastError('Restore failed', b?.error?.message || `HTTP ${r.status}`);
        return;
      }
      toastSuccess('Restored', 'The agent runs this version from its next call. The restore is in the history too.');
      setPending(null);
      onReverted?.();
      onClose();
    } catch {
      toastError('Restore failed', 'Could not reach the server.');
    } finally {
      setReverting(null);
    }
  };

  const first = revisions[revisions.length - 1];
  // an imported or copied agent has no state before its first version
  const hasOriginal = !!first && first.source !== 'import';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" role="dialog" aria-modal="true" aria-label={`Version history for ${agentName}`}>
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between gap-2 px-5 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-2 min-w-0">
            <GitBranch className="w-4 h-4 text-purple-400 shrink-0" />
            <h2 className="text-sm font-semibold text-white truncate">Version history: {agentName}</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 text-slate-500 animate-spin" /></div>
          ) : loadError ? (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-3 text-xs text-red-300">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">Could not load the history</div>
                <div className="text-red-400/80 mt-0.5">{loadError}</div>
                <button onClick={load} className="mt-2 underline hover:text-red-200">Retry</button>
              </div>
            </div>
          ) : revisions.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">No versions yet. Every saved change, publish, healing patch and improvement shows here.</p>
          ) : (
            <div className="space-y-2">
              {revisions.map((rev, i) => {
                const badge = sourceBadge(rev.source);
                const proof = proofLink(agentId, rev.proposal_id);
                return (
                  <div key={rev.id} data-testid={`version-row-${rev.revision_number}`} className="flex items-start gap-3 p-3 bg-slate-900/30 rounded-lg border border-slate-700/30">
                    <div className="flex flex-col items-center gap-1 shrink-0 pt-0.5">
                      <span className="text-[10px] font-bold text-slate-400">v{rev.revision_number}</span>
                      {i < revisions.length - 1 && <div className="w-px h-4 bg-slate-700/50" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span data-testid={`version-source-${rev.revision_number}`} className={`text-[10px] px-1.5 py-0.5 rounded border ${badge.className}`}>
                          {badge.label}
                        </span>
                        <span className="text-[10px] text-slate-500 flex items-center gap-1">
                          <Clock className="w-2.5 h-2.5" />
                          {new Date(rev.created_at).toLocaleDateString()} {new Date(rev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 break-words">{rev.diff_summary || 'No description'}</p>
                      {proof && (
                        <Link href={proof} data-testid={`version-proof-${rev.revision_number}`} className="mt-1 inline-flex items-center gap-1 text-[11px] text-purple-300 hover:text-purple-200 underline">
                          See the proof <ExternalLink className="w-2.5 h-2.5" />
                        </Link>
                      )}
                    </div>
                    {i > 0 && (
                      <button
                        data-testid={`version-revert-${rev.revision_number}`}
                        onClick={() => setPending({ rev, which: 'after' })}
                        disabled={reverting === rev.id}
                        className="shrink-0 flex items-center gap-1 px-2 py-1 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded hover:bg-amber-500/20 disabled:opacity-50"
                      >
                        {reverting === rev.id ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RotateCcw className="w-2.5 h-2.5" />}
                        Restore
                      </button>
                    )}
                  </div>
                );
              })}
              {hasOriginal && (
                <div className="flex items-center justify-between gap-3 p-3 bg-slate-900/30 rounded-lg border border-dashed border-slate-700/40">
                  <span className="text-[11px] text-slate-400">Original, before any saved change</span>
                  <button
                    data-testid="version-restore-original"
                    onClick={() => setPending({ rev: first, which: 'before' })}
                    disabled={reverting === first.id}
                    className="shrink-0 flex items-center gap-1 px-2 py-1 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded hover:bg-amber-500/20 disabled:opacity-50"
                  >
                    <RotateCcw className="w-2.5 h-2.5" /> Restore
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        open={!!pending}
        onClose={() => setPending(null)}
        onConfirm={() => { if (pending) void revert(pending); }}
        title={pending ? (pending.which === 'before' ? 'Restore the original?' : `Restore version ${pending.rev.revision_number}?`) : ''}
        description="The agent's prompt, model and tools go back to that version from its next run. The current version stays in the history, so you can restore it again."
        confirmLabel="Restore"
        variant="warning"
        icon={RotateCcw}
        loading={!!reverting}
        confirmTestId="version-revert-confirm"
      />
    </div>
  );
}
