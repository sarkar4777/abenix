'use client';

import { useState } from 'react';
import { GitMerge } from 'lucide-react';
import { ruleSentence, type MergeResult, type Rule, type RuleDoc } from '@/lib/decisions';

export default function MergeDialog({
  who,
  result,
  onApply,
  onTakeTheirs,
}: {
  who: string;
  result: MergeResult;
  onApply: (doc: RuleDoc) => void;
  onTakeTheirs: () => void;
}) {
  const [pick, setPick] = useState<Record<string, 'mine' | 'theirs'>>(() => Object.fromEntries(result.conflicts.map((c) => [c.ruleKey, 'mine'])));

  function apply() {
    const byKey = new Map(result.conflicts.map((c) => [c.ruleKey, c]));
    const rules: Rule[] = [];
    for (const r of result.doc.rules) {
      const k = r.key || r.id;
      const c = byKey.get(k);
      if (!c) rules.push(r);
      else {
        const chosen = pick[k] === 'mine' ? c.mine : c.theirs;
        if (chosen) rules.push(chosen);
      }
    }
    for (const c of result.conflicts) {
      if (pick[c.ruleKey] === 'mine' && c.mine && !result.doc.rules.some((r) => (r.key || r.id) === c.ruleKey)) rules.push(c.mine);
    }
    onApply({ ...result.doc, rules });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="merge-title" data-testid="merge-dialog">
      <div className="w-full max-w-3xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 id="merge-title" className="flex items-center gap-2 text-lg font-semibold text-white"><GitMerge className="w-5 h-5 text-cyan-400" /> {who} saved this draft while you were editing</h2>
          <p className="text-sm text-slate-400 mt-1">
            {result.conflicts.length === 0
              ? 'Your changes and theirs touch different rules, so they combine cleanly. Nothing is lost.'
              : `${result.conflicts.length} rule${result.conflicts.length === 1 ? ' was' : 's were'} changed by both of you. Pick which version of each to keep. Everything else combines on its own.`}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {result.conflicts.map((c) => (
            <div key={c.ruleKey} className="rounded-xl border border-slate-800 p-3">
              <div className="text-sm text-white font-medium mb-2">{c.ruleKey}</div>
              <div className="grid gap-2 md:grid-cols-2">
                {(['mine', 'theirs'] as const).map((side) => {
                  const r = side === 'mine' ? c.mine : c.theirs;
                  const on = pick[c.ruleKey] === side;
                  return (
                    <button key={side} type="button" onClick={() => setPick({ ...pick, [c.ruleKey]: side })} aria-pressed={on} className={`text-left rounded-lg border p-3 ${on ? 'border-cyan-500/60 bg-cyan-500/5' : 'border-slate-700 hover:border-slate-500'}`}>
                      <div className="text-xs text-slate-400 mb-1">{side === 'mine' ? 'Your version' : `${who}'s version`}</div>
                      <div className="text-sm text-slate-200">{r ? ruleSentence(result.doc, r) : 'Deleted'}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onTakeTheirs} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Discard mine, use theirs</button>
          <button type="button" onClick={apply} className="px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="merge-apply">
            {result.conflicts.length ? 'Combine with my choices' : 'Combine and save'}
          </button>
        </div>
      </div>
    </div>
  );
}
