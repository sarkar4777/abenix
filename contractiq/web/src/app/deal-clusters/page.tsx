'use client';


import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { apiFetch } from '@/lib/api';
import { PageExplainer } from '@/components/PageExplainer';
import {
  GitBranch, Loader2, FileText, Layers, Zap, DollarSign, Award,
  TrendingUp, Package, Info, Filter, Search, ArrowRight, Database,
  ExternalLink, X, BookOpen, AlertTriangle, Upload, ChevronDown, ChevronRight,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

type ClusterRow = {
  contract_id: string;
  contract_title: string;
  counterparty_a?: string;
  counterparty_b?: string;
  cluster_key: string;
  description?: string;
  clauses: (string | Record<string, any>)[];
  clause_rows?: ClauseRecord[];
  deal_legs: Record<string, any>;
};

type ClauseRecord = {
  id: string;
  number?: string | null;
  title: string;
  text: string;
  type: string;
  risk_level: string;
  risk_notes?: string | null;
};

const CLUSTER_META: Record<string, { label: string; color: string; icon: any; endurTemplate: string }> = {
  power_physical: { label: 'Power Physical', color: '#10b981', icon: Zap, endurTemplate: 'Power Phys Leg + Power Fin Leg + Per Unit Fee' },
  power_swap: { label: 'Power Swap', color: '#f59e0b', icon: TrendingUp, endurTemplate: 'Rec Fixed Leg + Pay Float Leg' },
  certificate_physical: { label: 'Certificate Physical', color: '#22c55e', icon: Award, endurTemplate: 'GoO Phys Leg + GoO Fin Leg' },
  fee_cash: { label: 'Fee / Cash', color: '#06b6d4', icon: DollarSign, endurTemplate: 'Cashflow' },
  gas_physical: { label: 'Gas Physical', color: '#0ea5e9', icon: Zap, endurTemplate: 'Gas Phys Leg + Gas Fin Leg' },
};

const LEG_ICON: Record<string, any> = {
  power_phys_leg: Zap, power_fin_leg: TrendingUp, per_unit_fee: DollarSign,
  rec_fixed_leg: TrendingUp, pay_float_leg: TrendingUp,
  goo_phys_leg: Award, goo_fin_leg: Award,
  cashflow: DollarSign,
  gas_phys_leg: Zap, gas_fin_leg: TrendingUp,
};

export default function DealClustersPage() {
  const [rows, setRows] = useState<ClusterRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedContract, setSelectedContract] = useState<string | 'all'>('all');
  const [clauseModal, setClauseModal] = useState<{ cluster: ClusterRow; title: string } | null>(null);
  const [legModal, setLegModal] = useState<{ row: ClusterRow; legKey: string; body: any } | null>(null);
  const [generateModal, setGenerateModal] = useState<{ cluster: ClusterRow; templateId: string } | null>(null);
  const [templates, setTemplates] = useState<EndurTemplate[]>([]);
  const [templateCategories, setTemplateCategories] = useState<{ key: string; label: string }[]>([]);

  const loadTemplates = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const r = await fetch(`${API_URL}/api/contractiq/templates`, { headers: { Authorization: `Bearer ${token}` } });
      const j = await r.json();
      setTemplates(j.data?.templates || []);
      setTemplateCategories(j.data?.categories || []);
    } catch { /* silent */ }
  }, []);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const r = await fetch(`${API_URL}/api/contractiq/deal-clusters`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      setRows(j.data?.clusters || []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); void loadTemplates(); }, [load, loadTemplates]);

  // Group templates by their category for quick lookup in the DAG.
  const templatesByCategory = useMemo(() => {
    const m = new Map<string, EndurTemplate[]>();
    for (const t of templates) {
      const arr = m.get(t.category) || [];
      arr.push(t);
      m.set(t.category, arr);
    }
    return m;
  }, [templates]);

  const contracts = useMemo(() => {
    const map = new Map<string, { id: string; title: string }>();
    for (const r of rows) {
      if (!map.has(r.contract_id)) map.set(r.contract_id, { id: r.contract_id, title: r.contract_title });
    }
    return Array.from(map.values());
  }, [rows]);

  const filtered = useMemo(() => {
    return rows.filter(r => {
      if (selectedContract !== 'all' && r.contract_id !== selectedContract) return false;
      if (search) {
        const q = search.toLowerCase();
        return r.contract_title.toLowerCase().includes(q)
          || r.cluster_key.toLowerCase().includes(q)
          || (r.description || '').toLowerCase().includes(q)
          || (r.counterparty_a || '').toLowerCase().includes(q)
          || (r.counterparty_b || '').toLowerCase().includes(q);
      }
      return true;
    });
  }, [rows, search, selectedContract]);

  const totals = useMemo(() => {
    const clusterTypes = new Set(filtered.map(r => r.cluster_key));
    const totalLegs = filtered.reduce((sum, r) => sum + Object.keys(r.deal_legs || {}).length, 0);
    const uniqueCounterparties = new Set<string>();
    for (const r of filtered) {
      if (r.counterparty_a) uniqueCounterparties.add(r.counterparty_a);
      if (r.counterparty_b) uniqueCounterparties.add(r.counterparty_b);
    }
    return {
      contracts: new Set(filtered.map(r => r.contract_id)).size,
      clusters: filtered.length,
      clusterTypes: clusterTypes.size,
      legs: totalLegs,
      counterparties: uniqueCounterparties.size,
    };
  }, [filtered]);

  if (loading) return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
    </div>
  );

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center">
              <GitBranch className="w-5 h-5 text-emerald-400" />
            </div>
            Deal Clusters &amp; Extraction Pipeline
          </h1>
          <p className="text-sm text-slate-400 mt-2 max-w-3xl">
            Every contract is broken into clauses, clauses are grouped into <strong className="text-white">deal clusters</strong>,
            each cluster produces the <strong className="text-white">deal JSON legs</strong> that downstream ETRM systems
            (Endur, Allegro, Openlink) consume as <strong className="text-white">deal templates</strong>. This is the
            end-to-end view of that pipeline across your portfolio.
          </p>
        </div>

        <PageExplainer routeKey="deal-clusters" />

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: 'Contracts', value: totals.contracts, icon: FileText, color: 'text-cyan-400' },
            { label: 'Deal Clusters', value: totals.clusters, icon: Layers, color: 'text-emerald-400' },
            { label: 'Cluster Types', value: totals.clusterTypes, icon: Package, color: 'text-purple-400' },
            { label: 'Deal Legs', value: totals.legs, icon: GitBranch, color: 'text-amber-400' },
            { label: 'Counterparties', value: totals.counterparties, icon: Database, color: 'text-rose-400' },
          ].map(k => (
            <div key={k.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <k.icon className={`w-4 h-4 ${k.color}`} />
                <span className="text-[10px] uppercase tracking-wider text-slate-500">{k.label}</span>
              </div>
              <p className={`text-2xl font-bold ${k.color}`}>{k.value}</p>
            </div>
          ))}
        </div>

        {/* ETRM Deal-Type Matrix — the canonical mapping from
            commodity × delivery × optionality × cashflow → ETRM deal
            type that downstream Endur/Allegro/Openlink templates
            consume. Drives Sheet2 of the spec. */}
        <DealTypeMatrix />

        {/* Endur JSON templates — operators upload a deal-type-specific
            JSON skeleton; the LLM populates it from any cluster on demand. */}
        <EndurTemplatesPanel
          rows={rows}
          templates={templates}
          categories={templateCategories}
          onChanged={() => { void loadTemplates(); }}
          onGenerated={() => void load()}
        />

        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/50 rounded-lg px-3 py-2 flex-1 max-w-md">
            <Search className="w-3.5 h-3.5 text-slate-500" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by contract, counterparty, cluster type…"
              className="flex-1 bg-transparent outline-none text-xs text-white placeholder-slate-500"
            />
          </div>
          <div className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/50 rounded-lg px-3 py-2">
            <Filter className="w-3.5 h-3.5 text-slate-500" />
            <select
              value={selectedContract}
              onChange={e => setSelectedContract(e.target.value)}
              className="bg-transparent outline-none text-xs text-white"
            >
              <option value="all">All contracts ({contracts.length})</option>
              {contracts.map(c => (
                <option key={c.id} value={c.id}>{c.title}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Empty state */}
        {filtered.length === 0 && rows.length === 0 && (
          <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
            <Upload className="w-14 h-14 text-slate-700 mx-auto mb-3" />
            <p className="text-base font-semibold text-white mb-1">No deal clusters yet</p>
            <p className="text-sm text-slate-400 mb-5 max-w-md mx-auto">
              Upload PPA / swap / tolling contracts — the extractor automatically breaks clauses into deal clusters ready for Endur-style deal templates.
            </p>
            <a href="/upload" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
              <Upload className="w-4 h-4" /> Upload your first contract
            </a>
          </div>
        )}

        {filtered.length === 0 && rows.length > 0 && (
          <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
            <Layers className="w-14 h-14 text-slate-700 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No clusters match your filter.</p>
          </div>
        )}

        {/* Pipeline DAG — grouped by contract, collapsible per group */}
        {filtered.length > 0 && (
          <PipelineDAG
            filtered={filtered}
            templatesByCategory={templatesByCategory}
            onOpenClauses={(row) => setClauseModal({
              cluster: row,
              title: `${row.contract_title} · ${(CLUSTER_META[row.cluster_key]?.label) || row.cluster_key}`,
            })}
            onPickTemplate={(row, tplId) => setGenerateModal({ cluster: row, templateId: tplId || '' })}
            onInspectLeg={(row, legKey, body) => setLegModal({ row, legKey, body })}
          />
        )}

        {clauseModal && (
          <ClauseModal
            cluster={clauseModal.cluster}
            title={clauseModal.title}
            onClose={() => setClauseModal(null)}
          />
        )}

        {legModal && (
          <LegInspectorModal
            row={legModal.row}
            legKey={legModal.legKey}
            body={legModal.body}
            onClose={() => setLegModal(null)}
            onPickTemplate={() => {
              setLegModal(null);
              setGenerateModal({ cluster: legModal.row, templateId: '' });
            }}
          />
        )}

        {generateModal && (
          <GenerateEndurModal
            cluster={generateModal.cluster}
            templates={templates}
            initialTemplateId={generateModal.templateId}
            onClose={() => { setGenerateModal(null); load(); }}
          />
        )}

        {/* Educational footer */}
        {filtered.length > 0 && (
          <section className="bg-slate-800/20 border border-slate-700/40 rounded-xl p-5 text-xs text-slate-400 leading-relaxed">
            <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
              <Info className="w-3.5 h-3.5 text-cyan-400" /> How the pipeline works
            </h3>
            <div className="grid grid-cols-4 gap-4">
              {[
                { step: '1', title: 'Contract Breakdown', body: 'The extractor agent reads the contract end-to-end and identifies every substantive clause with its full text, type, and risk level.' },
                { step: '2', title: 'Clause Grouping', body: 'Clauses are semantically grouped into deal clusters — Power Physical, Power Swap, Certificate, Gas, Fee/Cash — based on the trade economics they describe.' },
                { step: '3', title: 'Deal Legs', body: 'Each cluster is reshaped into the deal legs required by a deal message — e.g. Power Swap → Rec Fixed Leg + Pay Float Leg.' },
                { step: '4', title: 'Deal Templates', body: 'Legs are mapped to ETRM deal templates (Endur / Allegro / Openlink), ready for ingestion via the standard deal message format.' },
              ].map(s => (
                <div key={s.step}>
                  <div className="w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-[11px] font-bold text-emerald-300 mb-2">{s.step}</div>
                  <p className="text-xs font-semibold text-white mb-1">{s.title}</p>
                  <p className="text-[11px]">{s.body}</p>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

// ── Color legend ─────────────────────────────────────────────────────

function LegendKey() {
  return (
    <div className="flex items-center gap-3 text-[10px] flex-wrap">
      {Object.entries(CLUSTER_META).map(([k, m]) => (
        <span key={k} className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: m.color }} />
          <span className="text-slate-400">{m.label}</span>
        </span>
      ))}
    </div>
  );
}

// ── DAG container: groups clusters by contract, one collapsible per ──

function PipelineDAG({ filtered, templatesByCategory, onOpenClauses, onPickTemplate, onInspectLeg }: {
  filtered: ClusterRow[];
  templatesByCategory: Map<string, EndurTemplate[]>;
  onOpenClauses: (row: ClusterRow) => void;
  onPickTemplate: (row: ClusterRow, templateId?: string) => void;
  onInspectLeg: (row: ClusterRow, legKey: string, body: any) => void;
}) {
  // Group by contract_id, preserving first-seen order
  const groups = useMemo(() => {
    const m = new Map<string, { contractId: string; title: string; cpA?: string; cpB?: string; clusters: ClusterRow[] }>();
    for (const r of filtered) {
      let g = m.get(r.contract_id);
      if (!g) {
        g = { contractId: r.contract_id, title: r.contract_title, cpA: r.counterparty_a, cpB: r.counterparty_b, clusters: [] };
        m.set(r.contract_id, g);
      }
      g.clusters.push(r);
    }
    return Array.from(m.values());
  }, [filtered]);

  // Default-expanded: first group only — keeps the page scannable
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(groups.slice(0, 1).map(g => g.contractId)));

  const toggle = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allExpanded = groups.length > 0 && groups.every(g => expanded.has(g.contractId));
  const setAll = (on: boolean) => setExpanded(on ? new Set(groups.map(g => g.contractId)) : new Set());

  return (
    <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
      <header className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-cyan-400" /> Extraction Pipeline DAG
          </h2>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Per contract: clauses → deal clusters → JSON legs → matching uploaded templates.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <button
            onClick={() => setAll(!allExpanded)}
            className="text-[11px] text-cyan-400 hover:text-cyan-300"
          >
            {allExpanded ? 'Collapse all' : 'Expand all'}
          </button>
          <LegendKey />
        </div>
      </header>

      <div className="space-y-2">
        {groups.map(g => {
          const isOpen = expanded.has(g.contractId);
          return (
            <div key={g.contractId} className="border border-slate-700/40 rounded-lg overflow-hidden bg-slate-900/30">
              <button
                onClick={() => toggle(g.contractId)}
                className="w-full flex items-center gap-3 px-3 py-2 hover:bg-slate-800/40 text-left"
              >
                {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
                <FileText className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-white truncate">{g.title}</p>
                  <p className="text-[10px] text-slate-500 truncate">
                    {(g.cpA || '—')} → {(g.cpB || '—')}
                  </p>
                </div>
                <span className="text-[10px] text-slate-400 px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/60">
                  {g.clusters.length} cluster{g.clusters.length !== 1 ? 's' : ''}
                </span>
                <a
                  href={`/contracts/${g.contractId}`}
                  onClick={e => e.stopPropagation()}
                  className="text-[10px] text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1"
                >
                  Open <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </button>
              {isOpen && (
                <div className="border-t border-slate-700/40 p-3 bg-slate-950/40">
                  <ContractDAG
                    contractId={g.contractId}
                    contractTitle={g.title}
                    clusters={g.clusters}
                    templatesByCategory={templatesByCategory}
                    onOpenClauses={onOpenClauses}
                    onPickTemplate={onPickTemplate}
                    onInspectLeg={onInspectLeg}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}


function ContractDAG({ contractId, contractTitle, clusters, templatesByCategory, onOpenClauses, onPickTemplate, onInspectLeg }: {
  contractId: string;
  contractTitle: string;
  clusters: ClusterRow[];
  templatesByCategory: Map<string, EndurTemplate[]>;
  onOpenClauses: (row: ClusterRow) => void;
  onPickTemplate: (row: ClusterRow, templateId?: string) => void;
  onInspectLeg: (row: ClusterRow, legKey: string, body: any) => void;
}) {
  // Build the node graph for this contract.
  type Node = {
    id: string;
    kind: 'contract' | 'cluster' | 'leg' | 'template' | 'no-template';
    label: string;
    sub?: string;
    color: string;
    icon: any;
    onClick?: () => void;
    badge?: string;
  };
  type Edge = { from: string; to: string; color: string };

  const nodes: { contract: Node; clusters: Node[]; legs: Node[]; templates: Node[] } = {
    contract: {
      id: `c:${contractId}`,
      kind: 'contract',
      label: contractTitle,
      sub: `${clusters.length} cluster${clusters.length !== 1 ? 's' : ''}`,
      color: '#06b6d4',
      icon: FileText,
      onClick: () => { window.location.href = `/contracts/${contractId}`; },
    },
    clusters: [],
    legs: [],
    templates: [],
  };
  const edges: Edge[] = [];

  for (const row of clusters) {
    const meta = CLUSTER_META[row.cluster_key] || { label: row.cluster_key, color: '#64748b', icon: Layers, endurTemplate: '' };
    const clusterNodeId = `cl:${row.contract_id}:${row.cluster_key}`;
    nodes.clusters.push({
      id: clusterNodeId,
      kind: 'cluster',
      label: meta.label,
      sub: `${(row.clauses || []).length} clause${(row.clauses || []).length !== 1 ? 's' : ''}${row.clause_rows?.length ? ` · ${row.clause_rows.length} matched` : ''}`,
      color: meta.color,
      icon: meta.icon,
      onClick: () => onOpenClauses(row),
    });
    edges.push({ from: nodes.contract.id, to: clusterNodeId, color: meta.color });

    const legEntries = Object.entries(row.deal_legs || {});
    if (legEntries.length === 0) {
      const legId = `lg:${clusterNodeId}:none`;
      nodes.legs.push({ id: legId, kind: 'leg', label: 'no legs', color: '#475569', icon: GitBranch });
      edges.push({ from: clusterNodeId, to: legId, color: '#475569' });
    } else {
      for (const [legKey, legBody] of legEntries) {
        const fieldCount = legBody && typeof legBody === 'object' ? Object.keys(legBody as object).length : 0;
        const legId = `lg:${clusterNodeId}:${legKey}`;
        nodes.legs.push({
          id: legId,
          kind: 'leg',
          label: legKey.replace(/_/g, ' '),
          sub: `${fieldCount} field${fieldCount !== 1 ? 's' : ''}`,
          color: meta.color,
          icon: LEG_ICON[legKey] || GitBranch,
          onClick: () => onInspectLeg(row, legKey, legBody),
        });
        edges.push({ from: clusterNodeId, to: legId, color: meta.color });
      }
    }

    const matching = templatesByCategory.get(row.cluster_key) || [];
    if (matching.length === 0) {
      const tId = `tp:${clusterNodeId}:missing`;
      nodes.templates.push({
        id: tId,
        kind: 'no-template',
        label: 'No template',
        sub: `Upload one for ${row.cluster_key}`,
        color: '#f59e0b',
        icon: AlertTriangle,
        onClick: () => onPickTemplate(row),
      });
      // Connect every leg of this cluster to this single placeholder template
      for (const leg of nodes.legs) {
        if (leg.id.startsWith(`lg:${clusterNodeId}:`)) edges.push({ from: leg.id, to: tId, color: '#f59e0b' });
      }
    } else {
      for (const t of matching) {
        const tId = `tp:${clusterNodeId}:${t.id}`;
        nodes.templates.push({
          id: tId,
          kind: 'template',
          label: t.name,
          sub: `${t.field_count} field${t.field_count !== 1 ? 's' : ''} · ${t.is_starter ? 'starter' : 'custom'}`,
          color: '#a855f7',
          icon: Package,
          badge: t.is_starter ? 'starter' : 'custom',
          onClick: () => onPickTemplate(row, t.id),
        });
        for (const leg of nodes.legs) {
          if (leg.id.startsWith(`lg:${clusterNodeId}:`)) edges.push({ from: leg.id, to: tId, color: '#a855f7' });
        }
      }
    }
  }

  return (
    <DAGCanvas
      contract={nodes.contract}
      clusters={nodes.clusters}
      legs={nodes.legs}
      templates={nodes.templates}
      edges={edges}
    />
  );
}

// Generic DAG canvas: positions nodes in 4 columns, uses refs to compute
// pixel positions, renders an SVG overlay with curved edges. Re-measures
// on container resize so the lines stay glued to the nodes.

type DAGNode = {
  id: string;
  kind: 'contract' | 'cluster' | 'leg' | 'template' | 'no-template';
  label: string;
  sub?: string;
  color: string;
  icon: any;
  onClick?: () => void;
  badge?: string;
};
type DAGEdge = { from: string; to: string; color: string };

function DAGCanvas({ contract, clusters, legs, templates, edges }: {
  contract: DAGNode;
  clusters: DAGNode[];
  legs: DAGNode[];
  templates: DAGNode[];
  edges: DAGEdge[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [edgeGeo, setEdgeGeo] = useState<Array<{ d: string; color: string; key: string }>>([]);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const recompute = useCallback(() => {
    const c = containerRef.current; if (!c) return;
    const cb = c.getBoundingClientRect();
    setContainerSize({ w: cb.width, h: cb.height });
    const next: Array<{ d: string; color: string; key: string }> = [];
    for (const e of edges) {
      const a = nodeRefs.current[e.from];
      const b = nodeRefs.current[e.to];
      if (!a || !b) continue;
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      const x1 = ar.right - cb.left;
      const y1 = ar.top - cb.top + ar.height / 2;
      const x2 = br.left - cb.left;
      const y2 = br.top - cb.top + br.height / 2;
      const dx = Math.max(40, (x2 - x1) * 0.5);
      next.push({
        key: `${e.from}->${e.to}`,
        color: e.color,
        d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
      });
    }
    setEdgeGeo(next);
  }, [edges]);

  useEffect(() => {
    recompute();
    const ro = new ResizeObserver(() => recompute());
    if (containerRef.current) ro.observe(containerRef.current);
    window.addEventListener('resize', recompute);
    return () => { ro.disconnect(); window.removeEventListener('resize', recompute); };
  }, [recompute]);

  const adjacency = useMemo(() => {
    const out = new Map<string, Set<string>>();
    const inn = new Map<string, Set<string>>();
    for (const e of edges) {
      if (!out.has(e.from)) out.set(e.from, new Set());
      out.get(e.from)!.add(e.to);
      if (!inn.has(e.to)) inn.set(e.to, new Set());
      inn.get(e.to)!.add(e.from);
    }
    return { out, inn };
  }, [edges]);

  // BFS through outgoing + incoming from a hovered node to highlight the path
  const highlightedNodes = useMemo(() => {
    if (!hoveredId) return new Set<string>();
    const visit = new Set<string>([hoveredId]);
    const walk = (id: string, dir: 'out' | 'in') => {
      const m = dir === 'out' ? adjacency.out : adjacency.inn;
      const stack = [id];
      while (stack.length) {
        const cur = stack.pop()!;
        const neigh = m.get(cur);
        if (!neigh) continue;
        for (const n of neigh) if (!visit.has(n)) { visit.add(n); stack.push(n); }
      }
    };
    walk(hoveredId, 'out');
    walk(hoveredId, 'in');
    return visit;
  }, [hoveredId, adjacency]);

  const isHighlighted = (id: string) => !hoveredId || highlightedNodes.has(id);
  const isEdgeHighlighted = (e: { key: string }) => {
    if (!hoveredId) return true;
    const [from, to] = e.key.split('->');
    return highlightedNodes.has(from) && highlightedNodes.has(to);
  };

  const Column = ({ title, items, columnHint }: { title: string; items: DAGNode[]; columnHint?: string }) => (
    <div className="flex flex-col gap-2 min-w-[180px]">
      <div className="text-[9px] uppercase tracking-wider text-slate-500 px-1">
        {title} {columnHint && <span className="text-slate-600">· {columnHint}</span>}
      </div>
      <div className="flex flex-col gap-2">
        {items.map(n => (
          <button
            key={n.id}
            ref={el => { nodeRefs.current[n.id] = el; }}
            onClick={n.onClick}
            onMouseEnter={() => setHoveredId(n.id)}
            onMouseLeave={() => setHoveredId(null)}
            className={`text-left rounded-md px-2.5 py-2 border bg-slate-900/70 transition ${
              isHighlighted(n.id) ? 'opacity-100' : 'opacity-25'
            } ${n.onClick ? 'hover:bg-slate-800/80 cursor-pointer' : 'cursor-default'}`}
            style={{ borderColor: n.color + '55' }}
            disabled={!n.onClick}
          >
            <div className="flex items-center gap-1.5">
              <n.icon className="w-3 h-3 flex-shrink-0" style={{ color: n.color }} />
              <span className="text-[11px] font-semibold text-white truncate flex-1">{n.label}</span>
              {n.badge && (
                <span className="text-[9px] px-1 py-px rounded uppercase tracking-wider"
                  style={{ background: n.color + '20', color: n.color }}>
                  {n.badge}
                </span>
              )}
            </div>
            {n.sub && <p className="text-[10px] text-slate-500 truncate mt-0.5" title={n.sub}>{n.sub}</p>}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div ref={containerRef} className="relative overflow-x-auto">
      <svg
        className="absolute inset-0 pointer-events-none"
        width={containerSize.w}
        height={containerSize.h}
        style={{ minHeight: '100%' }}
      >
        <defs>
          {Array.from(new Set(edges.map(e => e.color))).map(c => (
            <marker key={c} id={`dag-arrow-${c.replace('#', '')}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <polygon points="0 0, 6 3, 0 6" fill={c} />
            </marker>
          ))}
        </defs>
        {edgeGeo.map(e => {
          const visible = isEdgeHighlighted(e);
          return (
            <path
              key={e.key}
              d={e.d}
              fill="none"
              stroke={e.color}
              strokeWidth={visible ? 1.5 : 0.6}
              opacity={visible ? 0.8 : 0.15}
              strokeDasharray="4 3"
              markerEnd={`url(#dag-arrow-${e.color.replace('#', '')})`}
            />
          );
        })}
      </svg>

      <div className="relative grid gap-10 py-3 px-1" style={{ gridTemplateColumns: '220px 200px 200px 220px' }}>
        <Column title="Contract" items={[contract]} />
        <Column title="Deal Clusters" items={clusters} columnHint={`${clusters.length}`} />
        <Column title="Deal Legs" items={legs} columnHint={`${legs.length}`} />
        <Column title="Endur Templates" items={templates} columnHint={`${templates.length}`} />
      </div>
    </div>
  );
}

// ── Reusable stage card ──────────────────────────────────────────────

function Stage({ accent, icon: Icon, kind, children }: { accent: string; icon: any; kind: string; children: React.ReactNode }) {
  return (
    <div className="border rounded-lg p-3 bg-slate-900/60 relative overflow-hidden"
      style={{ borderColor: accent + '40' }}>
      <div className="absolute top-0 left-0 bottom-0 w-0.5" style={{ background: accent }} />
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon className="w-3 h-3" style={{ color: accent }} />
        <span className="text-[9px] uppercase tracking-wider" style={{ color: accent }}>{kind}</span>
      </div>
      {children}
    </div>
  );
}

function Connector({ color }: { color: string }) {
  return (
    <div className="flex items-center justify-center relative h-full">
      <svg width="60" height="20" viewBox="0 0 60 20" className="overflow-visible">
        <defs>
          <marker id={`arrow-${color.replace('#', '')}`} markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto">
            <polygon points="0 0, 6 3, 0 6" fill={color} />
          </marker>
        </defs>
        <line x1="0" y1="10" x2="52" y2="10" stroke={color} strokeWidth="1.5" strokeDasharray="3 3" opacity="0.6" markerEnd={`url(#arrow-${color.replace('#', '')})`} />
      </svg>
    </div>
  );
}

// ── Cluster → Clause drill-through modal ─────────────────────────────

function ClauseModal({
  cluster, title, onClose,
}: {
  cluster: ClusterRow;
  title: string;
  onClose: () => void;
}) {
  const matched = cluster.clause_rows || [];
  const unmatched = (cluster.clauses || [])
    .map(c => typeof c === 'string' ? c : (c.title || c.number || JSON.stringify(c)))
    .filter(ref => {
      const refLow = String(ref).toLowerCase().trim();
      return !matched.some(m =>
        (m.number && m.number.toLowerCase() === refLow) ||
        (m.title && (refLow.includes(m.title.toLowerCase()) || m.title.toLowerCase().includes(refLow))),
      );
    });

  const riskColor: Record<string, string> = {
    low: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    medium: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    high: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
    critical: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-slate-700/60 rounded-2xl max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl"
      >
        <header className="flex items-center justify-between p-5 border-b border-slate-700/50">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Cluster → Clause drill-through</p>
            <h2 className="text-base font-semibold text-white">{title}</h2>
            <p className="text-xs text-slate-500 mt-1">
              {matched.length} matched clause{matched.length !== 1 ? 's' : ''}
              {unmatched.length > 0 && `  ·  ${unmatched.length} unresolved reference${unmatched.length !== 1 ? 's' : ''}`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-slate-400 hover:bg-slate-800/60 hover:text-white transition"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {matched.length === 0 && unmatched.length === 0 && (
            <p className="text-xs text-slate-500 italic text-center py-6">
              No clause references recorded for this cluster.
            </p>
          )}

          {matched.map(cl => (
            <div key={cl.id} className="border border-slate-700/50 rounded-xl p-4 bg-slate-900/40">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">
                    {cl.number ? `Clause ${cl.number}` : 'Clause'} · {cl.type.replace(/_/g, ' ')}
                  </p>
                  <h3 className="text-sm font-semibold text-white">{cl.title}</h3>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskColor[cl.risk_level?.toLowerCase()] || 'bg-slate-500/10 text-slate-400 border-slate-500/30'}`}>
                  {cl.risk_level || 'unknown'} risk
                </span>
              </div>
              <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">{cl.text}</p>
              {cl.risk_notes && (
                <div className="mt-2 pt-2 border-t border-slate-700/40 flex items-start gap-2">
                  <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 flex-shrink-0" />
                  <p className="text-[11px] text-amber-200/80 leading-relaxed">{cl.risk_notes}</p>
                </div>
              )}
            </div>
          ))}

          {unmatched.length > 0 && (
            <div className="border border-slate-700/30 border-dashed rounded-xl p-4 bg-slate-900/20">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Unresolved references</p>
              <ul className="space-y-1 text-xs text-slate-400 list-disc list-inside">
                {unmatched.map((u, i) => <li key={i}>{u}</li>)}
              </ul>
              <p className="text-[10px] text-slate-600 mt-2 italic">
                These references were recorded in the extraction's deal_clusters block
                but we could not match them to a persisted clause row.
              </p>
            </div>
          )}
        </div>

        <footer className="p-4 border-t border-slate-700/50 flex items-center justify-end gap-2">
          <a
            href={`/contracts/${cluster.contract_id}`}
            className="text-xs text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1"
          >
            Open full contract <ExternalLink className="w-3 h-3" />
          </a>
        </footer>
      </motion.div>
    </div>
  );
}


// ── Deal leg node (one per deal_legs key) ────────────────────────────

function LegNode({ legKey, body, clusterColor }: { legKey: string; body: any; clusterColor: string }) {
  const Icon = LEG_ICON[legKey] || GitBranch;
  const [open, setOpen] = useState(false);
  const hasFields = body && typeof body === 'object' && Object.keys(body).length > 0;

  return (
    <div
      className="bg-slate-800/40 border rounded-md overflow-hidden transition"
      style={{ borderColor: clusterColor + '40' }}
    >
      <button
        className="w-full px-2 py-1.5 flex items-center gap-1.5 hover:bg-slate-800/60 text-left"
        onClick={() => setOpen(o => !o)}
      >
        <Icon className="w-3 h-3" style={{ color: clusterColor }} />
        <span className="text-[11px] text-white font-medium flex-1 truncate">{legKey.replace(/_/g, ' ')}</span>
        {hasFields && (
          <span className="text-[9px] text-slate-500">{Object.keys(body).length}</span>
        )}
      </button>
      {open && hasFields && (
        <div className="px-2 pb-2 border-t border-slate-700/50 bg-slate-900/30">
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] mt-1.5">
            {Object.entries(body).map(([k, v]) => {
              const isEmpty = v === null || v === undefined || v === '';
              return (
                <div key={k}>
                  <span className="text-slate-600">{k.replace(/_/g, ' ')}</span>
                  <p className={`truncate ${isEmpty ? 'text-slate-700 italic' : 'text-slate-300'}`}>
                    {isEmpty ? '—' : (typeof v === 'object' ? JSON.stringify(v) : String(v))}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


type MatrixRow = {
  commodity: string;
  delivery: string;
  optionality: string;
  optionalityType: string;
  cashflow: string;
  etrm: string;
  notes: string;
};

const DEAL_TYPE_MATRIX: MatrixRow[] = [
  { commodity: 'Power',         delivery: 'Physical',  optionality: 'No',  optionalityType: '—',                                            cashflow: 'Commodity related payment',     etrm: 'Power Physical',                              notes: 'Cluster the volume (fixed/timeseries) + price (fixed/indexed/formula) clauses with the commodity payment clause.' },
  { commodity: 'Power',         delivery: 'Physical',  optionality: 'No',  optionalityType: '—',                                            cashflow: 'Volume-dependent payment',      etrm: 'Power Physical · Deal Fee',                  notes: 'Tolling fees, service fees on physical delivery captured as a Fee leg on the Power Physical deal.' },
  { commodity: 'Power',         delivery: 'Physical',  optionality: 'Yes', optionalityType: 'European',                                     cashflow: 'Premium (fixed, per unit, …)',  etrm: 'Power European Option · Phys underlying',     notes: 'Optionality clause clusters with the Premium clause to capture one option instrument in ETRM.' },
  { commodity: 'Power',         delivery: 'Physical',  optionality: 'Yes', optionalityType: 'European',                                     cashflow: 'Option pay-off',                etrm: 'Power European Option · Phys underlying',     notes: 'Pay-off clause attached to the same option deal.' },
  { commodity: 'Power',         delivery: 'Financial', optionality: 'No',  optionalityType: '—',                                            cashflow: 'Pay fix, receive float',        etrm: 'Power Financial Swap',                       notes: 'Standard fix-vs-float financial swap; index + tenor in the price clause.' },
  { commodity: 'Power',         delivery: 'Financial', optionality: 'Yes', optionalityType: 'Asian',                                        cashflow: 'Premium (fixed, per unit, …)',  etrm: 'Power Asian Option · Financial underlying',  notes: 'Asian-style averaging option settled financially.' },
  { commodity: 'Power',         delivery: 'Financial', optionality: 'Yes', optionalityType: 'Asian',                                        cashflow: 'Option pay-off',                etrm: 'Power Asian Option · Financial underlying',  notes: 'Pay-off attached to the same option deal.' },
  { commodity: 'Power',         delivery: 'Financial', optionality: 'Yes', optionalityType: 'Option strategy (Straddle, Floor, Collar, …)', cashflow: 'Premium (fixed, per unit, …)',  etrm: 'Split into multiple deals',                  notes: 'Strategy splits into standalone option / swap legs each as its own deal.' },
  { commodity: 'Power',         delivery: 'Financial', optionality: 'Yes', optionalityType: 'Option strategy (Straddle, Floor, Collar, …)', cashflow: 'Option pay-off',                etrm: 'Split into multiple deals',                  notes: 'Each underlying instrument carries its own pay-off leg.' },
  { commodity: 'Natural Gas',   delivery: 'Physical',  optionality: 'No',  optionalityType: '—',                                            cashflow: 'Commodity related payment',     etrm: 'Commodity Physical (Gas)',                   notes: 'Single physical-delivery deal type in Endur.' },
  { commodity: 'Natural Gas',   delivery: 'Physical',  optionality: 'No',  optionalityType: '—',                                            cashflow: 'Volume-dependent payment',      etrm: 'Commodity Fees',                             notes: 'Tolling / processor / demurrage fees captured as a separate Commodity Fees deal.' },
  { commodity: 'GoO Certificate', delivery: 'Physical', optionality: 'No', optionalityType: '—',                                            cashflow: 'Certificate related payment',   etrm: 'Commodity Physical (Certificate)',           notes: 'Includes Guarantees of Origin, RECs, PEPs etc.' },
];

function DealTypeMatrix() {
  const [open, setOpen] = useState(true);
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl overflow-hidden" data-testid="etrm-matrix">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-800/40"
      >
        <div>
          <h3 className="text-sm font-semibold text-white">ETRM Deal-Type Matrix</h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            commodity × delivery × optionality × cashflow → the Endur / Allegro / Openlink deal type a clause cluster should map to (12 rules).
          </p>
        </div>
        <span className="text-[10px] text-slate-500 uppercase tracking-wider">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="border-t border-slate-700/40 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/40 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">#</th>
                <th className="text-left px-3 py-2 font-medium">Commodity</th>
                <th className="text-left px-3 py-2 font-medium">Delivery</th>
                <th className="text-left px-3 py-2 font-medium">Optionality</th>
                <th className="text-left px-3 py-2 font-medium">Type</th>
                <th className="text-left px-3 py-2 font-medium">Cashflow</th>
                <th className="text-left px-3 py-2 font-medium">ETRM Deal Type</th>
                <th className="text-left px-3 py-2 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {DEAL_TYPE_MATRIX.map((r, i) => (
                <tr key={i} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-3 py-2 text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{r.commodity}</td>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{r.delivery}</td>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{r.optionality}</td>
                  <td className="px-3 py-2 text-slate-400">{r.optionalityType}</td>
                  <td className="px-3 py-2 text-slate-300">{r.cashflow}</td>
                  <td className="px-3 py-2 font-medium text-emerald-300 whitespace-nowrap">{r.etrm}</td>
                  <td className="px-3 py-2 text-slate-400 max-w-md">{r.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}



type EndurTemplate = {
  id: string;
  category: string;
  category_label: string;
  name: string;
  description: string | null;
  field_count: number;
  template_json: any;
  is_starter: boolean;
  created_at: string | null;
};

function EndurTemplatesPanel({ rows, templates, categories, onChanged, onGenerated }: {
  rows: ClusterRow[];
  templates: EndurTemplate[];
  categories: { key: string; label: string }[];
  onChanged: () => void;
  onGenerated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const loading = false;
  const [showUpload, setShowUpload] = useState(false);
  const [showGenerate, setShowGenerate] = useState<{ cluster: ClusterRow; templateId: string } | null>(null);
  const [viewing, setViewing] = useState<EndurTemplate | null>(null);

  const remove = async (id: string) => {
    const token = getToken();
    if (!token) return;
    if (!confirm('Delete this template?')) return;
    await fetch(`${API_URL}/api/contractiq/templates/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
    onChanged();
  };

  return (
    <>
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl overflow-hidden" data-testid="endur-templates">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-800/40"
        >
          <div>
            <h3 className="text-sm font-semibold text-white">Endur JSON Templates</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Upload a JSON skeleton per ETRM deal type. The LLM populates the <code className="text-emerald-300">{`\${placeholder}`}</code> tokens using a deal cluster&apos;s clauses + legs to produce a payload your ETRM team can paste straight into Endur.
            </p>
          </div>
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">{open ? 'hide' : 'show'}</span>
        </button>
        {open && (
          <div className="border-t border-slate-700/40">
            <div className="px-5 py-3 flex items-center justify-between gap-3 border-b border-slate-700/40 bg-slate-900/40">
              <div className="text-xs text-slate-400">
                {loading ? 'Loading…' : `${templates.length} template${templates.length === 1 ? '' : 's'} · ${categories.length} supported categories`}
              </div>
              <button
                onClick={() => setShowUpload(true)}
                className="px-3 py-1.5 text-xs rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 hover:bg-emerald-500/25 inline-flex items-center gap-2"
                data-testid="upload-template-btn"
              >
                <Upload className="w-3.5 h-3.5" /> Upload template
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-900/40 text-slate-400">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Category</th>
                    <th className="text-left px-3 py-2 font-medium">Name</th>
                    <th className="text-left px-3 py-2 font-medium">Fields</th>
                    <th className="text-left px-3 py-2 font-medium">Source</th>
                    <th className="text-left px-3 py-2 font-medium">Updated</th>
                    <th className="text-right px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {templates.map(t => (
                    <tr key={t.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                      <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{t.category_label}</td>
                      <td className="px-3 py-2 text-slate-200">{t.name}</td>
                      <td className="px-3 py-2 text-slate-400">{t.field_count}</td>
                      <td className="px-3 py-2">
                        {t.is_starter
                          ? <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300">starter</span>
                          : <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">custom</span>}
                      </td>
                      <td className="px-3 py-2 text-slate-500">{t.created_at ? new Date(t.created_at).toLocaleDateString() : '—'}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <button onClick={() => setViewing(t)} className="text-cyan-400 hover:underline mr-3">View</button>
                        {!t.is_starter && (
                          <button onClick={() => void remove(t.id)} className="text-rose-400 hover:underline">Delete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!loading && templates.length === 0 && (
                    <tr><td colSpan={6} className="text-center text-slate-500 px-3 py-6">No templates yet — click <em>Upload template</em> to add one.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {rows.length > 0 && (
              <div className="px-5 py-3 border-t border-slate-700/40 bg-slate-900/30">
                <div className="text-[11px] text-slate-500 mb-2 uppercase tracking-wider">Generate Endur JSON for a cluster</div>
                <div className="flex flex-wrap gap-2">
                  {rows.slice(0, 8).map((r, i) => (
                    <button
                      key={i}
                      onClick={() => setShowGenerate({ cluster: r, templateId: '' })}
                      className="px-3 py-1.5 text-[11px] rounded-lg border border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-200 inline-flex items-center gap-1.5"
                      data-testid="generate-endur-btn"
                    >
                      <Database className="w-3 h-3 text-emerald-400" />
                      <span className="truncate max-w-[180px]">{r.cluster_key}</span>
                      <ArrowRight className="w-3 h-3 text-slate-500" />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {showUpload && (
        <UploadTemplateModal
          categories={categories}
          onClose={() => setShowUpload(false)}
          onSaved={() => { setShowUpload(false); onChanged(); }}
        />
      )}
      {showGenerate && showGenerate.cluster && (
        <GenerateEndurModal
          cluster={showGenerate.cluster}
          templates={templates}
          initialTemplateId={showGenerate.templateId}
          onClose={() => { setShowGenerate(null); onGenerated(); }}
        />
      )}
      {viewing && (
        <ViewTemplateModal template={viewing} onClose={() => setViewing(null)} />
      )}
    </>
  );
}

function UploadTemplateModal({ categories, onClose, onSaved }: {
  categories: { key: string; label: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [category, setCategory] = useState(categories[0]?.key || 'power_physical');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [json, setJson] = useState('{\n  "deal_type": "...",\n  "field": "${placeholder}"\n}');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setError(null);
    let parsed: any;
    try { parsed = JSON.parse(json); }
    catch (e) { setError(`Invalid JSON: ${(e as Error).message}`); return; }
    if (!name.trim()) { setError('Name is required'); return; }
    setSaving(true);
    const token = getToken();
    const r = await fetch(`${API_URL}/api/contractiq/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ category, name: name.trim(), description, template_json: parsed }),
    });
    setSaving(false);
    if (!r.ok) { setError(`Save failed: ${r.status}`); return; }
    onSaved();
  };

  const onFile = async (f: File) => {
    const text = await f.text();
    setJson(text);
    if (!name) setName(f.name.replace(/\.json$/i, ''));
  };

  return (
    <ModalShell title="Upload Endur Template" onClose={onClose} testId="upload-template-modal">
      <div className="space-y-4">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Category</label>
          <select value={category} onChange={e => setCategory(e.target.value)} className="w-full bg-slate-900/60 border border-slate-700 rounded px-3 py-2 text-sm text-white">
            {categories.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Name</label>
          <input value={name} onChange={e => setName(e.target.value)} className="w-full bg-slate-900/60 border border-slate-700 rounded px-3 py-2 text-sm text-white" placeholder="e.g. Tenant Endur 24.2 — Power Physical"/>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Description</label>
          <input value={description} onChange={e => setDescription(e.target.value)} className="w-full bg-slate-900/60 border border-slate-700 rounded px-3 py-2 text-sm text-white"/>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-[10px] uppercase tracking-wider text-slate-500">Template JSON</label>
            <label className="text-[11px] text-cyan-400 hover:underline cursor-pointer">
              Upload .json
              <input type="file" accept="application/json,.json" className="hidden" onChange={e => e.target.files && onFile(e.target.files[0])} />
            </label>
          </div>
          <textarea
            value={json}
            onChange={e => setJson(e.target.value)}
            className="w-full h-56 bg-slate-900/60 border border-slate-700 rounded p-3 text-[12px] text-slate-200 font-mono"
            spellCheck={false}
          />
          <p className="text-[11px] text-slate-500 mt-1">Use <code className="text-emerald-300">{`\${placeholder}`}</code> tokens. The LLM resolves them using the cluster + clause data.</p>
        </div>
        {error && <div className="rounded border border-rose-500/30 bg-rose-500/10 p-2 text-rose-200 text-xs">{error}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-300">Cancel</button>
          <button onClick={submit} disabled={saving} className="px-3 py-1.5 text-xs rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save template'}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

function ViewTemplateModal({ template, onClose }: { template: EndurTemplate; onClose: () => void }) {
  return (
    <ModalShell title={`${template.category_label} · ${template.name}`} onClose={onClose} testId="view-template-modal">
      {template.description && <p className="text-xs text-slate-400 mb-3">{template.description}</p>}
      <JSONViewer value={template.template_json} />
    </ModalShell>
  );
}

// ── Leg JSON inspector — opens when a leg node in the DAG is clicked ──

function LegInspectorModal({ row, legKey, body, onClose, onPickTemplate }: {
  row: ClusterRow;
  legKey: string;
  body: any;
  onClose: () => void;
  onPickTemplate: () => void;
}) {
  const meta = CLUSTER_META[row.cluster_key] || { label: row.cluster_key, color: '#64748b', icon: Layers, endurTemplate: '' };
  const Icon = LEG_ICON[legKey] || GitBranch;
  const fieldEntries = body && typeof body === 'object' && !Array.isArray(body) ? Object.entries(body) : [];

  return (
    <ModalShell title={`Deal leg · ${legKey.replace(/_/g, ' ')}`} onClose={onClose} testId="leg-inspector-modal" wide>
      <div className="space-y-4">
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <Icon className="w-3.5 h-3.5" style={{ color: meta.color }} />
            <span className="text-white">{meta.label}</span>
          </span>
          <span className="text-slate-600">·</span>
          <span className="truncate" title={row.contract_title}>{row.contract_title}</span>
          <span className="text-slate-600">·</span>
          <span>{fieldEntries.length} field{fieldEntries.length !== 1 ? 's' : ''}</span>
        </div>

        <p className="text-[12px] text-slate-400">
          One leg of an Endur deal-message. The fields below are what the extractor lifted off the
          contract and what an Endur template will be populated from.
        </p>

        <JSONViewer value={body} testId="leg-json" />

        <div className="flex justify-end">
          <button
            onClick={onPickTemplate}
            className="px-3 py-1.5 text-xs rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 inline-flex items-center gap-2"
          >
            <Database className="w-3.5 h-3.5" /> Generate Endur JSON for this cluster
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

function GenerateEndurModal({ cluster, templates, initialTemplateId, onClose }: {
  cluster: ClusterRow;
  templates: EndurTemplate[];
  initialTemplateId: string;
  onClose: () => void;
}) {
  // Only show templates whose category matches this cluster's key — anything
  // else is irrelevant here. If none match, we render a clear empty state
  // with an upload prompt instead of a useless dropdown of unrelated templates.
  const matchingTemplates = useMemo(
    () => templates.filter(t => t.category === cluster.cluster_key),
    [templates, cluster.cluster_key],
  );
  const [tplId, setTplId] = useState<string>(initialTemplateId || matchingTemplates[0]?.id || '');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    setRunning(true); setError(null); setResult(null);
    const token = getToken();
    const res = await apiFetch<any>(`${API_URL}/api/contractiq/generate-endur-json`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ template_id: tplId, contract_id: cluster.contract_id, cluster_key: cluster.cluster_key }),
    });
    if (!res.ok) {
      setError(res.error || 'Generation failed');
    } else {
      const payload = res.data?.data;
      // Backend rejects mangled output by setting populated_json=null + parse_error.
      // Surface that as the primary error so the user doesn't see garbage JSON.
      if (payload?.parse_error) setError(payload.parse_error);
      setResult(payload);
    }
    setRunning(false);
  };

  const copyJson = async () => {
    if (!result?.populated_json) return;
    await navigator.clipboard.writeText(JSON.stringify(result.populated_json, null, 2));
  };

  const downloadJson = () => {
    if (!result?.populated_json) return;
    const blob = new Blob([JSON.stringify(result.populated_json, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url;
    a.download = `endur_${result.category}_${cluster.contract_id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const meta = CLUSTER_META[cluster.cluster_key] || { label: cluster.cluster_key, color: '#64748b', icon: Layers, endurTemplate: '' };
  const ClusterIcon = meta.icon;
  const legCount = Object.keys(cluster.deal_legs || {}).length;
  const clauseCount = (cluster.clauses || []).length;
  const noTemplates = matchingTemplates.length === 0;

  return (
    <ModalShell
      title="Generate Endur JSON"
      onClose={onClose}
      testId="generate-endur-modal"
      wide
    >
      {/* What this screen is — one-line, explicit */}
      <div className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2 mb-4 text-[12px] text-slate-300 flex items-center gap-2">
        <Info className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
        Pick one of <strong className="text-white">your uploaded {meta.label} templates</strong>.
        The agent fills its <code className="text-emerald-300">{`\${placeholder}`}</code> tokens
        from this cluster&apos;s {clauseCount} clause{clauseCount !== 1 ? 's' : ''} + {legCount} deal leg{legCount !== 1 ? 's' : ''}.
        Output is ready to paste into Endur.
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-4 space-y-4">
          {/* Source */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Source · cluster</p>
            <div className="rounded-md border bg-slate-900/40 px-2.5 py-2 flex items-start gap-2"
              style={{ borderColor: meta.color + '55' }}>
              <ClusterIcon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: meta.color }} />
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-white">{meta.label}</p>
                <p className="text-[10px] text-slate-500 truncate" title={cluster.contract_title}>{cluster.contract_title}</p>
                <p className="text-[10px] text-slate-500 mt-1">
                  {clauseCount} clause{clauseCount !== 1 ? 's' : ''} · {legCount} leg{legCount !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
          </div>

          {/* Template picker — only category-matched templates */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Template</p>
              <span className="text-[10px] text-slate-500">{matchingTemplates.length} match{matchingTemplates.length !== 1 ? 'es' : ''}</span>
            </div>
            {noTemplates ? (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-100">
                <div className="flex items-start gap-2 mb-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5" />
                  <div>
                    <p className="text-amber-200 font-semibold">No template uploaded for <code>{cluster.cluster_key}</code></p>
                    <p className="text-amber-100/70 mt-1">Upload an Endur JSON skeleton for this category in the panel above, then return here.</p>
                  </div>
                </div>
              </div>
            ) : (
              <select
                value={tplId}
                onChange={e => setTplId(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-2 text-xs text-white"
              >
                {matchingTemplates.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.name} · {t.field_count} fields {t.is_starter ? '· starter' : '· custom'}
                  </option>
                ))}
              </select>
            )}
          </div>

          <button
            onClick={run}
            disabled={running || !tplId || noTemplates}
            className="w-full px-3 py-2.5 text-sm rounded-lg bg-emerald-500/20 border border-emerald-500/50 text-emerald-100 hover:bg-emerald-500/30 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2 font-semibold"
            data-testid="run-generate-btn"
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
            {running ? 'Filling template…' : 'Run agent · Fill template'}
          </button>

          {result && (
            <div className="rounded-md border border-slate-700/60 bg-slate-900/40 p-2.5 space-y-1.5 text-[11px] text-slate-400">
              <div className="flex justify-between"><span>agent</span><span className="text-violet-300 font-mono truncate ml-2">{result.agent_slug || '—'}</span></div>
              <div className="flex justify-between"><span>cost</span><span className="text-emerald-300">${(result.cost_usd || 0).toFixed(4)}</span></div>
              <div className="flex justify-between"><span>time</span><span className="text-cyan-300">{Math.round((result.duration_ms || 0))}ms</span></div>
              {Array.isArray(result.unfilled) && result.unfilled.length > 0 && (
                <div className="flex justify-between"><span>unfilled</span><span className="text-amber-300">{result.unfilled.length}</span></div>
              )}
              <div className="flex gap-2 pt-2 border-t border-slate-800">
                <button onClick={copyJson} className="flex-1 px-2 py-1 text-[11px] rounded border border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-200">Copy</button>
                <button onClick={downloadJson} className="flex-1 px-2 py-1 text-[11px] rounded border border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-200">Download</button>
              </div>
              {result.summary && (
                <p className="text-[11px] text-slate-300 italic pt-2 border-t border-slate-800" data-testid="agent-summary">{result.summary}</p>
              )}
            </div>
          )}

          {/* Available data — what the agent has access to */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Agent will use</p>
            <div className="space-y-1 text-[11px]">
              {Object.entries(cluster.deal_legs || {}).slice(0, 6).map(([k, v]) => {
                const fc = v && typeof v === 'object' ? Object.keys(v as object).length : 0;
                const Icon = LEG_ICON[k] || GitBranch;
                return (
                  <div key={k} className="flex items-center gap-1.5 text-slate-300">
                    <Icon className="w-2.5 h-2.5 flex-shrink-0" style={{ color: meta.color }} />
                    <span className="truncate">{k.replace(/_/g, ' ')}</span>
                    <span className="text-slate-500 ml-auto">{fc}f</span>
                  </div>
                );
              })}
              {(cluster.clauses || []).slice(0, 4).map((c, i) => (
                <div key={`cl-${i}`} className="flex items-center gap-1.5 text-slate-400">
                  <BookOpen className="w-2.5 h-2.5 flex-shrink-0 text-slate-500" />
                  <span className="truncate">{typeof c === 'string' ? c : ((c as any).title || (c as any).number || '—')}</span>
                </div>
              ))}
              {clauseCount > 4 && <p className="text-[10px] text-slate-600">+{clauseCount - 4} more clause{clauseCount - 4 !== 1 ? 's' : ''}</p>}
            </div>
          </div>
        </div>
        <div className="col-span-8 space-y-3">
          {error && <div className="rounded border border-rose-500/30 bg-rose-500/10 p-3 text-rose-200 text-xs">{error}</div>}
          {!result && !error && noTemplates && (
            <div className="h-full min-h-[320px] flex flex-col items-center justify-center text-slate-400 text-sm border border-dashed border-amber-700/60 bg-amber-900/5 rounded-lg p-12 gap-2">
              <Upload className="w-8 h-8 text-amber-400/60" />
              <p>Upload an Endur JSON template for category <code className="text-amber-300">{cluster.cluster_key}</code> to use this screen.</p>
              <p className="text-[11px] text-slate-500">Use the <strong>Upload template</strong> button in the Endur JSON Templates panel.</p>
            </div>
          )}
          {!result && !error && !noTemplates && (
            <div className="h-full min-h-[320px] flex items-center justify-center text-slate-500 text-sm border border-dashed border-slate-700 rounded-lg p-12 text-center">
              Click <strong className="text-emerald-300">&quot;Run agent · Fill template&quot;</strong>.<br/>
              The populated Endur JSON will appear here, with a tool-call trace and a clause-level provenance map.
            </div>
          )}
          {result && (
            <>
              {/* Populated JSON */}
              <JSONViewer value={result.populated_json ?? result.raw_output ?? {}} testId="endur-json-result" />

              {/* Tool-calls trace — agentic transparency */}
              {Array.isArray(result.tool_calls) && result.tool_calls.length > 0 && (
                <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3" data-testid="agent-trace">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Agent reasoning trace · {result.tool_calls.length} tool call{result.tool_calls.length === 1 ? '' : 's'}</p>
                  <ol className="space-y-2">
                    {result.tool_calls.map((t: any, i: number) => (
                      <li key={i} className="text-[11px] text-slate-300 border-l-2 border-violet-400/50 pl-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-violet-300">{t.name}</span>
                          {typeof t.duration_ms === 'number' && (
                            <span className="text-slate-500">{t.duration_ms}ms</span>
                          )}
                        </div>
                        {t.arguments && (
                          <pre className="text-[10px] text-slate-400 mt-1 whitespace-pre-wrap break-all">
                            args: {typeof t.arguments === 'string' ? t.arguments : JSON.stringify(t.arguments).slice(0, 240)}
                          </pre>
                        )}
                        {t.result_preview && (
                          <pre className="text-[10px] text-slate-500 mt-1 whitespace-pre-wrap break-all">
                            → {t.result_preview}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* Provenance map */}
              {result.provenance && Object.keys(result.provenance).length > 0 && (
                <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3" data-testid="agent-provenance">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Provenance · {Object.keys(result.provenance).length} field{Object.keys(result.provenance).length === 1 ? '' : 's'} cited</p>
                  <table className="w-full text-[11px]">
                    <thead className="text-slate-500">
                      <tr><th className="text-left font-medium">JSON path</th><th className="text-left font-medium">Source</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(result.provenance).slice(0, 50).map(([k, v]) => (
                        <tr key={k} className="border-t border-slate-800/60">
                          <td className="py-1 text-emerald-300 font-mono">{k}</td>
                          <td className="py-1 text-slate-300 font-mono">{String(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Unfilled placeholders */}
              {Array.isArray(result.unfilled) && result.unfilled.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3" data-testid="agent-unfilled">
                  <p className="text-[10px] uppercase tracking-wider text-amber-300 mb-1.5">{result.unfilled.length} placeholder{result.unfilled.length === 1 ? '' : 's'} unfilled</p>
                  <p className="text-[11px] text-amber-100/80 mb-2">
                    The agent could not source these from the contract. Either the data really isn&apos;t there
                    (deal_legs / clauses don&apos;t cover these fields) or the template uses a placeholder name
                    the agent didn&apos;t recognise.
                  </p>
                  <ul className="text-[11px] text-amber-200 list-disc list-inside columns-2">
                    {result.unfilled.map((p: string, i: number) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </ModalShell>
  );
}

function ModalShell({ title, onClose, children, testId, wide }: {
  title: string; onClose: () => void; children: React.ReactNode; testId?: string; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-6" data-testid={testId} onClick={onClose}>
      <div
        className={`bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full ${wide ? 'max-w-6xl' : 'max-w-2xl'} max-h-[90vh] overflow-hidden flex flex-col`}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

function JSONViewer({ value, testId }: { value: any; testId?: string }) {
  const html = useMemo(() => {
    const json = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    return json
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"([^"\\]|\\.)*"\s*:/g, m => `<span class="text-emerald-300">${m}</span>`)
      .replace(/: ?"([^"\\]|\\.)*"/g, m => `: <span class="text-cyan-300">${m.slice(2)}</span>`)
      .replace(/\b(-?\d+\.?\d*)\b/g, '<span class="text-amber-300">$1</span>')
      .replace(/\b(true|false|null)\b/g, '<span class="text-violet-300">$1</span>');
  }, [value]);
  return (
    <pre
      className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-[11.5px] font-mono text-slate-300 overflow-auto max-h-[60vh] whitespace-pre"
      data-testid={testId}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
