'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Network, Loader2, Search, History, Pin, PinOff, Trash2, Copy } from 'lucide-react';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';

const GRAPH_PIPELINE = [
  { id: 'wingman-graph-query', label: 'Graph Query', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'plain English → typed graph traversal' },
  { id: 'knowledge_search', label: 'Atlas search', icon: 'tool' as const, hint: 'typed Atlas knowledge graph' },
  { id: 'neo4j_query', label: 'Neo4j', icon: 'db' as const, hint: 'graph database backing store' },
  { id: 'current_time', label: 'Time anchor', icon: 'tool' as const, hint: 'so "last 90 days" resolves' },
];

const SAMPLE_QUESTIONS = [
  'Show every offer from a counterparty involved in any vessel disruption in the last 90 days.',
  'Which corridors share a counterparty currently flagged as credit-watch?',
  'Trace the lineage of the Aug-15 USGC->NWE strategy from the originating broker email through the matched position to the approved hedge.',
  'List all VLGCs currently in the Atlantic that have ever called at Antwerp with cargo > 40kt.',
];

const HISTORY_KEY = 'wingman.graph.history.v1';

interface GraphNode { id?: string; type?: string; label?: string; name?: string; [k: string]: any }
interface GraphEdge { from?: string; to?: string; source?: string; target?: string; relation?: string; type?: string; [k: string]: any }

interface SavedQuery {
  id: string;
  question: string;
  asked_at: string;
  pinned?: boolean;
  answer?: any;
  execution_id?: string;
}

function loadHistory(): SavedQuery[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as SavedQuery[]) : [];
  } catch { return []; }
}

function saveHistory(items: SavedQuery[]) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 40))); } catch { /* ignore */ }
}

export default function GraphPage() {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [history, setHistory] = useState<SavedQuery[]>([]);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);

  useEffect(() => { setHistory(loadHistory()); }, []);

  const upsert = (q: SavedQuery) => {
    setHistory((prev) => {
      const others = prev.filter((p) => p.id !== q.id);
      const next = [q, ...others].slice(0, 40);
      saveHistory(next);
      return next;
    });
  };

  const togglePin = (id: string) => {
    setHistory((prev) => {
      const next = prev.map((p) => p.id === id ? { ...p, pinned: !p.pinned } : p);
      saveHistory(next);
      return next;
    });
  };

  const removeOne = (id: string) => {
    setHistory((prev) => {
      const next = prev.filter((p) => p.id !== id);
      saveHistory(next);
      return next;
    });
    if (activeId === id) setActiveId(null);
  };

  const clearAll = () => {
    if (!window.confirm('Clear unpinned queries?')) return;
    setHistory((prev) => {
      const next = prev.filter((p) => p.pinned);
      saveHistory(next);
      return next;
    });
    if (activeId && !history.find((h) => h.id === activeId && h.pinned)) setActiveId(null);
  };

  const ask = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setLoading(true);
    try {
      const r = await fetch('/api/wingman/graph/query', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      });
      const j = await r.json();
      const data = j.data || {};
      if (data.execution_id) setActiveExecution(data.execution_id);
      const id = `q-${Date.now()}`;
      const saved: SavedQuery = {
        id,
        question: text,
        asked_at: new Date().toISOString(),
        answer: data.answer || data,
        execution_id: data.execution_id,
      };
      upsert(saved);
      setActiveId(id);
    } catch { /* ignore */ }
    setLoading(false);
  };

  const active = useMemo(() => history.find((h) => h.id === activeId) || null, [history, activeId]);
  const sortedHistory = useMemo(() => {
    return [...history].sort((a, b) => {
      if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
      return b.asked_at.localeCompare(a.asked_at);
    });
  }, [history]);

  const totals = useMemo(() => {
    const pinned = history.filter((h) => h.pinned).length;
    const totalNodes = history.reduce((s, h) => s + (h.answer?.subgraph?.nodes?.length ?? 0), 0);
    const totalEdges = history.reduce((s, h) => s + (h.answer?.subgraph?.edges?.length ?? 0), 0);
    return { pinned, totalNodes, totalEdges };
  }, [history]);

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="ATLAS KNOWLEDGE GRAPH"
        title="Ask the graph anything."
        subtitle="Typed ontology of corridors → vessels → counterparties → broker offers → market events. Every answer comes back as nodes, edges, and citations — never paraphrased prose."
        rightSlot={
          <div className="flex items-center gap-3 text-[10px]">
            <span className="text-[10px] uppercase tracking-wider font-bold border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 rounded px-2 py-1">Atlas</span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">queries</span>
              <span className="text-xs font-mono font-semibold text-white">{history.length}</span>
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">pinned</span>
              <span className="text-xs font-mono font-semibold text-amber-300">{totals.pinned}</span>
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">N · E</span>
              <span className="text-xs font-mono font-semibold text-emerald-300">{totals.totalNodes} · {totals.totalEdges}</span>
            </span>
          </div>
        }
      />

      <PipelineStrip
        title="Pipeline · 1 agent · typed Atlas search · Neo4j backing"
        subtitle="Submit a question to light up the graph traversal — every node and edge returns with type"
        nodes={GRAPH_PIPELINE}
        executionId={activeExecution}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5">
        {/* History sidebar */}
        <aside className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 lg:sticky lg:top-4 self-start">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <History className="w-3.5 h-3.5" /> Queries ({history.length})
            </div>
            {history.some((h) => !h.pinned) && (
              <button onClick={clearAll} className="text-[10px] text-slate-500 hover:text-rose-300">clear unpinned</button>
            )}
          </div>
          {history.length === 0 ? (
            <div className="text-[11px] text-slate-600 italic">no queries yet — try a sample below or type your own</div>
          ) : (
            <div className="space-y-1.5 max-h-[60vh] overflow-y-auto -mr-2 pr-2">
              {sortedHistory.map((q) => {
                const isActive = activeId === q.id;
                const nodes = q.answer?.subgraph?.nodes?.length ?? 0;
                const edges = q.answer?.subgraph?.edges?.length ?? 0;
                return (
                  <div
                    key={q.id}
                    className={`group cursor-pointer rounded-lg border px-3 py-2 transition-colors ${
                      isActive
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'
                    }`}
                    onClick={() => setActiveId(q.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] text-slate-200 truncate" title={q.question}>
                          {q.question.slice(0, 70)}
                        </div>
                        <div className="text-[9px] text-slate-600 mt-0.5 flex items-center gap-2">
                          <span>{new Date(q.asked_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          {(nodes > 0 || edges > 0) && (
                            <span className="text-emerald-400">{nodes}n · {edges}e</span>
                          )}
                          {q.pinned && <span className="text-amber-300">📌</span>}
                        </div>
                      </div>
                      <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100">
                        <button
                          onClick={(e) => { e.stopPropagation(); togglePin(q.id); }}
                          className={`text-slate-500 ${q.pinned ? 'text-amber-300' : 'hover:text-amber-300'}`}
                          title={q.pinned ? 'unpin' : 'pin'}
                        >
                          {q.pinned ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); removeOne(q.id); }}
                          className="text-slate-500 hover:text-rose-300"
                          title="remove"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </aside>

        {/* Right column */}
        <div>
          <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-5 mb-5">
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && ask()}
                  placeholder="Ask the graph anything"
                  className="w-full bg-slate-950/50 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => ask()}
                disabled={!question.trim() || loading}
                className="px-4 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold inline-flex items-center gap-2"
              >
                {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Traversing...</> : <><Network className="w-3 h-3" /> Query graph</>}
              </button>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              {SAMPLE_QUESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => setQuestion(s)}
                  className="text-[10px] text-slate-400 hover:text-emerald-300 px-2 py-1 rounded bg-slate-800/40 hover:bg-emerald-500/10 max-w-[300px] truncate"
                  title={s}
                >
                  {s.slice(0, 70)}{s.length > 70 ? '...' : ''}
                </button>
              ))}
            </div>
          </section>

          {active ? (
            <ActiveAnswerView q={active} />
          ) : (
            <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/20 p-8 text-center text-sm text-slate-500">
              ask a question to begin — every answer saves to the history sidebar
            </div>
          )}
        </div>
      </div>

      <DagDrawer executionId={activeExecution} onClose={() => setActiveExecution(null)} />
    </div>
  );
}

function ActiveAnswerView({ q }: { q: SavedQuery }) {
  const ans = q.answer || {};
  const subgraph = ans.subgraph || {};
  const nodes: GraphNode[] = subgraph.nodes || [];
  const edges: GraphEdge[] = subgraph.edges || [];

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      {/* Question header */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Question</div>
          <div className="text-sm text-white">{q.question}</div>
          <div className="text-[10px] text-slate-600 mt-1">
            {new Date(q.asked_at).toLocaleString()} {q.execution_id && <>· exec #{q.execution_id.slice(0, 8)}</>}
          </div>
        </div>
        <button
          onClick={() => navigator.clipboard?.writeText(q.question)}
          className="text-slate-500 hover:text-slate-200 text-[11px] inline-flex items-center gap-1 shrink-0"
          title="copy"
        >
          <Copy className="w-3 h-3" /> copy
        </button>
      </div>

      {ans.narrative && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300 mb-2">Answer</div>
          <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{ans.narrative}</p>
        </div>
      )}

      {(nodes.length > 0 || edges.length > 0) && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-white">Returned subgraph</h3>
            <span className="text-[10px] text-slate-500">{nodes.length} nodes · {edges.length} edges</span>
          </div>
          <SubgraphViz nodes={nodes} edges={edges} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Nodes</div>
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {nodes.map((n, i) => (
                  <div key={i} className="text-xs px-3 py-1.5 rounded border border-slate-800 bg-slate-950/40">
                    <span className="font-mono text-[10px] uppercase tracking-wider mr-2"
                      style={{ color: nodeColor(n.type || n.label || '') }}>
                      {n.type || n.label}
                    </span>
                    <span className="text-slate-200">{n.name || n.id}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Edges</div>
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {edges.map((e, i) => (
                  <div key={i} className="text-xs px-3 py-1.5 rounded border border-slate-800 bg-slate-950/40">
                    <span className="text-slate-200">{e.from || e.source}</span>
                    <span className="text-cyan-400 mx-2">→</span>
                    <span className="text-cyan-300 font-mono text-[10px] uppercase tracking-wider mr-2">{e.relation || e.type}</span>
                    <span className="text-cyan-400 mr-2">→</span>
                    <span className="text-slate-200">{e.to || e.target}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {ans.citations && Array.isArray(ans.citations) && ans.citations.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Citations</div>
          <ul className="space-y-1">
            {ans.citations.map((c: any, i: number) => (
              <li key={i} className="text-[11px] text-slate-400">
                <span className="font-mono text-slate-600">[{i + 1}]</span> {typeof c === 'string' ? c : (c.source || JSON.stringify(c))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </motion.div>
  );
}

function nodeColor(type: string): string {
  const t = type.toLowerCase();
  if (t.includes('vessel')) return '#34d399';
  if (t.includes('port')) return '#60a5fa';
  if (t.includes('counterparty') || t.includes('party')) return '#f472b6';
  if (t.includes('cargo')) return '#fbbf24';
  if (t.includes('charter')) return '#a78bfa';
  if (t.includes('sanction')) return '#fb7185';
  if (t.includes('offer') || t.includes('email')) return '#22d3ee';
  if (t.includes('strategy') || t.includes('rule')) return '#facc15';
  if (t.includes('event')) return '#94a3b8';
  return '#cbd5e1';
}

function SubgraphViz({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const ref = useRef<SVGSVGElement>(null);
  const W = 880, H = 320;

  // Deterministic radial layout grouped by type — readable without a force layout dependency.
  const layout = useMemo(() => {
    if (nodes.length === 0) return [] as Array<{ id: string; x: number; y: number; n: GraphNode }>;
    const byType: Record<string, GraphNode[]> = {};
    for (const n of nodes) {
      const t = (n.type || n.label || 'Node') as string;
      (byType[t] ||= []).push(n);
    }
    const types = Object.keys(byType);
    const cx = W / 2, cy = H / 2;
    const ringR = Math.min(W, H * 1.4) * 0.34;
    const out: Array<{ id: string; x: number; y: number; n: GraphNode }> = [];
    types.forEach((t, ti) => {
      const arr = byType[t];
      const baseAngle = (2 * Math.PI * ti) / Math.max(1, types.length);
      const spread = Math.min(0.9, 0.25 + 0.12 * arr.length);
      arr.forEach((n, i) => {
        const f = arr.length > 1 ? i / (arr.length - 1) - 0.5 : 0;
        const angle = baseAngle + f * spread;
        const r = ringR + (i % 2 === 0 ? 0 : 24);
        const id = (n.id || n.name || `${t}-${i}`) as string;
        out.push({ id, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), n });
      });
    });
    return out;
  }, [nodes]);

  const idMap = useMemo(() => {
    const m = new Map<string, { x: number; y: number; n: GraphNode }>();
    layout.forEach((p) => m.set(p.id, p));
    layout.forEach((p) => {
      if (p.n.name && !m.has(p.n.name as string)) m.set(p.n.name as string, p);
    });
    return m;
  }, [layout]);

  if (layout.length === 0) {
    return <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 h-32 flex items-center justify-center text-[11px] text-slate-600 italic">no graph payload</div>;
  }

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-2">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full h-72">
        <defs>
          <marker id="arr" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L0,6 L6,3 z" fill="#475569" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const a = idMap.get(String(e.from ?? e.source ?? ''));
          const b = idMap.get(String(e.to ?? e.target ?? ''));
          if (!a || !b) return null;
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#475569" strokeWidth="1" markerEnd="url(#arr)" />
              <text x={mx} y={my - 3} fontSize="8" fill="#64748b" textAnchor="middle" className="font-mono">
                {e.relation || e.type || ''}
              </text>
            </g>
          );
        })}
        {layout.map((p) => {
          const c = nodeColor((p.n.type || p.n.label || '') as string);
          const label = (p.n.name || p.n.id || '') as string;
          return (
            <g key={p.id}>
              <circle cx={p.x} cy={p.y} r={9} fill={c} opacity="0.85" stroke="#0F172A" strokeWidth="1.5" />
              <text x={p.x} y={p.y + 22} fontSize="9" fill="#cbd5e1" textAnchor="middle">
                {label.length > 22 ? label.slice(0, 22) + '…' : label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="text-[9px] text-slate-600 px-2 pb-1">deterministic radial layout grouped by type · drag-pan & force-directed coming next</div>
    </div>
  );
}
