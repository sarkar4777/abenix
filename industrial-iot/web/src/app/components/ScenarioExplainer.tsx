'use client';

import { LucideIcon, Workflow, Database, Cpu } from 'lucide-react';

export interface ExplainerSection {
  icon: LucideIcon;
  title: string;
  body: React.ReactNode;
  tone?: 'cyan' | 'amber' | 'purple' | 'emerald';
}

export interface AgentTraceEntry {
  agent_slug: string;            // e.g. "iot-valueedge-scenario-configurator"
  when: string;                  // when in the flow
  inputs: string;                // human description of input data
  outputs: string;               // human description of expected output
  source?: 'agent' | 'inline' | 'tool';  // 'inline' = code_executor in pipeline, not LLM
}

export interface ExplainerProps {
  eyebrow: string;
  title: string;
  lede: React.ReactNode;
  sections: ExplainerSection[];
  callouts?: { label: string; value: string }[];
  /**
   * Each entry describes what gets called when the user fires the
   * pipeline — agent slug, the data it receives, what it returns, and
   * whether it's a real LLM agent or an inline pipeline step.
   */
  agentTrace?: AgentTraceEntry[];
  /** Tag any data the UI renders that came from a static fixture. */
  simulationNote?: React.ReactNode;
  footer?: React.ReactNode;
}

const SOURCE_TONE: Record<NonNullable<AgentTraceEntry['source']>, { label: string; cls: string }> = {
  agent:  { label: 'agent',  cls: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40' },
  inline: { label: 'inline', cls: 'bg-slate-700/40 text-slate-300 border-slate-600/40' },
  tool:   { label: 'tool',   cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
};

const toneClasses: Record<NonNullable<ExplainerSection['tone']>, string> = {
  cyan:    'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
  amber:   'bg-amber-500/10 text-amber-300 border-amber-500/30',
  purple:  'bg-purple-500/10 text-purple-300 border-purple-500/30',
  emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
};

/**
 * Sticky right-hand explainer that accompanies each IoT tab. Designed to
 * give a reader landing on the page enough grounding to understand both
 * the real-world problem AND the technical moving parts — without
 * drowning them in prose.
 */
export default function ScenarioExplainer({
  eyebrow, title, lede, sections, callouts, agentTrace, simulationNote, footer,
}: ExplainerProps) {
  return (
    <aside className="lg:sticky lg:top-6 space-y-4">
      <div className="rounded-2xl p-6 bg-gradient-to-br from-slate-900/80 to-slate-950/80 border border-slate-800">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-400 mb-2">
          {eyebrow}
        </p>
        <h2 className="text-xl font-bold text-white leading-tight">{title}</h2>
        <p className="mt-3 text-sm text-slate-300 leading-relaxed">{lede}</p>

        {callouts && callouts.length > 0 && (
          <div className="grid grid-cols-2 gap-3 mt-5">
            {callouts.map((c) => (
              <div
                key={c.label}
                className="rounded-lg px-3 py-2 bg-slate-900/70 border border-slate-800"
              >
                <p className="text-[10px] uppercase tracking-wider text-slate-500">
                  {c.label}
                </p>
                <p className="text-sm font-semibold text-white mt-0.5">{c.value}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-2xl bg-slate-900/50 border border-slate-800 divide-y divide-slate-800 overflow-hidden">
        {sections.map((s) => (
          <div key={s.title} className="p-5">
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`inline-flex w-7 h-7 rounded-lg items-center justify-center border ${
                  toneClasses[s.tone ?? 'cyan']
                }`}
              >
                <s.icon className="w-3.5 h-3.5" />
              </span>
              <h3 className="text-sm font-semibold text-white">{s.title}</h3>
            </div>
            <div className="text-xs text-slate-400 leading-relaxed space-y-2 pl-9">
              {s.body}
            </div>
          </div>
        ))}
      </div>

      {agentTrace && agentTrace.length > 0 && (
        <div className="rounded-2xl bg-slate-900/50 border border-slate-800 overflow-hidden">
          <div className="px-5 pt-4 pb-3 border-b border-slate-800/60 flex items-center gap-2">
            <Workflow className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">What runs under the hood</h3>
          </div>
          <div className="px-5 py-4 space-y-3">
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Every output on this page comes from one of the agents below. No client-side
              rule engine. The pipeline is wired live to the platform runtime.
            </p>
            {agentTrace.map((t, i) => {
              const tone = SOURCE_TONE[t.source ?? 'agent'];
              return (
                <div key={i} className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded border ${tone.cls}`}>
                      {tone.label}
                    </span>
                    <code className="text-[11px] text-cyan-300 font-mono break-all">{t.agent_slug}</code>
                  </div>
                  <div className="text-[11px] text-slate-400 leading-relaxed pl-1 space-y-1">
                    <div><span className="text-slate-500">when</span> · {t.when}</div>
                    <div><span className="text-slate-500">inputs</span> · {t.inputs}</div>
                    <div><span className="text-slate-500">outputs</span> · {t.outputs}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {simulationNote && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 flex items-start gap-3">
          <Database className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div className="text-[11px] text-amber-200/90 leading-relaxed">
            <p className="font-semibold text-amber-300 mb-1">What's simulated vs. live</p>
            {simulationNote}
          </div>
        </div>
      )}

      {footer && (
        <div className="rounded-2xl p-5 bg-slate-900/40 border border-slate-800">
          {footer}
        </div>
      )}
    </aside>
  );
}
