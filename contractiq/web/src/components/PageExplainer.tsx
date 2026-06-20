'use client';

import { useState } from 'react';
import {
  HelpCircle,
  ChevronDown,
  ChevronRight,
  BookOpen,
  Layers,
  GitBranch,
  Info,
} from 'lucide-react';
// Types only - the actual content store is lazy-loaded on first open
// to keep the ~89KB of static content out of every page's initial bundle.
import type {
  DataQuality,
  SectionExplanation,
  PageExplanation,
} from '@/lib/page_explanations';

export type PageExplainerProps = {
  routeKey: string;
};

type TabKey = 'purpose' | 'sections' | 'flow' | 'glossary';

const TABS: { key: TabKey; label: string; icon: any }[] = [
  { key: 'purpose', label: 'Page purpose', icon: Info },
  { key: 'sections', label: 'Sections on this page', icon: Layers },
  { key: 'flow', label: 'How the data flows', icon: GitBranch },
  { key: 'glossary', label: 'Glossary', icon: BookOpen },
];

const QUALITY_STYLE: Record<DataQuality, { label: string; cls: string }> = {
  'real-fetched': {
    label: 'real-fetched',
    cls: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40',
  },
  'agent-simulated': {
    label: 'agent-simulated',
    cls: 'bg-amber-500/15 text-amber-200 border-amber-500/40',
  },
  mixed: {
    label: 'mixed',
    cls: 'bg-sky-500/15 text-sky-200 border-sky-500/40',
  },
  degraded: {
    label: 'degraded — no data',
    cls: 'bg-slate-700/40 text-slate-300 border-slate-600',
  },
};

function QualityBadge({ quality }: { quality: DataQuality }) {
  const s = QUALITY_STYLE[quality];
  return (
    <span
      data-testid={`data-quality-${quality}`}
      className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wider ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

function LaymanExpander({ note }: { note: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-[11px] text-slate-400 hover:text-white inline-flex items-center gap-1"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        What this means in plain English
      </button>
      {open && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-slate-300 border-l-2 border-slate-700 pl-3">
          {note}
        </p>
      )}
    </div>
  );
}

function SectionRow({ section }: { section: SectionExplanation }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-md border border-slate-800 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-3 px-3 py-2.5 text-left hover:bg-slate-800/30"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {open ? (
              <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
            )}
            <span className="text-xs font-semibold text-white">{section.title}</span>
            <QualityBadge quality={section.data_quality} />
          </div>
          {!open && (
            <p className="text-[11px] text-slate-400 mt-1 ml-5 leading-relaxed">
              {section.what_it_shows}
            </p>
          )}
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-0 ml-5">
          <p className="text-xs text-slate-300 leading-relaxed mb-2">{section.what_it_shows}</p>
          {section.agent_slug && (
            <p className="text-[11px] text-slate-400">
              <span className="text-slate-500">Produced by agent </span>
              <code
                className="font-mono text-emerald-300"
                title="Agent slug — managed in the Abenix admin"
              >
                {section.agent_slug}
              </code>
            </p>
          )}
          {section.tools_used && section.tools_used.length > 0 && (
            <p className="text-[11px] text-slate-400 mt-1">
              <span className="text-slate-500">Tools called </span>
              {section.tools_used.map((t, i) => (
                <span key={t}>
                  <code className="font-mono text-amber-200 bg-slate-800/60 px-1 py-0.5 rounded text-[10px]">
                    {t}
                  </code>
                  {i < section.tools_used!.length - 1 ? <span className="text-slate-600"> · </span> : null}
                </span>
              ))}
            </p>
          )}
          {section.layman_note && <LaymanExpander note={section.layman_note} />}
        </div>
      )}
    </li>
  );
}

function PurposeTab({ purpose }: { purpose: string }) {
  const paragraphs = purpose.split(/\n\n+/).map(p => p.trim()).filter(Boolean);
  return (
    <div className="space-y-3">
      {paragraphs.map((p, i) => (
        <p key={i} className="text-sm text-slate-300 leading-relaxed">
          {p}
        </p>
      ))}
    </div>
  );
}

export function PageExplainer({ routeKey }: PageExplainerProps) {
  const [data, setData] = useState<PageExplanation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<TabKey>('purpose');

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) {
      const mod = await import('../lib/page_explanations');
      setData(mod.getPageExplanation(routeKey));
      setLoaded(true);
    }
  };

  // After first load, if the routeKey has no entry, hide the whole component
  // (silent no-op preserves the original behavior for unwired routes).
  if (loaded && !data) return null;

  return (
    <div
      data-testid="page-explainer"
      data-route-key={routeKey}
      className="mb-6"
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900/60 text-xs text-slate-300 hover:text-white hover:border-slate-600 transition-colors"
      >
        <HelpCircle className="w-3.5 h-3.5 text-sky-400" />
        <span>What is this page?</span>
        <span className="text-slate-600">·</span>
        <span>How does it work?</span>
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
        )}
      </button>

      {open && data && (
        <div
          data-testid="page-explainer-card"
          className="mt-3 rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden"
        >
          <div className="flex flex-wrap border-b border-slate-800 bg-slate-900/60">
            {TABS.map(t => {
              const Ic = t.icon;
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  data-testid={`explainer-tab-${t.key}`}
                  className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                    active
                      ? 'text-white border-emerald-400 bg-slate-800/40'
                      : 'text-slate-400 border-transparent hover:text-white hover:bg-slate-800/30'
                  }`}
                >
                  <Ic className="w-3.5 h-3.5" />
                  {t.label}
                </button>
              );
            })}
          </div>

          <div className="p-5">
            {tab === 'purpose' && <PurposeTab purpose={data.purpose} />}

            {tab === 'sections' && (
              <ul className="space-y-2" data-testid="explainer-sections">
                {data.sections.map((s, i) => (
                  <SectionRow key={i} section={s} />
                ))}
              </ul>
            )}

            {tab === 'flow' && (
              <ol className="space-y-3" data-testid="explainer-flow">
                {data.data_flow.map(step => (
                  <li key={step.step} className="flex gap-3">
                    <span className="shrink-0 w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-200 text-xs font-mono flex items-center justify-center">
                      {step.step}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-white">{step.label}</p>
                      <p className="text-[11px] text-slate-400 leading-relaxed mt-0.5">
                        {step.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}

            {tab === 'glossary' && (
              <dl className="space-y-3" data-testid="explainer-glossary">
                {data.glossary.length === 0 && (
                  <p className="text-xs text-slate-500">No glossary entries for this page yet.</p>
                )}
                {data.glossary.map(g => (
                  <div key={g.term}>
                    <dt className="text-xs font-semibold text-white">{g.term}</dt>
                    <dd className="text-[11px] text-slate-400 leading-relaxed mt-0.5">
                      {g.definition}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default PageExplainer;
