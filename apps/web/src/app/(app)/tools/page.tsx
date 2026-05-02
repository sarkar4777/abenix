'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Search, Bot, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface Tool {
  id: string;
  name?: string;
  description?: string;
  category?: string;
  input_schema?: Record<string, unknown>;
}

const CATEGORY_ORDER = [
  'core',
  'data',
  'enterprise',
  'pipeline',
  'integration',
  'finance',
  'kyc',
  'meeting',
  'ml',
  'multimodal',
  'code',
];

const CATEGORY_BLURB: Record<string, string> = {
  core: 'Calculator, web search, code execution, time and unit conversion — the building blocks every agent needs.',
  data: 'Parse and transform CSV / JSON / text / spreadsheets / documents. Includes sentiment, regex, schema validation, PII redaction.',
  enterprise: 'Atlas ontology graph, knowledge search, agent memory, sandboxed jobs, scenario planning, human approval gates.',
  pipeline: 'Compose multi-step agents — call other agents, route to models, merge outputs, run a one-shot LLM call.',
  integration: 'Talk to other systems — HTTP, email, GitHub, Kafka, Redis streams, cloud storage, generic API connectors.',
  finance: 'NPV / IRR / DCF / LCOE / portfolio risk, market data, ECB rates, credit risk scoring.',
  kyc: 'Sanctions screening, PEP checks, adverse media, UBO discovery, KYC scoring, regulatory enforcement lookups.',
  meeting: 'LiveKit-backed meeting bot — join / listen / speak / chat, persona-grounded RAG, scope gating.',
  ml: 'Run inference against deployed ML models registered with the platform.',
  multimodal: 'Image analysis, speech-to-text, text-to-speech.',
  code: 'Reference uploaded code repositories as a callable code asset inside agents.',
};

export default function ToolsCataloguePage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<Tool[] | { tools: Tool[] }>('/api/tools');
        const data: Tool[] = Array.isArray(r?.data)
          ? r.data
          : Array.isArray((r?.data as any)?.tools)
            ? (r.data as any).tools
            : [];
        if (!cancelled) {
          setTools(data);
          setLoading(false);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message || String(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Group + filter
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (t: Tool) =>
      !q ||
      (t.id || '').toLowerCase().includes(q) ||
      (t.name || '').toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.category || '').toLowerCase().includes(q);

    const out: Record<string, Tool[]> = {};
    for (const t of tools) {
      if (!matches(t)) continue;
      const cat = t.category || 'misc';
      (out[cat] = out[cat] || []).push(t);
    }
    for (const cat of Object.keys(out)) {
      out[cat].sort((a, b) =>
        (a.name || a.id || '').localeCompare(b.name || b.id || ''),
      );
    }
    return out;
  }, [tools, query]);

  const orderedCategories = useMemo(() => {
    const known = CATEGORY_ORDER.filter(c => grouped[c]);
    const rest = Object.keys(grouped).filter(c => !known.includes(c)).sort();
    return [...known, ...rest];
  }, [grouped]);

  const toggle = (c: string) =>
    setOpenCats(prev => ({ ...prev, [c]: prev[c] === undefined ? false : !prev[c] }));

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold text-white mb-2">Tools catalogue</h1>
        <p className="text-slate-400 max-w-3xl">
          Browse the {tools.length || 'available'} built-in tools your agents
          can call. Click into any tool for its argument schema and example
          usage. To wire a tool into an agent, head to{' '}
          <Link href="/agents/new" className="text-cyan-400 hover:underline">
            /agents/new
          </Link>{' '}
          or the visual{' '}
          <Link href="/builder" className="text-cyan-400 hover:underline">
            /builder
          </Link>
          .
        </p>
      </header>

      <div className="mb-6 relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          placeholder="Search tools by name, description, or category…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search tools"
          className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
        />
      </div>

      {loading && (
        <div className="text-slate-500 py-12 text-center">Loading tools…</div>
      )}

      {error && (
        <div className="flex items-start gap-3 p-4 mb-6 bg-red-500/10 border border-red-500/20 rounded-lg text-red-200">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Failed to load tools catalogue</p>
            <p className="text-sm text-red-300/80 mt-1">{error}</p>
          </div>
        </div>
      )}

      {!loading && !error && (
        <div className="space-y-4">
          {orderedCategories.length === 0 && (
            <div className="text-slate-500 py-12 text-center">
              No tools match &ldquo;{query}&rdquo;.
            </div>
          )}
          {orderedCategories.map(cat => {
            const items = grouped[cat] || [];
            const isOpen = openCats[cat] !== false; // default-open
            return (
              <section
                key={cat}
                className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden"
              >
                <button
                  onClick={() => toggle(cat)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center gap-3 px-5 py-4 hover:bg-slate-800/40"
                >
                  {isOpen ? (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-slate-400" />
                  )}
                  <h2 className="text-lg font-semibold text-white capitalize flex-1 text-left">
                    {cat.replace('_', ' ')}
                  </h2>
                  <span className="text-xs text-slate-500">{items.length}</span>
                </button>
                {isOpen && (
                  <div>
                    {CATEGORY_BLURB[cat] && (
                      <p className="px-5 pb-2 text-sm text-slate-400 border-b border-slate-800/50">
                        {CATEGORY_BLURB[cat]}
                      </p>
                    )}
                    <ul className="divide-y divide-slate-800/50">
                      {items.map(t => (
                        <li
                          key={t.id}
                          className="px-5 py-4 hover:bg-slate-800/30 transition-colors"
                        >
                          <div className="flex items-start gap-3">
                            <Bot className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-baseline gap-3 flex-wrap">
                                <span className="font-mono text-sm text-cyan-300">
                                  {t.id}
                                </span>
                                {t.name && t.name !== t.id && (
                                  <span className="text-sm text-slate-300">
                                    {t.name}
                                  </span>
                                )}
                              </div>
                              {t.description && (
                                <p className="text-sm text-slate-400 mt-1 leading-relaxed">
                                  {t.description}
                                </p>
                              )}
                              {!t.input_schema && (
                                <p className="text-[11px] text-amber-300/80 mt-2">
                                  ⚠ No schema published — the agent will have
                                  to guess argument names. Tracked in
                                  BUGS_TOOLS_DEEP &lsquo;B-META-1&rsquo;.
                                </p>
                              )}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
