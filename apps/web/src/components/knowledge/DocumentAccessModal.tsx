'use client';

import { useEffect, useState } from 'react';
import { History, Loader2, Lock, Trash2 } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import SubjectPicker, { useSubjectNames } from '@/components/share/SubjectPicker';
import { ShareExpiryBadge, ShareExpiryInput, expiryToIso, isExpired } from '@/components/share/ShareExpiry';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';

interface Grant {
  id: string;
  subject_type: 'user' | 'agent';
  subject_id: string;
  permission: string;
  expires_at: string | null;
  expired?: boolean;
}

interface Version {
  id: string;
  filename: string;
  version_number: number;
  is_current: boolean;
  status: string;
  created_at: string | null;
}

export default function DocumentAccessModal({
  kbId, doc, onClose, onChanged,
}: {
  kbId: string;
  doc: { id: string; filename: string } | null;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [tab, setTab] = useState<'access' | 'history'>('access');
  const [grants, setGrants] = useState<Grant[]>([]);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [kind, setKind] = useState<'user' | 'agent'>('user');
  const [subject, setSubject] = useState('');
  const [expiry, setExpiry] = useState('');
  const [busy, setBusy] = useState(false);
  const { names } = useSubjectNames();

  const base = doc ? `/api/knowledge/${kbId}/documents/${doc.id}` : '';

  const load = async () => {
    if (!doc) return;
    setLoading(true);
    try {
      const r = await apiFetch<Grant[]>(`${base}/grants`, { silent: true, throwOnError: false });
      if (r.error) toastError('Could not load access', r.error);
      setGrants(r.data || []);
    } finally { setLoading(false); }
  };

  const loadHistory = async () => {
    if (!doc) return;
    const r = await apiFetch<Version[]>(`${base}/versions`, { silent: true, throwOnError: false });
    setVersions(r.error ? [] : r.data || []);
  };

  useEffect(() => {
    if (!doc) return;
    setTab('access'); setSubject(''); setExpiry(''); setVersions(null);
    void load();
  }, [doc?.id]);

  useEffect(() => { if (tab === 'history' && versions === null) void loadHistory(); }, [tab]);

  const add = async () => {
    if (!subject) return;
    setBusy(true);
    try {
      const r = await apiFetch(`${base}/grants`, {
        method: 'POST',
        throwOnError: false,
        body: JSON.stringify({ subject_type: kind, subject_id: subject, permission: 'read', expires_at: expiryToIso(expiry) }),
      });
      if (r.error) { toastError('Could not share the document', r.error); return; }
      toastSuccess('Document restricted', `${names[subject] || 'They'} can read ${doc?.filename}`);
      setSubject(''); setExpiry('');
      await load();
      onChanged?.();
    } finally { setBusy(false); }
  };

  const revoke = async (g: Grant) => {
    if (!window.confirm(`Remove ${names[g.subject_id] || 'this grant'}?`)) return;
    const r = await apiFetch(`${base}/grants/${g.id}`, { method: 'DELETE', throwOnError: false });
    if (r.error) { toastError('Could not remove', r.error); return; }
    toastSuccess('Removed');
    await load();
    onChanged?.();
  };

  const restricted = grants.length > 0;

  return (
    <ResponsiveModal open={doc !== null} onClose={onClose} title={doc ? doc.filename : 'Document'}>
      <div className="space-y-4" data-testid="doc-access-modal">
        <div className="flex gap-2 border-b border-slate-800">
          <button onClick={() => setTab('access')} data-testid="doc-tab-access" className={`px-3 py-2 text-sm ${tab === 'access' ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}>
            <Lock className="w-4 h-4 inline -mt-px mr-1" />Who can read it
          </button>
          <button onClick={() => setTab('history')} data-testid="doc-tab-history" className={`px-3 py-2 text-sm ${tab === 'history' ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}>
            <History className="w-4 h-4 inline -mt-px mr-1" />Versions
          </button>
        </div>

        {tab === 'access' ? (
          <>
            <p className="text-xs text-slate-400" data-testid="doc-access-state">
              {restricted
                ? 'Restricted. Only the people and agents below can read it, plus admins and editors of this knowledge base. An expired grant keeps it restricted.'
                : 'Open to everyone who can read this knowledge base. Add someone below to restrict it to them.'}
            </p>
            <div className="space-y-2 max-h-64 overflow-auto pr-1">
              {loading ? (
                <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
              ) : grants.map((g) => (
                <div key={g.id} data-testid="doc-grant-row" data-subject={g.subject_id} className={`flex items-center justify-between gap-2 bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2 ${isExpired(g) ? 'opacity-70' : ''}`}>
                  <div className="min-w-0">
                    <div className="text-xs text-slate-200 truncate">{names[g.subject_id] || `${g.subject_id.slice(0, 8)}…`}</div>
                    <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500">{g.subject_type} · {g.permission}</span>
                      <ShareExpiryBadge row={g} />
                    </div>
                  </div>
                  <button onClick={() => void revoke(g)} aria-label={`Remove ${names[g.subject_id] || g.subject_id}`} className="text-slate-500 hover:text-red-400 p-1 shrink-0">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
            <div className="border-t border-slate-800 pt-4 space-y-2">
              <div className="flex flex-wrap gap-2">
                <select value={kind} onChange={(e) => { setKind(e.target.value as 'user' | 'agent'); setSubject(''); }} aria-label="Person or agent" data-testid="doc-grant-kind" className="bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100">
                  <option value="user">Person</option>
                  <option value="agent">Agent</option>
                </select>
                <SubjectPicker kind={kind} value={subject} onChange={setSubject} exclude={grants.filter((g) => !isExpired(g)).map((g) => g.subject_id)} testId="doc-grant-subject" />
                <button onClick={add} disabled={busy || !subject} data-testid="doc-grant-submit" className="px-3 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50">
                  {busy ? 'Saving…' : 'Let them read it'}
                </button>
              </div>
              <ShareExpiryInput value={expiry} onChange={setExpiry} testId="doc-grant-expiry" />
            </div>
          </>
        ) : (
          <div className="space-y-2" data-testid="doc-versions">
            <p className="text-xs text-slate-400">Search and agents only use the current version. Older versions stay here as history.</p>
            {versions === null ? (
              <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
            ) : versions.length === 0 ? (
              <p className="text-xs text-slate-500 py-4 text-center">No history for this document.</p>
            ) : versions.map((v) => (
              <div key={v.id} data-testid="doc-version-row" className="flex items-center justify-between gap-2 bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2">
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate">v{v.version_number} · {v.filename}</div>
                  <div className="text-[10px] text-slate-500">{v.created_at ? new Date(v.created_at).toLocaleString() : ''}</div>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${v.is_current ? 'text-emerald-300 bg-emerald-500/10' : 'text-slate-400 bg-slate-700/40'}`}>
                  {v.is_current ? 'current' : 'superseded'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </ResponsiveModal>
  );
}
