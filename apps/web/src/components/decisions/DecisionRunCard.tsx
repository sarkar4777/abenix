'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Check, Copy, FlaskConical, GitBranch, History, Scale } from 'lucide-react';
import { OUTCOME_CHIP, OUTCOME_TEXT, formatDuration, tryHref, type DecisionRecord } from '@/lib/decisions';

function show(v: unknown): string {
  if (v === null || v === undefined) return 'empty';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

function outputRows(result: unknown): [string, unknown][] {
  if (result === null || result === undefined) return [];
  if (Array.isArray(result)) {
    return result.flatMap((item, i) =>
      item && typeof item === 'object' ? Object.entries(item).map(([k, v]) => [`${i + 1}. ${k}`, v] as [string, unknown]) : [[`${i + 1}`, item] as [string, unknown]],
    );
  }
  if (typeof result === 'object') return Object.entries(result as Record<string, unknown>);
  return [['result', result]];
}

function CopyText({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }}
      className="text-slate-500 hover:text-white"
      aria-label={label}
      title={label}
    >
      {done ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

export default function DecisionRunCard({ record, args }: { record: DecisionRecord; args?: Record<string, unknown> }) {
  const facts = record.facts ?? (args?.facts && typeof args.facts === 'object' ? (args.facts as Record<string, unknown>) : null);
  const asOf = record.as_of ?? (typeof args?.as_of === 'string' ? args.as_of : null);
  const rows = outputRows(record.result);
  const versionHref = `/decisions/${encodeURIComponent(record.key)}?version=${record.version}`;
  const blocked = record.outcome === 'missing_facts' || record.outcome === 'invalid_facts';
  const dur = formatDuration(record.duration_us);

  return (
    <section className="rounded-lg border border-slate-700/60 bg-slate-900/60 p-3 space-y-3" aria-label={`Decision ${record.name || record.key}`} data-testid="decision-card">
      <div className="flex flex-wrap items-center gap-2">
        <Scale className="w-4 h-4 text-cyan-400" aria-hidden />
        <span className="text-sm font-medium text-white">{record.name || record.key}</span>
        <span className="text-[11px] font-mono text-slate-500">{record.key}</span>
        <span className={`text-[11px] px-1.5 py-0.5 rounded border ${OUTCOME_CHIP[record.outcome] || OUTCOME_CHIP.no_match}`} data-testid="decision-outcome" data-outcome={record.outcome}>
          {OUTCOME_TEXT[record.outcome] || record.outcome}
        </span>
        {dur && <span className="text-[10px] text-slate-500">evaluated in {dur}</span>}
      </div>

      {record.outcome === 'decided' && (
        <div data-testid="decision-outputs">
          <p className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Outputs</p>
          {record.result_truncated ? (
            <p className="text-xs text-slate-400">The result is too large to keep on the run. Open the evaluation to see all of it.</p>
          ) : rows.length === 0 ? (
            <p className="text-xs text-slate-400">The decision returned no output fields.</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="sr-only"><tr><th>Output</th><th>Value</th></tr></thead>
              <tbody>
                {rows.map(([k, v]) => (
                  <tr key={k} className="border-t border-slate-800 first:border-t-0">
                    <td className="py-1 pr-3 text-slate-400 font-mono align-top w-1/3">{k}</td>
                    <td className="py-1 text-white break-all" data-testid="decision-output-value">{show(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {record.outcome === 'no_match' && (
        <p className="text-xs text-slate-300" data-testid="decision-outputs">No rule applies to these facts, so this decision requires nothing.</p>
      )}

      {blocked && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2.5 py-2 text-xs text-amber-100 space-y-1" data-testid="decision-fact-problems" role="note">
          <p>It could not decide with the facts it was given.</p>
          {record.missing_facts.length > 0 && <p>Missing: <span className="font-mono">{record.missing_facts.join(', ')}</span></p>}
          {record.invalid_facts.length > 0 && (
            <ul className="space-y-0.5">
              {record.invalid_facts.map((x) => (
                <li key={x.fact}><span className="font-mono">{x.fact}</span> should be {x.expected || 'another type'}{x.value !== undefined ? `, got “${x.value}”` : ''}.</li>
              ))}
            </ul>
          )}
          {record.explanation && <p className="text-amber-200/80">{record.explanation}</p>}
        </div>
      )}

      {!blocked && (
        <div data-testid="decision-rules">
          <p className="text-[10px] uppercase font-semibold text-slate-500 mb-1">Rules that applied</p>
          {record.applied_rules.length === 0 ? (
            <p className="text-xs text-slate-400">No rule applied.</p>
          ) : (
            <ul className="space-y-1.5">
              {record.applied_rules.map((r) => (
                <li key={r.key} className="text-xs" data-testid="decision-rule" data-rule={r.key}>
                  <span className="font-mono text-cyan-300">{r.key}</span>
                  {r.description && <span className="text-slate-300"> · {r.description}</span>}
                  {r.citations.length > 0 ? (
                    <ul className="mt-0.5 ml-3 text-[11px] text-slate-400 list-disc list-inside">
                      {r.citations.map((c) => <li key={c} data-testid="decision-citation">Source: {c}</li>)}
                    </ul>
                  ) : (
                    <p className="mt-0.5 ml-3 text-[11px] text-slate-500">No source cited for this rule.</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <div className="flex items-center gap-1.5">
          <dt className="text-slate-500">Version</dt>
          <dd>
            <Link href={versionHref} className="inline-flex items-center gap-1 text-cyan-300 hover:underline" data-testid="decision-version-link" aria-label={`Open version ${record.version} of ${record.key}`}>
              <GitBranch className="w-3 h-3" aria-hidden /> Version {record.version}
            </Link>
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="text-slate-500">Activity date</dt>
          <dd className="text-slate-300">{asOf || 'today'}{record.known_at ? `, rules as known on ${record.known_at.slice(0, 10)}` : ''}</dd>
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          <dt className="text-slate-500 shrink-0">Trace hash</dt>
          {record.trace_hash ? (
            <>
              <dd className="font-mono text-slate-300 truncate" title={record.trace_hash} data-testid="decision-trace-hash">{record.trace_hash.slice(0, 16)}</dd>
              <CopyText text={record.trace_hash} label="Copy trace hash" />
            </>
          ) : (
            <dd className="text-slate-500" data-testid="decision-trace-hash">none, it did not run the rules</dd>
          )}
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          <dt className="text-slate-500 shrink-0">Evaluation</dt>
          {record.evaluation_id ? (
            <dd className="min-w-0 flex items-center gap-1">
              <Link
                href={`/decisions/${encodeURIComponent(record.key)}?tab=evaluations&evaluation=${record.evaluation_id}`}
                className="font-mono text-cyan-300 hover:underline truncate"
                data-testid="decision-evaluation-id"
                title={record.evaluation_id}
                aria-label={`Open recorded evaluation ${record.evaluation_id}`}
              >
                {record.evaluation_id.slice(0, 8)}
              </Link>
              <CopyText text={record.evaluation_id} label="Copy evaluation id" />
            </dd>
          ) : (
            <dd className="text-slate-500" data-testid="decision-evaluation-id">not recorded, the call asked not to keep it</dd>
          )}
        </div>
      </dl>

      <div className="flex flex-wrap gap-2 pt-1">
        {facts ? (
          <Link
            href={tryHref(record.key, record.version, { facts: facts as Record<string, unknown>, as_of: asOf })}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-cyan-500/15 text-cyan-200 border border-cyan-500/30 hover:bg-cyan-500/25"
            data-testid="decision-open-try"
          >
            <FlaskConical className="w-3.5 h-3.5" aria-hidden /> Open in Try with these facts
          </Link>
        ) : (
          <span className="text-[11px] text-slate-500" data-testid="decision-open-try-unavailable">The facts were too large to keep on the run, so Try cannot be preloaded.</span>
        )}
        <Link
          href={`/decisions/${encodeURIComponent(record.key)}?tab=evaluations`}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-slate-300 border border-slate-700 hover:bg-slate-800"
          data-testid="decision-open-evaluations"
        >
          <History className="w-3.5 h-3.5" aria-hidden /> All evaluations
        </Link>
      </div>
    </section>
  );
}
