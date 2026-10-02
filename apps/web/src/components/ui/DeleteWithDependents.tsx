'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';

type Dep = { id: string; name: string; kind?: string };
type Deps = Record<string, Dep[]>;

const GROUP_LABEL: Record<string, string> = {
  pipelines: 'Pipelines',
  agents: 'Agents',
  triggers: 'Triggers',
  atlas_graphs: 'Atlas graphs',
};

const AFTER: Record<string, string> = {
  pipelines: 'fail at the step that uses it',
  agents: 'can no longer call it',
  triggers: 'are switched off',
  atlas_graphs: 'are unbound from it',
};

function hrefFor(group: string, d: Dep): string {
  if (group === 'triggers') return '/triggers';
  if (group === 'atlas_graphs') return `/atlas?graph=${d.id}`;
  return `/agents/${d.id}/info`;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** e.g. `/api/agents/${id}` — dependents are read from `${resource}/dependents` */
  resource: string;
  name: string;
  what: string;
  /** called with force=true when the user confirmed despite dependents */
  onConfirm: (force: boolean) => Promise<void> | void;
  note?: string;
}

export default function DeleteWithDependents({ open, onClose, resource, name, what, onConfirm, note }: Props) {
  const [deps, setDeps] = useState<Deps | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEscapeToClose(open && !busy, onClose);

  useEffect(() => {
    if (!open) return;
    setDeps(null);
    setFailed(false);
    apiFetch<Deps>(`${resource}/dependents`, { silent: true })
      .then((r) => setDeps((r?.data as Deps) || {}))
      .catch(() => {
        setFailed(true);
        setDeps({});
      });
  }, [open, resource]);

  if (!open) return null;
  const groups = Object.entries(deps || {}).filter(([, v]) => v.length > 0);
  const total = groups.reduce((n, [, v]) => n + v.length, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="delete-deps-title" data-testid="delete-dialog">
      <div className="mx-4 w-full max-w-md rounded-2xl border border-slate-700/50 bg-slate-800/95 p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-3 mb-3">
          <h2 id="delete-deps-title" className="text-base font-semibold text-white flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400" /> Delete {what} &ldquo;{name}&rdquo;?
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white" disabled={busy}>
            <X className="w-4 h-4" />
          </button>
        </div>

        {deps === null ? (
          <p className="text-xs text-slate-400 flex items-center gap-2" data-testid="delete-checking">
            <Loader2 className="w-3 h-3 animate-spin" /> Checking what uses it…
          </p>
        ) : total === 0 ? (
          <p className="text-xs text-slate-300" data-testid="delete-no-dependents">
            {failed ? 'Could not check what uses it. ' : 'Nothing else uses it. '}
            {note || ''}
          </p>
        ) : (
          <div className="space-y-3" data-testid="delete-dependents" data-count={total}>
            <p className="text-xs text-amber-200">
              {total} item{total === 1 ? '' : 's'} use{total === 1 ? 's' : ''} this {what}. If you delete it:
            </p>
            {groups.map(([group, items]) => (
              <div key={group}>
                <p className="text-[11px] uppercase tracking-wider text-slate-400 mb-1">
                  {GROUP_LABEL[group] || group} {AFTER[group] ? <span className="normal-case tracking-normal text-slate-500">· {AFTER[group]}</span> : null}
                </p>
                <ul className="space-y-0.5 max-h-32 overflow-y-auto">
                  {items.map((d) => (
                    <li key={d.id} className="text-xs">
                      <Link href={hrefFor(group, d)} className="text-cyan-300 hover:underline" target="_blank">
                        {d.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {note && <p className="text-[11px] text-slate-500">{note}</p>}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="px-3 py-1.5 text-xs text-slate-300 hover:text-white">
            Cancel
          </button>
          <button
            data-testid="delete-confirm"
            disabled={busy || deps === null}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm(total > 0);
                onClose();
              } finally {
                setBusy(false);
              }
            }}
            className="px-3 py-1.5 rounded-lg bg-red-500/80 hover:bg-red-500 text-white text-xs disabled:opacity-50 flex items-center gap-1"
          >
            {busy && <Loader2 className="w-3 h-3 animate-spin" />}
            {total > 0 ? 'Delete anyway' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
