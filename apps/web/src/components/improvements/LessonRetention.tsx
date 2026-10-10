'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader2, Save, Timer } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface Retention {
  retention_days: number;
  default_days: number;
  min_days: number;
  max_days: number;
  updated_at: string | null;
  updated_by_name: string | null;
  can_edit: boolean;
}

// how long lessons, feedback and closed groups are kept before the hourly clean-up deletes them
export default function LessonRetention() {
  const [data, setData] = useState<Retention | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    apiFetch<Retention>('/api/improvements/retention', { silent: true }).then((r) => {
      if (r.data) {
        setData(r.data);
        setDraft(String(r.data.retention_days));
      }
    });
  }, []);

  if (!data) return null;
  const n = Number(draft);
  const invalid = draft.trim() === '' || !Number.isInteger(n) || n < data.min_days || n > data.max_days;
  const dirty = !invalid && n !== data.retention_days;

  async function save() {
    setSaving(true);
    setMsg(null);
    const r = await apiFetch<Retention>('/api/improvements/retention', {
      method: 'PUT',
      body: JSON.stringify({ retention_days: n }),
      throwOnError: false,
    });
    setSaving(false);
    if (r.data) {
      setData(r.data);
      setDraft(String(r.data.retention_days));
      setMsg({ ok: true, text: 'Saved. The hourly clean-up uses it from its next run.' });
    } else {
      setMsg({ ok: false, text: r.error || 'Could not save.' });
    }
  }

  return (
    <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" aria-labelledby="lesson-retention-title" data-testid="lesson-retention">
      <h2 id="lesson-retention-title" className="flex items-center gap-2 text-sm font-semibold text-white">
        <Timer className="h-4 w-4 text-cyan-400" aria-hidden /> How long lessons are kept
      </h2>
      <p className="mt-1 text-xs text-slate-400">
        Lessons and feedback can quote what people typed. After this many days they are deleted, with groups that are fixed or dismissed.
        Groups behind a fix that is still in progress are kept. Between {data.min_days} and {data.max_days} days, {data.default_days} by default.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-300">
          Days
          <input
            type="number"
            min={data.min_days}
            max={data.max_days}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setMsg(null);
            }}
            disabled={!data.can_edit || saving}
            aria-invalid={invalid}
            className="mt-1 block w-28 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-white disabled:opacity-60"
            data-testid="lesson-retention-days"
          />
        </label>
        {data.can_edit ? (
          <button
            type="button"
            onClick={save}
            disabled={!dirty || saving}
            title={invalid ? `Use a whole number from ${data.min_days} to ${data.max_days}` : !dirty ? 'Change the value to save' : undefined}
            className="inline-flex items-center gap-1.5 rounded-md bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-40"
            data-testid="lesson-retention-save"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
          </button>
        ) : (
          <p className="text-xs text-slate-500">Only admins can change this.</p>
        )}
        {data.can_edit && (
          <Link href="/admin/jobs?job=lesson_retention" className="text-xs text-cyan-300 hover:underline" data-testid="lesson-retention-run">
            Run the clean-up now
          </Link>
        )}
      </div>
      {invalid && <p className="mt-1 text-xs text-rose-300" data-testid="lesson-retention-error">Use a whole number from {data.min_days} to {data.max_days}.</p>}
      {msg && (
        <p role="status" className={`mt-2 text-xs ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="lesson-retention-msg">
          {msg.text}
        </p>
      )}
      {data.updated_at && (
        <p className="mt-1 text-[11px] text-slate-500">
          Last changed by {data.updated_by_name || 'an admin'} on {new Date(data.updated_at).toLocaleString()}.
        </p>
      )}
    </section>
  );
}
