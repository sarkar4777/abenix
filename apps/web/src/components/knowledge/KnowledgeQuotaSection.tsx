'use client';

import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';
import { quotaProblem } from '@/lib/settings-validation';
import { toastSuccess } from '@/stores/toastStore';

type LimitKey =
  | 'max_documents'
  | 'max_chunks'
  | 'max_storage_bytes'
  | 'monthly_embedding_usd'
  | 'monthly_cognify_usd';

interface QuotaState {
  limits: Record<LimitKey, number | null>;
  usage: {
    documents: number;
    chunks: number;
    storage_bytes: number;
    embedding_usd: number;
    cognify_usd: number;
  };
}

const GB = 1024 ** 3;

const ROWS: { key: LimitKey; label: string; whole: boolean; unit: string }[] = [
  { key: 'max_documents', label: 'Documents', whole: true, unit: '' },
  { key: 'max_chunks', label: 'Chunks', whole: true, unit: '' },
  { key: 'max_storage_bytes', label: 'Storage', whole: false, unit: 'GB' },
  { key: 'monthly_embedding_usd', label: 'Embedding spend this month', whole: false, unit: '$' },
  { key: 'monthly_cognify_usd', label: 'Knowledge graph spend this month', whole: false, unit: '$' },
];

function used(state: QuotaState, key: LimitKey): number {
  const u = state.usage;
  if (key === 'max_documents') return u.documents;
  if (key === 'max_chunks') return u.chunks;
  if (key === 'max_storage_bytes') return u.storage_bytes / GB;
  if (key === 'monthly_embedding_usd') return u.embedding_usd;
  return u.cognify_usd;
}

function shown(n: number, unit: string): string {
  if (unit === '$') return `$${n.toFixed(2)}`;
  if (unit === 'GB') return `${n.toFixed(2)} GB`;
  return n.toLocaleString();
}

function toInput(state: QuotaState, key: LimitKey): string {
  const v = state.limits[key];
  if (v === null || v === undefined) return '';
  return key === 'max_storage_bytes' ? String(v / GB) : String(v);
}

export function KnowledgeQuotaSection() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [state, setState] = useState<QuotaState | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const res = await apiFetch<QuotaState>('/api/knowledge-quotas', { throwOnError: false, silent: true });
    if (res.data) {
      setState(res.data);
      setDraft(Object.fromEntries(ROWS.map((r) => [r.key, toInput(res.data as QuotaState, r.key)])));
      setLoadError('');
    } else {
      setLoadError(res.error || 'Knowledge limits could not be loaded.');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const problems = ROWS.map((r) => quotaProblem(draft[r.key] ?? '', r.whole));
  const invalid = problems.some(Boolean);

  const save = async () => {
    if (invalid) return;
    setSaving(true);
    setSaveError('');
    const body: Record<string, number | null> = {};
    for (const r of ROWS) {
      const raw = (draft[r.key] ?? '').trim();
      if (!raw) body[r.key] = null;
      else body[r.key] = r.key === 'max_storage_bytes' ? Math.round(Number(raw) * GB) : Number(raw);
    }
    const res = await apiFetch('/api/admin/knowledge-quotas', {
      method: 'PUT',
      body: JSON.stringify(body),
      throwOnError: false,
    });
    setSaving(false);
    if (res.error) {
      setSaveError(res.error);
      return;
    }
    toastSuccess('Knowledge limits saved', 'They apply to the next upload, sync or re-embed');
    await load();
  };

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4 space-y-3" data-testid="knowledge-quotas">
      <h2 className="text-sm font-semibold text-white flex items-center gap-2">
        <BookOpen className="w-4 h-4 text-cyan-400" />
        Knowledge limits for this workspace
      </h2>
      <p className="text-xs text-slate-400">
        Uploads, connector syncs, re-embeds and graph builds stop with a clear message at these limits. Spend resets on the 1st. Blank means no limit, zero allows nothing more.
      </p>
      {loadError && <p role="alert" className="text-xs text-rose-300">{loadError}</p>}
      {!state && !loadError && (
        <p className="text-xs text-slate-500 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </p>
      )}
      {state && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {ROWS.map((r, i) => (
            <div key={r.key} className="rounded-lg bg-slate-900/40 p-3" data-testid={`knowledge-quota-${r.key}`}>
              <p className="text-xs text-slate-400">{r.label}</p>
              <p className="text-sm text-white mt-1">
                {shown(used(state, r.key), r.unit)}
                {!isAdmin && (
                  <span className="text-slate-500">
                    {' of '}
                    {state.limits[r.key] === null ? 'no limit' : shown(Number(toInput(state, r.key)), r.unit)}
                  </span>
                )}
              </p>
              {isAdmin && (
                <label className="block mt-2 text-[11px] text-slate-500">
                  Limit{r.unit ? ` (${r.unit})` : ''}
                  <input
                    inputMode="decimal"
                    value={draft[r.key] ?? ''}
                    onChange={(e) => { setDraft({ ...draft, [r.key]: e.target.value }); setSaveError(''); }}
                    placeholder="No limit"
                    aria-label={`Limit for ${r.label}`}
                    aria-invalid={!!problems[i]}
                    className={`mt-1 block w-full bg-slate-900 border rounded px-2 py-1 text-xs text-white ${problems[i] ? 'border-rose-500/70' : 'border-slate-600'}`}
                  />
                </label>
              )}
              {problems[i] && <p className="text-[10px] text-rose-300 mt-0.5">{problems[i]}</p>}
            </div>
          ))}
        </div>
      )}
      {saveError && <p role="alert" className="text-xs text-rose-300">{saveError}</p>}
      {state && isAdmin && (
        <button
          onClick={save}
          disabled={saving || invalid}
          data-testid="knowledge-quota-save"
          className="rounded-md bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save knowledge limits'}
        </button>
      )}
    </div>
  );
}

export default KnowledgeQuotaSection;
