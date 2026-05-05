'use client';

import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Workflow, ChevronDown, ChevronRight } from 'lucide-react';

export interface DagNode {
  id: string;
  label: string;
  kind: 'agent' | 'tool' | 'switch' | 'final' | 'inline';
  description?: string;
}

export interface DagEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface DagDef {
  title: string;
  description: string;
  pipelineSlug: string;
  nodes: DagNode[];
  edges: DagEdge[];
}

// SVG fill + stroke colours per node kind — set explicitly because SVG
// <text> doesn't pick up Tailwind text-color utilities.
const KIND_STYLE: Record<DagNode['kind'], { box: string; stroke: string; label: string }> = {
  agent:  { box: 'rgba(6, 182, 212, 0.18)',   stroke: '#22d3ee', label: '#e0f2fe' },
  tool:   { box: 'rgba(16, 185, 129, 0.18)',  stroke: '#34d399', label: '#d1fae5' },
  switch: { box: 'rgba(245, 158, 11, 0.18)',  stroke: '#fbbf24', label: '#fef3c7' },
  final:  { box: 'rgba(168, 85, 247, 0.20)',  stroke: '#c084fc', label: '#f3e8ff' },
  inline: { box: 'rgba(71, 85, 105, 0.45)',   stroke: '#94a3b8', label: '#e2e8f0' },
};

const KIND_LABEL: Record<DagNode['kind'], string> = {
  agent:  'agent',
  tool:   'tool',
  switch: 'router',
  final:  'output',
  inline: 'inline',
};

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

// BFS-based level assignment, then within-level positioning.
function layout(nodes: DagNode[], edges: DagEdge[]) {
  const incoming = new Map<string, number>();
  const successors = new Map<string, string[]>();
  for (const n of nodes) { incoming.set(n.id, 0); successors.set(n.id, []); }
  for (const e of edges) {
    incoming.set(e.to, (incoming.get(e.to) || 0) + 1);
    successors.get(e.from)?.push(e.to);
  }
  const level = new Map<string, number>();
  const queue: string[] = [];
  for (const [id, count] of incoming) {
    if (count === 0) { level.set(id, 0); queue.push(id); }
  }
  while (queue.length) {
    const id = queue.shift()!;
    const cur = level.get(id) ?? 0;
    for (const next of successors.get(id) || []) {
      const candidate = cur + 1;
      if ((level.get(next) ?? -1) < candidate) level.set(next, candidate);
      const remaining = (incoming.get(next) || 0) - 1;
      incoming.set(next, remaining);
      if (remaining === 0) queue.push(next);
    }
  }
  // Group nodes by level + assign within-level index by stable order.
  const byLevel = new Map<number, string[]>();
  for (const n of nodes) {
    const l = level.get(n.id) ?? 0;
    if (!byLevel.has(l)) byLevel.set(l, []);
    byLevel.get(l)!.push(n.id);
  }
  const positions = new Map<string, { x: number; y: number }>();
  const NODE_W = 200;
  const NODE_H = 64;
  const GAP_X = 56;
  const GAP_Y = 36;
  let maxX = 0;
  for (const [l, ids] of byLevel) {
    ids.forEach((id, i) => {
      const x = i * (NODE_W + GAP_X);
      const y = l * (NODE_H + GAP_Y);
      positions.set(id, { x, y });
      if (x + NODE_W > maxX) maxX = x + NODE_W;
    });
  }
  const maxY = (Math.max(...byLevel.keys()) + 1) * (NODE_H + GAP_Y);
  return { positions, NODE_W, NODE_H, width: maxX + 4, height: maxY + 4 };
}

export default function PipelineDagViz({ dag }: { dag: DagDef }) {
  const [open, setOpen] = useState(true);
  const { positions, NODE_W, NODE_H, width, height } = useMemo(
    () => layout(dag.nodes, dag.edges),
    [dag.nodes, dag.edges],
  );

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-slate-900/60 transition-colors"
      >
        <div className="flex items-center gap-3 text-left">
          <div className="w-9 h-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
            <Workflow className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Execution DAG · {dag.title}</p>
            <p className="text-[11px] text-slate-500">
              <code className="text-cyan-300">{dag.pipelineSlug}</code> · {dag.nodes.length} nodes · {dag.edges.length} edges
            </p>
          </div>
        </div>
        {open ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-3">
          <p className="text-[12px] text-slate-400 leading-relaxed">{dag.description}</p>

          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="overflow-x-auto rounded-lg bg-slate-950/60 border border-slate-800 p-4"
          >
            <svg
              width={width}
              height={height}
              viewBox={`0 0 ${width} ${height}`}
              className="block"
              role="img"
              aria-label={`${dag.title} agent DAG`}
            >
              <defs>
                <marker
                  id="dag-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" className="fill-slate-500" />
                </marker>
              </defs>

              {dag.edges.map((e, i) => {
                const a = positions.get(e.from);
                const b = positions.get(e.to);
                if (!a || !b) return null;
                const x1 = a.x + NODE_W / 2;
                const y1 = a.y + NODE_H;
                const x2 = b.x + NODE_W / 2;
                const y2 = b.y;
                const midY = (y1 + y2) / 2;
                const path = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
                return (
                  <g key={i}>
                    <path d={path} stroke="#475569" strokeWidth="1.5" fill="none" markerEnd="url(#dag-arrow)" />
                    {e.condition && (
                      <text
                        x={(x1 + x2) / 2}
                        y={midY - 4}
                        textAnchor="middle"
                        fill="#fcd34d"
                        fontSize="10"
                        fontWeight="500"
                      >
                        {e.condition}
                      </text>
                    )}
                  </g>
                );
              })}

              {dag.nodes.map((n) => {
                const p = positions.get(n.id);
                if (!p) return null;
                const style = KIND_STYLE[n.kind];
                return (
                  <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
                    <rect
                      width={NODE_W}
                      height={NODE_H}
                      rx={10}
                      ry={10}
                      fill={style.box}
                      stroke={style.stroke}
                      strokeWidth="1.5"
                    >
                      <title>{n.description || n.label}</title>
                    </rect>
                    <text
                      x={NODE_W / 2}
                      y={26}
                      textAnchor="middle"
                      fill={style.label}
                      fontSize="13"
                      fontWeight="600"
                    >
                      {truncate(n.label, 26)}
                    </text>
                    <text
                      x={NODE_W / 2}
                      y={48}
                      textAnchor="middle"
                      fill="#94a3b8"
                      fontSize="10"
                      letterSpacing="0.08em"
                      style={{ textTransform: 'uppercase' }}
                    >
                      {KIND_LABEL[n.kind]}
                    </text>
                  </g>
                );
              })}
            </svg>
          </motion.div>

          <div className="flex items-center gap-4 text-[11px] text-slate-500 pt-1">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded bg-cyan-500/60" /> Agent step
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded bg-emerald-500/60" /> Tool / inline call
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded bg-amber-500/60" /> Conditional router
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded bg-purple-500/60" /> Final output
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
