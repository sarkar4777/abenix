'use client';

import { useMemo, useState } from 'react';
import { Check, Loader2, Pencil, Trash2, X } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toast } from '@/stores/toastStore';
import { checkSummary, improvementsApi, needsConfirmation, plural, type Assertion, type CaseRow } from '@/lib/improvements';

const input = 'w-full rounded-md border border-slate-700 bg-slate-950/60 px-2.5 py-1.5 text-sm text-slate-100 focus:border-cyan-500 focus:outline-none';

function CaseEditor({ c, onSaved, onCancel }: { c: CaseRow; onSaved: (c: CaseRow) => void; onCancel: () => void }) {
  const judgeAt = c.assertions.findIndex((a) => a.type === 'judge');
  const [name, setName] = useState(c.name);
  const [inp, setInp] = useState(c.input_message);
  const [ref, setRef] = useState(c.reference_output || '');
  const [rubric, setRubric] = useState(judgeAt >= 0 ? String(c.assertions[judgeAt].rubric || '') : '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    if (!name.trim()) { setErr('Give the case a name.'); return; }
    if (!inp.trim()) { setErr('The input cannot be empty.'); return; }
    if (judgeAt >= 0 && !rubric.trim()) { setErr('Say what a good answer looks like.'); return; }
    const assertions: Assertion[] = c.assertions.map((a, i) => (i === judgeAt ? { ...a, rubric: rubric.trim() } : a));
    setBusy(true);
    setErr(null);
    const r = await improvementsApi.patchCase(c.id, {
      name: name.trim(), input_message: inp.trim(), reference_output: ref.trim() || null, assertions,
    });
    setBusy(false);
    if (r.error || !r.data) { setErr(r.error || 'The case was not saved.'); return; }
    onSaved(r.data);
  }

  return (
    <div className="mt-2 space-y-2" data-testid="improvement-case-editor">
      <label className="block text-xs text-slate-400">Name<input value={name} maxLength={255} onChange={(e) => setName(e.target.value)} className={`${input} mt-1`} /></label>
      <label className="block text-xs text-slate-400">Input the agent gets<textarea value={inp} rows={2} onChange={(e) => setInp(e.target.value)} className={`${input} mt-1`} /></label>
      <label className="block text-xs text-slate-400">Right answer <span className="text-slate-600">Optional</span><textarea value={ref} rows={2} onChange={(e) => setRef(e.target.value)} className={`${input} mt-1`} /></label>
      {judgeAt >= 0 && (
        <label className="block text-xs text-slate-400">What a good answer must do<textarea value={rubric} rows={3} onChange={(e) => setRubric(e.target.value)} className={`${input} mt-1`} data-testid="improvement-case-rubric" /></label>
      )}
      {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
        <button type="button" disabled={busy} onClick={save} className="inline-flex items-center gap-1 rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="improvement-case-save">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save
        </button>
      </div>
    </div>
  );
}

export default function SuggestedCases({ cases, canManage, onChanged }: { cases: CaseRow[]; canManage: boolean; onChanged: () => void }) {
  const [rows, setRows] = useState<CaseRow[]>(cases);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [dropIds, setDropIds] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const allPicked = rows.length > 0 && rows.every((c) => picked.has(c.id));
  const pickedIds = useMemo(() => rows.filter((c) => picked.has(c.id)).map((c) => c.id), [rows, picked]);

  function toggle(id: string) {
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  function remove(ids: string[]) {
    setRows((r) => r.filter((c) => !ids.includes(c.id)));
    setPicked((p) => new Set([...p].filter((x) => !ids.includes(x))));
  }

  async function run(ids: string[], action: 'accept' | 'drop') {
    if (!ids.length) return;
    setBusy(ids.length === 1 ? `${action}:${ids[0]}` : `bulk:${action}`);
    setErr(null);
    const r = ids.length === 1
      ? await (action === 'accept' ? improvementsApi.acceptCase(ids[0]) : improvementsApi.dropCase(ids[0]))
          .then((x) => ({ ...x, data: x.data ? { done: [x.data], skipped: [] } : null }))
      : await improvementsApi.bulkCases(ids, action);
    setBusy(null);
    setDropIds(null);
    if (r.error || !r.data) { setErr(r.error || 'Nothing changed. Try again.'); return; }
    const done = r.data.done.map((c) => c.id);
    remove(done);
    if (r.data.skipped.length) setErr(`${plural(r.data.skipped.length, 'case')} could not change: ${r.data.skipped[0].reason}`);
    if (done.length) {
      toast({
        type: 'success',
        title: action === 'accept' ? `${plural(done.length, 'case')} accepted` : `${plural(done.length, 'case')} dropped`,
        message: action === 'accept' ? 'They now run every time a fix is proven.' : undefined,
      });
    }
    onChanged();
  }

  if (rows.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-400" data-testid="improvement-cases-empty">
        No suggested test cases right now. They appear when two lessons point at the same mistake, or after one correction or harm flag.
      </p>
    );
  }

  const blocked = canManage ? undefined : "Only the agent's owner, or someone with the improvements.propose permission, can accept or drop cases.";
  const btn = 'inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50';
  return (
    <div className="space-y-2" data-testid="improvement-cases">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2">
        <label className="inline-flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={allPicked} disabled={!canManage} onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((c) => c.id)))} data-testid="improvement-cases-all" />
          {pickedIds.length ? `${pickedIds.length} picked` : 'Pick all'}
        </label>
        <div className="ml-auto flex flex-wrap gap-2">
          <button type="button" title={blocked} disabled={!canManage || !pickedIds.length || !!busy} onClick={() => run(pickedIds, 'accept')} className={`${btn} border-emerald-500/40 bg-emerald-500/10 text-emerald-200`} data-testid="improvement-cases-accept">
            {busy === 'bulk:accept' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Accept picked
          </button>
          <button type="button" title={blocked} disabled={!canManage || !pickedIds.length || !!busy} onClick={() => setDropIds(pickedIds)} className={`${btn} border-slate-600 text-slate-300`} data-testid="improvement-cases-drop">
            <Trash2 className="h-3.5 w-3.5" /> Drop picked
          </button>
        </div>
      </div>
      {blocked && <p className="text-[11px] text-slate-500">{blocked}</p>}
      {err && <p className="text-xs text-rose-300" role="alert" data-testid="improvement-cases-error">{err}</p>}
      <ul className="space-y-2">
        {rows.map((c) => (
          <li key={c.id} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3" data-testid="improvement-case" data-case-id={c.id}>
            <div className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-1" aria-label={`Pick ${c.name}`} checked={picked.has(c.id)} disabled={!canManage} onChange={() => toggle(c.id)} data-testid="improvement-case-pick" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-words text-sm font-medium text-white">{c.name}</span>
                  {needsConfirmation(c) && (
                    <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-200" title="Only 'wrong' was known, so check the rule before accepting">Check before accepting</span>
                  )}
                </div>
                {c.lesson_title && <p className="mt-0.5 text-[11px] text-slate-500">From: {c.lesson_title}</p>}
                {editing === c.id ? (
                  <CaseEditor c={c} onCancel={() => setEditing(null)} onSaved={(n) => { setRows((r) => r.map((x) => (x.id === n.id ? n : x))); setEditing(null); }} />
                ) : (
                  <>
                    <p className="mt-1.5 break-words text-xs text-slate-300"><span className="text-slate-500">Input: </span>{c.input_message}</p>
                    {c.reference_output && <p className="mt-0.5 break-words text-xs text-emerald-200/90"><span className="text-slate-500">Right answer: </span>{c.reference_output}</p>}
                    <ul className="mt-1 space-y-0.5">
                      {c.assertions.map((a, i) => <li key={i} className="break-words text-[11px] text-slate-400">{checkSummary(a)}</li>)}
                    </ul>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button type="button" title={blocked} disabled={!canManage || !!busy} onClick={() => run([c.id], 'accept')} className={`${btn} border-emerald-500/40 text-emerald-200`} data-testid="improvement-case-accept">
                        {busy === `accept:${c.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Accept
                      </button>
                      <button type="button" title={blocked} disabled={!canManage || !!busy} onClick={() => setEditing(c.id)} className={`${btn} border-slate-600 text-slate-300`} data-testid="improvement-case-edit">
                        <Pencil className="h-3.5 w-3.5" /> Edit
                      </button>
                      <button type="button" title={blocked} disabled={!canManage || !!busy} onClick={() => setDropIds([c.id])} className={`${btn} border-slate-700 text-slate-400`} data-testid="improvement-case-drop">
                        <X className="h-3.5 w-3.5" /> Drop
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      <ConfirmModal
        open={!!dropIds}
        onClose={() => setDropIds(null)}
        onConfirm={() => dropIds && run(dropIds, 'drop')}
        title={dropIds && dropIds.length > 1 ? `Drop ${dropIds.length} suggested cases?` : 'Drop this suggested case?'}
        description="Dropped cases never run. The lessons they came from stay."
        confirmLabel="Drop"
        variant="warning"
        loading={busy === 'bulk:drop' || (!!dropIds && busy === `drop:${dropIds[0]}`)}
        confirmTestId="improvement-cases-drop-confirm"
        icon={Trash2}
      />
    </div>
  );
}
