'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Search, Bot, AlertTriangle, ChevronDown, ChevronRight, Plus, Wrench } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { apiFetch } from '@/lib/api-client';
import { getToolDoc } from '@/lib/tool-docs';
import ToolDetails from '@/components/tools-catalogue/ToolDetails';
import { fullDescription, tidyDescription } from '@/components/tools-catalogue/toolSchema';
import { CredentialBadge, CredentialHint, adminConfigHref, type ToolConfigInfo } from '@/components/CredentialBadge';
import { useIsAdmin } from '@/hooks/useToolConfig';

interface Tool {
  id: string;
  name?: string;
  description?: string;
  category?: string;
  input_schema?: Record<string, unknown>;
  /** credential state, generated from the tool's config_fields */
  config?: ToolConfigInfo;
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
  const [openTool, setOpenTool] = useState<string | null>(null);
  const isAdmin = useIsAdmin();

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
          // a #tool_id link opens that tool
          const hash = decodeURIComponent(window.location.hash.slice(1));
          if (hash && data.some((t) => t.id === hash)) {
            setOpenTool(hash);
            setTimeout(() => document.getElementById(hash)?.scrollIntoView({ block: 'start' }), 50);
          }
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message ? `${e.message}. Reload the page to try again.` : 'The tools list could not be loaded. Reload the page to try again.');
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
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      <PageHeader
        title="Tools catalogue"
        icon={Wrench}
        purpose={`Browse the ${tools.length || 'available'} built-in tools your agents can call and see what each one needs. For builders.`}
        primaryAction={{ label: 'Build an agent', href: '/builder', icon: Plus }}
        steps={[
          'Search by name or open a category to find a tool.',
          'Click a tool to see its arguments, an example call and a shortcut to add it to an agent.',
          'A "needs key" badge means the tool needs a credential before it works. Admins set it with Configure.',
        ]}
        docSlug="02-runtime/02-tools"
        storageKey="tools"
        className="mb-8"
      />

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
              {query.trim()
                ? <>No tools match &ldquo;{query}&rdquo;. Try a shorter word or a category such as &ldquo;finance&rdquo;.</>
                : 'No tools are available on this platform yet.'}
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
                  type="button"
                  className="w-full flex items-center gap-3 px-4 sm:px-5 py-4 hover:bg-slate-800/40"
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
                      <p className="px-4 sm:px-5 pb-2 text-sm text-slate-400 border-b border-slate-800/50">
                        {CATEGORY_BLURB[cat]}
                      </p>
                    )}
                    <ul className="divide-y divide-slate-800/50">
                      {items.map(t => {
                        const expanded = openTool === t.id;
                        const doc = getToolDoc(t.id);
                        return (
                          <li
                            key={t.id}
                            id={t.id}
                            className={`px-4 sm:px-5 py-4 transition-colors scroll-mt-4 ${expanded ? 'bg-slate-800/30' : 'hover:bg-slate-800/30'}`}
                            data-testid={`tool-row-${t.id}`}
                          >
                            <div className="flex items-start gap-3">
                              <Bot className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-baseline gap-x-3 gap-y-1 flex-wrap">
                                  <button
                                    type="button"
                                    onClick={() => setOpenTool(expanded ? null : t.id)}
                                    aria-expanded={expanded}
                                    aria-controls={`tool-details-${t.id}`}
                                    className="inline-flex items-baseline gap-1.5 text-left min-w-0"
                                    data-testid={`tool-toggle-${t.id}`}
                                  >
                                    {expanded
                                      ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 self-center shrink-0" />
                                      : <ChevronRight className="w-3.5 h-3.5 text-slate-400 self-center shrink-0" />}
                                    <span className="font-mono text-sm text-cyan-300 break-all hover:underline">{t.id}</span>
                                  </button>
                                  {t.name && t.name !== t.id && (
                                    <span className="text-sm text-slate-300">{t.name}</span>
                                  )}
                                  <CredentialBadge config={t.config} />
                                  {isAdmin && t.config && t.config.status !== 'none' && (
                                    <Link
                                      href={adminConfigHref(t.config)}
                                      className="text-[11px] text-cyan-400 hover:underline"
                                      data-testid={`tool-configure-${t.id}`}
                                    >
                                      Configure
                                    </Link>
                                  )}
                                </div>
                                {expanded ? (
                                  <div id={`tool-details-${t.id}`}>
                                    <ToolDetails
                                      id={t.id}
                                      description={fullDescription(t.description, doc?.description)}
                                      inputSchema={t.input_schema}
                                    />
                                  </div>
                                ) : (
                                  t.description && (
                                    <button
                                      type="button"
                                      onClick={() => setOpenTool(t.id)}
                                      className="block text-left text-sm text-slate-400 mt-1 leading-relaxed line-clamp-2 hover:text-slate-300"
                                    >
                                      {tidyDescription(t.description)}
                                    </button>
                                  )
                                )}
                                <CredentialHint config={t.config} isAdmin={isAdmin} />
                              </div>
                            </div>
                          </li>
                        );
                      })}
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
