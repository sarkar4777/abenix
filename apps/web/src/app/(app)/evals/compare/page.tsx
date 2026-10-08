'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { CheckCircle2, CircleDashed, ExternalLink, GitCompare, XCircle } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { useApi } from '@/hooks/useApi';
import { TRIGGER_LABEL, pct, runVerdict, shortHash, type Comparison, type EvalResult, type EvalRun } from '@/lib/evals';

interface CompareData extends Comparison {
  a: EvalRun;
  b: EvalRun;
  same_suite: boolean;
  rows: { case_id: string | null; case_name: string; a: EvalResult | null; b: EvalResult | null }[];
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="max-w-6xl mx-auto px-6 py-8"><div className="h-24 rounded-xl bg-slate-800/40 animate-pulse" /></div>}>
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const sp = useSearchParams();
  const a = sp.get('a');
  const b = sp.get('b');
  const { data, error } = useApi<CompareData>(a && b ? `/api/evals/runs/${a}/compare/${b}` : null);
  const [onlyChanged, setOnlyChanged] = useState(false);

  if (!a || !b) return <div className="max-w-6xl mx-auto px-6 py-8 text-sm text-slate-400">Pick two runs on a suite&apos;s Runs tab to compare them.</div>;
  if (error) return <div className="max-w-6xl mx-auto px-6 py-8"><div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div></div>;
  if (!data) return <div className="max-w-6xl mx-auto px-6 py-8"><div className="h-24 rounded-xl bg-slate-800/40 animate-pulse" /></div>;

  const regressed = new Set(data.regressions.map((r) => r.case_id || r.case_name));
  const fixed = new Set(data.improvements.map((r) => r.case_id || r.case_name));
  const rows = data.rows.filter((r) => !onlyChanged || regressed.has(r.case_id || r.case_name) || fixed.has(r.case_id || r.case_name) || !r.a || !r.b);

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        className="mb-1"
        title="Compare runs"
        purpose="Two evaluation runs side by side, case by case, so you can see what got better or worse. For whoever is changing the agent."
        icon={GitCompare}
        storageKey="eval-compare"
        docSlug="08-howto/10-evals"
        back={{ href: `/evals/${data.a.suite_id}`, label: 'Back to the suite' }}
        primaryAction={{ label: 'Open run B', href: `/evals/runs/${data.b.id}`, icon: ExternalLink }}
        steps={[
          'A is the earlier run and B the one you are checking.',
          'Red rows passed in A and fail in B. Green rows were fixed.',
          'Tick Only what changed to hide cases that behaved the same. Click run to open the real execution.',
        ]}
      />
      {!data.same_suite && <p className="text-sm text-amber-300 mb-2">These runs belong to different suites, so only cases with the same id line up.</p>}
      <div className="grid gap-3 md:grid-cols-2 my-5" data-testid="eval-compare-heads">
        <RunHead label="A" run={data.a} />
        <RunHead label="B" run={data.b} />
      </div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs">
        <span className="text-rose-300">{data.counts.regressions} passed in A and fail in B</span>
        <span className="text-emerald-300">{data.counts.improvements} fail in A and pass in B</span>
        <span className="text-slate-400">{data.counts.still_passing} pass in both, {data.counts.still_failing} fail in both</span>
        <label className="ml-auto inline-flex items-center gap-1.5 text-slate-300">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} className="accent-cyan-500" /> Only what changed
        </label>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm" data-testid="eval-compare-table">
          <thead className="bg-slate-900/80 text-xs text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Case</th>
              <th className="px-3 py-2 text-left font-medium w-[38%]">A</th>
              <th className="px-3 py-2 text-left font-medium w-[38%]">B</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const k = r.case_id || r.case_name;
              const tone = regressed.has(k) ? 'bg-rose-500/5' : fixed.has(k) ? 'bg-emerald-500/5' : '';
              return (
                <tr key={k} className={`border-t border-slate-800 align-top ${tone}`}>
                  <td className="px-3 py-2 text-white">
                    {r.case_name}
                    {regressed.has(k) && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded border border-rose-500/30 text-rose-300">regressed</span>}
                    {fixed.has(k) && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-300">fixed</span>}
                  </td>
                  <Cell r={r.a} />
                  <Cell r={r.b} />
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunHead({ label, run }: { label: string; run: EvalRun }) {
  const v = runVerdict(run);
  return (
    <Link href={`/evals/runs/${run.id}`} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-600 block">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-400">{label}</span>
        <span className="text-2xl font-semibold text-white tabular-nums">{pct(run.score)}</span>
        <span className={`text-[11px] px-1.5 py-0.5 rounded border ${v.cls}`}>{v.label}</span>
      </div>
      <div className="mt-1 text-xs text-slate-400 font-mono">{run.model}{run.model_override ? ' (override)' : ''}</div>
      <div className="text-xs text-slate-500">
        {run.created_at ? new Date(run.created_at).toLocaleString() : ''} · {TRIGGER_LABEL[run.triggered_by]} · version {shortHash(run.config_hash)} · ${run.cost.toFixed(4)}
      </div>
    </Link>
  );
}

function Cell({ r }: { r: EvalResult | null }) {
  if (!r) return <td className="px-3 py-2 text-xs text-slate-500"><CircleDashed className="inline w-3.5 h-3.5 mr-1" />Not in this run</td>;
  const firstFail = r.error || r.assertion_results.find((x) => x.passed === false)?.reason;
  return (
    <td className="px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs">
        {r.passed ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : <XCircle className="w-3.5 h-3.5 text-rose-400" />}
        <span className={r.passed ? 'text-emerald-300' : 'text-rose-300'}>{r.passed ? 'Passed' : 'Failed'}</span>
        <span className="text-slate-500 tabular-nums">{pct(r.score)}</span>
        {r.execution_id && <Link href={`/executions/${r.execution_id}`} className="ml-auto text-cyan-300 hover:underline">run</Link>}
      </div>
      {firstFail && <p className="mt-1 text-xs text-rose-200/80">{firstFail}</p>}
      {r.output_excerpt && <p className="mt-1 text-xs text-slate-400 line-clamp-3 whitespace-pre-wrap">{r.output_excerpt}</p>}
    </td>
  );
}
