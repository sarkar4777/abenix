'use client';

import { LucideIcon } from 'lucide-react';

export interface ExplainerSection {
  icon: LucideIcon;
  title: string;
  body: React.ReactNode;
  tone?: 'cyan' | 'amber' | 'purple' | 'emerald';
}

export interface ExplainerProps {
  eyebrow: string;
  title: string;
  lede: React.ReactNode;
  sections: ExplainerSection[];
  callouts?: { label: string; value: string }[];
  footer?: React.ReactNode;
}

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
  eyebrow, title, lede, sections, callouts, footer,
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

      {footer && (
        <div className="rounded-2xl p-5 bg-slate-900/40 border border-slate-800">
          {footer}
        </div>
      )}
    </aside>
  );
}
