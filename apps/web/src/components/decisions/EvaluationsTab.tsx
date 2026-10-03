'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowRight, CheckCircle2, FlaskConical, Loader2, RefreshCw, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { OUTCOME_CHIP, OUTCOME_TEXT, tryHref, type VersionSummary } from '@/lib/decisions';

interface Caller { execution_id?: string; agent?: string; user_id?: string; email?: string; source?: string; tool?: string }
interface EvaluationRow {
  id: string; outcome: string; version: number | null; version_id: string; facts: Record<string, any>; result: any;
  applied_rules: string[]; trace_hash: string; as_of: string | null; known_at: string | null; caller: Caller;
  execution_id: string | null; created_at: string;
}
interface EvaluationDetail extends EvaluationRow {
  applied: { key: string; id?: string; description?: string; citations: string[] }[];
  replay: {
    error?: string; reproduced?: boolean; trace?: { rule_id: string; description: string; values_seen: Record<string, any> }[];
    missing_facts?: string[]; invalid_facts?: { fact: string; expected?: string; value?: string }[]; trace_hash?: string;
  };
}
interface Meta { total: number; limit: number; offset: number; counts: Record<string, number>; log_mode?: string }

const PAGE = 25;

function when(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function CallerCell({ c, executionId }: { c: Caller; executionId: string | null }) {
  if (executionId) {
    const who = c.agent || (c.source === 'pipeline' ? 'A pipeline' : 'An agent');
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        <span className="text-slate-200">{who}</span>
        <Link href={`/executions/${executionId}`} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-0.5 text-cyan-300 hover:underline" data-testid="evaluation-run-link" aria-label={`Open the run of ${who} in the Flight Recorder`}>
          run <ArrowRight className="w-3 h-3" aria-hidden />
        </Link>
      </span>
    );
  }
  if (c.email || c.user_id) return <span className="text-slate-300">API · {c.email || 'a user'}</span>;
  return <span className="text-slate-500">Not known</span>;
}

function Detail({ decisionKey, id, onClose, onOpenVersion }: { decisionKey: string; id: string; onClose: () => void; onOpenVersion: (n: number) => void }) {
  const [d, setD] = useState<EvaluationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setD(null); setErr(null);
    apiFetch<EvaluationDetail>(`/api/decisions/${encodeURIComponent(decisionKey)}/evaluations/${id}`, { throwOnError: false, silent: true }).then((r) => {
      if (!live) return;
      if (r.data) setD(r.data); else setErr(r.error || 'Could not load the evaluation');
    });
    return () => { live = false; };
  }, [decisionKey, id]);

  return (
    <aside className="rounded-xl border border-slate-700 bg-slate-900/70 p-4 space-y-4" aria-label="Evaluation detail" data-testid="evaluation-detail" data-evaluation-id={id}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-white">Evaluation <span className="font-mono text-slate-400">{id.slice(0, 8)}</span></h3>
        <button type="button" onClick={onClose} aria-label="Close evaluation detail" className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
      </div>
      {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
      {!d && !err && <div className="space-y-2" aria-busy="true"><div className="h-4 w-2/3 rounded bg-slate-800 animate-pulse" /><div className="h-24 rounded bg-slate-800 animate-pulse" /></div>}
      {d && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`px-1.5 py-0.5 rounded border ${OUTCOME_CHIP[d.outcome] || OUTCOME_CHIP.no_match}`} data-testid="evaluation-detail-outcome">{OUTCOME_TEXT[d.outcome] || d.outcome}</span>
            {d.version !== null && <button type="button" onClick={() => onOpenVersion(d.version!)} className="text-cyan-300 hover:underline" data-testid="evaluation-detail-version">Version {d.version}</button>}
            <span className="text-slate-500">{when(d.created_at)}</span>
            <span className="text-slate-500">activity date {d.as_of || 'not given'}</span>
          </div>
          <div className="text-xs space-y-1">
            <p className="text-slate-400">Called by <CallerCell c={d.caller || {}} executionId={d.execution_id} /></p>
            {d.execution_id && (
              <Link href={`/executions/${d.execution_id}`} className="inline-flex items-center gap-1 text-cyan-300 hover:underline" data-testid="evaluation-detail-run-link">
                Open the run in the Flight Recorder <ArrowRight className="w-3 h-3" aria-hidden />
              </Link>
            )}
          </div>

          <section>
            <h4 className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Facts given</h4>
            <pre className="text-[11px] text-slate-200 bg-slate-950 border border-slate-800 rounded-md p-2 max-h-48 overflow-auto whitespace-pre-wrap break-all" data-testid="evaluation-detail-facts">{JSON.stringify(d.facts, null, 2)}</pre>
          </section>
          <section>
            <h4 className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Result</h4>
            {d.outcome === 'decided' ? (
              <pre className="text-[11px] text-white bg-slate-950 border border-slate-800 rounded-md p-2 max-h-48 overflow-auto whitespace-pre-wrap break-all" data-testid="evaluation-detail-result">{JSON.stringify(d.result, null, 2)}</pre>
            ) : d.outcome === 'no_match' ? (
              <p className="text-xs text-slate-300" data-testid="evaluation-detail-result">No rule applied to these facts.</p>
            ) : (
              <div className="text-xs text-amber-200 space-y-0.5" data-testid="evaluation-detail-result">
                <p>It could not decide.</p>
                {(d.replay.missing_facts || []).length > 0 && <p>Missing: <span className="font-mono">{d.replay.missing_facts!.join(', ')}</span></p>}
                {(d.replay.invalid_facts || []).map((x) => <p key={x.fact}><span className="font-mono">{x.fact}</span> should be {x.expected}{x.value !== undefined ? `, got “${x.value}”` : ''}.</p>)}
              </div>
            )}
          </section>
          <section>
            <h4 className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Rules that applied</h4>
            {d.applied.length === 0 ? <p className="text-xs text-slate-400">None.</p> : (
              <ul className="space-y-1.5" data-testid="evaluation-detail-rules">
                {d.applied.map((r) => (
                  <li key={r.key} className="text-xs">
                    <span className="font-mono text-cyan-300">{r.key}</span>{r.description && <span className="text-slate-300"> · {r.description}</span>}
                    {r.citations.length > 0 && <ul className="ml-3 mt-0.5 text-[11px] text-slate-400 list-disc list-inside">{r.citations.map((c) => <li key={c}>Source: {c}</li>)}</ul>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h4 className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Trace</h4>
            {d.replay.error ? (
              <p className="text-xs text-rose-300">{d.replay.error}</p>
            ) : (
              <>
                {(d.replay.trace || []).length === 0 ? <p className="text-xs text-slate-400">No rule was traced.</p> : (
                  <ol className="space-y-1 text-[11px] text-slate-300 list-decimal list-inside" data-testid="evaluation-detail-trace">
                    {d.replay.trace!.map((t, i) => (
                      <li key={i}>
                        {t.description || t.rule_id}
                        {Object.keys(t.values_seen || {}).length > 0 && <span className="text-slate-500">, looked at {Object.entries(t.values_seen).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(', ')}</span>}
                      </li>
                    ))}
                  </ol>
                )}
                <p className="mt-2 text-[11px] text-slate-500 break-all">Trace hash <span className="font-mono text-slate-300" data-testid="evaluation-detail-trace-hash">{d.trace_hash || 'none'}</span></p>
                {d.trace_hash && (
                  d.replay.reproduced ? (
                    <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-emerald-300" data-testid="evaluation-reproduced"><CheckCircle2 className="w-3.5 h-3.5" aria-hidden /> Repeated just now with the same version and facts, and the trace hash matches.</p>
                  ) : (
                    <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-amber-300" data-testid="evaluation-reproduced"><AlertTriangle className="w-3.5 h-3.5" aria-hidden /> Repeating it now gives a different trace hash.</p>
                  )
                )}
              </>
            )}
          </section>
          <Link href={tryHref(decisionKey, d.version, { facts: d.facts, as_of: d.as_of })} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-cyan-500/15 text-cyan-200 border border-cyan-500/30 hover:bg-cyan-500/25" data-testid="evaluation-open-try">
            <FlaskConical className="w-3.5 h-3.5" aria-hidden /> Open in Try with these facts
          </Link>
        </>
      )}
    </aside>
  );
}

export default function EvaluationsTab({
  decisionKey, versions, initialEvaluation, onOpenVersion,
}: {
  decisionKey: string; versions: VersionSummary[]; initialEvaluation?: string | null; onOpenVersion: (n: number) => void;
}) {
  const [rows, setRows] = useState<EvaluationRow[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [outcome, setOutcome] = useState('');
  const [version, setVersion] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(initialEvaluation || null);

  const load = useCallback(async () => {
    setLoading(true);
    const q = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (outcome) q.set('outcome', outcome);
    if (version) q.set('version', version);
    const r = await apiFetch<EvaluationRow[]>(`/api/decisions/${encodeURIComponent(decisionKey)}/evaluations?${q}`, { throwOnError: false, silent: true });
    setLoading(false);
    if (r.data) { setRows(r.data); setMeta(r.meta as unknown as Meta); setErr(null); }
    else setErr(r.error || 'Could not load evaluations');
  }, [decisionKey, offset, outcome, version]);

  useEffect(() => { load(); }, [load]);

  const counts = meta?.counts || {};
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const total = meta?.total ?? 0;
  const published = [...versions].filter((v) => v.published_at).sort((a, b) => b.version - a.version);

  return (
    <div className="space-y-3" data-testid="evaluations-tab">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="eval-outcome" className="block text-xs text-slate-400 mb-1">Outcome</label>
          <select id="eval-outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white" data-testid="evaluations-filter-outcome">
            <option value="">All ({all})</option>
            {Object.entries(OUTCOME_TEXT).map(([k, label]) => <option key={k} value={k}>{label} ({counts[k] || 0})</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="eval-version" className="block text-xs text-slate-400 mb-1">Version</label>
          <select id="eval-version" value={version} onChange={(e) => { setVersion(e.target.value); setOffset(0); }} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white" data-testid="evaluations-filter-version">
            <option value="">Any version</option>
            {published.map((v) => <option key={v.id} value={v.version}>Version {v.version}</option>)}
          </select>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-sm border border-slate-700 text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="evaluations-refresh">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <RefreshCw className="w-4 h-4" aria-hidden />} Refresh
        </button>
        <p className="text-[11px] text-slate-500 basis-full">
          Every call from an agent or pipeline run is kept here with the run it came from. API calls are kept when they ask for it{meta?.log_mode && meta.log_mode !== 'none' ? `, and this decision also keeps ${meta.log_mode === 'all' ? 'every evaluation' : 'a sample of all evaluations'}` : ''}.
        </p>
      </div>

      {err && (
        <div className="flex items-center gap-2 rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-200" role="alert" data-testid="evaluations-error">
          <AlertTriangle className="w-4 h-4" aria-hidden /> {err}
          <button type="button" onClick={load} className="ml-auto text-xs underline">Try again</button>
        </div>
      )}

      <div className={`grid gap-4 ${selected ? 'xl:grid-cols-[minmax(0,1fr)_420px]' : ''}`}>
        <div className="min-w-0">
          {rows === null && !err ? (
            <div className="space-y-2" aria-busy="true" data-testid="evaluations-loading">{[0, 1, 2].map((i) => <div key={i} className="h-9 rounded bg-slate-800/50 animate-pulse" />)}</div>
          ) : rows && rows.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-700 px-4 py-10 text-center" data-testid="evaluations-empty">
              <p className="text-sm text-slate-300">{outcome || version ? 'No evaluations match these filters.' : 'No evaluations recorded yet.'}</p>
              <p className="text-xs text-slate-500 mt-1">{outcome || version ? 'Clear a filter to see more.' : 'They appear here as soon as an agent, a pipeline or an API call with persist on uses this decision.'}</p>
            </div>
          ) : rows ? (
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              <table className="w-full text-xs">
                <thead className="bg-slate-900/60 text-slate-400">
                  <tr>
                    <th scope="col" className="text-left font-medium px-3 py-2">Time</th>
                    <th scope="col" className="text-left font-medium px-3 py-2">Version</th>
                    <th scope="col" className="text-left font-medium px-3 py-2">Outcome</th>
                    <th scope="col" className="text-left font-medium px-3 py-2">Called by</th>
                    <th scope="col" className="text-left font-medium px-3 py-2">Trace hash</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => setSelected(r.id)}
                      className={`border-t border-slate-800 cursor-pointer hover:bg-slate-800/40 ${selected === r.id ? 'bg-cyan-500/5' : ''}`}
                      data-testid="evaluation-row"
                      data-evaluation-id={r.id}
                      data-execution-id={r.execution_id || ''}
                      aria-selected={selected === r.id}
                    >
                      <td className="px-3 py-2 whitespace-nowrap">
                        <button type="button" onClick={(e) => { e.stopPropagation(); setSelected(r.id); }} className="text-slate-200 hover:underline" aria-label={`Open the evaluation from ${when(r.created_at)}`}>{when(r.created_at)}</button>
                      </td>
                      <td className="px-3 py-2 text-slate-300">{r.version !== null ? `v${r.version}` : '?'}</td>
                      <td className="px-3 py-2"><span className={`px-1.5 py-0.5 rounded border ${OUTCOME_CHIP[r.outcome] || OUTCOME_CHIP.no_match}`}>{OUTCOME_TEXT[r.outcome] || r.outcome}</span></td>
                      <td className="px-3 py-2"><CallerCell c={r.caller || {}} executionId={r.execution_id} /></td>
                      <td className="px-3 py-2 font-mono text-slate-400" title={r.trace_hash}>{r.trace_hash ? r.trace_hash.slice(0, 12) : 'none'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between px-3 py-2 border-t border-slate-800 text-xs text-slate-400">
                <span data-testid="evaluations-range">{total ? `${offset + 1} to ${Math.min(offset + PAGE, total)} of ${total}` : '0'}</span>
                <span className="flex gap-2">
                  <button type="button" disabled={offset === 0 || loading} onClick={() => setOffset((o) => Math.max(0, o - PAGE))} className="px-2 py-0.5 rounded border border-slate-700 disabled:opacity-40" data-testid="evaluations-prev">Newer</button>
                  <button type="button" disabled={offset + PAGE >= total || loading} onClick={() => setOffset((o) => o + PAGE)} className="px-2 py-0.5 rounded border border-slate-700 disabled:opacity-40" data-testid="evaluations-next">Older</button>
                </span>
              </div>
            </div>
          ) : null}
        </div>
        {selected && <Detail decisionKey={decisionKey} id={selected} onClose={() => setSelected(null)} onOpenVersion={onOpenVersion} />}
      </div>
    </div>
  );
}
