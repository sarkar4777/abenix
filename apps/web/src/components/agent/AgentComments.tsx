'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2, MessageSquare, RotateCcw, Send, Trash2 } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';
import { toastError, toastSuccess } from '@/stores/toastStore';

interface Comment {
  id: string;
  content: string;
  user_id: string;
  user_name: string | null;
  user_email: string;
  is_resolved: boolean;
  parent_id: string | null;
  created_at: string | null;
}

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
}

/** Notes the team leaves on an agent. Its owner hears about each new one. */
export default function AgentComments({ agentId, ownerId, canModerate }: { agentId: string; ownerId?: string | null; canModerate: boolean }) {
  const { user } = useAuth();
  const { data, isLoading, error, mutate } = useApi<Comment[]>(`/api/agents/${agentId}/comments`);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [showResolved, setShowResolved] = useState(false);

  const comments = data || [];
  const open = comments.filter((c) => !c.is_resolved);
  const shown = showResolved ? comments : open;

  const post = async () => {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    const r = await apiFetch(`/api/agents/${agentId}/comments`, { method: 'POST', body: JSON.stringify({ content }), throwOnError: false });
    setBusy(false);
    if (r.error) { toastError('Comment not posted', r.error); return; }
    // keep anything typed while this one was sending
    setText((t) => (t.trim() === content ? '' : t));
    toastSuccess('Comment posted', ownerId && ownerId !== user?.id ? 'The agent owner was notified.' : undefined);
    mutate();
  };

  const resolve = async (c: Comment, value: boolean) => {
    const r = await apiFetch(`/api/agents/${agentId}/comments/${c.id}`, { method: 'PUT', body: JSON.stringify({ is_resolved: value }), throwOnError: false });
    if (r.error) { toastError('Could not update', r.error); return; }
    mutate();
  };

  const remove = async (c: Comment) => {
    if (!confirm('Delete this comment?')) return;
    const r = await apiFetch(`/api/agents/${agentId}/comments/${c.id}`, { method: 'DELETE', throwOnError: false });
    if (r.error) { toastError('Could not delete', r.error); return; }
    toastSuccess('Comment deleted');
    mutate();
  };

  return (
    <div id="comments" className="space-y-4" data-testid="agent-comments">
      <div className="flex flex-wrap items-center gap-2">
        <MessageSquare className="w-4 h-4 text-cyan-400" />
        <h3 className="text-sm font-semibold text-white">Comments</h3>
        <span className="text-xs text-slate-500">{open.length} open{comments.length > open.length ? `, ${comments.length - open.length} resolved` : ''}</span>
        {comments.length > open.length && (
          <button onClick={() => setShowResolved((v) => !v)} className="ml-auto text-xs text-slate-400 hover:text-white" data-testid="comments-toggle-resolved">
            {showResolved ? 'Hide resolved' : 'Show resolved'}
          </button>
        )}
      </div>

      <div className="flex gap-2 items-end">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void post(); } }}
          rows={2}
          maxLength={4000}
          placeholder="Leave a note for the team, like what to change or a run that went wrong"
          aria-label="New comment"
          data-testid="comment-input"
          className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 resize-y"
        />
        <button onClick={post} disabled={busy || !text.trim()} data-testid="comment-submit" className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-sm rounded-lg hover:bg-cyan-500/30 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Post
        </button>
      </div>

      {isLoading && !data && <p className="text-xs text-slate-500">Loading comments…</p>}
      {error && <p role="alert" className="text-xs text-red-400">Could not load comments. {error}</p>}
      {!isLoading && !error && shown.length === 0 && (
        <p className="text-xs text-slate-500" data-testid="comments-empty">No open comments. Notes you post here are seen by everyone who can open this agent.</p>
      )}

      <div className="space-y-2">
        {shown.map((c) => {
          const mine = c.user_id === user?.id;
          return (
            <div key={c.id} data-testid="comment-row" data-resolved={c.is_resolved ? '1' : '0'} className={`rounded-lg border px-3 py-2 ${c.is_resolved ? 'border-slate-800 bg-slate-900/20 opacity-70' : 'border-slate-700/60 bg-slate-800/30'}`}>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span className="text-slate-300">{c.user_name || c.user_email}</span>
                <span>{when(c.created_at)}</span>
                {c.is_resolved && <span className="text-emerald-400">resolved</span>}
                <span className="ml-auto flex items-center gap-2">
                  {(mine || canModerate) && (
                    <button onClick={() => resolve(c, !c.is_resolved)} className="inline-flex items-center gap-1 text-slate-400 hover:text-emerald-300" data-testid="comment-resolve">
                      {c.is_resolved ? <RotateCcw className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                      {c.is_resolved ? 'Reopen' : 'Resolve'}
                    </button>
                  )}
                  {(mine || canModerate) && (
                    <button onClick={() => remove(c)} aria-label="Delete comment" className="text-slate-500 hover:text-red-400" data-testid="comment-delete">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  )}
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-200 whitespace-pre-wrap break-words">{c.content}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
