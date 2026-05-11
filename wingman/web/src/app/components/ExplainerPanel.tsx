'use client';

import { useEffect, useState } from 'react';
import { BookOpen, ChevronDown, ChevronRight, Database, Cpu, Workflow, Wrench } from 'lucide-react';

export interface ExplainerSection {
  title: string;
  body: string | string[];
}

export interface ExplainerSpec {
  pageKey: string;
  what: string;
  how: string;
  tools?: string[];
  models?: { name: string; role: string }[];
  inputs?: string[];
  outputs?: string[];
  extras?: ExplainerSection[];
}

const STORAGE_KEY_PREFIX = 'wingman.explainer.open.';

export default function ExplainerPanel({ spec }: { spec: ExplainerSpec }) {
  const key = STORAGE_KEY_PREFIX + spec.pageKey;
  const [open, setOpen] = useState<boolean>(false);

  useEffect(() => {
    try {
      const v = localStorage.getItem(key);
      if (v === '1') setOpen(true);
    } catch {}
  }, [key]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try { localStorage.setItem(key, next ? '1' : '0'); } catch {}
  };

  return (
    <section className="mb-4">
      <button
        onClick={toggle}
        data-testid={`explainer-toggle-${spec.pageKey}`}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-900/40 hover:bg-slate-800/60 text-[11px] font-semibold text-slate-300 transition-colors"
        aria-expanded={open}
      >
        <BookOpen className="w-3.5 h-3.5 text-emerald-300" />
        {open ? 'Hide explainer' : 'Show explainer — how this page works'}
        {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
      </button>

      {open && (
        <div
          data-testid={`explainer-body-${spec.pageKey}`}
          className="mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5"
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Block title="What this page does" icon={<BookOpen className="w-3.5 h-3.5 text-emerald-300" />}>
              <p className="text-[12px] text-slate-200 leading-relaxed">{spec.what}</p>
            </Block>
            <Block title="How it works under the hood" icon={<Workflow className="w-3.5 h-3.5 text-cyan-300" />}>
              <p className="text-[12px] text-slate-200 leading-relaxed">{spec.how}</p>
            </Block>
          </div>

          {(spec.tools?.length || spec.models?.length) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-4">
              {spec.tools && spec.tools.length > 0 && (
                <Block title={`Tools (${spec.tools.length})`} icon={<Wrench className="w-3.5 h-3.5 text-amber-300" />}>
                  <div className="flex flex-wrap gap-1">
                    {spec.tools.map((t) => (
                      <span key={t} className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800/60 text-slate-300 border border-slate-700/50">
                        {t}
                      </span>
                    ))}
                  </div>
                </Block>
              )}
              {spec.models && spec.models.length > 0 && (
                <Block title={`Models (${spec.models.length})`} icon={<Cpu className="w-3.5 h-3.5 text-fuchsia-300" />}>
                  <ul className="text-[11px] text-slate-200 space-y-1.5">
                    {spec.models.map((m) => (
                      <li key={m.name} className="leading-relaxed">
                        <span className="font-mono text-fuchsia-200">{m.name}</span>
                        <span className="text-slate-400"> — {m.role}</span>
                      </li>
                    ))}
                  </ul>
                </Block>
              )}
            </div>
          )}

          {(spec.inputs?.length || spec.outputs?.length) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-4">
              {spec.inputs && spec.inputs.length > 0 && (
                <Block title="Inputs" icon={<Database className="w-3.5 h-3.5 text-sky-300" />}>
                  <ul className="text-[11px] text-slate-300 space-y-1 list-disc list-inside leading-relaxed">
                    {spec.inputs.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </Block>
              )}
              {spec.outputs && spec.outputs.length > 0 && (
                <Block title="What you get" icon={<Database className="w-3.5 h-3.5 text-emerald-300" />}>
                  <ul className="text-[11px] text-slate-300 space-y-1 list-disc list-inside leading-relaxed">
                    {spec.outputs.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </Block>
              )}
            </div>
          )}

          {spec.extras && spec.extras.length > 0 && (
            <div className="mt-4 space-y-3">
              {spec.extras.map((ex, i) => (
                <Block key={i} title={ex.title}>
                  {Array.isArray(ex.body) ? (
                    <ul className="text-[11px] text-slate-300 space-y-1 list-disc list-inside leading-relaxed">
                      {ex.body.map((b, j) => <li key={j}>{b}</li>)}
                    </ul>
                  ) : (
                    <p className="text-[12px] text-slate-200 leading-relaxed">{ex.body}</p>
                  )}
                </Block>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Block({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
      <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}
