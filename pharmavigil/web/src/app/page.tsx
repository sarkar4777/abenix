'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, CheckCircle2, ClipboardList, Clock,
  FlaskConical, Loader2, ShieldAlert, TrendingUp,
} from 'lucide-react';

type Stats = {
  total_cases: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  serious: number;
  expedited: number;
  signals: number;
  awaiting_review: number;
};

type Case = {
  id: string;
  status: string;
  suspect_drug?: string;
  primary_pt?: string | null;
  priority?: string | null;
  serious?: boolean | null;
  expedited?: boolean | null;
  who_umc?: string | null;
  escalation_probability?: number | null;
  sla_hours?: number | null;
  due_date?: string | null;
  signal?: boolean | null;
  assessment_gaps?: string[] | null;
  created_at?: string;
  error_message?: string | null;
};

type Sample = {
  id: string; label: string; suspect_drug: string;
  reporter_type: string; country: string; narrative: string;
};

const PRIORITY_STYLE: Record<string, string> = {
  P1: 'bg-rose-500/15 text-rose-300 ring-rose-500/40',
  P2: 'bg-amber-500/15 text-amber-300 ring-amber-500/40',
  P3: 'bg-sky-500/15 text-sky-300 ring-sky-500/40',
  P4: 'bg-slate-500/15 text-slate-400 ring-slate-500/40',
};

const STATUS_STYLE: Record<string, string> = {
  received: 'text-slate-400',
  assessing: 'text-cyan-300',
  assessed: 'text-emerald-300',
  submitted: 'text-emerald-400',
  rejected: 'text-slate-400',
  merged: 'text-violet-300',
  failed: 'text-rose-400',
};

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) return null;
    const body = await r.json();
    return (body?.data ?? body) as T;
  } catch {
    return null;
  }
}

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([
      getJson<Stats>('/api/pv/cases/stats'),
      getJson<Case[]>('/api/pv/cases?limit=50'),
    ]);
    if (s) setStats(s);
    if (c) setCases(c);
  }, []);

  useEffect(() => {
    void load();
    void getJson<Sample[]>('/api/pv/samples').then((s) => s && setSamples(s));
    // Cases move through the pipeline over minutes, so the queue refreshes
    // rather than making the reviewer reload to see a status change.
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [load]);

  const fileSample = async (s: Sample) => {
    setBusy(s.id);
    setErr(null);
    try {
      const r = await fetch('/api/pv/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          narrative: s.narrative,
          suspect_drug: s.suspect_drug,
          reporter_type: s.reporter_type,
          country: s.country,
        }),
      });
      if (!r.ok) setErr(`Intake failed: HTTP ${r.status}`);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const kpis = [
    { label: 'Cases', value: stats?.total_cases ?? 0, icon: ClipboardList },
    { label: 'Serious', value: stats?.serious ?? 0, icon: AlertTriangle },
    { label: 'Expedited', value: stats?.expedited ?? 0, icon: Clock },
    { label: 'Signals', value: stats?.signals ?? 0, icon: TrendingUp },
    { label: 'Awaiting review', value: stats?.awaiting_review ?? 0, icon: ShieldAlert },
  ];

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">

      <div className="mx-auto max-w-7xl px-6 py-8 space-y-8">
        <section className="pt-2">
          <h2 className="text-2xl font-bold text-white">Case queue</h2>
          <p className="text-sm text-slate-400 mt-1">
            Ordered by predicted reviewer escalation, not arrival time. Nine
            agents assess every report; a human signs off before anything is
            submitted.
          </p>
        </section>

        {err && (
          <div className="rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 px-4 py-3 text-sm text-rose-300">
            {err}
          </div>
        )}

        <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {kpis.map((k) => (
            <div key={k.label} className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 p-4">
              <div className="flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-wider text-slate-500">{k.label}</span>
                <k.icon className="w-4 h-4 text-slate-600" />
              </div>
              <div className="text-3xl font-bold text-teal-300 mt-2">{k.value}</div>
            </div>
          ))}
        </section>

        {samples.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-white mb-3">File a sample report</h3>
            <div className="grid md:grid-cols-3 gap-3">
              {samples.map((s) => (
                <button
                  key={s.id}
                  data-testid={`sample-${s.id}`}
                  onClick={() => void fileSample(s)}
                  disabled={busy !== null}
                  className="text-left rounded-xl bg-slate-900/60 ring-1 ring-slate-800 hover:ring-teal-500/50 p-4 transition-colors disabled:opacity-50"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{s.label}</span>
                    {busy === s.id
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-300" />
                      : <ArrowRight className="w-3.5 h-3.5 text-slate-600" />}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">
                    {s.suspect_drug} · {s.reporter_type} · {s.country}
                  </div>
                  <p className="text-xs text-slate-400 mt-2 line-clamp-2">{s.narrative}</p>
                </button>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
              <Activity className="w-4 h-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-white">Cases</h3>
              <span className="text-xs text-slate-500">({cases.length})</span>
            </div>
            {cases.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-slate-500">
                No cases yet. File a sample report above to watch the pipeline run.
              </p>
            ) : (
              <div className="divide-y divide-slate-800/70">
                {cases.map((c) => (
                  <a
                    key={c.id}
                    href={`/cases/${c.id}`}
                    data-testid={`case-row-${c.id}`}
                    className="flex items-center gap-4 px-4 py-3 hover:bg-slate-800/40 transition-colors"
                  >
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded ring-1 ${
                        PRIORITY_STYLE[c.priority || 'P4'] || PRIORITY_STYLE.P4
                      }`}
                    >
                      {c.priority || '—'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-white truncate">{c.suspect_drug || 'unknown drug'}</span>
                        {c.primary_pt && (
                          <span className="text-xs text-slate-400 truncate">· {c.primary_pt}</span>
                        )}
                        {c.serious && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/30">
                            serious
                          </span>
                        )}
                        {c.expedited && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/30">
                            expedited
                          </span>
                        )}
                        {c.signal && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/30">
                            signal
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-3">
                        <span className={STATUS_STYLE[c.status] || 'text-slate-400'}>{c.status}</span>
                        {c.who_umc && <span>WHO-UMC {c.who_umc}</span>}
                        {typeof c.escalation_probability === 'number' && (
                          <span>escalation {(c.escalation_probability * 100).toFixed(0)}%</span>
                        )}
                        {c.due_date && <span>due {c.due_date}</span>}
                        {/* A run can finish and still be short of a submission.
                            Say so on the row, not only on the detail page. */}
                        {c.assessment_gaps && c.assessment_gaps.length > 0 && (
                          <span className="text-amber-400/80">
                            {c.assessment_gaps.length} gap{c.assessment_gaps.length > 1 ? 's' : ''}
                          </span>
                        )}
                        {c.error_message && (
                          <span className="text-rose-400/80 truncate">{c.error_message.slice(0, 70)}</span>
                        )}
                      </div>
                    </div>
                    {c.status === 'assessing' && <Loader2 className="w-4 h-4 animate-spin text-cyan-300" />}
                    {c.status === 'submitted' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                  </a>
                ))}
              </div>
            )}
          </div>
        </section>

        <footer className="text-center text-[11px] text-slate-600 pt-4 pb-10">
          PharmaVigil · every assessment runs on Abenix through the SDK ·
          MedDRA coding and disproportionality are code assets, review priority is a model
        </footer>
      </div>
    </main>
  );
}
