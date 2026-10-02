'use client';

import { useState } from 'react';
import { RotateCcw, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';

type Row = { id: string; name: string; updated_at?: string; creator_name?: string | null };

// Deleted agents the viewer can bring back, with their triggers.
export default function DeletedAgents({ onRestored }: { onRestored?: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { data, meta, mutate } = useApi<Row[]>(open ? '/api/agents/deleted?limit=100' : null);
  const total = Number((meta as { total?: number } | null)?.total ?? (data?.length || 0));

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30" data-testid="deleted-agents">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-300 hover:text-white"
        data-testid="deleted-agents-toggle"
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          Recently deleted
        </span>
        {open && <span className="text-xs text-slate-500">{total}</span>}
      </button>
      {open && (
        <ul className="border-t border-slate-700/50 divide-y divide-slate-700/30">
          {(data || []).length === 0 && (
            <li className="px-4 py-3 text-xs text-slate-500">Nothing deleted that you can restore.</li>
          )}
          {(data || []).map((a) => (
            <li key={a.id} className="px-4 py-2 flex items-center justify-between text-sm">
              <span className="text-slate-300">
                {a.name}
                {a.updated_at && <span className="text-xs text-slate-500"> · deleted {new Date(a.updated_at).toLocaleString()}</span>}
              </span>
              <button
                disabled={busy === a.id}
                onClick={async () => {
                  setBusy(a.id);
                  try {
                    const r = await apiFetch<{ triggers_resumed?: number }>(`/api/agents/${a.id}/restore`, { method: 'POST' });
                    const n = r?.data?.triggers_resumed || 0;
                    toastSuccess(`${a.name} restored`, n ? `${n} trigger${n === 1 ? '' : 's'} switched back on` : undefined);
                    mutate();
                    onRestored?.();
                  } catch (e: any) {
                    toastError('Restore failed', e?.message);
                  }
                  setBusy(null);
                }}
                className="text-xs text-emerald-300 hover:underline flex items-center gap-1 disabled:opacity-50"
                data-testid={`agent-restore-${a.id}`}
              >
                {busy === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />} Restore
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
