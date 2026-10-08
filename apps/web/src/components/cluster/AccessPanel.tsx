'use client';

import { Info, Lock } from 'lucide-react';
import { hiddenAccess, type AccessRow } from '@/lib/cluster';

export default function AccessPanel({ access, rbacValue, rbacSetting }: { access: AccessRow[]; rbacValue: string; rbacSetting: string | null }) {
  const { blocking, optional } = hiddenAccess(access);
  if (!blocking.length && !optional.length) return null;
  return (
    <div className="space-y-3 mb-6">
      {blocking.length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4" data-testid="cluster-access-panel">
          <div className="flex items-start gap-3">
            <Lock className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-amber-200">Some cluster details are hidden</div>
              <p className="text-xs text-amber-100/80 mt-1">
                The API&apos;s service account is not allowed to read everything this page shows.
                {rbacSetting === 'false'
                  ? <> The read-only role is switched off in this release (<code className="px-1 rounded bg-black/30">{rbacValue}: false</code>).</>
                  : <> The read-only role from the helm chart is not installed yet.</>}
                {' '}Set <code className="px-1 rounded bg-black/30">{rbacValue}=true</code> and run <code className="px-1 rounded bg-black/30">helm upgrade</code>. It grants get, list and watch only, never secrets or writes.
              </p>
              <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                {blocking.map((a) => (
                  <li key={a.key} className="text-xs rounded-lg border border-amber-500/20 bg-black/20 px-3 py-2" data-testid="cluster-access-missing" data-key={a.key}>
                    <div className="text-amber-200 font-medium">{a.label}</div>
                    <div className="text-amber-100/70">Missing: {a.why}.</div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
      {optional.length > 0 && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3" data-testid="cluster-access-optional">
          {optional.filter((a, i) => optional.findIndex((b) => b.fix === a.fix) === i).map((a) => (
            <div key={a.key} className="flex items-start gap-2 text-xs text-slate-400 py-0.5">
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-slate-500" />
              <span>{a.fix}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
