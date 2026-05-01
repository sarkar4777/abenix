'use client';

import { useState, useEffect } from 'react';
import { Clock, GitBranch, Loader2, RotateCcw, X } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Revision {
  id: string;
  revision_number: number;
  change_type: string;
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

export default function VersionHistoryDialog({ open, onClose, agentId, agentName, onReverted }: Props) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);
  const [reverting, setReverting] = useState<string | null>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : '';

  useEffect(() => {
    if (!open || !agentId) return;
    setLoading(true);
    fetch(`${API_URL}/api/agents/${agentId}/revisions`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(b => setRevisions(b.data || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open, agentId, token]);

  if (!open) return null;

  const revert = async (revId: string) => {
    setReverting(revId);
    try {
      await fetch(`${API_URL}/api/agents/${agentId}/revisions/${revId}/revert`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      onReverted?.();
      onClose();
    } catch {}
    finally { setReverting(null); }
  };

  const typeColors: Record<string, string> = {
    config_update: 'text-cyan-400 bg-cyan-500/10',
    prompt_update: 'text-purple-400 bg-purple-500/10',
    tools_update: 'text-emerald-400 bg-emerald-500/10',
    publish: 'text-amber-400 bg-amber-500/10',
    revert: 'text-red-400 bg-red-500/10',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-lg max-h-[70vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-semibold text-white">Version History — {agentName}</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 text-slate-500 animate-spin" /></div>
          ) : revisions.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">No revisions yet. Changes are tracked automatically when you save.</p>
          ) : (
            <div className="space-y-2">
              {revisions.map((rev, i) => (
                <div key={rev.id} className="flex items-start gap-3 p-3 bg-slate-900/30 rounded-lg border border-slate-700/30">
                  <div className="flex flex-col items-center gap-1 shrink-0 pt-0.5">
                    <span className="text-[10px] font-bold text-slate-400">v{rev.revision_number}</span>
                    {i < revisions.length - 1 && <div className="w-px h-4 bg-slate-700/50" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded ${typeColors[rev.change_type] || 'text-slate-400 bg-slate-700/50'}`}>
                        {rev.change_type.replace(/_/g, ' ')}
                      </span>
                      <span className="text-[9px] text-slate-600 flex items-center gap-1">
                        <Clock className="w-2.5 h-2.5" />
                        {new Date(rev.created_at).toLocaleDateString()} {new Date(rev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="text-[10px] text-slate-400 truncate">{rev.diff_summary || 'No description'}</p>
                  </div>
                  {i > 0 && (
                    <button
                      onClick={() => revert(rev.id)}
                      disabled={reverting === rev.id}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 text-[9px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded hover:bg-amber-500/20 disabled:opacity-50"
                    >
                      {reverting === rev.id ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RotateCcw className="w-2.5 h-2.5" />}
                      Revert
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
