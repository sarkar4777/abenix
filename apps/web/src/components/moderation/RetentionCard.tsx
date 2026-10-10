'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Archive, Loader2, Lock, Save } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

type Key = 'held_content_days' | 'decision_record_days' | 'event_preview_days';

interface Retention {
  held_content_days: number;
  decision_record_days: number;
  event_preview_days: number;
  updated_at: string | null;
  updated_by_name: string | null;
  defaults: Record<Key, number>;
  limits: Record<Key, [number, number]>;
  can_edit: boolean;
}

const FIELDS: Array<{ key: Key; title: string; help: string }> = [
  {
    key: 'held_content_days',
    title: 'Full text of held content, after a decision',
    help: 'While a review is waiting we keep the full text so a reviewer can read it. Once it is decided we keep it this many days, then delete it. Use 0 to delete it the moment a decision is made.',
  },
  {
    key: 'decision_record_days',
    title: 'Decision records',
    help: 'Who decided what, when and why, with the matched parts masked. This is your audit trail. After this many days the record is deleted too.',
  },
  {
    key: 'event_preview_days',
    title: 'Event previews',
    help: 'Each check leaves an event with a short preview, matched parts masked. After this many days the preview text is removed and only the outcome and categories stay.',
  },
];

export function retentionErrors(v: Record<Key, string>, limits: Record<Key, [number, number]>): Partial<Record<Key, string>> {
  const out: Partial<Record<Key, string>> = {};
  for (const f of FIELDS) {
    const raw = v[f.key].trim();
    const [lo, hi] = limits[f.key];
    if (!raw) { out[f.key] = 'Enter a number of days.'; continue; }
    if (!/^\d+$/.test(raw)) { out[f.key] = 'Use a whole number of days.'; continue; }
    const n = Number(raw);
    if (n < lo || n > hi) out[f.key] = `Between ${lo} and ${hi} days.`;
  }
  if (!out.held_content_days && !out.decision_record_days && Number(v.held_content_days) > Number(v.decision_record_days)) {
    out.held_content_days = 'Cannot be longer than the decision record.';
  }
  return out;
}

export default function RetentionCard() {
  const [data, setData] = useState<Retention | null>(null);
  const [values, setValues] = useState<Record<Key, string>>({ held_content_days: '', decision_record_days: '', event_preview_days: '' });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const apply = (d: Retention) => {
    setData(d);
    setValues({
      held_content_days: String(d.held_content_days),
      decision_record_days: String(d.decision_record_days),
      event_preview_days: String(d.event_preview_days),
    });
  };

  useEffect(() => {
    (async () => {
      const r = await apiFetch<Retention>('/api/moderation/retention', { silent: true });
      setLoading(false);
      if (r.data) apply(r.data);
      else setLoadError(r.errorDetail?.message || 'The retention settings could not be loaded.');
    })();
  }, []);

  const errors = data ? retentionErrors(values, data.limits) : {};
  const dirty = !!data && FIELDS.some((f) => values[f.key] !== String(data[f.key]));
  const invalid = Object.keys(errors).length > 0;

  const save = async () => {
    if (!data || invalid) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    const body = Object.fromEntries(FIELDS.map((f) => [f.key, Number(values[f.key])]));
    const r = await apiFetch<Retention>('/api/moderation/retention', {
      method: 'PUT',
      body: JSON.stringify(body),
      throwOnError: false,
      silent: true,
    });
    setSaving(false);
    if (r.data) {
      apply(r.data);
      setSaved(true);
    } else {
      setSaveError(r.errorDetail?.message || 'The settings were not saved. Try again.');
    }
  };

  return (
    <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5" data-testid="retention-card" aria-labelledby="retention-title">
      <h2 id="retention-title" className="text-lg font-semibold flex items-center gap-2 text-white">
        <Archive className="w-4 h-4" /> What we keep and for how long
      </h2>
      <p className="text-sm text-slate-400 mt-1">
        Matched parts are always masked in previews, events and logs, for every category. The full text of held content is
        kept only while it waits for a reviewer and for the window below{' '}
        <span className="inline-flex items-center gap-1 text-slate-300"><Lock className="w-3 h-3" /> encrypted when your deployment has an encryption key</span>.
        Erasing a person under GDPR removes all of it for them straight away.
      </p>

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
      ) : loadError || !data ? (
        <p role="alert" className="mt-4 text-sm text-rose-300">{loadError}</p>
      ) : (
        <>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {FIELDS.map((f) => {
              const [lo, hi] = data.limits[f.key];
              const err = errors[f.key];
              const id = `retention-${f.key}`;
              return (
                <div key={f.key} className="min-w-0">
                  <label htmlFor={id} className="block text-sm font-medium text-slate-200">{f.title}</label>
                  <div className="mt-1.5 flex items-center gap-2">
                    <input
                      id={id}
                      data-testid={id}
                      inputMode="numeric"
                      value={values[f.key]}
                      disabled={!data.can_edit}
                      onChange={(e) => { setValues((v) => ({ ...v, [f.key]: e.target.value })); setSaved(false); }}
                      aria-invalid={!!err}
                      aria-describedby={`${id}-help`}
                      className={`w-24 bg-slate-900/50 border rounded px-3 py-2 text-sm text-white disabled:opacity-60 ${err ? 'border-rose-500/60' : 'border-slate-700/50'}`}
                    />
                    <span className="text-sm text-slate-400">days</span>
                  </div>
                  <p id={`${id}-help`} className="mt-1 text-xs text-slate-400 leading-relaxed">
                    {f.help} Default {data.defaults[f.key]}, allowed {lo} to {hi}.
                  </p>
                  {err && <p className="mt-1 text-xs text-rose-300" data-testid={`${id}-error`}>{err}</p>}
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <p className="text-xs text-slate-500 flex-1 min-w-0" data-testid="retention-audit">
              {data.updated_at
                ? `Last changed by ${data.updated_by_name || 'an admin'} on ${new Date(data.updated_at).toLocaleString()}.`
                : 'Using the defaults, nobody has changed these yet.'}
            </p>
            {!data.can_edit ? (
              <p className="text-xs text-slate-400">Only admins can change these.</p>
            ) : (
              <button
                type="button"
                data-testid="retention-save"
                onClick={save}
                disabled={saving || !dirty || invalid}
                title={!dirty ? 'Change a value to save' : invalid ? 'Fix the highlighted values first' : undefined}
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-2 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                Save retention
              </button>
            )}
          </div>
          {data.can_edit && !dirty && !saved && <p className="mt-1 text-[11px] text-slate-500 text-right">Change a value to enable Save.</p>}
          {saved && (
            <p role="status" className="mt-2 text-xs text-emerald-300" data-testid="retention-saved">
              Saved. The next hourly clean-up uses these values.{' '}
              <Link href="/admin/jobs?job=moderation_retention" className="text-cyan-300 hover:underline" data-testid="retention-run-now">
                Run it now
              </Link>
            </p>
          )}
          {saveError && <p role="alert" className="mt-2 text-xs text-rose-300">{saveError}</p>}
        </>
      )}
    </section>
  );
}
