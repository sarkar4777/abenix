'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Layers, Loader2, Plus, Save } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';

interface SetRow { id: string; key: string; name: string; description: string; version: number; count: number; values?: any[] | null; updated_at: string | null }

function toLines(values: any[]) {
  return values.map(String).join('\n');
}
function fromLines(text: string) {
  return Array.from(new Set(text.split(/[\n,\t]/).map((s) => s.trim()).filter(Boolean)));
}

function Editor({ row, onSaved }: { row: SetRow; onSaved: () => void }) {
  const { data } = useApi<SetRow>(`/api/decision-reference-sets/${row.key}`);
  const [text, setText] = useState('');
  const [name, setName] = useState(row.name);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data?.values) setText(toLines(data.values)); }, [data]);
  const vals = fromLines(text);
  async function save() {
    setBusy(true);
    const r = await apiFetch<any>(`/api/decision-reference-sets/${row.key}`, { method: 'PUT', body: JSON.stringify({ name, description: row.description, values: vals }), throwOnError: false });
    setBusy(false);
    if (r.error) setMsg(r.error);
    else { setMsg(r.data.version !== row.version ? `Saved as version ${r.data.version}. ${r.data.note}` : 'No change to the values.'); onSaved(); }
  }
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-[1fr_260px]">
      <div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono" aria-label={`Values of ${row.key}`} data-testid={`refset-values-${row.key}`} />
        <p className="text-[11px] text-slate-500">One value per line. Pasting a column from a spreadsheet works. Duplicates and blank lines are dropped.</p>
      </div>
      <div className="space-y-2">
        <label className="block text-xs text-slate-400" htmlFor={`rs-name-${row.key}`}>Name</label>
        <input id={`rs-name-${row.key}`} value={name} onChange={(e) => setName(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white" />
        <p className="text-sm text-slate-300">{vals.length} value{vals.length === 1 ? '' : 's'}</p>
        <button type="button" onClick={save} disabled={busy} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-cyan-500 text-white disabled:opacity-40" data-testid={`refset-save-${row.key}`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save
        </button>
        {msg && <p className="text-xs text-cyan-200" role="status">{msg}</p>}
      </div>
    </div>
  );
}

export default function ReferenceSetsPage() {
  const { perms } = useMyPermissions();
  const canAuthor = holds(perms?.capabilities, 'decisions.author');
  const { data, mutate, isLoading } = useApi<SetRow[]>('/api/decision-reference-sets');
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [text, setText] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const autoKey = (key || name).toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');

  async function create() {
    const r = await apiFetch<SetRow>('/api/decision-reference-sets', { method: 'POST', body: JSON.stringify({ key: autoKey, name, values: fromLines(text) }), throwOnError: false });
    if (r.error) return setErr(r.error);
    setCreating(false); setName(''); setKey(''); setText(''); setErr(null);
    mutate();
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <Link href="/decisions" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"><ArrowLeft className="w-3.5 h-3.5" /> Decisions</Link>
      <header className="mt-1 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2"><Layers className="w-6 h-6 text-cyan-400" /><h1 className="text-3xl font-semibold text-white">Reference sets</h1></div>
          <p className="text-slate-400 max-w-3xl">Named lists rules can check against, such as covered product codes. Each change is a new version. A decision keeps the values it was compiled with until a new draft picks up the change, so published answers never move by themselves.</p>
        </div>
        {canAuthor && <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white" data-testid="refset-new"><Plus className="w-4 h-4" /> New set</button>}
      </header>

      {creating && (
        <div className="mb-6 rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3" data-testid="refset-create">
          <div className="grid gap-3 md:grid-cols-2">
            <div><label className="block text-xs text-slate-400 mb-1" htmlFor="rs-new-name">Name</label><input id="rs-new-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Remote postcodes" className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white" data-testid="refset-name" /></div>
            <div><label className="block text-xs text-slate-400 mb-1" htmlFor="rs-new-key">Key used in rules</label><input id="rs-new-key" value={key || autoKey} onChange={(e) => setKey(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white font-mono" data-testid="refset-key" /></div>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder={'IV27\nZE2\nHS2'} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono" aria-label="Values" data-testid="refset-new-values" />
          <p className="text-[11px] text-slate-500">{fromLines(text).length} values. One per line, or paste a spreadsheet column.</p>
          {err && <p className="text-xs text-rose-300">{err}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setCreating(false)} className="px-3 py-1.5 text-sm text-slate-300">Cancel</button>
            <button type="button" onClick={create} disabled={!name.trim() || !autoKey} className="px-3 py-1.5 rounded-md text-sm bg-cyan-500 text-white disabled:opacity-40" data-testid="refset-create-go">Create</button>
          </div>
        </div>
      )}

      {isLoading && !data ? <div className="h-24 rounded-xl bg-slate-800/40 animate-pulse" /> : !(data || []).length ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">No reference sets yet. Create one, then pick it in a rule with “is in reference set”.</div>
      ) : (
        <ul className="space-y-2">
          {(data || []).map((r) => (
            <li key={r.id} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4" data-testid={`refset-${r.key}`}>
              <button type="button" onClick={() => setOpen(open === r.key ? null : r.key)} className="w-full flex flex-wrap items-center gap-3 text-left">
                <span className="text-white font-medium">{r.name}</span>
                <span className="text-xs font-mono text-slate-500">{r.key}</span>
                <span className="ml-auto text-xs text-slate-400">{r.count} values · version {r.version}</span>
              </button>
              {open === r.key && (canAuthor ? <Editor row={r} onSaved={mutate} /> : <p className="mt-2 text-xs text-slate-500">Editing needs the decisions.author capability.</p>)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
