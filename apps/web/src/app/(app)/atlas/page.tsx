'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactFlow, {
  Background, BackgroundVariant, Controls, MiniMap,
  applyNodeChanges, applyEdgeChanges, addEdge,
  type Connection, type Edge, type Node as RFNode,
  type NodeChange, type EdgeChange, type ReactFlowInstance,
  Handle, Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  Network, Plus, Trash2, Loader2, Sparkles, Send, Upload, Wand2,
  History, Download, Check, X, AlertTriangle, Info, Bot, Lightbulb,
  ChevronRight, Save, Layers, Database, FileText, GitBranch,
  Workflow, Box, Zap, Eye, ArrowRight, RotateCcw,
  LibraryBig, Search, ScanLine, Link2, Compass, ListChecks,
  CircleDot, Grid3x3, HelpCircle, Mouse,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

// ── Types ────────────────────────────────────────────────────────────

type NodeKind = 'concept' | 'instance' | 'document' | 'property';

interface AtlasNodeRow {
  id: string;
  graph_id: string;
  label: string;
  kind: NodeKind;
  description: string;
  properties: Record<string, any>;
  position: { x: number; y: number } | null;
  document_id: string | null;
  source: string;
  confidence: number | null;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
}

interface AtlasEdgeRow {
  id: string;
  graph_id: string;
  from_node_id: string;
  to_node_id: string;
  label: string;
  description: string;
  cardinality_from: string | null;
  cardinality_to: string | null;
  inverse_edge_id: string | null;
  is_directed: boolean;
  properties: Record<string, any>;
  source: string;
  confidence: number | null;
}

interface GraphMeta {
  id: string;
  name: string;
  description: string;
  kb_id: string | null;
  version: number;
  node_count: number;
  edge_count: number;
  settings: Record<string, any>;
  created_at: string | null;
  updated_at: string | null;
}

interface SnapshotRow {
  id: string;
  version: number;
  label: string | null;
  auto: boolean;
  created_at: string | null;
}

interface Suggestion {
  kind: string;
  title: string;
  detail: string;
  severity: 'info' | 'warning' | 'error';
  node_ids?: string[];
  edge_id?: string;
  edge_ids?: string[];
  from_node_id?: string;
  to_node_id?: string;
}

interface Starter {
  id: string;
  name: string;
  description: string;
  node_count: number;
  edge_count: number;
}

interface KBCollection {
  id: string;
  name: string;
  description?: string;
  doc_count?: number;
}

interface QueryPattern {
  label_like: string;
  kind?: NodeKind | '';
}

interface QueryMatch {
  nodes: AtlasNodeRow[];
  edges: AtlasEdgeRow[];
}

interface InstanceRow {
  id: string;
  label: string;
  file_type?: string;
  file_size?: number;
  status?: string;
  kb_id?: string;
}

// ── Custom React Flow node renderer ──────────────────────────────────

const KIND_STYLE: Record<NodeKind, { bg: string; border: string; icon: any; accent: string }> = {
  concept:  { bg: 'from-violet-500/15 to-violet-500/5', border: 'border-violet-500/40',  icon: Box,      accent: 'text-violet-300' },
  instance: { bg: 'from-emerald-500/15 to-emerald-500/5', border: 'border-emerald-500/40', icon: Database, accent: 'text-emerald-300' },
  document: { bg: 'from-amber-500/15 to-amber-500/5',   border: 'border-amber-500/40',   icon: FileText, accent: 'text-amber-300' },
  property: { bg: 'from-cyan-500/15 to-cyan-500/5',     border: 'border-cyan-500/40',    icon: Zap,      accent: 'text-cyan-300' },
};

interface ConceptNodeData {
  row: AtlasNodeRow;
  selected: boolean;
}

function ConceptNode({ data }: { data: ConceptNodeData }) {
  const { row } = data;
  const style = KIND_STYLE[row.kind] || KIND_STYLE.concept;
  const Icon = style.icon;
  const ghost = row.source !== 'user';
  return (
    <div
      className={`relative min-w-[180px] max-w-[260px] rounded-xl border ${style.border} bg-gradient-to-br ${style.bg} backdrop-blur-sm shadow-lg ${ghost ? 'opacity-70' : ''}`}
      style={{ boxShadow: data.selected ? '0 0 0 2px rgba(139,92,246,0.6), 0 8px 32px rgba(139,92,246,0.25)' : undefined }}
    >
      <Handle type="target" position={Position.Left} className="!bg-violet-400 !border-violet-300 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} className="!bg-violet-400 !border-violet-300 !w-2 !h-2" />
      <div className="px-3 py-2.5">
        <div className="flex items-center gap-2 mb-1">
          <Icon className={`w-3.5 h-3.5 ${style.accent}`} />
          <span className="text-[9px] uppercase tracking-wider text-slate-500 font-mono">{row.kind}</span>
          {ghost && <span className="ml-auto text-[9px] text-slate-500 italic">proposed</span>}
        </div>
        <div className="text-sm font-semibold text-white leading-tight">{row.label}</div>
        {row.description && <div className="text-[10px] text-slate-400 mt-1 line-clamp-2">{row.description}</div>}
        {row.confidence !== null && row.confidence !== undefined && (
          <div className="mt-1.5 flex items-center gap-1">
            <div className="h-1 flex-1 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-violet-400 to-cyan-400" style={{ width: `${Math.round((row.confidence || 0) * 100)}%` }} />
            </div>
            <span className="text-[9px] text-slate-500 font-mono">{Math.round((row.confidence || 0) * 100)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { concept: ConceptNode };

// ── Page ─────────────────────────────────────────────────────────────

export default function AtlasPage() {
  const [graphs, setGraphs] = useState<GraphMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphMeta | null>(null);
  const [nodesData, setNodesData] = useState<AtlasNodeRow[]>([]);
  const [edgesData, setEdgesData] = useState<AtlasEdgeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [nlInput, setNlInput] = useState('');
  const [parsing, setParsing] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [proposedOps, setProposedOps] = useState<any[] | null>(null);
  const [proposedSource, setProposedSource] = useState<'nl' | 'extract' | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotRow[]>([]);
  const [showSnapshots, setShowSnapshots] = useState(false);
  const [model, setModel] = useState('gemini-2.5-pro');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const rfRef = useRef<ReactFlowInstance | null>(null);

  // ─── In-app modal + toast plumbing (replaces native prompt/confirm/alert)
  const [promptState, setPromptState] = useState<{
    open: boolean; title: string; placeholder: string; defaultValue: string;
    confirmLabel: string; resolve: ((v: string | null) => void) | null;
  }>({ open: false, title: '', placeholder: '', defaultValue: '', confirmLabel: 'OK', resolve: null });
  const [confirmState, setConfirmState] = useState<{
    open: boolean; title: string; body: string; danger: boolean;
    confirmLabel: string; resolve: ((v: boolean) => void) | null;
  }>({ open: false, title: '', body: '', danger: false, confirmLabel: 'Confirm', resolve: null });
  const [toasts, setToasts] = useState<Array<{ id: number; kind: 'info' | 'error' | 'success'; text: string }>>([]);

  const askText = useCallback((opts: { title: string; placeholder?: string; defaultValue?: string; confirmLabel?: string }) => {
    return new Promise<string | null>(resolve => {
      setPromptState({
        open: true,
        title: opts.title,
        placeholder: opts.placeholder || '',
        defaultValue: opts.defaultValue || '',
        confirmLabel: opts.confirmLabel || 'OK',
        resolve,
      });
    });
  }, []);

  const askConfirm = useCallback((opts: { title: string; body?: string; danger?: boolean; confirmLabel?: string }) => {
    return new Promise<boolean>(resolve => {
      setConfirmState({
        open: true,
        title: opts.title,
        body: opts.body || '',
        danger: !!opts.danger,
        confirmLabel: opts.confirmLabel || 'Confirm',
        resolve,
      });
    });
  }, []);

  const toast = useCallback((kind: 'info' | 'error' | 'success', text: string) => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, kind, text }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  // ─── Cheat-sheet for novices ──────────────────────────────────────
  const [showCheatSheet, setShowCheatSheet] = useState(false);

  // ─── Phase 2 state ────────────────────────────────────────────────
  const [showStarters, setShowStarters] = useState(false);
  const [starters, setStarters] = useState<Starter[]>([]);
  const [importingKit, setImportingKit] = useState<string | null>(null);
  const [kbList, setKbList] = useState<KBCollection[]>([]);
  const [showKbPicker, setShowKbPicker] = useState(false);
  const [layoutBusy, setLayoutBusy] = useState<string | null>(null);
  const [showQuery, setShowQuery] = useState(false);
  const [queryPatterns, setQueryPatterns] = useState<QueryPattern[]>([{ label_like: '', kind: '' }]);
  const [queryRunning, setQueryRunning] = useState(false);
  const [queryResults, setQueryResults] = useState<QueryMatch[] | null>(null);
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);

  // ─── Load graph list on mount ─────────────────────────────────────
  useEffect(() => {
    void (async () => {
      const r = await apiFetch<any>('/api/atlas/graphs');
      const list = r.data?.graphs || [];
      setGraphs(list);
      if (list.length > 0) setActiveId(list[0].id);
      setLoading(false);
    })();
  }, []);

  // ─── Load full graph when active changes ──────────────────────────
  const reload = useCallback(async (gid: string) => {
    const r = await apiFetch<any>(`/api/atlas/graphs/${gid}`);
    if (r.data) {
      setGraph(r.data.graph);
      setNodesData(r.data.nodes || []);
      setEdgesData(r.data.edges || []);
    }
  }, []);

  useEffect(() => {
    if (!activeId) { setGraph(null); setNodesData([]); setEdgesData([]); return; }
    void reload(activeId);
  }, [activeId, reload]);

  // ─── Suggestions (cheap, deterministic — refresh on any graph change)
  useEffect(() => {
    if (!activeId) { setSuggestions([]); return; }
    void (async () => {
      const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/suggestions`);
      if (r.data?.suggestions) setSuggestions(r.data.suggestions);
    })();
  }, [activeId, graph?.version]);

  // ─── React Flow node/edge derivations ─────────────────────────────
  const rfNodes: RFNode[] = useMemo(() => nodesData.map((n, i) => ({
    id: n.id,
    type: 'concept',
    position: n.position || { x: 80 + (i % 6) * 220, y: 80 + Math.floor(i / 6) * 160 },
    data: { row: n, selected: n.id === selectedNodeId },
    selected: n.id === selectedNodeId,
  })), [nodesData, selectedNodeId]);

  const rfEdges: Edge[] = useMemo(() => edgesData.map(e => ({
    id: e.id,
    source: e.from_node_id,
    target: e.to_node_id,
    label: e.label + (e.cardinality_to ? ` (${e.cardinality_to})` : ''),
    type: 'smoothstep',
    animated: e.source !== 'user',
    style: {
      stroke: e.source !== 'user' ? '#a78bfa' : '#475569',
      strokeWidth: 1.5,
      strokeDasharray: e.source !== 'user' ? '6 3' : undefined,
    },
    labelStyle: { fill: '#cbd5e1', fontSize: 11, fontFamily: 'ui-monospace, monospace' },
    labelBgStyle: { fill: '#0f172a', fillOpacity: 0.85 },
    labelBgPadding: [6, 3],
    labelBgBorderRadius: 4,
    selected: e.id === selectedEdgeId,
  })), [edgesData, selectedEdgeId]);

  // ─── Mutations ────────────────────────────────────────────────────
  const createGraph = async () => {
    const name = await askText({
      title: 'New atlas',
      placeholder: 'e.g. Trade-lifecycle ontology',
      defaultValue: 'Untitled Atlas',
      confirmLabel: 'Create',
    });
    if (name === null) return;
    const finalName = (name || 'Untitled Atlas').trim() || 'Untitled Atlas';
    const r = await apiFetch<any>('/api/atlas/graphs', { method: 'POST', body: JSON.stringify({ name: finalName }) });
    if (r.data?.graph) {
      setGraphs(g => [r.data.graph, ...g]);
      setActiveId(r.data.graph.id);
      toast('success', `Atlas “${finalName}” created`);
    } else {
      toast('error', `Could not create atlas: ${r.error || 'unknown'}`);
    }
  };

  const deleteGraph = async (id: string) => {
    const ok = await askConfirm({
      title: 'Delete this atlas?',
      body: 'All nodes, edges, and snapshots will be removed. This cannot be undone.',
      danger: true,
      confirmLabel: 'Delete atlas',
    });
    if (!ok) return;
    setGraphs(prev => prev.filter(g => g.id !== id));
    if (activeId === id) setActiveId(null);
    const r = await apiFetch(`/api/atlas/graphs/${id}`, { method: 'DELETE' });
    if (r.error) toast('error', `Delete failed: ${r.error}`);
    else toast('success', 'Atlas deleted');
  };

  // Persist node moves on drag-end so the layout survives reload.
  const persistNodePosition = async (nodeId: string, x: number, y: number) => {
    if (!activeId) return;
    await apiFetch(`/api/atlas/graphs/${activeId}/nodes/${nodeId}`, {
      method: 'PATCH', body: JSON.stringify({ position: { x, y } }),
    });
  };

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    // Apply visually first (instant feedback), persist on drag-end.
    setNodesData(prev => {
      let next = prev;
      for (const ch of changes) {
        if (ch.type === 'position' && ch.position) {
          next = next.map(n => n.id === ch.id ? { ...n, position: { x: ch.position!.x, y: ch.position!.y } } : n);
        } else if (ch.type === 'remove') {
          next = next.filter(n => n.id !== ch.id);
        }
      }
      return next;
    });
    for (const ch of changes) {
      if (ch.type === 'position' && !ch.dragging && ch.position) {
        void persistNodePosition(ch.id, ch.position.x, ch.position.y);
      }
    }
  }, [activeId]);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdgesData(prev => prev.filter(e => !changes.some(ch => ch.type === 'remove' && ch.id === e.id)));
  }, []);

  const onConnect = useCallback(async (conn: Connection) => {
    if (!activeId || !conn.source || !conn.target) return;
    const label = await askText({
      title: 'Name this relationship',
      placeholder: 'snake_case verb (e.g. settles_via)',
      defaultValue: 'related_to',
      confirmLabel: 'Create edge',
    });
    if (label === null) return;
    const finalLabel = (label || 'related_to').trim() || 'related_to';
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/edges`, {
      method: 'POST',
      body: JSON.stringify({
        from_node_id: conn.source,
        to_node_id: conn.target,
        label: finalLabel,
        cardinality_from: '1',
        cardinality_to: '*',
      }),
    });
    if (r.data?.edge) {
      setEdgesData(prev => [...prev, r.data.edge]);
      setGraph(g => g ? { ...g, version: r.data.graph?.version || g.version } : g);
    } else {
      toast('error', `Could not create edge: ${r.error || 'unknown'}`);
    }
  }, [activeId, askText, toast]);

  const addNodeAtCenter = async (kind: NodeKind = 'concept') => {
    if (!activeId) return;
    const label = await askText({
      title: `New ${kind}`,
      placeholder: kind === 'concept' ? 'e.g. Counterparty' : kind === 'instance' ? 'e.g. ACME Corp' : 'Label',
      defaultValue: '',
      confirmLabel: 'Create',
    });
    if (label === null) return;
    const finalLabel = (label || '').trim();
    if (!finalLabel) {
      toast('error', 'Label is required');
      return;
    }
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/nodes`, {
      method: 'POST',
      body: JSON.stringify({ label: finalLabel, kind, position: { x: 400, y: 300 } }),
    });
    if (r.data?.node) {
      setNodesData(prev => [...prev, r.data.node]);
      setGraph(g => g ? { ...g, ...r.data.graph } : r.data.graph);
    } else {
      toast('error', `Could not create node: ${r.error || 'unknown'}`);
    }
  };

  const deleteSelected = async () => {
    if (!activeId) return;
    if (selectedNodeId) {
      await apiFetch(`/api/atlas/graphs/${activeId}/nodes/${selectedNodeId}`, { method: 'DELETE' });
      setNodesData(prev => prev.filter(n => n.id !== selectedNodeId));
      setEdgesData(prev => prev.filter(e => e.from_node_id !== selectedNodeId && e.to_node_id !== selectedNodeId));
      setSelectedNodeId(null);
    } else if (selectedEdgeId) {
      await apiFetch(`/api/atlas/graphs/${activeId}/edges/${selectedEdgeId}`, { method: 'DELETE' });
      setEdgesData(prev => prev.filter(e => e.id !== selectedEdgeId));
      setSelectedEdgeId(null);
    }
  };

  const updateSelectedNode = async (patch: Partial<AtlasNodeRow>) => {
    if (!activeId || !selectedNodeId) return;
    const body: any = {};
    if (patch.label !== undefined) body.label = patch.label;
    if (patch.description !== undefined) body.description = patch.description;
    if (patch.kind !== undefined) body.kind = patch.kind;
    if (patch.properties !== undefined) body.properties = patch.properties;
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/nodes/${selectedNodeId}`, {
      method: 'PATCH', body: JSON.stringify(body),
    });
    if (r.data?.node) {
      setNodesData(prev => prev.map(n => n.id === selectedNodeId ? r.data.node : n));
    }
  };

  // ─── Natural-language parsing ────────────────────────────────────
  const submitNl = async () => {
    if (!activeId || !nlInput.trim()) return;
    setParsing(true);
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/parse-nl`, {
      method: 'POST',
      body: JSON.stringify({ text: nlInput, model }),
    });
    setParsing(false);
    if (r.error) {
      toast('error', `Parse failed: ${r.error}`);
      return;
    }
    if (r.data?.ops?.length) {
      setProposedOps(r.data.ops);
      setProposedSource('nl');
    } else {
      toast('info', 'No operations proposed — try rephrasing');
    }
  };

  // ─── Drop-to-extract: any modality → proposed ops ────────────────
  const submitFile = async (file: File) => {
    if (!activeId) return;
    setExtracting(true);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('model', model);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const tok = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const r = await fetch(`${apiUrl}/api/atlas/graphs/${activeId}/extract`, {
        method: 'POST', body: fd, headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      const j = await r.json();
      if (!r.ok || !j.data) throw new Error(j.error?.message || `HTTP ${r.status}`);
      if (j.data.ops?.length) {
        setProposedOps(j.data.ops);
        setProposedSource('extract');
      }
    } catch (e: any) {
      toast('error', `Extract failed: ${e.message}`);
    }
    setExtracting(false);
  };

  // ─── Apply proposed ops atomically ───────────────────────────────
  const applyProposed = async () => {
    if (!activeId || !proposedOps) return;
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/apply`, {
      method: 'POST', body: JSON.stringify({ ops: proposedOps }),
    });
    if (r.data) {
      setNodesData(prev => [...prev, ...(r.data.created_nodes || [])]);
      setEdgesData(prev => [...prev, ...(r.data.created_edges || [])]);
      setGraph(r.data.graph);
      setProposedOps(null);
      setProposedSource(null);
      setNlInput('');
    }
  };

  // ─── Snapshots ───────────────────────────────────────────────────
  const loadSnapshots = async () => {
    if (!activeId) return;
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/snapshots`);
    setSnapshots(r.data?.snapshots || []);
  };

  const captureSnapshot = async () => {
    if (!activeId) return;
    const label = await askText({
      title: 'Capture snapshot',
      placeholder: 'e.g. before importing FIBO',
      defaultValue: 'manual checkpoint',
      confirmLabel: 'Snap',
    });
    if (label === null) return;
    const r = await apiFetch(`/api/atlas/graphs/${activeId}/snapshots`, {
      method: 'POST', body: JSON.stringify({ label: (label || 'manual checkpoint').trim() || 'manual checkpoint' }),
    });
    if (r.error) toast('error', `Snapshot failed: ${r.error}`);
    else toast('success', 'Snapshot captured');
    await loadSnapshots();
  };

  const restoreSnapshot = async (sid: string) => {
    if (!activeId) return;
    const ok = await askConfirm({
      title: 'Restore this snapshot?',
      body: 'Your current state will be auto-saved as a snapshot first, so you can roll back if needed.',
      confirmLabel: 'Restore',
    });
    if (!ok) return;
    const r = await apiFetch(`/api/atlas/graphs/${activeId}/snapshots/${sid}/restore`, { method: 'POST' });
    if (r.error) toast('error', `Restore failed: ${r.error}`);
    else toast('success', 'Snapshot restored');
    await reload(activeId);
    await loadSnapshots();
  };

  // ─── Phase 2: Starters ────────────────────────────────────────────
  const openStarters = async () => {
    setShowStarters(true);
    if (starters.length === 0) {
      const r = await apiFetch<any>('/api/atlas/starters');
      setStarters(r.data?.starters || []);
    }
  };
  const importStarter = async (kitId: string) => {
    if (!activeId) return;
    setImportingKit(kitId);
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/import-starter`, {
      method: 'POST', body: JSON.stringify({ kit: kitId }),
    });
    setImportingKit(null);
    if (r.data) {
      setNodesData(prev => [...prev, ...(r.data.created_nodes || [])]);
      setEdgesData(prev => [...prev, ...(r.data.created_edges || [])]);
      setGraph(r.data.graph);
      setShowStarters(false);
    } else {
      toast('error', `Import failed: ${r.error || 'unknown'}`);
    }
  };

  // ─── Phase 2: KB binding ─────────────────────────────────────────
  const openKbPicker = async () => {
    setShowKbPicker(true);
    if (kbList.length === 0) {
      const r = await apiFetch<any>('/api/knowledge-bases');
      const list = r.data?.knowledge_bases || r.data?.collections || r.data || [];
      setKbList(Array.isArray(list) ? list : []);
    }
  };
  const bindKb = async (kbId: string | null) => {
    if (!activeId) return;
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/bind-kb`, {
      method: 'POST', body: JSON.stringify({ kb_id: kbId }),
    });
    if (r.data?.graph) setGraph(r.data.graph);
    setShowKbPicker(false);
  };
  const projectKb = async () => {
    if (!activeId) return;
    if (!graph?.kb_id) { toast('info', 'Bind to a knowledge collection first.'); return; }
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/sync-kb`, { method: 'POST' });
    if (r.data) {
      setNodesData(prev => [...prev, ...(r.data.created_nodes || [])]);
      setGraph(r.data.graph);
      const n = r.data.imported || 0;
      toast(n > 0 ? 'success' : 'info', n > 0 ? `Imported ${n} document${n === 1 ? '' : 's'} into the canvas` : 'Already in sync');
    } else {
      toast('error', `Sync failed: ${r.error || 'unknown'}`);
    }
  };

  // ─── Phase 2: Layout ─────────────────────────────────────────────
  const relayout = async (mode: 'semantic' | 'circle' | 'grid') => {
    if (!activeId) return;
    setLayoutBusy(mode);
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/relayout`, {
      method: 'POST', body: JSON.stringify({ mode }),
    });
    setLayoutBusy(null);
    if (r.data?.nodes) {
      setNodesData(r.data.nodes);
      setGraph(r.data.graph);
      setTimeout(() => rfRef.current?.fitView({ padding: 0.2, duration: 600 }), 50);
    } else {
      toast('error', `Layout failed: ${r.error || 'unknown'}`);
    }
  };

  // ─── Phase 2: Visual query ───────────────────────────────────────
  const runQuery = async () => {
    if (!activeId) return;
    const cleaned = queryPatterns.filter(p => p.label_like.trim());
    if (cleaned.length === 0) { setQueryResults([]); return; }
    setQueryRunning(true);
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/query`, {
      method: 'POST',
      body: JSON.stringify({
        patterns: cleaned.map(p => ({ label_like: p.label_like, kind: p.kind || undefined })),
        limit: 50,
      }),
    });
    setQueryRunning(false);
    setQueryResults(r.data?.matches || []);
  };

  // ─── Phase 2: Live instances ─────────────────────────────────────
  const loadInstances = useCallback(async (nid: string) => {
    if (!activeId) return;
    setInstancesLoading(true);
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/nodes/${nid}/instances`);
    setInstances(r.data?.instances || []);
    setInstancesLoading(false);
  }, [activeId]);

  useEffect(() => {
    if (selectedNodeId) void loadInstances(selectedNodeId);
    else setInstances([]);
  }, [selectedNodeId, loadInstances]);

  const bindNodeToKb = async (kbId: string) => {
    if (!activeId || !selectedNodeId) return;
    const r = await apiFetch<any>(`/api/atlas/graphs/${activeId}/nodes/${selectedNodeId}/binding`, {
      method: 'PATCH',
      body: JSON.stringify({ binding: { kind: 'kb_collection', ref_id: kbId } }),
    });
    if (r.data?.node) {
      setNodesData(prev => prev.map(n => n.id === selectedNodeId ? r.data.node : n));
      void loadInstances(selectedNodeId);
    }
  };

  // ─── Export ──────────────────────────────────────────────────────
  const exportGraph = async (format: 'json-ld' | 'json' = 'json-ld') => {
    if (!activeId) return;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const tok = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    const r = await fetch(`${apiUrl}/api/atlas/graphs/${activeId}/export?format=${format}`, {
      headers: tok ? { Authorization: `Bearer ${tok}` } : {},
    });
    if (!r.ok) { toast('error', 'Export failed'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${graph?.name || 'atlas'}.${format === 'json-ld' ? 'jsonld' : 'json'}`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // ─── Drag-drop handlers (file onto canvas) ───────────────────────
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (e.dataTransfer.types.includes('Files')) setDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void submitFile(f);
  };

  const selectedNode = useMemo(() => nodesData.find(n => n.id === selectedNodeId) || null, [nodesData, selectedNodeId]);

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#0B0F19] flex">
      {/* ── Left rail: graph list ─────────────────────────────────── */}
      <aside className="w-64 border-r border-slate-800/50 flex flex-col shrink-0">
        <div className="p-4 border-b border-slate-800/50">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center">
              <Network className="w-4 h-4 text-violet-300" />
            </div>
            <div>
              <p className="text-sm font-bold text-white leading-none">Atlas</p>
              <p className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Ontology · KB Canvas</p>
            </div>
          </div>
          <button
            onClick={createGraph}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-violet-500/15 border border-violet-500/40 text-violet-200 hover:bg-violet-500/25 text-xs font-semibold"
          >
            <Plus className="w-3.5 h-3.5" /> New atlas
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loading && <div className="text-center py-6"><Loader2 className="w-4 h-4 text-violet-400 animate-spin mx-auto" /></div>}
          {!loading && graphs.length === 0 && (
            <div className="text-center py-8 text-[11px] text-slate-600">
              <Network className="w-6 h-6 mx-auto mb-2 text-slate-700" />
              No atlases yet
            </div>
          )}
          {graphs.map(g => (
            <div
              key={g.id}
              onClick={() => setActiveId(g.id)}
              className={`group rounded-lg p-2 cursor-pointer transition-colors mb-1 ${
                activeId === g.id ? 'bg-violet-500/10 border border-violet-500/30' : 'hover:bg-slate-800/40 border border-transparent'
              }`}
            >
              <div className="flex items-start justify-between gap-1">
                <p className="text-[12px] text-slate-200 truncate flex-1" title={g.name}>{g.name}</p>
                <button onClick={e => { e.stopPropagation(); void deleteGraph(g.id); }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-rose-400">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              <p className="text-[10px] text-slate-500 mt-0.5">{g.node_count} nodes · {g.edge_count} edges</p>
              <p className="text-[9px] text-slate-600">v{g.version} · {g.updated_at ? new Date(g.updated_at).toLocaleDateString() : ''}</p>
            </div>
          ))}
        </div>
      </aside>

      {/* ── Canvas + overlays ─────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 relative">
        <header className="border-b border-slate-800/50 px-6 py-3">
          {/* Title row — title + counts kept on one line, never wraps */}
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1 flex items-center gap-3 flex-wrap">
              <h1 className="text-base font-bold text-white flex items-center gap-2 min-w-0">
                <Network className="w-4 h-4 text-violet-300 shrink-0" />
                <span className="truncate">{graph?.name || (activeId ? 'Loading…' : 'Pick or create an atlas →')}</span>
              </h1>
              {graph && (
                <div className="flex items-center gap-1.5 text-[11px] text-slate-400 whitespace-nowrap">
                  <span className="px-1.5 py-0.5 rounded bg-slate-800/80 border border-slate-700/50 font-mono">v{graph.version}</span>
                  <span className="text-slate-600">·</span>
                  <span><span className="text-slate-200 font-semibold">{graph.node_count}</span> nodes</span>
                  <span className="text-slate-600">·</span>
                  <span><span className="text-slate-200 font-semibold">{graph.edge_count}</span> edges</span>
                  {graph.kb_id && (
                    <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/10 border border-emerald-500/40 text-emerald-200 inline-flex items-center gap-1">
                      <Link2 className="w-2.5 h-2.5" /> KB linked
                    </span>
                  )}
                </div>
              )}
            </div>
            {graph && (
              <select
                value={model} onChange={e => setModel(e.target.value)}
                className="bg-slate-800/60 border border-slate-700 rounded-lg text-[11px] text-slate-200 px-2 py-1.5 shrink-0"
                title="LLM used for natural-language parsing and extraction"
              >
                <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                <option value="claude-sonnet-4-5-20250929">Claude Sonnet 4.5</option>
                <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o-mini</option>
              </select>
            )}
          </div>
          {/* Toolbar row — wraps on narrow screens instead of overflowing */}
          {graph && (
            <div className="mt-3 flex items-center gap-1.5 flex-wrap">
              <ToolbarGroup label="Add">
                <ToolbarBtn onClick={() => addNodeAtCenter('concept')} icon={Plus} accent="violet">Concept</ToolbarBtn>
                <ToolbarBtn onClick={() => addNodeAtCenter('instance')} icon={Database} accent="emerald">Instance</ToolbarBtn>
              </ToolbarGroup>
              <ToolbarGroup label="Ingest">
                <ToolbarBtn onClick={() => fileInputRef.current?.click()} icon={Upload} accent="amber">Drop file</ToolbarBtn>
                <ToolbarBtn onClick={openStarters} icon={LibraryBig} accent="cyan">Starters</ToolbarBtn>
              </ToolbarGroup>
              <ToolbarGroup label="Knowledge">
                <ToolbarBtn onClick={openKbPicker} icon={Link2} accent="emerald" active={!!graph.kb_id}>
                  {graph.kb_id ? 'KB linked' : 'Bind KB'}
                </ToolbarBtn>
                {graph.kb_id && (
                  <ToolbarBtn onClick={() => void projectKb()} icon={ScanLine} accent="emerald">Project KB</ToolbarBtn>
                )}
              </ToolbarGroup>
              <ToolbarGroup label="Explore">
                <ToolbarBtn onClick={() => setShowQuery(s => !s)} icon={Search} accent="violet" active={showQuery}>Query</ToolbarBtn>
                <div className="inline-flex items-center bg-slate-800/60 border border-slate-700 rounded-lg overflow-hidden">
                  <ToolbarIcon onClick={() => relayout('semantic')} icon={layoutBusy === 'semantic' ? Loader2 : Compass} spinning={layoutBusy === 'semantic'} title="Semantic layout (embedding-aware)" />
                  <ToolbarIcon onClick={() => relayout('circle')} icon={layoutBusy === 'circle' ? Loader2 : CircleDot} spinning={layoutBusy === 'circle'} title="Circular layout" />
                  <ToolbarIcon onClick={() => relayout('grid')} icon={layoutBusy === 'grid' ? Loader2 : Grid3x3} spinning={layoutBusy === 'grid'} title="Grid layout" />
                </div>
              </ToolbarGroup>
              <ToolbarGroup label="Time">
                <ToolbarBtn onClick={() => { void captureSnapshot(); }} icon={Save}>Snap</ToolbarBtn>
                <ToolbarBtn onClick={() => { void loadSnapshots(); setShowSnapshots(true); }} icon={History}>History</ToolbarBtn>
              </ToolbarGroup>
              <ToolbarGroup label="Export">
                <ToolbarBtn onClick={() => exportGraph('json-ld')} icon={Download}>JSON-LD</ToolbarBtn>
              </ToolbarGroup>
              <ToolbarGroup label="Help">
                <ToolbarBtn onClick={() => setShowCheatSheet(true)} icon={HelpCircle}>How do I…?</ToolbarBtn>
              </ToolbarGroup>
              <input ref={fileInputRef} type="file" className="hidden"
                accept="application/pdf,image/*,audio/*,video/*,.docx,.txt,.md,.csv,text/plain,text/markdown,text/csv"
                onChange={e => e.target.files && submitFile(e.target.files[0])} />
            </div>
          )}
        </header>

        {!activeId && (
          <div className="flex-1 flex items-center justify-center p-12">
            <div className="text-center max-w-lg">
              <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 border border-violet-500/30 flex items-center justify-center">
                <Network className="w-10 h-10 text-violet-300" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">Build an ontology that lives</h2>
              <p className="text-sm text-slate-400 mb-6">
                Drop any artefact, type a sentence, draw a relationship — Atlas keeps the schema and the source documents fused as one graph. The agent watches over your shoulder for missing inverses, duplicates, and orphans.
              </p>
              <button onClick={createGraph} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white font-semibold hover:shadow-lg hover:shadow-violet-500/30">
                <Plus className="w-4 h-4" /> Create your first atlas
              </button>
            </div>
          </div>
        )}

        {activeId && (
          <>
            <div
              className="flex-1 relative"
              onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
              onKeyDown={(e) => { if ((e.key === 'Backspace' || e.key === 'Delete') && (selectedNodeId || selectedEdgeId)) deleteSelected(); }}
              tabIndex={0}
            >
              <ReactFlow
                nodes={rfNodes}
                edges={rfEdges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(_, n) => { setSelectedNodeId(n.id); setSelectedEdgeId(null); }}
                onEdgeClick={(_, e) => { setSelectedEdgeId(e.id); setSelectedNodeId(null); }}
                onPaneClick={() => { setSelectedNodeId(null); setSelectedEdgeId(null); }}
                onInit={(inst) => { rfRef.current = inst; setTimeout(() => inst.fitView({ padding: 0.2, duration: 400 }), 50); }}
                fitView
                proOptions={{ hideAttribution: true }}
              >
                <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1e293b" />
                {/* Hide MiniMap + Controls when the canvas is empty —
                    they collide with the onboarding panel and aren't
                    useful with no nodes to navigate. */}
                {nodesData.length > 0 && (
                  <>
                    <Controls className="!bg-slate-900/80 !border-slate-700" />
                    <MiniMap
                      className="!bg-slate-900/80 !border-slate-700"
                      nodeColor={(n) => {
                        const k = (n.data as any)?.row?.kind as NodeKind | undefined;
                        return k === 'instance' ? '#10B981' : k === 'document' ? '#F59E0B' : k === 'property' ? '#06B6D4' : '#A855F7';
                      }}
                    />
                  </>
                )}
              </ReactFlow>

              {/* Empty-canvas onboarding — shows the four concrete first
                  actions a brand-new user can take. Disappears as soon
                  as the first node lands. */}
              {nodesData.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none px-6 py-8 overflow-y-auto">
                  <motion.div
                    initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                    className="pointer-events-auto max-w-3xl w-full my-auto"
                  >
                    <div className="text-center mb-6">
                      <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center">
                        <Sparkles className="w-6 h-6 text-violet-200" />
                      </div>
                      <h2 className="text-lg font-bold text-white">Your atlas is empty — let's fill it</h2>
                      <p className="text-sm text-slate-400 mt-1.5">Pick any of the four ways to begin. They all work together; you can mix and match later.</p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <OnboardCard
                        icon={LibraryBig}
                        title="Start from a template"
                        body="Pick a curated starter ontology — FIBO, FIX, EMIR, ISDA, or ETRM EOD — drops a ready-made graph onto the canvas in a single click."
                        cta="Browse starters"
                        accent="cyan"
                        onClick={openStarters}
                      />
                      <OnboardCard
                        icon={Upload}
                        title="Drop a document"
                        body="Drag a PDF, image, audio, video, DOCX, or text file onto the canvas. Atlas extracts entities and relationships and shows them as a reviewable proposal."
                        cta="Pick a file"
                        accent="amber"
                        onClick={() => fileInputRef.current?.click()}
                      />
                      <OnboardCard
                        icon={Wand2}
                        title="Type a sentence"
                        body='Use the bar at the bottom — e.g. "Counterparty has many Trades. Each Trade settles via exactly one SSI." — and we’ll convert it into nodes and edges.'
                        cta="Focus the input"
                        accent="violet"
                        onClick={() => {
                          const el = document.querySelector<HTMLInputElement>('input[data-atlas-nl]');
                          el?.focus();
                        }}
                      />
                      <OnboardCard
                        icon={Plus}
                        title="Draw it yourself"
                        body="Add concepts and instances by hand, then drag from the right edge of one to the left edge of another to create relationships."
                        cta="Add a concept"
                        accent="emerald"
                        onClick={() => addNodeAtCenter('concept')}
                      />
                    </div>
                    {graph?.kb_id ? (
                      <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 flex items-center gap-3">
                        <Link2 className="w-4 h-4 text-emerald-300 shrink-0" />
                        <p className="text-[12px] text-emerald-100 flex-1">This atlas is bound to a KB. Click <strong>Project KB</strong> to pull the documents you already have onto the canvas.</p>
                        <button onClick={() => void projectKb()} className="px-2.5 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 text-xs font-semibold inline-flex items-center gap-1.5">
                          <ScanLine className="w-3 h-3" /> Project KB
                        </button>
                      </div>
                    ) : (
                      <div className="mt-4 rounded-xl border border-slate-700 bg-slate-800/30 p-3 flex items-center gap-3">
                        <Link2 className="w-4 h-4 text-slate-400 shrink-0" />
                        <p className="text-[12px] text-slate-400 flex-1">Optionally bind to a knowledge collection — extracted documents will be persisted there so every agent can query them.</p>
                        <button onClick={openKbPicker} className="px-2.5 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700 hover:border-emerald-500/50 text-slate-200 text-xs font-semibold inline-flex items-center gap-1.5">
                          <Link2 className="w-3 h-3" /> Bind KB
                        </button>
                      </div>
                    )}
                  </motion.div>
                </div>
              )}

              {/* Drop overlay */}
              <AnimatePresence>
                {dragOver && (
                  <motion.div
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    className="absolute inset-4 rounded-2xl border-2 border-dashed border-violet-400/60 bg-violet-500/10 backdrop-blur-sm pointer-events-none flex items-center justify-center"
                  >
                    <div className="text-center">
                      <Upload className="w-10 h-10 text-violet-300 mx-auto mb-2" />
                      <p className="text-violet-200 font-semibold">Drop to extract ontology</p>
                      <p className="text-xs text-violet-300/70 mt-1">PDF · image · audio · video · DOCX · text</p>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Suggestions ghost-cursor card (top-right) */}
              {suggestions.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                  className="absolute top-4 right-4 w-72 rounded-xl border border-violet-500/30 bg-slate-900/90 backdrop-blur-md shadow-xl"
                >
                  <div className="px-3 py-2 border-b border-slate-800/60 flex items-center gap-2">
                    <div className="w-6 h-6 rounded bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center">
                      <Lightbulb className="w-3.5 h-3.5 text-white" />
                    </div>
                    <p className="text-xs font-semibold text-white flex-1">Atlas Agent</p>
                    <span className="text-[10px] text-slate-500">{suggestions.length} note{suggestions.length === 1 ? '' : 's'}</span>
                  </div>
                  <div className="max-h-72 overflow-y-auto p-2 space-y-1.5">
                    {suggestions.slice(0, 8).map((s, i) => (
                      <div key={i} className={`rounded-lg p-2 border ${
                        s.severity === 'warning' ? 'bg-amber-500/5 border-amber-500/30' :
                        s.severity === 'error'   ? 'bg-rose-500/5 border-rose-500/30' :
                                                    'bg-slate-800/40 border-slate-700/40'
                      }`}>
                        <div className="flex items-start gap-1.5">
                          {s.severity === 'warning' ? <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                            : s.severity === 'error' ? <AlertTriangle className="w-3 h-3 text-rose-400 mt-0.5 shrink-0" />
                            : <Info className="w-3 h-3 text-violet-400 mt-0.5 shrink-0" />}
                          <p className="text-[11px] text-slate-200 leading-snug font-medium">{s.title}</p>
                        </div>
                        <p className="text-[10px] text-slate-500 mt-1 ml-4 leading-snug">{s.detail}</p>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}

              {/* Snapshots panel (slides in) */}
              <AnimatePresence>
                {showSnapshots && (
                  <motion.div
                    initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
                    className="absolute bottom-20 right-4 w-80 max-h-96 rounded-xl border border-violet-500/30 bg-slate-900/95 backdrop-blur-md shadow-xl overflow-hidden flex flex-col"
                  >
                    <div className="px-3 py-2 border-b border-slate-800/60 flex items-center gap-2">
                      <History className="w-3.5 h-3.5 text-violet-300" />
                      <p className="text-xs font-semibold text-white flex-1">Time slider</p>
                      <button onClick={() => setShowSnapshots(false)} className="p-0.5 text-slate-500 hover:text-white">
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-2">
                      {snapshots.length === 0 && <p className="text-[11px] text-slate-500 p-4 text-center">No snapshots yet</p>}
                      {snapshots.map(s => (
                        <button key={s.id} onClick={() => restoreSnapshot(s.id)}
                          className="w-full text-left rounded-lg p-2 hover:bg-slate-800/50 transition-colors mb-1 group">
                          <div className="flex items-center gap-2">
                            <RotateCcw className="w-3 h-3 text-slate-500 group-hover:text-violet-400" />
                            <span className="text-[11px] text-slate-200 flex-1">v{s.version}</span>
                            {!s.auto && <span className="text-[9px] text-violet-300 bg-violet-500/20 px-1 rounded">manual</span>}
                          </div>
                          <p className="text-[10px] text-slate-500 mt-0.5 ml-5">{s.label || 'auto-snapshot'}</p>
                          <p className="text-[9px] text-slate-600 mt-0.5 ml-5">{s.created_at ? new Date(s.created_at).toLocaleString() : ''}</p>
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Proposed-ops review ribbon */}
              <AnimatePresence>
                {proposedOps && (
                  <motion.div
                    initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
                    className="absolute bottom-16 left-1/2 -translate-x-1/2 w-[640px] max-w-[90%] rounded-xl border border-violet-500/40 bg-slate-900/95 backdrop-blur-md shadow-2xl shadow-violet-500/20 overflow-hidden"
                  >
                    <div className="px-4 py-2.5 bg-gradient-to-r from-violet-500/20 to-cyan-500/15 border-b border-violet-500/30 flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-violet-300" />
                      <p className="text-xs font-semibold text-white flex-1">
                        {proposedSource === 'extract' ? 'Extracted ontology fragment' : 'Parsed sentence'} · {proposedOps.length} operation{proposedOps.length === 1 ? '' : 's'}
                      </p>
                      <button onClick={() => { setProposedOps(null); setProposedSource(null); }} className="p-1 text-slate-500 hover:text-white">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="max-h-48 overflow-y-auto p-2 space-y-1">
                      {proposedOps.map((op, i) => (
                        <div key={i} className="text-[11px] font-mono text-slate-300 px-2 py-1 rounded bg-slate-800/40 flex items-center gap-2">
                          {op.op === 'add_node' ? <Box className="w-3 h-3 text-violet-400" /> : <ArrowRight className="w-3 h-3 text-cyan-400" />}
                          <span className="text-slate-500">{op.op}</span>
                          {op.op === 'add_node' && <span className="text-white">{op.label}</span>}
                          {op.op === 'add_edge' && <span><span className="text-emerald-300">{op.from}</span> <span className="text-violet-300">·{op.label}·</span> <span className="text-emerald-300">{op.to}</span></span>}
                          {op.confidence !== undefined && op.confidence !== null && (
                            <span className="ml-auto text-slate-500">{Math.round((op.confidence || 0) * 100)}%</span>
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="px-3 py-2 border-t border-slate-800/60 flex items-center justify-end gap-2">
                      <button onClick={() => { setProposedOps(null); setProposedSource(null); }}
                        className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 text-xs hover:text-white">Discard</button>
                      <button onClick={applyProposed}
                        className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-xs font-semibold inline-flex items-center gap-1.5">
                        <Check className="w-3 h-3" /> Apply all
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* NL bar */}
            <div className="border-t border-slate-800/50 px-6 py-3 flex items-center gap-2">
              <Wand2 className="w-4 h-4 text-violet-400 shrink-0" />
              <input
                data-atlas-nl
                value={nlInput}
                onChange={e => setNlInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !parsing && submitNl()}
                placeholder='Describe a relationship — e.g. "Counterparty has many Trades."'
                className="flex-1 bg-slate-800/40 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                disabled={parsing || extracting}
              />
              <button onClick={submitNl} disabled={parsing || !nlInput.trim()}
                className="px-3 py-2 rounded-lg bg-violet-500/20 border border-violet-500/40 text-violet-200 hover:bg-violet-500/30 text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50">
                {parsing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                {parsing ? 'Parsing…' : 'Add to atlas'}
              </button>
              {extracting && <span className="text-[11px] text-amber-300 inline-flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" /> Extracting…</span>}
            </div>
            {/* Example chips — clicking pastes the sentence into the NL input */}
            <div className="px-6 pb-2 flex items-center gap-1.5 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-slate-600 mr-1">Try:</span>
              {[
                'Counterparty has many Trades. Each Trade settles via exactly one SSI.',
                'Customer has many Orders. Each Order has one ShippingAddress.',
                'Process consists of Steps. Each Step has an Owner and a Duration.',
              ].map((ex, i) => (
                <button key={i} onClick={() => setNlInput(ex)}
                  className="px-2 py-0.5 rounded-full text-[10px] bg-slate-800/40 border border-slate-700 hover:border-violet-500/40 hover:text-violet-200 text-slate-400 transition-colors max-w-md truncate" title={ex}>
                  {ex.slice(0, 50)}…
                </button>
              ))}
            </div>
          </>
        )}
      </main>

      {/* ── Phase 2 modals + slide-ins ──────────────────────────── */}
      <AnimatePresence>
        {showStarters && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
            onClick={() => setShowStarters(false)}
          >
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
              onClick={e => e.stopPropagation()}
              className="bg-[#0B0F19] border border-violet-500/40 rounded-2xl w-full max-w-2xl shadow-2xl shadow-violet-500/20 overflow-hidden"
            >
              <header className="px-5 py-4 border-b border-slate-800/60 bg-gradient-to-r from-violet-500/10 to-cyan-500/10 flex items-center gap-2">
                <LibraryBig className="w-4 h-4 text-violet-300" />
                <h3 className="text-base font-bold text-white flex-1">Starter ontologies</h3>
                <button onClick={() => setShowStarters(false)} className="p-1 text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
              </header>
              <div className="p-4 max-h-[60vh] overflow-y-auto space-y-2">
                {starters.length === 0 && <div className="text-center py-8 text-slate-500"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></div>}
                {starters.map(s => (
                  <div key={s.id} className="rounded-xl border border-slate-700 hover:border-violet-500/50 bg-slate-900/40 p-4 flex items-start gap-3 transition-colors">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center shrink-0">
                      <LibraryBig className="w-5 h-5 text-violet-300" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-white">{s.name}</p>
                      <p className="text-xs text-slate-400 mt-0.5">{s.description}</p>
                      <p className="text-[10px] text-slate-600 mt-1 font-mono">{s.node_count} nodes · {s.edge_count} edges</p>
                    </div>
                    <button onClick={() => importStarter(s.id)} disabled={!!importingKit}
                      className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50 shrink-0">
                      {importingKit === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                      Import
                    </button>
                  </div>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}

        {showKbPicker && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
            onClick={() => setShowKbPicker(false)}
          >
            <motion.div
              initial={{ scale: 0.96 }} animate={{ scale: 1 }} exit={{ scale: 0.96 }}
              onClick={e => e.stopPropagation()}
              className="bg-[#0B0F19] border border-emerald-500/40 rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden"
            >
              <header className="px-5 py-4 border-b border-slate-800/60 bg-gradient-to-r from-emerald-500/10 to-cyan-500/10 flex items-center gap-2">
                <Link2 className="w-4 h-4 text-emerald-300" />
                <h3 className="text-base font-bold text-white flex-1">Bind to knowledge collection</h3>
                <button onClick={() => setShowKbPicker(false)} className="p-1 text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
              </header>
              <div className="p-4 max-h-[60vh] overflow-y-auto space-y-1">
                <button onClick={() => bindKb(null)}
                  className={`w-full text-left rounded-lg p-3 border transition-colors ${graph?.kb_id == null ? 'bg-emerald-500/10 border-emerald-500/40' : 'bg-slate-900/40 border-slate-700 hover:border-emerald-500/40'}`}>
                  <p className="text-sm text-slate-200 font-medium">— None —</p>
                  <p className="text-[11px] text-slate-500 mt-0.5">Standalone graph (no KB write-back)</p>
                </button>
                {kbList.length === 0 && <div className="text-center py-8 text-slate-500 text-xs"><Loader2 className="w-3.5 h-3.5 animate-spin mx-auto mb-2" /> Loading…</div>}
                {kbList.map(kb => (
                  <button key={kb.id} onClick={() => bindKb(kb.id)}
                    className={`w-full text-left rounded-lg p-3 border transition-colors ${graph?.kb_id === kb.id ? 'bg-emerald-500/10 border-emerald-500/40' : 'bg-slate-900/40 border-slate-700 hover:border-emerald-500/40'}`}>
                    <div className="flex items-start gap-2">
                      <Database className="w-3.5 h-3.5 text-emerald-300 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-200 font-medium">{kb.name}</p>
                        {kb.description && <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-1">{kb.description}</p>}
                        <p className="text-[10px] text-slate-600 mt-0.5">{kb.doc_count || 0} docs</p>
                      </div>
                      {graph?.kb_id === kb.id && <Check className="w-4 h-4 text-emerald-400" />}
                    </div>
                  </button>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Visual query panel (slides up from bottom-left) */}
      <AnimatePresence>
        {showQuery && activeId && (
          <motion.div
            initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 30 }}
            className="fixed bottom-20 left-72 w-[440px] max-h-[60vh] z-30 rounded-xl border border-violet-500/40 bg-slate-900/95 backdrop-blur-md shadow-2xl shadow-violet-500/20 overflow-hidden flex flex-col"
          >
            <header className="px-3 py-2 border-b border-slate-800/60 bg-gradient-to-r from-violet-500/10 to-cyan-500/10 flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-violet-300" />
              <p className="text-xs font-semibold text-white flex-1">Visual query</p>
              <button onClick={() => setShowQuery(false)} className="p-1 text-slate-500 hover:text-white"><X className="w-3.5 h-3.5" /></button>
            </header>
            <div className="p-3 space-y-2 border-b border-slate-800/60">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Patterns</p>
              {queryPatterns.map((p, i) => (
                <div key={i} className="flex gap-1.5">
                  <input
                    value={p.label_like}
                    onChange={e => setQueryPatterns(prev => prev.map((q, j) => j === i ? { ...q, label_like: e.target.value } : q))}
                    placeholder="Label contains…"
                    className="flex-1 bg-slate-800/40 border border-slate-700 rounded px-2 py-1 text-xs text-white placeholder-slate-500"
                  />
                  <select
                    value={p.kind || ''}
                    onChange={e => setQueryPatterns(prev => prev.map((q, j) => j === i ? { ...q, kind: e.target.value as any } : q))}
                    className="bg-slate-800/40 border border-slate-700 rounded text-[11px] text-slate-300 px-1"
                  >
                    <option value="">any</option>
                    <option value="concept">concept</option>
                    <option value="instance">instance</option>
                    <option value="document">document</option>
                    <option value="property">property</option>
                  </select>
                  {queryPatterns.length > 1 && (
                    <button onClick={() => setQueryPatterns(prev => prev.filter((_, j) => j !== i))}
                      className="px-1.5 text-slate-500 hover:text-rose-400"><Trash2 className="w-3 h-3" /></button>
                  )}
                </div>
              ))}
              <div className="flex justify-between">
                <button onClick={() => setQueryPatterns(prev => [...prev, { label_like: '', kind: '' }])}
                  className="text-[11px] text-violet-300 hover:text-violet-200 inline-flex items-center gap-1"><Plus className="w-3 h-3" /> add pattern</button>
                <button onClick={runQuery} disabled={queryRunning}
                  className="px-3 py-1 rounded bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-xs font-semibold inline-flex items-center gap-1 disabled:opacity-50">
                  {queryRunning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />} Run
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {queryResults === null && <p className="text-[11px] text-slate-500 p-4 text-center">Type a label to search</p>}
              {queryResults?.length === 0 && <p className="text-[11px] text-slate-500 p-4 text-center">No matches</p>}
              {queryResults?.map((m, i) => (
                <div key={i} className="rounded-lg bg-slate-800/40 border border-slate-700/40 p-2 mb-1">
                  <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">match {i + 1}</p>
                  {m.nodes.map((n, j) => (
                    <button key={j} onClick={() => { setSelectedNodeId(n.id); rfRef.current?.setCenter(n.position?.x || 400, n.position?.y || 300, { zoom: 1.2, duration: 600 }); }}
                      className="block text-[11px] text-slate-200 hover:text-violet-300 text-left">
                      • {n.label} <span className="text-slate-500">({n.kind})</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Right rail: multi-lens inspector ──────────────────────── */}
      {activeId && (
        <aside className="w-80 border-l border-slate-800/50 flex flex-col shrink-0 bg-slate-950/40">
          <div className="px-4 py-3 border-b border-slate-800/50 flex items-center gap-2">
            <Eye className="w-3.5 h-3.5 text-violet-300" />
            <p className="text-xs font-semibold text-white">Inspector</p>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {!selectedNode && !selectedEdgeId && (
              <div className="text-center py-8 text-[11px] text-slate-600">
                <Layers className="w-6 h-6 mx-auto mb-2 text-slate-700" />
                Click a node or edge to inspect
              </div>
            )}
            {selectedNode && <NodeInspector
              node={selectedNode}
              edges={edgesData.filter(e => e.from_node_id === selectedNode.id || e.to_node_id === selectedNode.id)}
              allNodes={nodesData}
              instances={instances}
              instancesLoading={instancesLoading}
              kbList={kbList}
              onLoadKbs={openKbPicker}
              onBindKb={bindNodeToKb}
              onUpdate={updateSelectedNode}
              onDelete={deleteSelected}
            />}
          </div>
        </aside>
      )}

      {/* ── In-app prompt modal (replaces native window.prompt) ─── */}
      <AnimatePresence>
        {promptState.open && (
          <PromptModal
            title={promptState.title}
            placeholder={promptState.placeholder}
            defaultValue={promptState.defaultValue}
            confirmLabel={promptState.confirmLabel}
            onCancel={() => {
              promptState.resolve?.(null);
              setPromptState(p => ({ ...p, open: false, resolve: null }));
            }}
            onConfirm={(value) => {
              promptState.resolve?.(value);
              setPromptState(p => ({ ...p, open: false, resolve: null }));
            }}
          />
        )}
      </AnimatePresence>

      {/* ── In-app confirm modal (replaces native window.confirm) ─ */}
      <AnimatePresence>
        {confirmState.open && (
          <ConfirmModal
            title={confirmState.title}
            body={confirmState.body}
            danger={confirmState.danger}
            confirmLabel={confirmState.confirmLabel}
            onCancel={() => {
              confirmState.resolve?.(false);
              setConfirmState(c => ({ ...c, open: false, resolve: null }));
            }}
            onConfirm={() => {
              confirmState.resolve?.(true);
              setConfirmState(c => ({ ...c, open: false, resolve: null }));
            }}
          />
        )}
      </AnimatePresence>

      {/* ── Cheat sheet modal (the on-screen "?" novice helper) ── */}
      <AnimatePresence>
        {showCheatSheet && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
            onClick={() => setShowCheatSheet(false)}
          >
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
              onClick={e => e.stopPropagation()}
              className="bg-[#0B0F19] border border-violet-500/40 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-y-auto shadow-2xl shadow-violet-500/20"
            >
              <header className="px-5 py-4 border-b border-slate-800/60 bg-gradient-to-r from-violet-500/10 to-cyan-500/10 flex items-center gap-2">
                <HelpCircle className="w-4 h-4 text-violet-300" />
                <h3 className="text-base font-bold text-white flex-1">Atlas — Cheat sheet</h3>
                <button onClick={() => setShowCheatSheet(false)} className="p-1 text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
              </header>
              <div className="p-5 space-y-4 text-[12.5px] text-slate-300 leading-relaxed">
                <p className="text-slate-400">Atlas is an ontology + knowledge-base canvas. Documents and concepts share one graph. Pick any of the four ways to build it — they all combine.</p>

                <section>
                  <p className="text-[10px] uppercase tracking-wider text-violet-300 font-bold mb-2">Five ways to fill the canvas</p>
                  <ul className="space-y-1.5">
                    <li className="flex gap-2"><LibraryBig className="w-3.5 h-3.5 text-cyan-300 mt-0.5 shrink-0" /><span><strong className="text-white">Starters</strong> — pick a curated kit (FIBO, FIX, EMIR, ISDA, ETRM EOD); a ready-made graph drops onto the canvas in one click.</span></li>
                    <li className="flex gap-2"><Upload className="w-3.5 h-3.5 text-amber-300 mt-0.5 shrink-0" /><span><strong className="text-white">Drop a file</strong> — drag any PDF, image, audio, video, DOCX or text onto the canvas. Atlas extracts entities + relationships and shows them as a reviewable proposal.</span></li>
                    <li className="flex gap-2"><Wand2 className="w-3.5 h-3.5 text-violet-300 mt-0.5 shrink-0" /><span><strong className="text-white">Type a sentence</strong> — the NL bar at the bottom converts plain English into structured ops. Try the example chips below it.</span></li>
                    <li className="flex gap-2"><Plus className="w-3.5 h-3.5 text-emerald-300 mt-0.5 shrink-0" /><span><strong className="text-white">Draw it</strong> — click <em>Concept</em> or <em>Instance</em> in the toolbar. Drag from the right edge of one node to the left edge of another to make a relationship.</span></li>
                    <li className="flex gap-2"><Link2 className="w-3.5 h-3.5 text-emerald-300 mt-0.5 shrink-0" /><span><strong className="text-white">Bind a KB</strong> — link the graph to a knowledge collection so existing documents project as nodes and dropped files round-trip into the KB.</span></li>
                  </ul>
                </section>

                <section>
                  <p className="text-[10px] uppercase tracking-wider text-violet-300 font-bold mb-2">Canvas shortcuts</p>
                  <ul className="space-y-1 text-[12px]">
                    <li>• Click a node → inspect on the right rail (Schema / Relations / Properties / Instances / Lineage tabs).</li>
                    <li>• Drag from a node's right handle to another node's left handle → create an edge (you'll be prompted for the verb).</li>
                    <li>• Press <kbd className="px-1 rounded bg-slate-800 border border-slate-700 text-[10px]">Backspace</kbd> or <kbd className="px-1 rounded bg-slate-800 border border-slate-700 text-[10px]">Delete</kbd> with a node or edge selected to remove it.</li>
                    <li>• Layout toolbar: <Compass className="inline w-3 h-3 text-violet-300" /> semantic (embedding clusters), <CircleDot className="inline w-3 h-3 text-violet-300" /> circle, <Grid3x3 className="inline w-3 h-3 text-violet-300" /> grid.</li>
                    <li>• <Save className="inline w-3 h-3" /> Snap captures a checkpoint; <History className="inline w-3 h-3" /> History restores any past state.</li>
                  </ul>
                </section>

                <section>
                  <p className="text-[10px] uppercase tracking-wider text-violet-300 font-bold mb-2">For agents</p>
                  <p>Four tools let agents read this graph: <code className="text-cyan-300">atlas_describe</code>, <code className="text-cyan-300">atlas_query</code>, <code className="text-cyan-300">atlas_traverse</code>, <code className="text-cyan-300">atlas_search_grounded</code>. Attach them to any agent; pin it to specific atlases via <code className="text-cyan-300">model_config.atlas_graphs</code> for tenant isolation across multiple domain ontologies.</p>
                </section>

                <section>
                  <p className="text-[10px] uppercase tracking-wider text-violet-300 font-bold mb-2">Read more</p>
                  <a href="/help#atlas" className="text-violet-300 hover:text-violet-200 underline text-[12px]">Full Atlas guide in /help →</a>
                </section>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Toast stack (replaces native window.alert) ──────────── */}
      <div className="fixed bottom-6 right-6 z-[60] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }}
              className={`pointer-events-auto rounded-xl border px-4 py-3 shadow-2xl backdrop-blur-md text-[13px] flex items-start gap-2.5 max-w-sm ${
                t.kind === 'error' ? 'bg-rose-500/15 border-rose-500/40 text-rose-100' :
                t.kind === 'success' ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-100' :
                                       'bg-slate-800/90 border-slate-700 text-slate-100'
              }`}
            >
              {t.kind === 'error' ? <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> :
               t.kind === 'success' ? <Check className="w-4 h-4 mt-0.5 shrink-0" /> :
                                       <Info className="w-4 h-4 mt-0.5 shrink-0" />}
              <span className="flex-1 leading-snug">{t.text}</span>
              <button onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))} className="text-slate-500 hover:text-slate-200 -mr-1"><X className="w-3 h-3" /></button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ── In-app modal primitives ─────────────────────────────────────────

function PromptModal({
  title, placeholder, defaultValue, confirmLabel, onCancel, onConfirm,
}: {
  title: string; placeholder: string; defaultValue: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: (value: string) => void;
}) {
  const [val, setVal] = useState(defaultValue);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select(); }, []);
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onCancel}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-violet-500/40 rounded-xl w-full max-w-md shadow-2xl shadow-violet-500/20 overflow-hidden"
      >
        <div className="px-5 py-4 border-b border-slate-800/60 bg-gradient-to-r from-violet-500/10 to-cyan-500/10">
          <h3 className="text-sm font-bold text-white">{title}</h3>
        </div>
        <div className="p-5">
          <input
            ref={inputRef}
            value={val}
            onChange={e => setVal(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') onConfirm(val);
              if (e.key === 'Escape') onCancel();
            }}
            placeholder={placeholder}
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
          />
        </div>
        <div className="px-5 py-3 border-t border-slate-800/60 flex items-center justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 text-xs hover:text-white">Cancel</button>
          <button onClick={() => onConfirm(val)}
            className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-xs font-semibold inline-flex items-center gap-1.5">
            <Check className="w-3 h-3" /> {confirmLabel}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

function ConfirmModal({
  title, body, danger, confirmLabel, onCancel, onConfirm,
}: {
  title: string; body: string; danger: boolean; confirmLabel: string;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onCancel}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
        onClick={e => e.stopPropagation()}
        className={`bg-[#0B0F19] border rounded-xl w-full max-w-md shadow-2xl overflow-hidden ${danger ? 'border-rose-500/50 shadow-rose-500/10' : 'border-violet-500/40 shadow-violet-500/20'}`}
      >
        <div className={`px-5 py-4 border-b border-slate-800/60 ${danger ? 'bg-rose-500/10' : 'bg-gradient-to-r from-violet-500/10 to-cyan-500/10'} flex items-center gap-2`}>
          {danger ? <AlertTriangle className="w-4 h-4 text-rose-300" /> : <Info className="w-4 h-4 text-violet-300" />}
          <h3 className="text-sm font-bold text-white flex-1">{title}</h3>
        </div>
        {body && <div className="p-5 text-sm text-slate-300 leading-relaxed">{body}</div>}
        <div className="px-5 py-3 border-t border-slate-800/60 flex items-center justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 text-xs hover:text-white">Cancel</button>
          <button onClick={onConfirm}
            className={`px-3 py-1.5 rounded-lg text-white text-xs font-semibold inline-flex items-center gap-1.5 ${danger ? 'bg-rose-500 hover:bg-rose-400' : 'bg-gradient-to-r from-violet-500 to-cyan-500'}`}>
            <Check className="w-3 h-3" /> {confirmLabel}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Toolbar primitives ──────────────────────────────────────────────

function ToolbarGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-1 pr-2 mr-1 border-r border-slate-800/60 last:border-r-0 last:mr-0 last:pr-0">
      <span className="text-[9px] uppercase tracking-wider text-slate-600 mr-1 hidden xl:inline">{label}</span>
      {children}
    </div>
  );
}

function ToolbarBtn({
  icon: Icon, children, onClick, accent, active,
}: {
  icon: any;
  children: React.ReactNode;
  onClick: () => void;
  accent?: 'violet' | 'cyan' | 'emerald' | 'amber';
  active?: boolean;
}) {
  const ringByAccent: Record<string, string> = {
    violet: 'hover:border-violet-500/50',
    cyan: 'hover:border-cyan-500/50',
    emerald: 'hover:border-emerald-500/50',
    amber: 'hover:border-amber-500/50',
  };
  const activeByAccent: Record<string, string> = {
    violet: 'bg-violet-500/15 border-violet-500/50 text-violet-200',
    cyan: 'bg-cyan-500/15 border-cyan-500/50 text-cyan-200',
    emerald: 'bg-emerald-500/15 border-emerald-500/50 text-emerald-200',
    amber: 'bg-amber-500/15 border-amber-500/50 text-amber-200',
  };
  const cls = active
    ? activeByAccent[accent || 'violet']
    : `bg-slate-800/60 border-slate-700 text-slate-200 ${ringByAccent[accent || 'violet']}`;
  return (
    <button onClick={onClick}
      className={`px-2.5 py-1.5 rounded-lg border text-xs inline-flex items-center gap-1.5 transition-colors ${cls}`}>
      <Icon className="w-3 h-3" /> {children}
    </button>
  );
}

function ToolbarIcon({ icon: Icon, onClick, spinning, title }: { icon: any; onClick: () => void; spinning?: boolean; title?: string }) {
  return (
    <button onClick={onClick} disabled={spinning} title={title}
      className="px-2 py-1.5 text-xs text-slate-300 hover:bg-violet-500/15 hover:text-violet-200 inline-flex items-center disabled:opacity-50">
      <Icon className={`w-3 h-3 ${spinning ? 'animate-spin' : ''}`} />
    </button>
  );
}

// ── Empty-canvas onboarding card ────────────────────────────────────

function OnboardCard({
  icon: Icon, title, body, cta, accent, onClick,
}: {
  icon: any;
  title: string;
  body: string;
  cta: string;
  accent: 'violet' | 'cyan' | 'emerald' | 'amber';
  onClick: () => void;
}) {
  const tone: Record<string, { bg: string; border: string; iconBg: string; iconText: string; ctaBg: string }> = {
    violet:  { bg: 'from-violet-500/10 to-violet-500/5',   border: 'border-violet-500/30',  iconBg: 'bg-violet-500/20',  iconText: 'text-violet-200',  ctaBg: 'bg-violet-500/20 border-violet-500/40 text-violet-100' },
    cyan:    { bg: 'from-cyan-500/10 to-cyan-500/5',       border: 'border-cyan-500/30',    iconBg: 'bg-cyan-500/20',    iconText: 'text-cyan-200',    ctaBg: 'bg-cyan-500/20 border-cyan-500/40 text-cyan-100' },
    emerald: { bg: 'from-emerald-500/10 to-emerald-500/5', border: 'border-emerald-500/30', iconBg: 'bg-emerald-500/20', iconText: 'text-emerald-200', ctaBg: 'bg-emerald-500/20 border-emerald-500/40 text-emerald-100' },
    amber:   { bg: 'from-amber-500/10 to-amber-500/5',     border: 'border-amber-500/30',   iconBg: 'bg-amber-500/20',   iconText: 'text-amber-200',   ctaBg: 'bg-amber-500/20 border-amber-500/40 text-amber-100' },
  };
  const t = tone[accent];
  return (
    <button onClick={onClick}
      className={`group text-left rounded-xl border ${t.border} bg-gradient-to-br ${t.bg} p-4 hover:translate-y-[-1px] hover:shadow-lg transition-all`}>
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-lg ${t.iconBg} flex items-center justify-center shrink-0`}>
          <Icon className={`w-4.5 h-4.5 ${t.iconText}`} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="text-[11px] text-slate-400 mt-1 leading-snug">{body}</p>
          <span className={`mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${t.ctaBg} group-hover:translate-x-0.5 transition-transform`}>
            {cta} <ArrowRight className="w-3 h-3" />
          </span>
        </div>
      </div>
    </button>
  );
}

// ── Multi-lens inspector for a selected node ─────────────────────────

function NodeInspector({
  node, edges, allNodes, instances, instancesLoading, kbList,
  onLoadKbs, onBindKb, onUpdate, onDelete,
}: {
  node: AtlasNodeRow;
  edges: AtlasEdgeRow[];
  allNodes: AtlasNodeRow[];
  instances: InstanceRow[];
  instancesLoading: boolean;
  kbList: KBCollection[];
  onLoadKbs: () => void;
  onBindKb: (kbId: string) => void;
  onUpdate: (patch: Partial<AtlasNodeRow>) => void;
  onDelete: () => void;
}) {
  const binding = (node.properties as any)?._binding as { kind: string; ref_id: string } | undefined;
  const [tab, setTab] = useState<'schema' | 'relations' | 'properties' | 'lineage' | 'instances'>(binding ? 'instances' : 'schema');
  const [showBindMenu, setShowBindMenu] = useState(false);
  const [label, setLabel] = useState(node.label);
  const [desc, setDesc] = useState(node.description);

  useEffect(() => { setLabel(node.label); setDesc(node.description); }, [node.id]);

  const commit = () => {
    if (label !== node.label || desc !== node.description) {
      onUpdate({ label, description: desc });
    }
  };

  const incoming = edges.filter(e => e.to_node_id === node.id);
  const outgoing = edges.filter(e => e.from_node_id === node.id);
  const nodeName = (id: string) => allNodes.find(n => n.id === id)?.label || '?';

  const style = KIND_STYLE[node.kind] || KIND_STYLE.concept;
  const Icon = style.icon;

  return (
    <div>
      {/* Header */}
      <div className={`rounded-xl border ${style.border} bg-gradient-to-br ${style.bg} p-3 mb-4`}>
        <div className="flex items-center gap-2 mb-2">
          <Icon className={`w-4 h-4 ${style.accent}`} />
          <select
            value={node.kind}
            onChange={e => onUpdate({ kind: e.target.value as NodeKind })}
            className="bg-transparent text-[10px] uppercase tracking-wider text-slate-400 border-none outline-none cursor-pointer"
          >
            <option value="concept">concept</option>
            <option value="instance">instance</option>
            <option value="document">document</option>
            <option value="property">property</option>
          </select>
          <span className="ml-auto text-[9px] text-slate-500 font-mono">{node.source}</span>
        </div>
        <input
          value={label} onChange={e => setLabel(e.target.value)} onBlur={commit}
          className="w-full bg-transparent text-base font-semibold text-white border-none outline-none"
        />
        <textarea
          value={desc} onChange={e => setDesc(e.target.value)} onBlur={commit}
          placeholder="Add a description…"
          className="w-full mt-1 bg-transparent text-[11px] text-slate-300 border-none outline-none resize-none"
          rows={2}
        />
      </div>

      {/* Lens tabs */}
      <div className="flex gap-1 mb-3 overflow-x-auto">
        {(['schema', 'relations', 'properties', 'instances', 'lineage'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`shrink-0 px-2 py-1.5 rounded text-[9px] uppercase tracking-wider font-semibold transition-colors ${
              tab === t ? 'bg-violet-500/20 text-violet-200 border border-violet-500/40' : 'text-slate-500 hover:text-slate-300'
            }`}>{t}</button>
        ))}
      </div>

      {tab === 'schema' && (
        <div className="space-y-2 text-[11px]">
          <Row label="Kind">{node.kind}</Row>
          <Row label="Source">{node.source}</Row>
          {node.confidence !== null && <Row label="Confidence">{Math.round((node.confidence || 0) * 100)}%</Row>}
          {node.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {node.tags.map(t => <span key={t} className="px-1.5 py-0.5 rounded text-[9px] bg-slate-800 text-slate-400 border border-slate-700">{t}</span>)}
            </div>
          )}
        </div>
      )}

      {tab === 'relations' && (
        <div className="space-y-3 text-[11px]">
          <div>
            <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Outgoing ({outgoing.length})</p>
            {outgoing.length === 0 && <p className="text-slate-600 text-[10px]">none</p>}
            {outgoing.map(e => (
              <div key={e.id} className="rounded bg-slate-800/40 px-2 py-1.5 mb-1">
                <p className="text-slate-300"><span className="text-violet-300">{e.label}</span> → <span className="text-emerald-300">{nodeName(e.to_node_id)}</span></p>
                {(e.cardinality_from || e.cardinality_to) && <p className="text-[9px] text-slate-500 font-mono mt-0.5">{e.cardinality_from || '?'} : {e.cardinality_to || '?'}</p>}
              </div>
            ))}
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Incoming ({incoming.length})</p>
            {incoming.length === 0 && <p className="text-slate-600 text-[10px]">none</p>}
            {incoming.map(e => (
              <div key={e.id} className="rounded bg-slate-800/40 px-2 py-1.5 mb-1">
                <p className="text-slate-300"><span className="text-emerald-300">{nodeName(e.from_node_id)}</span> → <span className="text-violet-300">{e.label}</span></p>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'properties' && (
        <div className="text-[11px]">
          {Object.keys(node.properties || {}).length === 0 ? (
            <p className="text-slate-600 text-[10px]">No properties yet. Hint: drop a doc onto the canvas to extract them.</p>
          ) : (
            <div className="space-y-1">
              {Object.entries(node.properties || {}).map(([k, v]) => (
                <div key={k} className="rounded bg-slate-800/40 px-2 py-1.5">
                  <p className="text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                  <p className="text-slate-300 break-words">{typeof v === 'string' ? v : JSON.stringify(v)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'instances' && (
        <div className="text-[11px] space-y-2">
          {!binding && (
            <div className="rounded-lg border border-dashed border-slate-700 p-3 text-center">
              <Database className="w-5 h-5 text-slate-600 mx-auto mb-1.5" />
              <p className="text-slate-400 text-[11px] mb-2">No live binding yet.</p>
              <p className="text-[10px] text-slate-500 mb-2">Bind this concept to a knowledge collection to see live document instances under this node.</p>
              <button onClick={() => { onLoadKbs(); setShowBindMenu(true); }}
                className="px-2.5 py-1 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-200 text-[11px] font-semibold inline-flex items-center gap-1">
                <Link2 className="w-3 h-3" /> Bind to KB
              </button>
            </div>
          )}
          {binding && (
            <div className="rounded bg-emerald-500/5 border border-emerald-500/30 px-2 py-1.5 text-[10px]">
              <p className="text-emerald-200 inline-flex items-center gap-1.5"><Link2 className="w-3 h-3" /> Bound · {binding.kind}</p>
            </div>
          )}
          {showBindMenu && (
            <div className="rounded border border-slate-700 bg-slate-900/80 p-2 max-h-60 overflow-y-auto">
              {kbList.length === 0 && <p className="text-slate-500 text-[10px]">No collections — create one in Knowledge Bases first.</p>}
              {kbList.map(kb => (
                <button key={kb.id} onClick={() => { onBindKb(kb.id); setShowBindMenu(false); }}
                  className="w-full text-left rounded hover:bg-emerald-500/10 px-2 py-1 text-[11px] text-slate-200">
                  {kb.name} <span className="text-slate-500 text-[10px]">({kb.doc_count || 0} docs)</span>
                </button>
              ))}
            </div>
          )}
          {instancesLoading && <div className="text-center py-4"><Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400 mx-auto" /></div>}
          {!instancesLoading && binding && instances.length === 0 && (
            <p className="text-slate-500 text-[10px] p-2 text-center">No instances yet.</p>
          )}
          {!instancesLoading && instances.map(inst => (
            <div key={inst.id} className="rounded bg-slate-800/40 px-2 py-1.5 border border-slate-700/40">
              <p className="text-slate-200 text-[11px] truncate" title={inst.label}>{inst.label}</p>
              <p className="text-[9px] text-slate-500 mt-0.5 font-mono">{inst.file_type || ''} · {inst.status || ''}</p>
            </div>
          ))}
        </div>
      )}

      {tab === 'lineage' && (
        <div className="text-[11px] space-y-2">
          <Row label="Created">{node.created_at ? new Date(node.created_at).toLocaleString() : '—'}</Row>
          <Row label="Updated">{node.updated_at ? new Date(node.updated_at).toLocaleString() : '—'}</Row>
          <Row label="Source">{node.source}</Row>
          {node.document_id && <Row label="Doc">{node.document_id.slice(0, 8)}…</Row>}
        </div>
      )}

      {/* Footer actions */}
      <div className="mt-4 pt-3 border-t border-slate-800/50">
        <button onClick={onDelete} className="w-full px-3 py-2 rounded-lg border border-rose-500/30 text-rose-300 text-xs hover:bg-rose-500/10 inline-flex items-center justify-center gap-1.5">
          <Trash2 className="w-3 h-3" /> Delete node
        </button>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-[9px] uppercase tracking-wider text-slate-500 shrink-0 w-20 mt-0.5">{label}</span>
      <span className="text-slate-300 flex-1 break-words">{children}</span>
    </div>
  );
}
