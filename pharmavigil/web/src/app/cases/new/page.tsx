'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, FilePlus2, Loader2 } from 'lucide-react';

type Sample = {
  id: string; label: string; suspect_drug: string;
  reporter_type: string; country: string; narrative: string;
};

const REPORTER_TYPES = [
  { value: 'consumer', label: 'Consumer or patient' },
  { value: 'physician', label: 'Physician' },
  { value: 'pharmacist', label: 'Pharmacist' },
  { value: 'nurse', label: 'Nurse' },
  { value: 'other_hcp', label: 'Other healthcare professional' },
  { value: 'lawyer', label: 'Lawyer' },
  { value: 'other', label: 'Other' },
];

type Form = {
  narrative: string;
  suspect_drug: string;
  reporter_type: string;
  country: string;
  received_date: string;
};

const today = () => new Date().toISOString().slice(0, 10);

function problems(f: Form): Partial<Record<keyof Form, string>> {
  const p: Partial<Record<keyof Form, string>> = {};
  if (f.narrative.trim().length < 10) p.narrative = 'Describe what happened in at least 10 characters.';
  if (!f.suspect_drug.trim()) p.suspect_drug = 'Name the suspect drug.';
  if (!/^[A-Z]{2}$/.test(f.country)) p.country = 'Use a two letter country code, such as GB.';
  if (f.received_date && f.received_date > today()) p.received_date = 'The report cannot arrive in the future.';
  return p;
}

const input =
  'w-full rounded-lg bg-slate-900 ring-1 ring-slate-700 focus:ring-teal-500/60 px-3 py-2 text-sm text-slate-100 outline-none';

export default function NewCase() {
  const router = useRouter();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [form, setForm] = useState<Form>({
    narrative: '', suspect_drug: '', reporter_type: 'consumer', country: 'GB', received_date: today(),
  });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/pv/samples', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => Array.isArray(b?.data) && setSamples(b.data))
      .catch(() => undefined);
  }, []);

  const issues = useMemo(() => problems(form), [form]);
  const shown = touched ? issues : {};
  const set = (k: keyof Form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: k === 'country' ? e.target.value.toUpperCase().slice(0, 2) : e.target.value }));

  const prefill = (id: string) => {
    const s = samples.find((x) => x.id === id);
    if (!s) return;
    setForm((f) => ({
      ...f, narrative: s.narrative, suspect_drug: s.suspect_drug,
      reporter_type: s.reporter_type, country: s.country,
    }));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(issues).length) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch('/api/pv/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, received_date: form.received_date || undefined }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) {
        const d = body?.detail;
        setErr(Array.isArray(d) ? d.map((x: any) => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join(', ')
          : typeof d === 'string' ? d : `The case was not filed (HTTP ${r.status}).`);
        return;
      }
      router.push(`/cases/${body.data.id}`);
    } catch {
      setErr('PharmaVigil could not be reached. Check your connection and try again.');
    } finally {
      setBusy(false);
    }
  };

  const err_ = (k: keyof Form) =>
    shown[k] ? <p className="text-xs text-rose-300 mt-1" role="alert">{shown[k]}</p> : null;

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">
      <div className="mx-auto max-w-3xl px-4 sm:px-6 py-8 space-y-6">
        <a href="/" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-teal-300">
          <ArrowLeft className="w-3.5 h-3.5" /> Case queue
        </a>
        <section>
          <h2 className="text-2xl font-bold text-white">New adverse event report</h2>
          <p className="text-sm text-slate-400 mt-1">
            Enter the report as the reporter gave it. The assessment starts as soon as you file it, and a
            reviewer signs it off before anything goes to a regulator.
          </p>
        </section>

        {samples.length > 0 && (
          <div>
            <label htmlFor="sample" className="text-xs text-slate-400">Start from a sample report (optional)</label>
            <select id="sample" data-testid="intake-sample" className={`${input} mt-1`} defaultValue=""
              onChange={(e) => prefill(e.target.value)}>
              <option value="">Write my own</option>
              {samples.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
        )}

        <form onSubmit={submit} noValidate className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 p-4 sm:p-5 space-y-4">
          <div>
            <label htmlFor="narrative" className="text-sm text-white">What happened</label>
            <p className="text-xs text-slate-500">The reporter&apos;s own words, including timing and outcome.</p>
            <textarea id="narrative" data-testid="intake-narrative" rows={7} value={form.narrative}
              onChange={set('narrative')} className={`${input} mt-1`} aria-invalid={!!shown.narrative} />
            {err_('narrative')}
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="drug" className="text-sm text-white">Suspect drug</label>
              <input id="drug" data-testid="intake-drug" value={form.suspect_drug} onChange={set('suspect_drug')}
                className={`${input} mt-1`} placeholder="e.g. atorvastatin" aria-invalid={!!shown.suspect_drug} />
              {err_('suspect_drug')}
            </div>
            <div>
              <label htmlFor="reporter" className="text-sm text-white">Reporter</label>
              <select id="reporter" data-testid="intake-reporter" value={form.reporter_type}
                onChange={set('reporter_type')} className={`${input} mt-1`}>
                {REPORTER_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="country" className="text-sm text-white">Country</label>
              <input id="country" data-testid="intake-country" value={form.country} onChange={set('country')}
                className={`${input} mt-1 uppercase`} maxLength={2} aria-invalid={!!shown.country} />
              {err_('country')}
            </div>
            <div>
              <label htmlFor="received" className="text-sm text-white">Received on</label>
              <input id="received" type="date" data-testid="intake-received" value={form.received_date}
                max={today()} onChange={set('received_date')} className={`${input} mt-1`}
                aria-invalid={!!shown.received_date} />
              {err_('received_date')}
            </div>
          </div>

          {err && (
            <div className="rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 px-3 py-2 text-sm text-rose-300" role="alert">
              {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <a href="/" className="text-sm text-slate-400 hover:text-white px-3 py-2">Cancel</a>
            <button type="submit" disabled={busy} data-testid="intake-submit"
              className="inline-flex items-center gap-2 rounded-lg bg-teal-500/15 text-teal-200 ring-1 ring-teal-500/40 hover:bg-teal-500/25 px-4 py-2 text-sm font-medium disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FilePlus2 className="w-4 h-4" />}
              File the report
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
