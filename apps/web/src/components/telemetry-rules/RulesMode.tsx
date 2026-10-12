'use client';

import { useState } from 'react';
import { Cpu, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';

export interface ModeDoc {
  default: string;
  override: string | null;
  chosen: string;
  effective: 'inprocess' | 'pool';
  pool_replicas: number;
  help: string;
}

const LABEL: Record<string, string> = { inprocess: 'inside the ingest', pool: 'in the rules pool' };

// where rules run, and for an admin a quiet way to move them
export default function RulesMode({ mode, isAdmin, onChanged }: { mode: ModeDoc | null; isAdmin: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  if (!mode) return null;
  const waiting = mode.chosen === 'pool' && mode.effective !== 'pool';

  async function set(next: string) {
    setBusy(true);
    const res = await apiFetch('/api/telemetry/rules/mode', { method: 'PUT', body: JSON.stringify({ mode: next === 'default' ? null : next }), silent: true });
    setBusy(false);
    if (res.error) { toastError(res.error); return; }
    toastSuccess(next === 'pool' ? 'Rules move to the rules pool within a couple of seconds.' : 'Rules run where the platform default says, within a couple of seconds.');
    onChanged();
  }

  return (
    <details className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-xs text-slate-400" data-testid="rules-mode">
      <summary className="flex cursor-pointer select-none items-center gap-1.5">
        <Cpu className="h-3.5 w-3.5 text-slate-500" aria-hidden />
        <span>
          Rules run <span className="text-slate-200" data-testid="rules-mode-effective">{LABEL[mode.effective]}</span>
          {mode.effective === 'pool' ? ` (${mode.pool_replicas} ${mode.pool_replicas === 1 ? 'replica' : 'replicas'})` : ''}
          {waiting ? ', the pool is not running so they stay in the ingest' : ''}
        </span>
      </summary>
      <p className="mt-2 max-w-3xl text-slate-400">{mode.help}</p>
      {isAdmin ? (
        <label className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-slate-300">For this workspace</span>
          <select
            value={mode.override ?? 'default'}
            disabled={busy}
            onChange={(e) => void set(e.target.value)}
            className="min-h-[34px] rounded-md border border-slate-700 bg-slate-900 px-2 text-xs text-slate-200"
            data-testid="rules-mode-select"
          >
            <option value="default">Platform default ({LABEL[mode.default] ?? mode.default})</option>
            <option value="inprocess">Inside the ingest</option>
            <option value="pool" disabled={!mode.pool_replicas}>In the rules pool{mode.pool_replicas ? '' : ', not running here'}</option>
          </select>
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-label="Saving" />}
          {!mode.pool_replicas && <span className="text-slate-500">An operator turns the pool on with telemetryRules.enabled in the Helm values.</span>}
        </label>
      ) : (
        <p className="mt-1 text-slate-500">An admin chooses where rules run.</p>
      )}
    </details>
  );
}
