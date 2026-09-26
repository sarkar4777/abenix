'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Copy, FileText, GitBranch,
  Loader2, Tags, TrendingUp, XCircle,
} from 'lucide-react';

type Coded = {
  verbatim: string; llt?: string; pt?: string; hlt?: string; soc?: string;
  meddra_code?: string; confidence?: number; source?: string; note?: string;
};

type Case = Record<string, any> & {
  id: string;
  status: string;
  coded_terms?: Coded[] | null;
  uncoded_terms?: Array<{ verbatim: string; reason: string }> | null;
  assessment_gaps?: string[] | null;
  events?: Array<{ at: string; type: string; summary: string }>;
};

function Section({ title, icon: Icon, children, note }: {
  title: string; icon: any; children: React.ReactNode; note?: string;
}) {
  return (
    <section className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Icon className="w-4 h-4 text-slate-500" />
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {note && <span className="text-[11px] text-slate-500">{note}</span>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function Field({ k, v }: { k: string; v: any }) {
  const empty = v === null || v === undefined || v === '';
  return (
    <div className="flex items-start gap-3 py-1 text-xs">
      <span className="text-slate-500 font-mono w-44 shrink-0">{k}</span>
      <span className={empty ? 'text-slate-600 italic' : 'text-slate-200 break-words'}>
        {empty ? 'not reported' : typeof v === 'object' ? JSON.stringify(v) : String(v)}
      </span>
    </div>
  );
}

export default function CaseDetail() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [c, setC] = useState<Case | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const r = await fetch(`/api/pv/cases/${id}`, { cache: 'no-store' });
      if (!r.ok) return;
      const body = await r.json();
      setC((body?.data ?? body) as Case);
    } catch {
      /* transient */
    }
  }, [id]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [load]);

  const decide = async (decision: string) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch(`/api/pv/cases/${id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reviewer: 'medical.reviewer', notes: '' }),
      });
      setMsg(r.ok ? `Recorded: ${decision}` : `Failed: HTTP ${r.status}`);
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (!c) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-400 grid place-items-center">
        <Loader2 className="w-5 h-5 animate-spin" />
      </main>
    );
  }

  const assessing = c.status === 'assessing' || c.status === 'received';
  const coded: Coded[] = Array.isArray(c.coded_terms) ? c.coded_terms : [];
  const uncoded = Array.isArray(c.uncoded_terms) ? c.uncoded_terms : [];
  const gaps = Array.isArray(c.assessment_gaps) ? c.assessment_gaps : [];

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800/80 bg-slate-900/40">
        <div className="mx-auto max-w-5xl px-6 py-4 flex items-center gap-3">
          <a href="/" className="text-slate-500 hover:text-teal-300"><ArrowLeft className="w-4 h-4" /></a>
          <div className="flex-1">
            <h1 className="text-base font-bold text-white">
              {c.suspect_drug || 'unknown drug'}
              {c.primary_pt ? <span className="text-slate-400 font-normal"> · {c.primary_pt}</span> : null}
            </h1>
            <p className="text-[11px] text-slate-500 font-mono">{c.id}</p>
          </div>
          {c.priority && (
            <span className="text-xs px-2 py-1 rounded ring-1 ring-slate-700 text-slate-300">
              {c.priority}{c.sla_hours ? ` · ${c.sla_hours}h SLA` : ''}
            </span>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-6 space-y-5">
        {assessing && (
          <div className="rounded-lg bg-cyan-500/10 ring-1 ring-cyan-500/30 px-4 py-3 text-sm text-cyan-200 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Assessment running — nine nodes, typically two to four minutes.
          </div>
        )}
        {c.error_message && (
          <div className="rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 px-4 py-3 text-sm text-rose-300">
            {c.error_message}
          </div>
        )}
        {gaps.length > 0 && (
          // Completed is not the same as submittable, and a reviewer needs to
          // see the difference before they sign anything.
          <div className="rounded-lg bg-amber-500/10 ring-1 ring-amber-500/30 px-4 py-3 text-sm text-amber-200">
            <strong>Assessment completed with gaps.</strong>
            <ul className="list-disc pl-5 mt-1 text-xs space-y-0.5">
              {gaps.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </div>
        )}
        {msg && (
          <div className="rounded-lg bg-slate-800/60 ring-1 ring-slate-700 px-4 py-2 text-xs text-slate-300">{msg}</div>
        )}

        <Section title="Reported" icon={FileText}>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{c.narrative}</p>
          <div className="mt-3 pt-3 border-t border-slate-800">
            <Field k="reporter_type" v={c.reporter_type} />
            <Field k="country" v={c.country} />
            <Field k="received_date" v={c.received_date} />
          </div>
        </Section>

        <div className="grid md:grid-cols-2 gap-5">
          <Section title="Seriousness" icon={AlertTriangle} note="CIOMS">
            <Field k="serious" v={c.serious} />
            <Field k="criteria" v={c.seriousness_criteria} />
            <Field k="expedited" v={c.expedited} />
            <Field k="clock (days)" v={c.reporting_clock_days} />
            <Field k="due_date" v={c.due_date} />
            <Field k="listedness" v={c.listedness} />
          </Section>

          <Section title="Causality" icon={GitBranch} note="WHO-UMC + Naranjo">
            <Field k="who_umc" v={c.who_umc} />
            <Field k="naranjo_score" v={c.naranjo_score} />
            <Field k="naranjo_category" v={c.naranjo_category} />
          </Section>
        </div>

        <Section title="MedDRA coding" icon={Tags} note="code asset, adjudicated by the coder agent">
          {coded.length === 0 ? (
            <p className="text-xs text-slate-500 italic">No coded terms yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 text-left">
                    <th className="pb-2 pr-3 font-medium">Verbatim</th>
                    <th className="pb-2 pr-3 font-medium">PT</th>
                    <th className="pb-2 pr-3 font-medium">SOC</th>
                    <th className="pb-2 pr-3 font-medium">Code</th>
                    <th className="pb-2 pr-3 font-medium">Conf.</th>
                    <th className="pb-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {coded.map((t, i) => (
                    <tr key={i}>
                      <td className="py-1.5 pr-3 text-slate-300">{t.verbatim}</td>
                      <td className="py-1.5 pr-3 text-white">{t.pt || '—'}</td>
                      <td className="py-1.5 pr-3 text-slate-400">{t.soc || '—'}</td>
                      <td className="py-1.5 pr-3 font-mono text-slate-500">{t.meddra_code || '—'}</td>
                      <td className="py-1.5 pr-3 text-slate-400">
                        {typeof t.confidence === 'number' ? t.confidence.toFixed(2) : '—'}
                      </td>
                      <td className="py-1.5 text-slate-500">{t.source || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {uncoded.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-800">
              <p className="text-[11px] uppercase tracking-wider text-amber-400/80 mb-1">
                Uncoded — {uncoded.length}
              </p>
              {uncoded.map((u, i) => (
                <div key={i} className="text-xs text-slate-400">
                  <span className="text-slate-300">{u.verbatim}</span> — {u.reason}
                </div>
              ))}
            </div>
          )}
        </Section>

        <div className="grid md:grid-cols-2 gap-5">
          <Section title="Disproportionality" icon={TrendingUp} note="closed form, from the code asset">
            <Field k="primary_pt" v={c.primary_pt} />
            <Field k="signal" v={c.signal} />
            <Field k="PRR" v={c.prr} />
            <Field k="EB05" v={c.eb05} />
            <Field k="recommendation" v={c.signal_recommendation} />
            <p className="text-[11px] text-slate-600 mt-2 leading-relaxed">
              Disproportionality measures reporting, not risk. A high ratio means
              the pair is reported more than expected — not that the drug caused it.
            </p>
          </Section>

          <Section title="Review priority" icon={CheckCircle2} note="ML model">
            <Field k="priority" v={c.priority} />
            <Field
              k="escalation_prob"
              v={typeof c.escalation_probability === 'number'
                ? `${(c.escalation_probability * 100).toFixed(0)}%` : null}
            />
            <Field k="sla_hours" v={c.sla_hours} />
            <Field k="reviewer" v={c.recommended_reviewer} />
          </Section>
        </div>

        {c.is_duplicate && (
          <Section title="Possible duplicate" icon={Copy}>
            <Field k="matched_case" v={c.duplicate_of} />
          </Section>
        )}

        <Section title="Regulatory narrative" icon={FileText} note="CIOMS I">
          {c.narrative_text ? (
            <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{c.narrative_text}</p>
          ) : (
            <p className="text-xs text-slate-500 italic">No narrative produced.</p>
          )}
          {Array.isArray(c.reviewer_questions) && c.reviewer_questions.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-800">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Reviewer questions</p>
              <ul className="list-disc pl-5 text-xs text-slate-400 space-y-0.5">
                {c.reviewer_questions.map((q: string) => <li key={q}>{q}</li>)}
              </ul>
            </div>
          )}
          {Array.isArray(c.missing_information) && c.missing_information.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-800">
              <p className="text-[11px] uppercase tracking-wider text-amber-400/80 mb-1">Missing information</p>
              <ul className="list-disc pl-5 text-xs text-slate-400 space-y-0.5">
                {c.missing_information.map((m: string) => <li key={m}>{m}</li>)}
              </ul>
            </div>
          )}
        </Section>

        <Section title="Medical review" icon={CheckCircle2} note="nothing is submitted without this">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-400 mr-2">
              ready_to_submit: <strong className={c.ready_to_submit ? 'text-emerald-300' : 'text-amber-300'}>
                {String(c.ready_to_submit ?? 'unknown')}
              </strong>
            </span>
            <button
              data-testid="review-approve"
              disabled={busy || c.status === 'assessing'}
              onClick={() => void decide('approve')}
              className="text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/40 hover:bg-emerald-500/20 disabled:opacity-40"
            >
              Approve and submit
            </button>
            <button
              disabled={busy || c.status === 'assessing'}
              onClick={() => void decide('reject')}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-700/30 text-slate-300 ring-1 ring-slate-600 hover:bg-slate-700/50 disabled:opacity-40"
            >
              Reject
            </button>
            {c.is_duplicate && (
              <button
                disabled={busy}
                onClick={() => void decide('merge')}
                className="text-xs px-3 py-1.5 rounded-lg bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/40 hover:bg-violet-500/20 disabled:opacity-40"
              >
                Merge duplicate
              </button>
            )}
            {c.review_decision && (
              <span className="text-xs text-slate-400 ml-2">
                {c.reviewed_by} chose <strong className="text-white">{c.review_decision}</strong>
              </span>
            )}
          </div>
        </Section>

        {Array.isArray(c.events) && c.events.length > 0 && (
          <Section title="Timeline" icon={XCircle}>
            <div className="space-y-1">
              {c.events.map((e, i) => (
                <div key={i} className="flex gap-3 text-xs">
                  <span className="text-slate-600 font-mono">{e.at.slice(11, 19)}</span>
                  <span className="text-slate-400 w-24">{e.type}</span>
                  <span className="text-slate-300">{e.summary}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        <div className="text-[11px] text-slate-600 pb-10">
          {c.execution_id && <>Abenix execution <span className="font-mono">{c.execution_id}</span></>}
          {c.duration_ms ? <> · {(c.duration_ms / 1000).toFixed(1)}s</> : null}
        </div>
      </div>
    </main>
  );
}
