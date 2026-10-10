'use client';

import { useMemo, useState } from 'react';
import { ClipboardPaste, X } from 'lucide-react';
import { TYPE_LABEL, type FactType, type OutcomeType, type RuleDoc } from '@/lib/decisions';
import { OUTCOME_TYPE_LABEL } from '@/lib/decisionValues';
import { EXTRA_COLUMNS, applyPaste, planPaste, type ColRole, type PasteColumn, type PastePlan } from '@/lib/decisionPaste';

const ROLE_LABEL: Record<ColRole, string> = {
  rule: 'Rule key', description: 'What it means', sources: 'Sources', requires: 'Facts it needs', valid_from: 'Valid from', valid_to: 'Valid to',
  fact: 'Fact (a condition)', outcome: 'Outcome (the answer)', skip: 'Leave out',
};

export const PASTE_EXAMPLE = 'rule\tworker.distance_m\taction\nstop.close\t< 2\tstop\nok.clear\t>= 2\tok';

// the review step: what each column becomes, and what will be created
export function PastePreview({ plan, onPlan }: { plan: PastePlan; onPlan: (p: PastePlan) => void }) {
  const setCol = (i: number, patch: Partial<PasteColumn>) => onPlan({ ...plan, columns: plan.columns.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  return (
    <div className="space-y-2" data-testid="paste-preview">
      <p className="text-xs text-slate-400">
        {plan.rows.length} row{plan.rows.length === 1 ? '' : 's'} found{plan.hasHeader ? ', with a header row' : ', no header row so the columns follow the table'}. Check what each column is.
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-900/60 text-slate-400">
            <tr><th className="px-2 py-1.5 text-left">Column</th><th className="px-2 py-1.5 text-left">Is</th><th className="px-2 py-1.5 text-left">Type</th><th className="px-2 py-1.5 text-left">First value</th></tr>
          </thead>
          <tbody>
            {plan.columns.map((c, i) => {
              const custom = !c.exists || c.role === 'skip';
              const sample = plan.rows.find((r) => (r[i] ?? '').trim())?.[i] ?? '';
              return (
                <tr key={i} className="border-t border-slate-800" data-testid={`paste-col-${i}`}>
                  <td className="px-2 py-1 font-mono text-slate-200 max-w-[180px] truncate" title={c.header}>{c.header || `column ${i + 1}`}</td>
                  <td className="px-2 py-1">
                    {custom ? (
                      <select value={c.role} onChange={(e) => setCol(i, { role: e.target.value as ColRole })} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-xs text-white" aria-label={`What ${c.header || `column ${i + 1}`} is`} data-testid={`paste-col-${i}-role`}>
                        {c.target && <option value="fact">{ROLE_LABEL.fact}</option>}
                        {c.target && <option value="outcome">{ROLE_LABEL.outcome}</option>}
                        <option value="rule">{ROLE_LABEL.rule}</option>
                        {EXTRA_COLUMNS.map((x) => <option key={x.role} value={x.role}>{ROLE_LABEL[x.role]}</option>)}
                        <option value="skip">{ROLE_LABEL.skip}</option>
                      </select>
                    ) : (
                      <span className="text-slate-300">{ROLE_LABEL[c.role]}{c.role === 'fact' || c.role === 'outcome' ? <span className="text-slate-500"> · already there</span> : null}</span>
                    )}
                    {!c.exists && (c.role === 'fact' || c.role === 'outcome') && <span className="ml-1.5 text-[10px] px-1 rounded bg-cyan-500/15 text-cyan-200">new {c.target}</span>}
                  </td>
                  <td className="px-2 py-1">
                    {!c.exists && c.role === 'fact' ? (
                      <select value={c.type} onChange={(e) => setCol(i, { type: e.target.value as FactType })} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-xs text-white" aria-label={`Type of ${c.target}`} data-testid={`paste-col-${i}-type`}>
                        {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                      </select>
                    ) : !c.exists && c.role === 'outcome' ? (
                      <select value={c.type} onChange={(e) => setCol(i, { type: e.target.value as OutcomeType })} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-xs text-white" aria-label={`Type of ${c.target}`} data-testid={`paste-col-${i}-type`}>
                        {(['number', 'string', 'boolean', 'date'] as OutcomeType[]).map((t) => <option key={t} value={t}>{OUTCOME_TYPE_LABEL[t]}</option>)}
                      </select>
                    ) : c.role === 'fact' ? <span className="text-slate-500">{TYPE_LABEL[c.type as FactType] ?? ''}</span> : c.role === 'outcome' ? <span className="text-slate-500">{OUTCOME_TYPE_LABEL[c.type as OutcomeType] ?? ''}</span> : null}
                  </td>
                  <td className="px-2 py-1 text-slate-400 max-w-[160px] truncate" title={sample}>{sample || <span className="italic text-slate-600">empty</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function usePastePlan(doc: RuleDoc, defaults: PasteColumn[], initialText = '') {
  const [text, setText] = useState(initialText);
  const [edited, setEdited] = useState<PastePlan | null>(null);
  const auto = useMemo(() => (text.trim() ? planPaste(text, doc, defaults) : null), [text, doc, defaults]);
  const plan = edited ?? auto;
  return {
    text,
    setText: (t: string) => { setText(t); setEdited(null); },
    plan,
    setPlan: setEdited,
  };
}

export function pasteSummary(plan: PastePlan): string {
  const facts = plan.columns.filter((c) => !c.exists && c.role === 'fact').length;
  const outs = plan.columns.filter((c) => !c.exists && c.role === 'outcome').length;
  const bits = [`${plan.rows.length} rule${plan.rows.length === 1 ? '' : 's'}`];
  if (facts) bits.push(`${facts} new fact${facts === 1 ? '' : 's'}`);
  if (outs) bits.push(`${outs} new outcome${outs === 1 ? '' : 's'}`);
  return bits.join(', ');
}

export function pasteProblem(plan: PastePlan | null, doc: RuleDoc): string | null {
  if (!plan) return null;
  if (!plan.rows.length) return 'There are no rows under the header. Paste the header row and at least one rule.';
  if (!plan.hasHeader && !doc.facts.length && !doc.outputs.length) return 'Start with a header row that names each column, like rule, then the facts, then the outcomes.';
  const used = plan.columns.filter((c) => c.role === 'fact' || c.role === 'outcome');
  if (!used.length) return 'No column is a fact or an outcome. Set at least one below.';
  const targets = used.map((c) => c.target);
  const dupe = targets.find((t, i) => targets.indexOf(t) !== i);
  if (dupe) return `${dupe} is used by two columns. Leave one of them out.`;
  return null;
}

export default function PasteRulesDialog({ doc, defaults, initialText, onApply, onClose }: {
  doc: RuleDoc; defaults: PasteColumn[]; initialText?: string; onApply: (d: RuleDoc, msg: string) => void; onClose: () => void;
}) {
  const { text, setText, plan, setPlan } = usePastePlan(doc, defaults, initialText);
  const problem = pasteProblem(plan, doc);

  function apply() {
    if (!plan || problem) return;
    const r = applyPaste(doc, plan);
    onApply(r.doc, `Pasted ${plan.rows.length} row${plan.rows.length === 1 ? '' : 's'}: ${r.added} new, ${r.updated} updated.${r.skipped.length ? ` Left out: ${r.skipped.join(', ')}.` : ''}`);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="paste-title" data-testid="paste-dialog">
      <div className="w-full max-w-3xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 id="paste-title" className="flex items-center gap-2 text-base font-semibold text-white"><ClipboardPaste className="w-4 h-4 text-cyan-400" /> Paste rules from a spreadsheet</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          <p className="text-sm text-slate-400">
            Copy the rows in Excel or Sheets, header row included, and paste them here. Each row becomes a rule. Columns you have not used yet become new facts or outcomes, and you can check them before anything changes. <a href="/docs?doc=08-howto%2F09-decisions#writing-rules" className="text-cyan-300 hover:underline">How cells are written</a>
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            spellCheck={false}
            placeholder={'Paste here. For example:\n' + PASTE_EXAMPLE.replace(/\t/g, '    ')}
            className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono placeholder:text-slate-600"
            aria-label="Rows to paste"
            autoFocus
            data-testid="paste-text"
          />
          {plan && <PastePreview plan={plan} onPlan={setPlan} />}
          {problem && <p className="text-xs text-rose-300" role="alert" data-testid="paste-problem">{problem}</p>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-3 border-t border-slate-800">
          {plan && !problem && <span className="mr-auto text-xs text-slate-400" data-testid="paste-summary">Adds {pasteSummary(plan)}.</span>}
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={apply} disabled={!plan || !!problem} title={!plan ? 'Paste some rows first' : problem || ''} className="px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="paste-apply">
            Add these rules
          </button>
        </div>
      </div>
    </div>
  );
}
