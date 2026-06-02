'use client';

import { useState } from 'react';
import { Database, ChevronDown, ChevronUp, ExternalLink, Lock } from 'lucide-react';

export interface DataSource {
  name: string;
  role: string;
  status: 'live' | 'planned' | 'configurable' | 'demo-seed';
  url?: string;
  notes?: string;
}

export interface DataSourceGroup {
  category: string;
  description?: string;
  sources: DataSource[];
}

const STATUS_STYLE: Record<DataSource['status'], { tone: string; label: string }> = {
  live:         { tone: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200', label: 'live' },
  configurable: { tone: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200',           label: 'configurable' },
  planned:      { tone: 'border-amber-500/30 bg-amber-500/10 text-amber-200',         label: 'planned' },
  'demo-seed':  { tone: 'border-slate-700 bg-slate-800/40 text-slate-400',            label: 'demo seed' },
};

export default function DataSourcePanel({
  title = 'Production data sources',
  description,
  groups,
  defaultOpen = false,
}: {
  title?: string;
  description?: string;
  groups: DataSourceGroup[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const total = groups.reduce((a, g) => a + g.sources.length, 0);
  const live = groups.reduce((a, g) => a + g.sources.filter(s => s.status === 'live').length, 0);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/30 mt-6">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Database className="w-4 h-4 text-cyan-400" />
          <div className="text-left">
            <p className="text-sm font-semibold text-white">{title}</p>
            <p className="text-[11px] text-slate-500">
              {total} source{total === 1 ? '' : 's'} ·
              <span className="text-emerald-400 ml-1">{live} live</span> ·
              <span className="text-cyan-400 ml-1">{groups.reduce((a, g) => a + g.sources.filter(s => s.status === 'configurable').length, 0)} configurable</span> ·
              <span className="text-amber-400 ml-1">{groups.reduce((a, g) => a + g.sources.filter(s => s.status === 'planned').length, 0)} planned</span>
            </p>
          </div>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
      </button>
      {open && (
        <div className="border-t border-slate-800 px-5 py-4 space-y-5">
          {description && <p className="text-[12px] text-slate-400 leading-relaxed">{description}</p>}
          {groups.map((g, gi) => (
            <div key={gi}>
              <div className="flex items-baseline gap-2 mb-2">
                <h4 className="text-[10px] uppercase tracking-[0.16em] text-slate-500 font-bold">{g.category}</h4>
                {g.description && <p className="text-[11px] text-slate-500">{g.description}</p>}
              </div>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {g.sources.map((s, si) => {
                  const st = STATUS_STYLE[s.status];
                  const body = (
                    <div className={`rounded-md border p-2.5 ${st.tone} hover:opacity-90 transition-opacity`}>
                      <div className="flex items-baseline justify-between gap-2 mb-0.5">
                        <p className="text-xs font-semibold flex items-center gap-1.5">
                          {s.name}
                          {s.url && <ExternalLink className="w-3 h-3 opacity-60" />}
                          {!s.url && s.status !== 'demo-seed' && <Lock className="w-3 h-3 opacity-40" />}
                        </p>
                        <span className="text-[9px] uppercase tracking-wider opacity-70 shrink-0">{st.label}</span>
                      </div>
                      <p className="text-[11px] opacity-80 leading-snug">{s.role}</p>
                      {s.notes && <p className="text-[10px] opacity-60 mt-1 italic">{s.notes}</p>}
                    </div>
                  );
                  return s.url
                    ? <li key={si}><a href={s.url} target="_blank" rel="noopener noreferrer">{body}</a></li>
                    : <li key={si}>{body}</li>;
                })}
              </ul>
            </div>
          ))}
          <p className="text-[10px] text-slate-600 italic">
            All live + configurable feeds are accessed through Abenix agents that hold the credentials and rate-limit centrally —
            E&amp;C-Copilot never carries third-party API keys. Demo-seed values are static rows in Postgres for offline rendering.
          </p>
        </div>
      )}
    </section>
  );
}
