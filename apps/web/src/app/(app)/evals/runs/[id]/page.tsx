'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, GitCompare, Loader2, Sparkles, TrendingDown, TrendingUp, XCircle } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { TRIGGER_LABEL, pct, runVerdict, shortHash, type EvalResult, type RunDetail } from '@/lib/evals';

type Filter = 'all' | 'failed' | 'passed' | 'changed';

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [live, setLive] = useState(true);
  const { data: run, error } = useApi<RunDetail>(id ? `/api/evals/runs/${id}` : null, {
    refreshInterval: live ? 2500 : 0,
    onSuccess: (d: any) => setLive(d?.data?.status === 'queued' || d?.data?.status === 'running'),
  });
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<string | null>(null);

  const changed = useMemo(() => {
    const m = new Map<string, 'regression' | 'improvement'>();
    run?.comparison?.regressions.forEach((r) => r.case_id && m.set(r.case_id, 'regression'));
    run?.comparison?.improvements.forEach((r) => r.case_id && m.set(r.case_id, 'improvement'));
    return m;
  }, [run]);

  const rows = useMemo(() => {
    const all = run?.results || [];
    const by = (r: EvalResult) =>
      filter === 'failed' ? !r.passed : filter === 'passed' ? r.passed : filter === 'changed' ? !!(r.case_id && changed.has(r.case_id)) : true;
    return all.filter(by).sort((a, b) => Number(a.passed) - Number(b.passed));
  }, [run, filter, changed]);

  if (error) return <div className="max-w-6xl mx-auto px-6 py-8"><div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div></div>;
  if (!run) return <div className="max-w-6xl mx-auto px-6 py-8 space-y-3">{[0, 1].map((i) => <div key={i} className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>;

  const v = runVerdict(run);
  const running = run.status === 'queued' || run.status === 'running';
  const cmp = run.comparison;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {run.suite && <Link href={`/evals/${run.suite.id}`} className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-white mb-4"><ArrowLeft className="w-4 h-4" /> {run.suite.name}</Link>}
      <header className="flex flex-wrap items-start gap-6 mb-6">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-white">Run {run.created_at ? new Date(run.created_at).toLocaleString() : ''}</h1>
            <span className={`text-xs px-2 py-0.5 rounded border ${v.cls}`} data-testid="eval-run-verdict">{v.label}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
            <span>{TRIGGER_LABEL[run.triggered_by]}</span>
            <span className="font-mono">{run.model}{run.model_override ? ' (model override)' : ''}</span>
            <span>version <span className="font-mono">{shortHash(run.config_hash)}</span>{run.agent_revision ? `, revision ${run.agent_revision}` : ''}</span>
            <span>${run.cost.toFixed(4)}</span>
          </div>
          {run.error && <p className="mt-2 text-sm text-amber-300">{run.error}</p>}
        </div>
        <div className="flex items-center gap-6">
          <Stat label="Score" value={pct(run.score)} sub={`needs ${pct(run.threshold)}`} testid="eval-run-score" />
          <Stat label="Passed" value={`${run.passed}`} sub={`of ${run.total}`} />
          <Stat label="Failed" value={`${run.failed}`} sub={run.errored ? `${run.errored} did not run` : ' '} />
        </div>
      </header>

      {running && (
        <div className="mb-5 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4" data-testid="eval-run-progress">
          <div className="flex items-center gap-2 text-sm text-sky-100"><Loader2 className="w-4 h-4 animate-spin" /> {run.done} of {run.total} cases done</div>
          <div className="mt-2 h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <div className="h-full bg-sky-400 transition-all" style={{ width: `${run.total ? (run.done / run.total) * 100 : 0}%` }} />
          </div>
        </div>
      )}

      {cmp && (
        <div className="mb-5 rounded-xl border border-slate-800 bg-slate-900/50 p-4" data-testid="eval-run-comparison">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-sm text-white">
              Against the {run.model_override ? 'last regular run' : 'previous run'}
              <span className="text-slate-400"> ({pct(cmp.base_run.score)} on <span className="font-mono">{cmp.base_run.model}</span>)</span>
            </div>
            <div className="flex-1" />
            <span className="inline-flex items-center gap-1 text-xs text-rose-300"><TrendingDown className="w-3.5 h-3.5" /> {cmp.counts.regressions} regressed</span>
            <span className="inline-flex items-center gap-1 text-xs text-emerald-300"><TrendingUp className="w-3.5 h-3.5" /> {cmp.counts.improvements} fixed</span>
            {cmp.counts.added > 0 && <span className="text-xs text-slate-400">{cmp.counts.added} new</span>}
            <Link href={`/evals/compare?a=${cmp.base_run.id}&b=${run.id}`} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline"><GitCompare className="w-3.5 h-3.5" /> Side by side</Link>
          </div>
          {cmp.regressions.length > 0 && (
            <ul className="mt-2 text-xs text-rose-200/90 list-disc list-inside">
              {cmp.regressions.slice(0, 8).map((r) => <li key={r.case_id || r.case_name}>{r.case_name}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="flex items-center gap-1 mb-3" role="radiogroup" aria-label="Filter cases">
        {(
          [
            ['all', `All ${run.results.length}`],
            ['failed', `Failed ${run.results.filter((r) => !r.passed).length}`],
            ['passed', `Passed ${run.results.filter((r) => r.passed).length}`],
            ...(cmp ? [['changed', `Changed ${changed.size}`]] : []),
          ] as [Filter, string][]
        ).map(([f, label]) => (
          <button key={f} type="button" role="radio" aria-checked={filter === f} onClick={() => setFilter(f)} className={`px-3 py-1 text-xs rounded-md ${filter === f ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="space-y-2" data-testid="eval-run-results">
        {rows.map((r) => {
          const isOpen = open === r.id;
          const ch = r.case_id ? changed.get(r.case_id) : undefined;
          return (
            <div key={r.id} className={`rounded-xl border ${r.passed ? 'border-slate-800' : 'border-rose-500/25'} bg-slate-900/50`} data-testid={`eval-result-${r.case_id}`}>
              <button type="button" onClick={() => setOpen(isOpen ? null : r.id)} className="w-full flex items-center gap-3 px-4 py-3 text-left" aria-expanded={isOpen}>
                {isOpen ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                {r.passed ? <CheckCircle2 className="w-4 h-4 text-emerald-400" aria-label="passed" /> : <XCircle className="w-4 h-4 text-rose-400" aria-label="failed" />}
                <span className="flex-1 min-w-0 text-sm text-white truncate">{r.case_name}</span>
                {ch === 'regression' && <span className="text-[10px] px-1.5 py-0.5 rounded border border-rose-500/30 text-rose-300">regressed</span>}
                {ch === 'improvement' && <span className="text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-300">fixed</span>}
                <span className="text-xs text-slate-500 tabular-nums">{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)} s` : ''}</span>
                <span className="text-xs text-slate-400 tabular-nums w-12 text-right">{pct(r.score)}</span>
              </button>
              {!isOpen && !r.passed && (
                <p className="px-11 pb-3 -mt-1 text-xs text-rose-200/80 truncate">
                  {r.error || r.assertion_results.find((a) => a.passed === false)?.reason}
                </p>
              )}
              {isOpen && (
                <div className="border-t border-slate-800 px-4 py-3 space-y-3">
                  {r.error && <p className="text-sm text-amber-300">{r.error}</p>}
                  <ul className="space-y-1.5">
                    {r.assertion_results.map((a, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        {a.passed ? <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" /> : <XCircle className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" />}
                        <span>
                          <span className="text-slate-200">{a.label}</span>
                          {a.deterministic === false && <Sparkles className="inline w-3 h-3 ml-1 text-violet-300" aria-label="judged by a model, not deterministic" />}
                          <span className="block text-xs text-slate-400">{a.reason}</span>
                        </span>
                      </li>
                    ))}
                    {r.assertion_results.length === 0 && <li className="text-xs text-slate-500">No assertions, the case passes when the run finishes.</li>}
                  </ul>
                  {r.output_excerpt && (
                    <div>
                      <div className="text-xs text-slate-500 mb-1">Answer</div>
                      <pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 border border-slate-800 p-3 text-xs text-slate-300 whitespace-pre-wrap">{r.output_excerpt}</pre>
                    </div>
                  )}
                  {r.execution_id && (
                    <Link href={`/executions/${r.execution_id}`} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" data-testid="eval-result-execution">
                      <ExternalLink className="w-3.5 h-3.5" /> Open the execution, with its tools, trace and provenance
                    </Link>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {rows.length === 0 && <p className="text-sm text-slate-500">{running ? 'Results appear as each case finishes.' : 'Nothing matches this filter.'}</p>}
      </div>
    </div>
  );
}

function Stat({ label, value, sub, testid }: { label: string; value: string; sub: string; testid?: string }) {
  return (
    <div className="text-right">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-white tabular-nums" data-testid={testid}>{value}</div>
      <div className="text-[11px] text-slate-500">{sub}</div>
    </div>
  );
}
