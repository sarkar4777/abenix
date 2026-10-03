'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { FlaskConical, Loader2, Lock, Plus, Search } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import { Sparkline } from '@/components/evals/RunsChart';
import CreateSuiteDialog from '@/components/evals/CreateSuiteDialog';
import { SCHEDULES, ago, pct, runVerdict, type SuiteRow, type Tier } from '@/lib/evals';

export default function EvalsPage() {
  const { perms } = useMyPermissions();
  const canRun = holds(perms?.capabilities, 'evals.run');
  const canManage = holds(perms?.capabilities, 'evals.manage');
  const { data, isLoading, error } = useApi<SuiteRow[]>(canRun ? '/api/evals/suites' : null, { refreshInterval: 10000 });
  const [q, setQ] = useState('');
  const [creating, setCreating] = useState(false);

  const rows = useMemo(() => {
    const n = q.trim().toLowerCase();
    return (data || []).filter((s) => !n || s.name.toLowerCase().includes(n) || (s.agent?.name || '').toLowerCase().includes(n));
  }, [data, q]);

  if (perms && !canRun) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <FlaskConical className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h1 className="text-xl font-semibold text-white">Evaluations</h1>
        <p className="text-slate-400 mt-2">Evaluations need the evals.run capability. An admin can grant it under Admin, Permissions.</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <FlaskConical className="w-6 h-6 text-cyan-400" />
            <h1 className="text-3xl font-semibold text-white">Evaluations</h1>
          </div>
          <p className="text-slate-400 max-w-3xl">
            Golden cases for an agent or pipeline, each with checks on its answer. Run them on every change, compare
            versions and models, and let high risk agents publish only when their gating suite passes.
          </p>
        </div>
        {canManage && (
          <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="eval-new-suite">
            <Plus className="w-4 h-4" /> New suite
          </button>
        )}
      </header>

      {(data || []).length > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 mb-4 max-w-md">
          <Search className="w-4 h-4 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search suites or agents…" className="flex-1 bg-transparent py-2 text-sm text-white outline-none" aria-label="Search suites" />
        </div>
      )}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div>
      ) : isLoading && !data ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
      ) : (data || []).length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-700 p-8" data-testid="eval-empty">
          <h2 className="text-lg font-semibold text-white">No suites yet</h2>
          <ol className="mt-3 space-y-1.5 text-sm text-slate-400 list-decimal list-inside">
            <li>Create a suite for an agent or pipeline.</li>
            <li>Add cases by hand, or open any past run under Executions and choose Save as eval case.</li>
            <li>Run the suite. Each case is executed for real and scored against its assertions.</li>
          </ol>
          {canManage ? (
            <button type="button" onClick={() => setCreating(true)} className="mt-5 inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400">
              <Plus className="w-4 h-4" /> Create the first suite
            </button>
          ) : (
            <p className="text-xs text-slate-500 mt-4">Creating suites needs the evals.manage capability.</p>
          )}
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">No suite matches “{q}”.</p>
      ) : (
        <div className="grid gap-3" data-testid="eval-suite-list">
          {rows.map((s) => {
            const tier = (s.agent?.risk_tier || 'low') as Tier;
            const last = s.last_run;
            const v = last ? runVerdict(last) : null;
            return (
              <Link key={s.id} href={`/evals/${s.id}`} className="block rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-600 transition" data-testid={`eval-suite-${s.id}`}>
                <div className="flex flex-wrap items-center gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-semibold text-white">{s.name}</span>
                      {s.gating && (
                        <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-300 bg-amber-500/10" title="This suite must pass before a new version is published, when the tier policy asks for it">
                          <Lock className="w-3 h-3" /> Gates publishing
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <span>{s.agent?.kind === 'pipeline' ? 'Pipeline' : 'Agent'} {s.agent?.name || 'deleted'}</span>
                      <span className={`px-1.5 py-0.5 rounded border ${TIER_STYLE[tier]?.chip}`}>{TIER_STYLE[tier]?.label} risk</span>
                      <span>{s.case_count} case{s.case_count === 1 ? '' : 's'}</span>
                      {s.schedule_cron && <span>· {SCHEDULES.find((x) => x.cron === s.schedule_cron)?.label || s.schedule_cron}</span>}
                    </div>
                  </div>
                  <Sparkline values={s.trend.map((t) => t.score)} />
                  <div className="text-right min-w-[8rem]">
                    {s.active_run ? (
                      <span className="inline-flex items-center gap-1.5 text-xs text-sky-300"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running</span>
                    ) : last ? (
                      <>
                        <div className="text-2xl font-semibold text-white tabular-nums">{pct(last.score)}</div>
                        <div className="flex items-center justify-end gap-1.5 text-[11px]">
                          <span className={`px-1.5 py-0.5 rounded border ${v!.cls}`}>{v!.label}</span>
                          <span className="text-slate-500">{ago(last.completed_at)}</span>
                        </div>
                        {!s.current_version_evaluated && <div className="text-[11px] text-amber-300/80 mt-0.5">Agent changed since</div>}
                      </>
                    ) : (
                      <span className="text-xs text-slate-500">Not run yet</span>
                    )}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {creating && <CreateSuiteDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
