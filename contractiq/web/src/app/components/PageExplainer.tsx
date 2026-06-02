'use client';

import { useState, useEffect } from 'react';
import { Info, X, Sparkles, Database, Cpu, Activity, ChevronRight } from 'lucide-react';

export interface AbenixModel {
  slug: string;
  family: string;
  status: 'registered' | 'missing' | 'reused';
  notes?: string;
}

export interface AbenixAgent {
  slug: string;
  role: string;
  status: 'seeded' | 'missing';
}

export interface AbenixTool {
  name: string;
  role: string;
  status: 'live-free' | 'configurable-paid' | 'missing';
}

export interface ComponentDoc {
  name: string;
  what: string;
  data_source: string;
  is_live: boolean;
}

export interface PageDoc {
  title: string;
  one_liner: string;
  what_user_does: string;
  components: ComponentDoc[];
  abenix_models: AbenixModel[];
  abenix_agents: AbenixAgent[];
  abenix_tools: AbenixTool[];
  data_flow: string;
  demo_status: 'fully-live' | 'partial-live' | 'demo-seed-only' | 'awaiting-model';
  demo_caveat?: string;
}

export default function PageExplainer({ doc }: { doc: PageDoc }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const statusTone = (s: PageDoc['demo_status']) => {
    switch (s) {
      case 'fully-live':       return { bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', text: 'text-emerald-200', label: 'Live data' };
      case 'partial-live':     return { bg: 'bg-cyan-500/10',    border: 'border-cyan-500/40',    text: 'text-cyan-200',    label: 'Partly live' };
      case 'awaiting-model':   return { bg: 'bg-amber-500/10',   border: 'border-amber-500/40',   text: 'text-amber-200',   label: 'Awaiting Abenix model' };
      case 'demo-seed-only':   return { bg: 'bg-slate-700/40',   border: 'border-slate-600',      text: 'text-slate-300',   label: 'Layout-demo seed' };
    }
  };

  const tone = statusTone(doc.demo_status);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="page-explainer-trigger"
        data-page-explainer="true"
        className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border ${tone.border} ${tone.bg} ${tone.text} hover:opacity-90 transition-opacity text-[11px]`}
      >
        <Info className="w-3.5 h-3.5" />
        <span className="font-semibold">What is this page?</span>
        <span className="opacity-60">·</span>
        <span>{tone.label}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Page explainer"
          data-testid="page-explainer"
          className="fixed inset-0 z-[60] bg-slate-950/85 backdrop-blur-sm overflow-y-auto"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <div className="max-w-4xl mx-auto my-8 rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
            <div className="flex items-start justify-between p-6 border-b border-slate-800">
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500 font-bold mb-1">Page explainer</p>
                <h2 className="text-xl font-bold text-white">{doc.title}</h2>
                <p className="text-sm text-slate-400 mt-1">{doc.one_liner}</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="text-slate-500 hover:text-white p-1.5 rounded hover:bg-slate-800/60"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="px-6 py-4 border-b border-slate-800">
              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-md border ${tone.border} ${tone.bg} ${tone.text}`}>
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
                <span className="text-[11px] font-bold uppercase tracking-wider">{tone.label}</span>
              </div>
              {doc.demo_caveat && <p className="text-[12px] text-slate-400 mt-2 leading-relaxed">{doc.demo_caveat}</p>}
            </div>

            <Section title="What you do here">
              <p className="text-[13px] text-slate-300 leading-relaxed">{doc.what_user_does}</p>
            </Section>

            <Section title="Every component on this page">
              <div className="space-y-2.5">
                {doc.components.map((c, i) => (
                  <div key={i} className={`rounded-md border p-3 ${c.is_live ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-slate-700/60 bg-slate-800/30'}`}>
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-sm font-semibold text-white">{c.name}</p>
                      <span className={`text-[9px] uppercase tracking-wider ${c.is_live ? 'text-emerald-300' : 'text-amber-300'}`}>
                        {c.is_live ? 'live' : 'demo seed'}
                      </span>
                    </div>
                    <p className="text-[12px] text-slate-400 mt-1 leading-relaxed">{c.what}</p>
                    <p className="text-[10px] text-slate-500 mt-1.5"><span className="font-mono">Source:</span> {c.data_source}</p>
                  </div>
                ))}
              </div>
            </Section>

            {doc.abenix_models.length > 0 && (
              <Section title="AI / ML models on Abenix that power this page" icon={Cpu}>
                <div className="grid grid-cols-1 gap-2">
                  {doc.abenix_models.map((m, i) => {
                    const styles =
                      m.status === 'registered' ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200' :
                      m.status === 'reused'     ? 'border-cyan-500/30 bg-cyan-500/5 text-cyan-200' :
                                                  'border-amber-500/30 bg-amber-500/5 text-amber-200';
                    const label =
                      m.status === 'registered' ? 'registered in Abenix' :
                      m.status === 'reused'     ? 'reusing existing Abenix model' :
                                                  'NOT in Abenix yet';
                    return (
                      <div key={i} className={`rounded-md border p-2.5 ${styles}`}>
                        <div className="flex items-baseline justify-between">
                          <code className="text-[12px] font-mono font-semibold">{m.slug}</code>
                          <span className="text-[10px] opacity-70 uppercase tracking-wider">{label}</span>
                        </div>
                        <p className="text-[11px] opacity-80 mt-0.5">{m.family}</p>
                        {m.notes && <p className="text-[10px] opacity-60 mt-1 italic">{m.notes}</p>}
                      </div>
                    );
                  })}
                </div>
              </Section>
            )}

            {doc.abenix_agents.length > 0 && (
              <Section title="Abenix agents involved" icon={Sparkles}>
                <ul className="space-y-1.5">
                  {doc.abenix_agents.map((a, i) => (
                    <li key={i} className="flex items-baseline gap-2 text-[12px]">
                      <ChevronRight className="w-3 h-3 text-slate-600 mt-0.5 shrink-0" />
                      <code className="font-mono text-cyan-300">{a.slug}</code>
                      <span className="text-slate-400">— {a.role}</span>
                      <span className={`ml-auto text-[9px] uppercase tracking-wider ${a.status === 'seeded' ? 'text-emerald-300' : 'text-amber-300'}`}>{a.status}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {doc.abenix_tools.length > 0 && (
              <Section title="External tools called (via Abenix)" icon={Database}>
                <ul className="space-y-1.5">
                  {doc.abenix_tools.map((t, i) => {
                    const lbl = t.status === 'live-free' ? 'free public API' : t.status === 'configurable-paid' ? 'paid · needs API key' : 'not built yet';
                    return (
                      <li key={i} className="flex items-baseline gap-2 text-[12px]">
                        <ChevronRight className="w-3 h-3 text-slate-600 mt-0.5 shrink-0" />
                        <code className="font-mono text-amber-300">{t.name}</code>
                        <span className="text-slate-400">— {t.role}</span>
                        <span className="ml-auto text-[9px] uppercase tracking-wider text-slate-500">{lbl}</span>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            <Section title="How a click flows through to Abenix" icon={Activity}>
              <pre className="text-[11px] text-slate-300 bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto leading-relaxed whitespace-pre-wrap font-mono">{doc.data_flow}</pre>
            </Section>

            <div className="px-6 py-4 border-t border-slate-800 text-[11px] text-slate-500 italic">
              All execution + tool-call logs live in <span className="text-slate-300">Abenix</span> — this app stores nothing locally beyond seeded demo rows + provenance pointers. Click the live activity rail on the right to follow any agent run in real time.
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Section({ title, icon: Icon, children }: { title: string; icon?: any; children: React.ReactNode }) {
  return (
    <div className="px-6 py-4 border-b border-slate-800 last:border-b-0">
      <div className="flex items-center gap-2 mb-3">
        {Icon && <Icon className="w-3.5 h-3.5 text-cyan-400" />}
        <h3 className="text-[11px] uppercase tracking-[0.16em] text-slate-400 font-bold">{title}</h3>
      </div>
      {children}
    </div>
  );
}
