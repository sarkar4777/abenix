'use client';

import { useEffect, useState } from 'react';
import { Loader2, Mail, Share2, Trash2, Users, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';

export type Shareable =
  | 'agent'
  | 'pipeline'
  | 'ml_model'
  | 'code_asset'
  | 'knowledge_base'
  | 'saved_tool';

interface ShareRow {
  id: string;
  resource_type: string;
  resource_id: string;
  shared_with_email: string;
  permission: 'view' | 'use' | 'edit';
  created_at: string | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  resourceType: Shareable;
  resourceId: string;
  resourceName: string;
}

const PERM_INFO: Record<'view' | 'use' | 'edit', { color: string; help: string }> = {
  view: { color: 'text-slate-300 bg-slate-700/40', help: 'See it in their list; cannot run or change it.' },
  use:  { color: 'text-cyan-300 bg-cyan-500/10', help: 'Run / call it but cannot modify the definition.' },
  edit: { color: 'text-amber-300 bg-amber-500/10', help: 'Full editor — can change config, schema, version.' },
};

export default function ResourceShareDialog({
  open, onClose, resourceType, resourceId, resourceName,
}: Props) {
  const [email, setEmail] = useState('');
  const [permission, setPermission] = useState<'view' | 'use' | 'edit'>('use');
  const [shares, setShares] = useState<ShareRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadShares = async () => {
    try {
      const res = await apiFetch<ShareRow[]>(
        `/api/me/shares/of/${resourceType}/${resourceId}`,
        { throwOnError: false, silent: true },
      );
      setShares(res.data || []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load shares');
    }
  };

  useEffect(() => {
    if (!open || !resourceId) return;
    setError(null);
    loadShares();
  }, [open, resourceId, resourceType]);

  if (!open) return null;

  const onShare = async () => {
    if (!email.includes('@')) { setError('Enter a valid email'); return; }
    setBusy(true); setError(null);
    try {
      await apiFetch(`/api/me/shares`, {
        method: 'POST',
        body: JSON.stringify({
          resource_type: resourceType,
          resource_id: resourceId,
          shared_with_email: email,
          permission,
        }),
      });
      toastSuccess('Shared', `${email} can now ${permission} this ${resourceType.replace('_', ' ')}`);
      setEmail('');
      await loadShares();
    } catch (e: any) {
      const msg = e?.message || 'Failed to share';
      setError(msg);
      toastError('Share failed', msg);
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (shareId: string, recipient: string) => {
    if (!confirm(`Revoke ${recipient}'s access?`)) return;
    try {
      await apiFetch(`/api/me/shares/${shareId}`, { method: 'DELETE' });
      toastSuccess('Access revoked');
      setShares((prev) => prev.filter((s) => s.id !== shareId));
    } catch (e: any) {
      toastError('Revoke failed', e?.message || 'Unknown error');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" data-testid="resource-share-dialog">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <Share2 className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">
              Share "{resourceName}"
              <span className="ml-2 text-[10px] text-slate-500 uppercase">{resourceType.replace('_', ' ')}</span>
            </h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <div className="flex gap-2">
              <input
                type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="user@yourcompany.com"
                className="flex-1 px-3 py-2 text-xs bg-slate-900/50 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-cyan-500"
                data-testid="share-email-input"
              />
              <select
                value={permission}
                onChange={(e) => setPermission(e.target.value as 'view' | 'use' | 'edit')}
                className="px-2 py-2 text-xs bg-slate-900/50 border border-slate-700 rounded-lg text-white"
                data-testid="share-permission-select"
              >
                <option value="view">View</option>
                <option value="use">Use</option>
                <option value="edit">Edit</option>
              </select>
              <button
                onClick={onShare} disabled={busy}
                className="px-3 py-2 bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs rounded-lg hover:bg-cyan-500/30 disabled:opacity-50"
                data-testid="share-submit"
              >
                {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Mail className="w-3 h-3" />}
              </button>
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5">{PERM_INFO[permission].help}</p>
          </div>

          {error && <p className="text-xs text-red-400" data-testid="share-error">{error}</p>}

          {shares.length > 0 ? (
            <div className="space-y-1.5">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Shared with</p>
              {shares.map((s) => (
                <div key={s.id} className="flex items-center justify-between p-2 bg-slate-900/30 rounded-lg" data-testid={`share-row-${s.id}`}>
                  <div className="flex items-center gap-2 min-w-0">
                    <Users className="w-3 h-3 text-slate-500 shrink-0" />
                    <span className="text-xs text-slate-300 truncate">{s.shared_with_email}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded shrink-0 ${PERM_INFO[s.permission].color}`}>
                      {s.permission}
                    </span>
                  </div>
                  <button
                    onClick={() => onRevoke(s.id, s.shared_with_email)}
                    className="text-red-400 hover:text-red-300 shrink-0"
                    aria-label={`Revoke ${s.shared_with_email}`}
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500 text-center py-3">No shares yet — invite a teammate above.</p>
          )}
        </div>
      </div>
    </div>
  );
}
