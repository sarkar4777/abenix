'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, ChevronLeft, Calendar, Zap, Send, Loader2, ArrowRight, Building2,
  GitBranch, Play, Download, AlertTriangle, CheckCircle2, RefreshCw, Search,
} from 'lucide-react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }
function getUser() { if (typeof window === 'undefined') return null; try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; } }

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

const TABS = ['Overview', 'Clauses', 'Assets', 'Risk Analysis', 'Events', 'Extracted Data', 'Functional Analysis', 'Chat'];
const PIE_COLORS = ['#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#ef4444', '#ec4899', '#84cc16', '#14b8a6', '#f97316', '#6366f1', '#a855f7', '#eab308'];
const RISK_COLORS: Record<string, string> = { low: '#10b981', medium: '#f59e0b', high: '#ef4444', critical: '#dc2626' };

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (<div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
    <p className="text-xs text-slate-400 mb-1">{label}</p>
    {payload.map((p: any, i: number) => (<p key={i} className="text-xs font-medium" style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</p>))}
  </div>);
};


const NODE_COLORS: Record<string, { fill: string; border: string; text: string; label: string; prefix: string }> = {
  electricity_delivery: { fill: '#064e3b', border: '#10b981', text: '#d1fae5', label: 'Electricity Delivery', prefix: 'ED' },
  certificate_delivery: { fill: '#14532d', border: '#22c55e', text: '#bbf7d0', label: 'Certificate Delivery', prefix: 'CD' },
  gas_delivery: { fill: '#0c4a6e', border: '#0ea5e9', text: '#bae6fd', label: 'Gas Delivery', prefix: 'GD' },
  payment: { fill: '#713f12', border: '#f59e0b', text: '#fef3c7', label: 'Payment', prefix: 'PM' },
  volumetric: { fill: '#581c87', border: '#a855f7', text: '#e9d5ff', label: 'Volumetric / TS', prefix: 'VT' },
  price_market: { fill: '#9a3412', border: '#f97316', text: '#fed7aa', label: 'Price / Market', prefix: 'PR' },
  imbalance: { fill: '#78350f', border: '#b45309', text: '#fef3c7', label: 'Imbalance', prefix: 'IM' },
  termination: { fill: '#7f1d1d', border: '#ef4444', text: '#fecaca', label: 'Termination', prefix: 'TM' },
  credit_collateral: { fill: '#134e4a', border: '#14b8a6', text: '#ccfbf1', label: 'Credit & Collateral', prefix: 'CC' },
  force_majeure: { fill: '#1e1b4b', border: '#6366f1', text: '#c7d2fe', label: 'Force Majeur', prefix: 'FM' },
  constraint: { fill: '#3b0764', border: '#c084fc', text: '#e9d5ff', label: 'Constraint', prefix: 'CN' },
  optionality: { fill: '#18181b', border: '#eab308', text: '#fef9c3', label: 'Optionality', prefix: 'OP' },
  capacity: { fill: '#164e63', border: '#06b6d4', text: '#cffafe', label: 'Capacity', prefix: 'CP' },
  event: { fill: '#450a0a', border: '#dc2626', text: '#fecaca', label: 'Event', prefix: 'EV' },
  default: { fill: '#334155', border: '#64748b', text: '#e2e8f0', label: 'Other', prefix: '??' },
};

// Order matters: column-layout in the DAG renders in this order, which
// mirrors the data-flow left→right: sources (VT, PR, CN, FM) → delivery
// rules (ED, GD, CD) → computations (IM, PM) → risk (TM, CC) → modifiers
// (OP, CP).
const SECTION_CONFIG: Array<{ key: string; type: string }> = [
  { key: 'volumetric_timeseries_rules', type: 'volumetric' },
  { key: 'price_market_data_rules', type: 'price_market' },
  { key: 'constraint_rules', type: 'constraint' },
  { key: 'force_majeure_rules', type: 'force_majeure' },
  { key: 'electricity_delivery_rules', type: 'electricity_delivery' },
  { key: 'gas_delivery_rules', type: 'gas_delivery' },
  { key: 'certificate_delivery_rules', type: 'certificate_delivery' },
  { key: 'capacity_rules', type: 'capacity' },
  { key: 'optionality_rules', type: 'optionality' },
  { key: 'imbalance_rules', type: 'imbalance' },
  { key: 'payment_rules', type: 'payment' },
  { key: 'termination_rules', type: 'termination' },
  { key: 'credit_collateral_rules', type: 'credit_collateral' },
];

function FunctionalAnalysisTab({ contractId }: { contractId: string }) {
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

  const fetchAnalysis = async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : '';
    if (!token) return;
    setLoading(true);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}/functional-analysis`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const j = await r.json();
        setAnalysis(j.data?.analysis || null);
      }
    } catch { /* skip */ }
    setLoading(false);
  };

  const triggerAnalysis = async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : '';
    if (!token) return;
    setRunning(true); setError(null);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}/functional-analysis`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      });
      const j = await r.json();
      if (r.ok) {
        setAnalysis(j.data?.analysis || null);
      } else {
        setError(j.error?.message || j.error || 'Analysis failed');
      }
    } catch (e: any) {
      setError(e.message || 'Network error');
    }
    setRunning(false);
  };

  useEffect(() => { fetchAnalysis(); }, [contractId]);

  if (loading) {
    return <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 text-emerald-400 animate-spin" /></div>;
  }

  if (!analysis) {
    return (
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-8 text-center" data-testid="fa-empty">
        <GitBranch className="w-10 h-10 text-emerald-400/30 mx-auto mb-3" />
        <h3 className="text-sm font-semibold text-white mb-2">Functional Analysis</h3>
        <p className="text-xs text-slate-400 max-w-md mx-auto mb-4">
          Extracts the SEE-BV 11-section taxonomy (Electricity / Certificate / Gas delivery, Payment,
          Volumetric, Price, Imbalance, Termination, Credit &amp; Collateral, Force Majeur, Constraint) plus
          per-clause contract events, linked into two dependency DAGs.
        </p>
        {error && (
          <div className="flex items-center justify-center gap-2 text-xs text-rose-400 mb-3">
            <AlertTriangle className="w-3 h-3" /> {error}
          </div>
        )}
        <button
          onClick={triggerAnalysis}
          disabled={running}
          data-testid="fa-run-button"
          className="px-4 py-2 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-400 disabled:opacity-50 inline-flex items-center gap-2"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          {running ? 'Analyzing contract...' : 'Run Functional Analysis'}
        </button>
      </div>
    );
  }

  // ── Clause DAG ─────────────────────────────────────────────────────
  // Always auto-build from rule sections so we don't depend on the agent
  // consistently emitting clause_dag. The agent-provided DAG is merged in
  // as a supplement when present.
  const clauseNodes: Array<{ id: string; label: string; type: string; data?: any }> = [];
  const clauseEdges: Array<{ from: string; to: string; label?: string }> = [];
  const seenNodes = new Set<string>();
  const seenEdges = new Set<string>();

  for (const s of SECTION_CONFIG) {
    for (const rule of (analysis[s.key] || [])) {
      const rid = rule.rule_id || `${NODE_COLORS[s.type].prefix}-?`;
      if (!seenNodes.has(rid)) {
        clauseNodes.push({
          id: rid,
          label: rule.rule_name || rid,
          type: s.type,
          data: rule,
        });
        seenNodes.add(rid);
      }
      for (const linked of (rule.linked_rules || [])) {
        const key = `${linked}->${rid}`;
        if (!seenEdges.has(key)) {
          clauseEdges.push({ from: linked, to: rid, label: 'linked' });
          seenEdges.add(key);
        }
      }
    }
  }

  // Merge agent-provided clause_dag supplementally (nodes we don't already have)
  const providedClauseDag = analysis.clause_dag || analysis.dag || { nodes: [], edges: [] };
  for (const n of (providedClauseDag.nodes || [])) {
    if (!seenNodes.has(n.id)) { clauseNodes.push(n); seenNodes.add(n.id); }
  }
  for (const e of (providedClauseDag.edges || [])) {
    const key = `${e.from}->${e.to}`;
    if (!seenEdges.has(key)) { clauseEdges.push(e); seenEdges.add(key); }
  }

  // ── Event DAG ──────────────────────────────────────────────────────
  const eventNodes: Array<{ id: string; label: string; type: string; data?: any; parent_rule_id?: string }> = [];
  const eventEdges: Array<{ from: string; to: string; label?: string }> = [];
  const seenEventNodes = new Set<string>();
  const seenEventEdges = new Set<string>();
  for (const ev of (analysis.events || [])) {
    const eid = ev.event_id || '?';
    if (!seenEventNodes.has(eid)) {
      eventNodes.push({
        id: eid,
        label: ev.event_name || ev.trigger || eid,
        type: 'event',
        data: ev,
        parent_rule_id: ev.parent_rule_id,
      });
      seenEventNodes.add(eid);
    }
    if (ev.parent_rule_id) {
      const k = `${ev.parent_rule_id}->${eid}`;
      if (!seenEventEdges.has(k)) {
        eventEdges.push({ from: ev.parent_rule_id, to: eid, label: 'generates' });
        seenEventEdges.add(k);
      }
    }
    for (const linked of (ev.linked_events || [])) {
      const k = `${eid}->${linked}`;
      if (!seenEventEdges.has(k)) {
        eventEdges.push({ from: eid, to: linked, label: 'triggers' });
        seenEventEdges.add(k);
      }
    }
  }

  // Combined DAG (clauses + events) for the full cascade view
  const combinedNodes = [...clauseNodes, ...eventNodes];
  const combinedEdges = [...clauseEdges, ...eventEdges];
  const overview = analysis.overview || {};

  // Stats
  const ruleStats = SECTION_CONFIG.map(s => ({
    key: s.key,
    type: s.type,
    label: NODE_COLORS[s.type].label,
    count: (analysis[s.key] || []).length,
  }));
  const eventCount = (analysis.events || []).length;

  return (
    <div className="space-y-4" data-testid="fa-tab">
      {/* Overview strip */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Contract Overview
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          {overview.bundle_name && <div><span className="text-slate-500">Bundle</span><p className="text-white font-medium">{overview.bundle_name}</p></div>}
          {overview.contract_name && <div><span className="text-slate-500">Contract</span><p className="text-white font-medium">{overview.contract_name}</p></div>}
          {overview.counterparty && <div><span className="text-slate-500">Counterparty</span><p className="text-white font-medium">{overview.counterparty}</p></div>}
          {overview.contract_type && <div><span className="text-slate-500">Type</span><p className="text-white font-medium">{overview.contract_type}</p></div>}
          {overview.house_entity && <div><span className="text-slate-500">House Entity</span><p className="text-white font-medium">{overview.house_entity}</p></div>}
          {overview.party_type && <div><span className="text-slate-500">Party Type</span><p className="text-white font-medium">{overview.party_type}</p></div>}
          {overview.capacity_mw != null && overview.capacity_mw !== 0 && <div><span className="text-slate-500">Capacity</span><p className="text-white font-medium">{overview.capacity_mw} MW</p></div>}
          {overview.country_market && <div><span className="text-slate-500">Market</span><p className="text-white font-medium">{overview.country_market}</p></div>}
          {overview.technology_type && <div><span className="text-slate-500">Technology</span><p className="text-white font-medium">{overview.technology_type}</p></div>}
          {overview.start_date && <div><span className="text-slate-500">Start</span><p className="text-white font-medium">{overview.start_date}</p></div>}
          {overview.end_date && <div><span className="text-slate-500">End</span><p className="text-white font-medium">{overview.end_date}</p></div>}
          {overview.cod_date && <div><span className="text-slate-500">COD</span><p className="text-white font-medium">{overview.cod_date}</p></div>}
        </div>
      </div>

      {/* Rule stats — 12 mini-cards (11 types + Events) */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
        {ruleStats.map(s => {
          const c = NODE_COLORS[s.type];
          return (
            <div key={s.key} className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-2.5 text-center">
              <p className="text-lg font-bold" style={{ color: c.border }}>{s.count}</p>
              <p className="text-[9px] text-slate-500 truncate">{s.label}</p>
            </div>
          );
        })}
        <div className="bg-slate-800/30 border border-red-500/20 rounded-lg p-2.5 text-center">
          <p className="text-lg font-bold text-red-400">{eventCount}</p>
          <p className="text-[9px] text-slate-500">Events</p>
        </div>
      </div>

      {/* Primary view: clause DAG. Click any node to open a 2-panel
          modal with details (left) + event sub-DAG for that clause (right). */}
      <DagView
        title="Clause Dependency Graph"
        subtitle="Rules grouped by category · arrows = data flow (upstream → downstream) · click a node to drill into its events"
        nodes={clauseNodes}
        edges={clauseEdges}
        typeOrder={SECTION_CONFIG.map(s => s.type)}
        selectedNode={selectedNode}
        setSelectedNode={setSelectedNode}
        testId="fa-clause-dag"
        eventNodes={eventNodes}
        eventEdges={eventEdges}
      />
    </div>
  );
}

// ── Reusable DAG view ────────────────────────────────────────────────

function DagView({
  title, subtitle, nodes, edges, typeOrder,
  selectedNode, setSelectedNode, testId, showOnlyEventsAndParents,
  eventNodes, eventEdges,
}: {
  title: string;
  subtitle: string;
  nodes: Array<{ id: string; label: string; type: string; data?: any; parent_rule_id?: string }>;
  edges: Array<{ from: string; to: string; label?: string }>;
  typeOrder: string[];
  selectedNode: string | null;
  setSelectedNode: (id: string | null) => void;
  testId: string;
  showOnlyEventsAndParents?: boolean;
  // When provided, clicking a node opens a modal with an event sub-DAG
  // filtered to the events that hang off the selected clause.
  eventNodes?: Array<{ id: string; label: string; type: string; data?: any; parent_rule_id?: string }>;
  eventEdges?: Array<{ from: string; to: string; label?: string }>;
}) {
  const nodeWidth = 200;
  const nodeHeight = 52;
  const gapX = 36;
  const gapY = 14;

  let filteredNodes = nodes;
  let filteredEdges = edges;
  if (showOnlyEventsAndParents) {
    const eventParentIds = new Set(
      nodes.filter(n => n.type === 'event').map(n => n.parent_rule_id).filter(Boolean) as string[]
    );
    const keep = new Set<string>([
      ...nodes.filter(n => n.type === 'event').map(n => n.id),
      ...Array.from(eventParentIds),
    ]);
    filteredNodes = nodes.filter(n => keep.has(n.id));
    filteredEdges = edges.filter(e => keep.has(e.from) && keep.has(e.to));
    if (filteredNodes.length === 0) return null;
  }

  const grouped: Record<string, typeof filteredNodes> = {};
  for (const n of filteredNodes) {
    const t = typeOrder.includes(n.type) ? n.type : 'default';
    (grouped[t] = grouped[t] || []).push(n);
  }
  let col = 0;
  const positions: Record<string, { x: number; y: number }> = {};
  const columnOrder: string[] = [];
  for (const t of typeOrder) {
    const group = grouped[t] || [];
    if (group.length === 0) continue;
    columnOrder.push(t);
    group.forEach((n, row) => {
      positions[n.id] = { x: 24 + col * (nodeWidth + gapX), y: 60 + row * (nodeHeight + gapY) };
    });
    col++;
  }
  const maxRow = Math.max(1, ...Object.values(grouped).map(g => g.length));
  const svgWidth = Math.max(800, col * (nodeWidth + gapX) + 48);
  const svgHeight = maxRow * (nodeHeight + gapY) + 100;

  const selNode = filteredNodes.find(n => n.id === selectedNode);

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4" data-testid={testId}>
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-cyan-400" />
          {title}
          <span className="text-slate-600 font-normal normal-case text-xs">
            ({filteredNodes.length} nodes, {filteredEdges.length} edges)
          </span>
        </h3>
      </div>
      <p className="text-[11px] text-slate-500 mb-3">{subtitle}</p>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-3">
        {columnOrder.map(t => {
          const c = NODE_COLORS[t] || NODE_COLORS.default;
          return (
            <span key={t} className="flex items-center gap-1.5 text-[10px]">
              <span className="w-3 h-3 rounded-sm" style={{ background: c.fill, border: `1px solid ${c.border}` }} />
              <span className="text-slate-400">{c.label}</span>
            </span>
          );
        })}
      </div>

      <div className="overflow-x-auto">
        <svg width={svgWidth} height={svgHeight} data-testid={`${testId}-svg`}>
          {/* Column headers */}
          {columnOrder.map((t, ci) => {
            const c = NODE_COLORS[t] || NODE_COLORS.default;
            const x = 24 + ci * (nodeWidth + gapX);
            return (
              <text key={t} x={x + nodeWidth / 2} y={40} textAnchor="middle"
                fill={c.border} fontSize={10} fontWeight={700} letterSpacing="0.05em">
                {c.prefix}  ·  {c.label.toUpperCase()}
              </text>
            );
          })}
          {/* Edges */}
          {filteredEdges.map((e, i) => {
            const from = positions[e.from];
            const to = positions[e.to];
            if (!from || !to) return null;
            const fromNode = filteredNodes.find(n => n.id === e.from);
            const edgeColor = fromNode ? (NODE_COLORS[fromNode.type] || NODE_COLORS.default).border : '#64748b';
            const highlight = selectedNode === e.from || selectedNode === e.to;
            return (
              <line key={`e-${i}`}
                x1={from.x + nodeWidth} y1={from.y + nodeHeight / 2}
                x2={to.x} y2={to.y + nodeHeight / 2}
                stroke={highlight ? edgeColor : '#475569'}
                strokeWidth={highlight ? 2.5 : 1.4}
                markerEnd="url(#fa-arrow)"
                opacity={highlight ? 0.95 : 0.55}
              />
            );
          })}
          <defs>
            <marker id="fa-arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#64748b" />
            </marker>
          </defs>
          {/* Nodes */}
          {filteredNodes.map(n => {
            const pos = positions[n.id];
            if (!pos) return null;
            const c = NODE_COLORS[n.type] || NODE_COLORS.default;
            const isSel = selectedNode === n.id;
            return (
              <g key={n.id} className="cursor-pointer" onClick={() => setSelectedNode(isSel ? null : n.id)} data-testid={`fa-node-${n.id}`}>
                <rect x={pos.x} y={pos.y} width={nodeWidth} height={nodeHeight} rx={8}
                  fill={c.fill} stroke={isSel ? '#f59e0b' : c.border} strokeWidth={isSel ? 2.5 : 1.4}
                  opacity={isSel ? 1 : 0.92}
                />
                <text x={pos.x + 10} y={pos.y + 18} fill={c.text} fontSize={11} fontWeight={700}>
                  {n.id}
                </text>
                <text x={pos.x + 10} y={pos.y + 34} fill="#cbd5e1" fontSize={9.5}>
                  {(n.label || '').length > 28 ? (n.label || '').slice(0, 26) + '…' : n.label}
                </text>
                <text x={pos.x + 10} y={pos.y + 46} fill={c.border} fontSize={8} letterSpacing="0.05em">
                  {c.label.toUpperCase()}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Floating detail modal — always visible when a node is selected.
          When eventNodes/edges are provided, shows a 2-panel layout with
          an event sub-DAG on the right filtered to this clause's events. */}
      {selNode && (
        <NodeDetailModal
          node={selNode}
          color={NODE_COLORS[selNode.type] || NODE_COLORS.default}
          onClose={() => setSelectedNode(null)}
          testId={`${testId}-detail`}
          eventNodes={eventNodes}
          eventEdges={eventEdges}
          clauseEdges={edges}
        />
      )}
    </div>
  );
}

// ── Event sub-DAG — rendered inside NodeDetailModal's right panel ────
function EventSubDag({
  parentId, parentColor, events, edges,
}: {
  parentId: string;
  parentColor: { fill: string; border: string; text: string; label: string; prefix: string };
  events: Array<{ id: string; label: string; type: string; data?: any; parent_rule_id?: string }>;
  edges: Array<{ from: string; to: string; label?: string }>;
}) {
  const [selectedEv, setSelectedEv] = useState<string | null>(null);

  const nodeW = 180;
  const nodeH = 46;
  const gap = 16;
  // Simple topological layout: layer 0 = events with no incoming edge from
  // another event in the set; subsequent layers expand outward.
  const incoming: Record<string, number> = {};
  for (const e of events) incoming[e.id] = 0;
  for (const e of edges) incoming[e.to] = (incoming[e.to] || 0) + 1;
  const layers: string[][] = [];
  const seen = new Set<string>();
  const firstLayer = events.filter(e => (incoming[e.id] || 0) === 0).map(e => e.id);
  if (firstLayer.length) { layers.push(firstLayer); firstLayer.forEach(id => seen.add(id)); }
  while (seen.size < events.length && layers.length < 6) {
    const prev = layers[layers.length - 1];
    const next: string[] = [];
    for (const e of edges) {
      if (prev.includes(e.from) && !seen.has(e.to)) {
        next.push(e.to);
        seen.add(e.to);
      }
    }
    if (next.length === 0) {
      // Any remaining orphans go into a trailing layer
      for (const ev of events) if (!seen.has(ev.id)) { next.push(ev.id); seen.add(ev.id); }
    }
    if (next.length) layers.push(next);
  }
  if (layers.length === 0) layers.push(events.map(e => e.id));

  const positions: Record<string, { x: number; y: number }> = {};
  layers.forEach((layer, li) => {
    layer.forEach((id, ri) => {
      positions[id] = { x: 8 + li * (nodeW + gap), y: 8 + ri * (nodeH + 10) };
    });
  });
  const maxRow = Math.max(1, ...layers.map(l => l.length));
  const svgW = Math.max(320, layers.length * (nodeW + gap));
  const svgH = maxRow * (nodeH + 10) + 20;

  const selectedEv_ = events.find(e => e.id === selectedEv);

  return (
    <div className="space-y-3">
      <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-3 overflow-auto">
        <svg width={svgW} height={svgH} style={{ minWidth: svgW }}>
          {/* edges */}
          {edges.map((e, i) => {
            const p1 = positions[e.from]; const p2 = positions[e.to];
            if (!p1 || !p2) return null;
            const x1 = p1.x + nodeW, y1 = p1.y + nodeH / 2;
            const x2 = p2.x, y2 = p2.y + nodeH / 2;
            const midX = (x1 + x2) / 2;
            return (
              <g key={`${e.from}->${e.to}-${i}`}>
                <path d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                  stroke="#f43f5e" strokeWidth={1.2} fill="none" markerEnd="url(#arrow-ev)" opacity={0.7} />
              </g>
            );
          })}
          <defs>
            <marker id="arrow-ev" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#f43f5e" />
            </marker>
          </defs>
          {/* nodes */}
          {events.map(ev => {
            const p = positions[ev.id]; if (!p) return null;
            const isSel = selectedEv === ev.id;
            return (
              <g key={ev.id} className="cursor-pointer" onClick={() => setSelectedEv(isSel ? null : ev.id)}>
                <rect x={p.x} y={p.y} width={nodeW} height={nodeH} rx={6}
                  fill="#7f1d1d" stroke={isSel ? '#fecaca' : '#ef4444'} strokeWidth={isSel ? 2 : 1} opacity={isSel ? 1 : 0.95} />
                <text x={p.x + 8} y={p.y + 18} fontSize="10" fontWeight="600" fill="#fecaca">{ev.id}</text>
                <text x={p.x + 8} y={p.y + 34} fontSize="10" fill="#fecaca">
                  {(ev.label || '').slice(0, 26)}{(ev.label || '').length > 26 ? '…' : ''}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Selected event details — inline below the mini-DAG */}
      {selectedEv_ && (
        <div className="bg-slate-900/60 border border-red-500/30 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-red-400 font-semibold">Event · {selectedEv_.id}</p>
              <p className="text-sm text-white font-medium">{selectedEv_.label}</p>
            </div>
            <button onClick={() => setSelectedEv(null)}
              className="text-[10px] text-slate-500 hover:text-white">Close</button>
          </div>
          {selectedEv_.data && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1.5 mt-2">
              {Object.entries(selectedEv_.data)
                .filter(([k, v]) => !['event_id', 'event_name', 'parent_rule_id'].includes(k) && v != null && v !== '' && !(Array.isArray(v) && (v as any[]).length === 0))
                .map(([k, v]) => (
                  <div key={k}>
                    <p className="text-[9px] uppercase text-slate-500">{k.replace(/_/g, ' ')}</p>
                    <p className="text-[11px] text-slate-200">
                      {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                    </p>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NodeDetailModal({
  node, color, onClose, testId, eventNodes, eventEdges, clauseEdges,
}: {
  node: { id: string; label: string; type: string; data?: any };
  color: { fill: string; border: string; text: string; label: string; prefix: string };
  onClose: () => void;
  testId: string;
  eventNodes?: Array<{ id: string; label: string; type: string; data?: any; parent_rule_id?: string }>;
  eventEdges?: Array<{ from: string; to: string; label?: string }>;
  clauseEdges?: Array<{ from: string; to: string; label?: string }>;
}) {
  const entries = node.data
    ? Object.entries(node.data)
        .filter(([k, v]) => !['rule_id', 'event_id', 'rule_name', 'event_name', 'notes', 'clause_reference'].includes(k) && v !== null && v !== '' && !(Array.isArray(v) && (v as any[]).length === 0))
    : [];

  // Build the event sub-DAG for this clause: every event with parent_rule_id
  // = this clause, plus any events those events link to (1-hop expansion).
  const subEvents: typeof eventNodes = [];
  const subEventIds = new Set<string>();
  const subEdges: typeof eventEdges = [];
  if (eventNodes && eventEdges) {
    for (const ev of eventNodes) {
      if (ev.parent_rule_id === node.id) {
        subEvents.push(ev);
        subEventIds.add(ev.id);
      }
    }
    // 1-hop: include linked events that the clause's direct events trigger
    for (const e of eventEdges) {
      if (subEventIds.has(e.from) && !subEventIds.has(e.to)) {
        const tgt = eventNodes.find(n => n.id === e.to);
        if (tgt) { subEvents.push(tgt); subEventIds.add(tgt.id); }
      }
    }
    for (const e of eventEdges) {
      if (subEventIds.has(e.from) && subEventIds.has(e.to)) subEdges.push(e);
    }
    // Also include the clause's inbound/outbound clause edges for context
    // so the user sees where this clause sits in the data-flow graph.
  }

  // Upstream/downstream clause neighbours for context chips.
  const upstream: string[] = [];
  const downstream: string[] = [];
  if (clauseEdges) {
    for (const e of clauseEdges) {
      if (e.to === node.id) upstream.push(e.from);
      if (e.from === node.id) downstream.push(e.to);
    }
  }

  // close on Escape
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const hasSubDag = subEvents.length > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      data-testid={testId}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.15 }}
        className={`bg-[#0F172A] border rounded-2xl shadow-2xl w-full ${hasSubDag ? 'max-w-6xl' : 'max-w-3xl'} max-h-[90vh] overflow-hidden flex flex-col`}
        style={{ borderColor: color.border + '60', boxShadow: `0 0 40px ${color.border}20` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="relative px-6 py-4 border-b" style={{ borderColor: color.border + '30', background: `linear-gradient(to right, ${color.fill}, transparent)` }}>
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute top-3 right-3 w-8 h-8 rounded-lg bg-slate-800/60 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition"
          >
            ×
          </button>
          <div className="flex items-center gap-4">
            <div
              className="w-14 h-14 rounded-xl border-2 flex items-center justify-center text-lg font-bold shrink-0"
              style={{ background: color.fill, borderColor: color.border, color: color.text }}
            >
              {node.id}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] uppercase tracking-[0.15em] font-semibold" style={{ color: color.border }}>
                {color.label}
              </p>
              <h3 className="text-lg font-semibold text-white truncate">{node.label}</h3>
              {node.data?.clause_reference && (
                <p className="text-xs text-slate-500 mt-0.5">
                  Ref: <span className="text-slate-300 font-mono">{node.data.clause_reference}</span>
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Body — 2-panel layout when we have an event sub-DAG to show */}
        <div className={`overflow-y-auto ${hasSubDag ? 'grid grid-cols-1 lg:grid-cols-[1fr_1.1fr]' : ''}`}>
          {/* LEFT: clause/rule attributes + neighbours */}
          <div className="p-6 border-r border-slate-800/60">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-3">
              Attributes
            </p>
            {entries.length === 0 ? (
              <p className="text-sm text-slate-500 italic">No additional attributes extracted for this node.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
                {entries.map(([k, v]) => (
                  <div key={k} className="border-l-2 border-slate-800 pl-3">
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-0.5">
                      {k.replace(/_/g, ' ')}
                    </p>
                    <div className="text-sm text-slate-200 break-words">
                      {Array.isArray(v)
                        ? (v as any[]).map((x, i) => typeof x === 'object' ? JSON.stringify(x) : String(x)).join(' · ')
                        : typeof v === 'object'
                        ? <pre className="text-xs bg-slate-900 rounded p-2 overflow-x-auto mt-1">{JSON.stringify(v, null, 2)}</pre>
                        : String(v)}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {node.data?.notes && (
              <div className="mt-4 border-t border-slate-800 pt-4">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Notes</p>
                <p className="text-sm text-slate-300 italic leading-relaxed">{node.data.notes}</p>
              </div>
            )}

            {/* Upstream / Downstream neighbours — helps the user see where
                this clause sits in the data-flow graph without closing the
                modal. */}
            {(upstream.length > 0 || downstream.length > 0) && (
              <div className="mt-5 border-t border-slate-800 pt-4 space-y-2">
                {upstream.length > 0 && (
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                      Feeds in ({upstream.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {upstream.map(id => (
                        <span key={id} className="inline-flex items-center px-2 py-0.5 rounded bg-slate-800/60 border border-slate-700/60 text-[10px] font-mono text-slate-200">
                          {id}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {downstream.length > 0 && (
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                      Feeds out to ({downstream.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {downstream.map(id => (
                        <span key={id} className="inline-flex items-center px-2 py-0.5 rounded bg-slate-800/60 border border-slate-700/60 text-[10px] font-mono text-slate-200">
                          {id}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* RIGHT: event sub-DAG for this clause (if any events exist) */}
          {hasSubDag && (
            <div className="p-6">
              <div className="flex items-baseline justify-between mb-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
                  Events generated by this clause ({subEvents.length})
                </p>
                <p className="text-[10px] text-slate-600">Click an event for details</p>
              </div>
              <EventSubDag
                parentId={node.id}
                parentColor={color}
                events={subEvents as any[]}
                edges={subEdges as any[]}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-800/60 bg-slate-900/50 flex items-center justify-between">
          <p className="text-[10px] text-slate-600">Press Esc or click outside to close</p>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-xs font-medium text-white border transition"
            style={{ background: color.fill, borderColor: color.border }}
          >
            Close
          </button>
        </div>
      </motion.div>
    </div>
  );
}


export default function ContractDetailPage() {
  const router = useRouter();
  const params = useParams();
  const contractId = params.id as string;
  const [user, setUser] = useState<any>(null);
  const [contract, setContract] = useState<any>(null);
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractionStatus, setExtractionStatus] = useState<string | null>(null);
  const [deepExtracting, setDeepExtracting] = useState(false);
  const [deepExtractStatus, setDeepExtractStatus] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
    fetch(`${API_URL}/api/contractiq/contracts/${contractId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(body => { setContract(body.data); setLoading(false); }).catch(() => setLoading(false));
  }, [router, contractId]);

  const sendChat = async () => {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatMessages(prev => [...prev, { role: 'user', content: msg }]);
    setChatInput('');
    setChatLoading(true);
    try {
      const token = getToken();
      const res = await fetch(`${API_URL}/api/contractiq/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ query: `About "${contract?.title}": ${msg}` }),
      });
      const json = await res.json();
      setChatMessages(prev => [...prev, { role: 'assistant', content: json.data?.answer || 'No response.' }]);
    } catch { setChatMessages(prev => [...prev, { role: 'assistant', content: 'Error getting response.' }]); }
    setChatLoading(false);
  };

  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };

  const reExtract = async () => {
    const token = getToken();
    if (!token) return;
    setExtracting(true);
    setExtractionStatus('Starting extraction...');
    try {
      const res = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}/extract`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setExtractionStatus(`Error: ${body?.error?.message || res.status}`);
        setExtracting(false);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) { setExtracting(false); return; }
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) currentEvent = line.slice(7).trim();
          else if (line.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));
              if (currentEvent === 'status') setExtractionStatus(`${data.agent}: ${data.status}`);
              else if (currentEvent === 'done') setExtractionStatus('Extraction complete!');
              else if (currentEvent === 'error') setExtractionStatus(`Error: ${data.message}`);
            } catch { /* skip */ }
            currentEvent = '';
          }
        }
      }
      // Refresh contract data
      const refreshRes = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}`, { headers: { Authorization: `Bearer ${token}` } });
      const refreshJson = await refreshRes.json();
      if (refreshJson.data) setContract(refreshJson.data);
    } catch (e) {
      setExtractionStatus(`Failed: ${e instanceof Error ? e.message : 'Network error'}`);
    }
    setExtracting(false);
  };

  const runDeepExtract = async () => {
    const token = getToken();
    if (!token) return;
    setDeepExtracting(true);
    setDeepExtractStatus(null);
    try {
      const res = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}/deep-extract`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const reader = res.body?.getReader();
      if (!reader) { setDeepExtracting(false); return; }
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.message || evt.phase) setDeepExtractStatus(evt.message || evt.phase);
            if (evt.complete) setDeepExtractStatus('Deep extraction complete');
          } catch {}
        }
      }
      const refreshRes = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}`, { headers: { Authorization: `Bearer ${token}` } });
      const refreshJson = await refreshRes.json();
      if (refreshJson.data) setContract(refreshJson.data);
    } catch (e) {
      setDeepExtractStatus(`Failed: ${e instanceof Error ? e.message : 'Network error'}`);
    }
    setDeepExtracting(false);
  };

  if (!user || loading) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;
  if (!contract) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><p className="text-slate-400">Contract not found</p></div>;

  const c = contract;
  const radarData = (c.risk_analyses || []).map((r: any) => ({ category: r.category?.charAt(0).toUpperCase() + r.category?.slice(1), score: r.score, fullMark: 100 }));
  const clauseTypeData = Object.entries((c.clauses || []).reduce((acc: Record<string, number>, cl: any) => { acc[cl.type] = (acc[cl.type] || 0) + 1; return acc; }, {} as Record<string, number>)).map(([type, count]) => ({ name: type.replace(/_/g, ' '), value: count as number }));
  const clauseRiskData = ['low', 'medium', 'high', 'critical'].map(level => ({ level, count: (c.clauses || []).filter((cl: any) => cl.risk_level === level).length })).filter(d => d.count > 0);
  const eventTypeData = Object.entries((c.events || []).reduce((acc: Record<string, number>, ev: any) => { acc[ev.type] = (acc[ev.type] || 0) + 1; return acc; }, {} as Record<string, number>)).map(([type, count]) => ({ name: type.replace(/_/g, ' '), value: count as number }));

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      <div className="p-6">
        <div className="max-w-6xl mx-auto space-y-4">
          <button onClick={() => router.push('/contracts')} className="flex items-center gap-1 text-xs text-slate-400 hover:text-white transition-colors"><ChevronLeft className="w-3 h-3" /> Back to Contracts</button>

          {/* Header */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <h1 className="text-xl font-bold text-white">{c.title}</h1>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${c.contract_type === 'ppa' ? 'bg-emerald-500/10 text-emerald-400' : c.contract_type === 'gas' ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-500/10 text-slate-400'}`}>{c.contract_type?.toUpperCase()}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${c.status === 'analyzed' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-500/10 text-slate-400'}`}>{c.status}</span>
                  {(c.status === 'uploaded' || c.status === 'error') && (
                    <button
                      onClick={reExtract}
                      disabled={extracting}
                      className="flex items-center gap-1.5 text-xs px-3 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                    >
                      {extracting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                      {extracting ? 'Extracting...' : 'Re-Extract via AI'}
                    </button>
                  )}
                  {c.status === 'analyzed' && (
                    <button
                      onClick={runDeepExtract}
                      disabled={deepExtracting}
                      title="Run the 100+ field deep extractor — indexation, escalation, FX, cure periods, ROFR/ROFO, side-letter terms."
                      className="flex items-center gap-1.5 text-xs px-3 py-1 rounded-lg bg-violet-500/10 text-violet-300 border border-violet-500/30 hover:bg-violet-500/20 transition-colors disabled:opacity-50"
                    >
                      {deepExtracting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                      {deepExtracting ? (deepExtractStatus || 'Deep extracting...') : 'Deep Extract'}
                    </button>
                  )}
                  {c.status === 'analyzed' && (
                    <button
                      onClick={() => router.push(`/what-if/${contractId}`)}
                      className="flex items-center gap-1.5 text-xs px-3 py-1 rounded-lg bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20 transition-colors"
                    >
                      What-If
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-6 text-xs text-slate-400">
                  <span className="flex items-center gap-1"><Building2 className="w-3 h-3" /> {c.counterparty_a || '—'} <ArrowRight className="w-3 h-3" /> {c.counterparty_b || '—'}</span>
                  {c.total_capacity_mw ? <span className="flex items-center gap-1"><Zap className="w-3 h-3 text-emerald-400" /> {c.total_capacity_mw} MW</span> : null}
                  {c.effective_date && <span className="flex items-center gap-1"><Calendar className="w-3 h-3" /> {new Date(c.effective_date).toLocaleDateString()} → {c.expiry_date ? new Date(c.expiry_date).toLocaleDateString() : '?'}</span>}
                </div>
              </div>
              <div className="flex items-center gap-6">
                {c.extraction_summary?.completeness_score != null && (
                  <div className="text-center" title={
                    (c.extraction_summary.missing_fields && c.extraction_summary.missing_fields.length)
                      ? `Missing: ${c.extraction_summary.missing_fields.join(', ')}`
                      : 'All template sections populated'
                  }>
                    <div className={`text-3xl font-bold ${c.extraction_summary.completeness_score >= 80 ? 'text-emerald-400' : c.extraction_summary.completeness_score >= 60 ? 'text-amber-400' : 'text-red-400'}`}>
                      {Math.round(c.extraction_summary.completeness_score)}
                    </div>
                    <p className="text-[10px] text-slate-500 uppercase">Completeness</p>
                  </div>
                )}
                {c.risk_score != null && (
                  <div className="text-center">
                    <div className={`text-3xl font-bold ${c.risk_score > 60 ? 'text-red-400' : c.risk_score > 35 ? 'text-amber-400' : 'text-emerald-400'}`}>{c.risk_score.toFixed(0)}</div>
                    <p className="text-[10px] text-slate-500 uppercase">Risk Score</p>
                  </div>
                )}
              </div>
            </div>
            {c.extraction_summary?.missing_fields && c.extraction_summary.missing_fields.length > 0 && (
              <div className="mt-3 border border-amber-500/30 bg-amber-500/5 rounded-lg px-3 py-2">
                <p className="text-[10px] uppercase tracking-wider text-amber-400 mb-1">Incomplete extraction — {c.extraction_summary.missing_fields.length} template section{c.extraction_summary.missing_fields.length !== 1 ? 's' : ''} missing</p>
                <p className="text-xs text-amber-200/80">{c.extraction_summary.missing_fields.join(' · ')}</p>
              </div>
            )}
          </div>

          {/* Extraction Status */}
          {extractionStatus && (
            <div className={`rounded-lg px-4 py-2 text-sm flex items-center gap-2 ${extractionStatus.startsWith('Error') || extractionStatus.startsWith('Failed') ? 'bg-red-500/10 text-red-300 border border-red-500/30' : extractionStatus.includes('complete') ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30' : 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'}`}>
              {extracting && <Loader2 className="w-4 h-4 animate-spin" />}
              {extractionStatus}
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 border-b border-slate-700/50 pb-0">
            {TABS.map((t, i) => (<button key={t} onClick={() => setTab(i)} className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px ${tab === i ? 'text-emerald-400 border-emerald-400' : 'text-slate-400 border-transparent hover:text-white'}`}>{t}</button>))}
          </div>

          {/* Tab Content */}
          <motion.div key={tab} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            {/* Overview */}
            {tab === 0 && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-4">
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Extraction Summary</h3>
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: 'Fields', value: c.extracted_data?.length || 0, color: 'text-cyan-400' },
                        { label: 'Clauses', value: c.clauses?.length || 0, color: 'text-emerald-400' },
                        { label: 'Assets', value: c.assets?.length || 0, color: 'text-purple-400' },
                        { label: 'Events', value: c.events?.length || 0, color: 'text-amber-400' },
                        { label: 'Risk Cats', value: c.risk_analyses?.length || 0, color: 'text-red-400' },
                        { label: 'Pages', value: c.page_count || '?', color: 'text-slate-400' },
                      ].map(s => (<div key={s.label} className="text-center"><p className={`text-xl font-bold ${s.color}`}>{s.value}</p><p className="text-[10px] text-slate-500">{s.label}</p></div>))}
                    </div>
                  </div>
                  {c.extracted_data?.length > 0 && (
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Key Terms</h3>
                      <div className="space-y-2">
                        {c.extracted_data.slice(0, 10).map((d: any, i: number) => (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <span className="text-slate-400">{d.field_name?.replace(/_/g, ' ')}</span>
                            <span className="text-white font-medium max-w-[200px] truncate text-right">{d.field_value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                {radarData.length > 0 ? (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Risk Profile</h3>
                    <ResponsiveContainer width="100%" height={280}>
                      <RadarChart data={radarData}>
                        <PolarGrid stroke="#1e293b" />
                        <PolarAngleAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                        <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#475569', fontSize: 9 }} />
                        <Radar name="Risk" dataKey="score" stroke="#ef4444" fill="#ef4444" fillOpacity={0.2} strokeWidth={2} />
                        <Tooltip content={<CustomTooltip />} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div />}
              </div>
            )}

            {/* Clauses */}
            {tab === 1 && (
              <div className="space-y-4">
                {clauseTypeData.length > 0 && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Clause Types</h3>
                      <ResponsiveContainer width="100%" height={220}>
                        <PieChart><Pie data={clauseTypeData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={2} strokeWidth={0}>
                          {clauseTypeData.map((_: any, i: number) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                        </Pie><Tooltip content={<CustomTooltip />} /><Legend verticalAlign="bottom" height={36} formatter={(v: string) => <span className="text-[10px] text-slate-400">{v}</span>} /></PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Risk Levels</h3>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={clauseRiskData}><XAxis dataKey="level" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} /><Bar dataKey="count" name="Clauses" radius={[4, 4, 0, 0]}>
                          {clauseRiskData.map((d, i) => <Cell key={i} fill={RISK_COLORS[d.level] || '#64748b'} />)}
                        </Bar></BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  {(c.clauses || []).map((cl: any) => (
                    <div key={cl.id} className={`bg-slate-800/30 border rounded-xl p-4 ${cl.risk_level === 'critical' ? 'border-red-500/30' : cl.risk_level === 'high' ? 'border-orange-500/30' : cl.risk_level === 'medium' ? 'border-amber-500/30' : 'border-slate-700/50'}`}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {cl.number && <span className="text-xs text-slate-500 font-mono">{cl.number}</span>}
                          <span className="text-sm font-medium text-white">{cl.title}</span>
                        </div>
                        <div className="flex gap-2">
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-300">{cl.type?.replace(/_/g, ' ')}</span>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full ${cl.risk_level === 'critical' ? 'bg-red-500/10 text-red-400' : cl.risk_level === 'high' ? 'bg-orange-500/10 text-orange-400' : cl.risk_level === 'medium' ? 'bg-amber-500/10 text-amber-400' : 'bg-emerald-500/10 text-emerald-400'}`}>{cl.risk_level}</span>
                        </div>
                      </div>
                      <p className="text-xs text-slate-400 leading-relaxed">{cl.text}</p>
                      {cl.risk_notes && <p className="text-xs text-amber-400/80 mt-2 italic">{cl.risk_notes}</p>}
                    </div>
                  ))}
                  {(!c.clauses || c.clauses.length === 0) && <p className="text-sm text-slate-500 text-center py-8">No clauses extracted</p>}
                </div>
              </div>
            )}

            {/* Assets */}
            {tab === 2 && (
              <div className="space-y-4">
                {(c.assets || []).length > 1 && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Capacity by Asset</h3>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={(c.assets || []).filter((a: any) => a.capacity_mw).map((a: any) => ({ name: a.name?.slice(0, 20), mw: a.capacity_mw }))}>
                        <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} /><Bar dataKey="mw" name="MW" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  {(c.assets || []).map((a: any) => (
                    <div key={a.id} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h4 className="text-sm font-medium text-white mb-2">{a.name}</h4>
                      <div className="space-y-1 text-xs">
                        <p className="text-slate-400">Type: <span className="text-white">{a.type?.replace(/_/g, ' ')}</span></p>
                        {a.capacity_mw ? <p className="text-slate-400">Capacity: <span className="text-emerald-400 font-medium">{a.capacity_mw} MW</span></p> : null}
                        {a.technology && <p className="text-slate-400">Technology: <span className="text-white">{a.technology}</span></p>}
                        {a.location && <p className="text-slate-400">Location: <span className="text-white">{a.location}</span></p>}
                        {a.cod_date && <p className="text-slate-400">COD: <span className="text-white">{new Date(a.cod_date).toLocaleDateString()}</span></p>}
                      </div>
                    </div>
                  ))}
                  {(!c.assets || c.assets.length === 0) && <p className="text-sm text-slate-500 text-center py-8 col-span-2">No assets extracted</p>}
                </div>
              </div>
            )}

            {/* Risk Analysis */}
            {tab === 3 && (
              <div className="space-y-4">
                {radarData.length > 0 && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Risk Spider Chart</h3>
                      <ResponsiveContainer width="100%" height={280}>
                        <RadarChart data={radarData}><PolarGrid stroke="#1e293b" /><PolarAngleAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 10 }} /><PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#475569', fontSize: 9 }} /><Radar name="Risk" dataKey="score" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} strokeWidth={2} /><Tooltip content={<CustomTooltip />} /></RadarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Scores by Category</h3>
                      <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={radarData} layout="vertical"><XAxis type="number" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><YAxis type="category" dataKey="category" width={80} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} /><Bar dataKey="score" name="Score" radius={[0, 4, 4, 0]}>
                          {radarData.map((d: any, i: number) => <Cell key={i} fill={d.score > 60 ? '#ef4444' : d.score > 35 ? '#f59e0b' : '#10b981'} />)}
                        </Bar></BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  {(c.risk_analyses || []).map((r: any, i: number) => (
                    <div key={i} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium text-white capitalize">{r.category}</span>
                        <span className={`text-lg font-bold ${r.score > 60 ? 'text-red-400' : r.score > 35 ? 'text-amber-400' : 'text-emerald-400'}`}>{r.score?.toFixed(0)}/100</span>
                      </div>
                      <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden mb-2"><div className={`h-full rounded-full ${r.score > 60 ? 'bg-red-500' : r.score > 35 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${r.score}%` }} /></div>
                      <p className="text-xs text-slate-400">{r.description}</p>
                      {r.mitigation && <p className="text-xs text-cyan-400/80 mt-1">Mitigation: {r.mitigation}</p>}
                    </div>
                  ))}
                  {(!c.risk_analyses || c.risk_analyses.length === 0) && <p className="text-sm text-slate-500 text-center py-8">No risk analyses</p>}
                </div>
              </div>
            )}

            {/* Events */}
            {tab === 4 && (
              <div className="space-y-4">
                {eventTypeData.length > 0 && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Events by Type</h3>
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart><Pie data={eventTypeData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={35} outerRadius={60} paddingAngle={3} strokeWidth={0}>
                        {eventTypeData.map((_: any, i: number) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                      </Pie><Tooltip content={<CustomTooltip />} /><Legend verticalAlign="bottom" height={36} formatter={(v: string) => <span className="text-[10px] text-slate-400">{v}</span>} /></PieChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <div className="space-y-2">
                  {(c.events || []).map((ev: any, i: number) => {
                    const typeColors: Record<string, string> = { milestone: 'border-emerald-500', deadline: 'border-red-500', review: 'border-cyan-500', renewal: 'border-purple-500', termination_trigger: 'border-amber-500' };
                    return (
                      <div key={i} className={`border-l-2 pl-3 py-2 ${typeColors[ev.type] || 'border-slate-600'}`}>
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-white font-medium">{ev.description}</span>
                          <span className="text-[10px] text-slate-500 ml-2">{ev.date ? new Date(ev.date).toLocaleDateString() : '—'}</span>
                        </div>
                        <span className={`text-[10px] ${ev.status === 'upcoming' ? 'text-cyan-400' : 'text-slate-600'}`}>{ev.type?.replace(/_/g, ' ')} · {ev.status}</span>
                      </div>
                    );
                  })}
                  {(!c.events || c.events.length === 0) && <p className="text-sm text-slate-500 text-center py-8">No events extracted</p>}
                </div>
              </div>
            )}

            {/* Extracted Data */}
            {tab === 5 && (
              <div className="space-y-2">
                {(() => {
                  const bySection: Record<string, any[]> = {};
                  (c.extracted_data || []).forEach((d: any) => { const s = d.section || 'other'; if (!bySection[s]) bySection[s] = []; bySection[s].push(d); });
                  return Object.entries(bySection).map(([section, fields]) => (
                    <div key={section} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3 capitalize">{section.replace(/_/g, ' ')}</h3>
                      <div className="space-y-1.5">
                        {fields.map((d: any, i: number) => (
                          <div key={i} className="flex items-start justify-between text-xs gap-4 py-1 border-b border-slate-800/30 last:border-0">
                            <span className="text-slate-400 shrink-0 min-w-[140px]">{d.field_name?.replace(/_/g, ' ')}</span>
                            <div className="flex items-start gap-2 min-w-0">
                              <span className="text-white font-medium text-right break-words" title={d.field_value}>{d.field_value}</span>
                              {d.confidence != null && <div className="w-8 h-1 mt-1.5 shrink-0 bg-slate-700 rounded-full overflow-hidden"><div className={`h-full rounded-full ${d.confidence > 0.8 ? 'bg-emerald-500' : d.confidence > 0.5 ? 'bg-amber-500' : 'bg-red-500'}`} style={{ width: `${(d.confidence || 0) * 100}%` }} /></div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ));
                })()}
                {(!c.extracted_data || c.extracted_data.length === 0) && <p className="text-sm text-slate-500 text-center py-8">No data extracted</p>}
              </div>
            )}

            {/* Functional Analysis — interactive DAG */}
            {tab === 6 && (
              <FunctionalAnalysisTab contractId={contractId} />
            )}

            {/* Chat */}
            {tab === 7 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden" style={{ height: '500px' }}>
                <div ref={scrollRef} className="h-[430px] overflow-y-auto p-4 space-y-3">
                  {chatMessages.length === 0 && <div className="text-center py-12"><p className="text-xs text-slate-500">Ask questions about this contract</p></div>}
                  {chatMessages.map((m, i) => (
                    <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] px-3 py-2 rounded-lg text-xs leading-relaxed ${m.role === 'user' ? 'bg-emerald-500/10 border border-emerald-500/20 text-white' : 'bg-slate-700/30 border border-slate-700/50 text-slate-300 whitespace-pre-wrap'}`}>
                        {m.content}
                      </div>
                    </div>
                  ))}
                  {chatLoading && <div className="flex justify-start"><div className="px-3 py-2 rounded-lg bg-slate-700/30 border border-slate-700/50"><Loader2 className="w-4 h-4 text-emerald-400 animate-spin" /></div></div>}
                </div>
                <div className="border-t border-slate-700/50 p-3 flex gap-2">
                  <input type="text" value={chatInput} onChange={e => setChatInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendChat()} placeholder={`Ask about ${c.title}...`} className="flex-1 bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none" />
                  <button onClick={sendChat} disabled={chatLoading || !chatInput.trim()} className="px-4 py-2 rounded-lg bg-emerald-500 text-white text-xs hover:bg-emerald-400 disabled:opacity-50 transition-colors"><Send className="w-3 h-3" /></button>
                </div>
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </div>
  );
}
