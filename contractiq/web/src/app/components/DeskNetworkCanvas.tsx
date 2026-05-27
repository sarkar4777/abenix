'use client';

import { useEffect, useRef, useState } from 'react';
import { Maximize2, Minimize2 } from 'lucide-react';
import { NarrationEvent } from './useNarrationStream';

interface Node {
  id: string;
  label: string;
  kind: 'meta' | 'specialist' | 'tool';
  parent?: string;
  status: 'idle' | 'running' | 'done' | 'failed';
  x: number;
  y: number;
  vx: number;
  vy: number;
  spawnedAt: number;
  pulseUntil?: number;
}

interface Edge {
  from: string;
  to: string;
  status: 'running' | 'done' | 'failed';
  pulseUntil?: number;
}

interface Props {
  rootExecutionId: string;
  events: NarrationEvent[];
  height?: number;
  title?: string;
}

const SPECIALIST_LABEL: Record<string, string> = {
  'ciq-arb-analyzer': 'Arb Analyzer',
  'ciq-mispricing-extractor': 'Price at Risk Lens',
  'ciq-scenario-forecaster': 'Forward Scenarios',
  'ciq-ops-monitor': 'Ops Monitor',
  'ciq-graph-query': 'Knowledge Graph',
  'ciq-market-brief': 'Market Brief',
  'ciq-broker-classifier': 'Broker Classifier',
  'ciq-broker-parser': 'Broker Parser',
};

export default function DeskNetworkCanvas({ rootExecutionId, events, height = 360, title = 'Live agent network' }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [size, setSize] = useState({ w: 800, h: height });
  const nodesRef = useRef<Map<string, Node>>(new Map());
  const edgesRef = useRef<Edge[]>([]);
  const [_tick, setTick] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const effectiveHeight = expanded && typeof window !== 'undefined'
    ? Math.max(window.innerHeight - 140, 480)
    : height;

  useEffect(() => {
    const ro = new ResizeObserver(() => {
      const el = svgRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      setSize({ w: rect.width || 800, h: rect.height || effectiveHeight });
    });
    if (svgRef.current) ro.observe(svgRef.current);
    return () => ro.disconnect();
  }, [effectiveHeight]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [expanded]);

  useEffect(() => {
    nodesRef.current.clear();
    edgesRef.current = [];
    const cx = size.w / 2;
    const cy = size.h / 2;
    nodesRef.current.set('root', {
      id: 'root', label: 'E&C-Copilot', kind: 'meta',
      status: 'running', x: cx, y: cy, vx: 0, vy: 0, spawnedAt: performance.now(),
      pulseUntil: performance.now() + 1200,
    });
  }, [rootExecutionId, size.w, size.h]);

  useEffect(() => {
    const cx = size.w / 2;
    const cy = size.h / 2;
    const map = nodesRef.current;

    for (const evt of events) {
      const now = performance.now();
      if (evt.phase === 'tool_call') {
        const parent = evt.execution_id === rootExecutionId
          ? 'root'
          : (events.find((e) => e.phase === 'sub_started' && e.sub_execution_id === evt.execution_id)?.agent_slug || 'root');
        if (!map.has(parent)) continue;
        const parentNode = map.get(parent)!;
        const nodeId = `${parent}::${evt.tool}::${evt.ts}`;
        if (!map.has(nodeId)) {
          const angle = Math.random() * Math.PI * 2;
          const dist = parent === 'root' ? 120 : 70;
          map.set(nodeId, {
            id: nodeId,
            label: evt.tool || 'tool',
            kind: 'tool',
            parent,
            status: 'running',
            x: parentNode.x + Math.cos(angle) * dist + (Math.random() - 0.5) * 20,
            y: parentNode.y + Math.sin(angle) * dist + (Math.random() - 0.5) * 20,
            vx: 0, vy: 0,
            spawnedAt: now,
            pulseUntil: now + 900,
          });
          edgesRef.current.push({ from: parent, to: nodeId, status: 'running', pulseUntil: now + 900 });
        }
      } else if (evt.phase === 'tool_result') {
        let matchId: string | null = null;
        for (const [id, node] of map.entries()) {
          if (node.kind === 'tool' && node.label === evt.tool && node.status === 'running') {
            matchId = id;
            break;
          }
        }
        if (matchId) {
          const n = map.get(matchId)!;
          n.status = evt.is_error ? 'failed' : 'done';
          n.pulseUntil = now + 800;
          const edge = edgesRef.current.find((e) => e.to === matchId);
          if (edge) {
            edge.status = evt.is_error ? 'failed' : 'done';
            edge.pulseUntil = now + 800;
          }
        }
      } else if (evt.phase === 'sub_started' && evt.agent_slug && evt.sub_execution_id) {
        const id = evt.agent_slug;
        if (!map.has(id)) {
          const angle = (Array.from(map.values()).filter((n) => n.kind === 'specialist').length) * (Math.PI * 2 / 6) - Math.PI / 2;
          const dist = Math.min(size.w, size.h) * 0.30;
          map.set(id, {
            id,
            label: SPECIALIST_LABEL[id] || id.replace(/^ciq-/, ''),
            kind: 'specialist',
            parent: 'root',
            status: 'running',
            x: cx + Math.cos(angle) * dist,
            y: cy + Math.sin(angle) * dist,
            vx: 0, vy: 0,
            spawnedAt: now,
            pulseUntil: now + 1500,
          });
          edgesRef.current.push({ from: 'root', to: id, status: 'running', pulseUntil: now + 1500 });
        }
      } else if (evt.phase === 'sub_finished' && evt.agent_slug) {
        const n = map.get(evt.agent_slug);
        if (n) {
          n.status = (evt.status === 'completed' || evt.status === 'succeeded') ? 'done' : 'failed';
          n.pulseUntil = now + 1200;
          const edge = edgesRef.current.find((e) => e.to === evt.agent_slug);
          if (edge) {
            edge.status = n.status === 'done' ? 'done' : 'failed';
            edge.pulseUntil = now + 1200;
          }
        }
      } else if (evt.phase === 'narration') {
        const root = map.get('root');
        if (root) root.pulseUntil = now + 800;
      }
    }
    setTick((t) => t + 1);
  }, [events, rootExecutionId, size.w, size.h]);

  useEffect(() => {
    let raf = 0;
    const step = () => {
      const map = nodesRef.current;
      const cx = size.w / 2;
      const cy = size.h / 2;
      for (const a of map.values()) {
        let fx = 0, fy = 0;
        const parent = a.parent ? map.get(a.parent) : null;
        if (parent) {
          const dx = parent.x - a.x;
          const dy = parent.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
          const targetDist = a.kind === 'specialist' ? Math.min(size.w, size.h) * 0.30 : 70;
          const f = (dist - targetDist) * 0.04;
          fx += (dx / dist) * f;
          fy += (dy / dist) * f;
        }
        for (const b of map.values()) {
          if (a === b) continue;
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy + 0.01;
          const d = Math.sqrt(d2);
          if (d < 90) {
            const repulse = 220 / d2;
            fx += (dx / d) * repulse;
            fy += (dy / d) * repulse;
          }
        }
        fx += (cx - a.x) * 0.001;
        fy += (cy - a.y) * 0.001;
        a.vx = (a.vx + fx) * 0.78;
        a.vy = (a.vy + fy) * 0.78;
        a.x += a.vx;
        a.y += a.vy;
        const pad = 30;
        if (a.x < pad) { a.x = pad; a.vx = 0; }
        if (a.x > size.w - pad) { a.x = size.w - pad; a.vx = 0; }
        if (a.y < pad) { a.y = pad; a.vy = 0; }
        if (a.y > size.h - pad) { a.y = size.h - pad; a.vy = 0; }
      }
      setTick((t) => (t + 1) % 1_000_000);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [size.w, size.h]);

  const now = performance.now();
  const nodes = Array.from(nodesRef.current.values());
  const edges = edgesRef.current;

  const nodeColor = (n: Node) => {
    if (n.status === 'failed') return '#f43f5e';
    if (n.status === 'done') return '#10b981';
    if (n.status === 'running') return n.kind === 'meta' ? '#22d3ee' : n.kind === 'specialist' ? '#a78bfa' : '#22d3ee';
    return '#475569';
  };
  const radius = (n: Node) => n.kind === 'meta' ? 22 : n.kind === 'specialist' ? 16 : 9;
  const edgeColor = (e: Edge) => e.status === 'failed' ? '#f43f5e' : e.status === 'done' ? '#10b981' : '#22d3ee';

  const wrapperClass = expanded
    ? 'fixed inset-3 z-50 rounded-xl border border-emerald-500/30 bg-gradient-to-br from-slate-950/95 via-slate-900/80 to-slate-950/95 backdrop-blur-xl overflow-hidden shadow-2xl flex flex-col'
    : 'relative rounded-xl border border-emerald-500/15 bg-gradient-to-br from-slate-950/80 via-slate-900/40 to-slate-950/80 overflow-hidden';
  return (
    <div className={wrapperClass}>
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800/60">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-[10px] uppercase tracking-[0.18em] text-emerald-300 font-semibold">{title}</span>
        <span className="text-[10px] font-mono text-slate-500">#{rootExecutionId.slice(0, 8)}</span>
        <span className="flex-1" />
        <span className="text-[10px] text-slate-500">{nodes.length} nodes · {edges.length} edges</span>
        <button
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? 'Collapse (esc)' : 'Expand'}
          className="ml-1 p-1 rounded text-slate-400 hover:text-emerald-300 hover:bg-slate-800/60"
          aria-label={expanded ? 'collapse' : 'expand'}
        >
          {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${size.w} ${size.h}`}
        preserveAspectRatio="xMidYMid meet"
        className={expanded ? 'w-full flex-1 block' : 'w-full block'}
        style={expanded ? undefined : { height: effectiveHeight }}
      >
        <defs>
          <radialGradient id="meta-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
        </defs>
        {edges.map((e, i) => {
          const a = nodesRef.current.get(e.from);
          const b = nodesRef.current.get(e.to);
          if (!a || !b) return null;
          const pulsing = e.pulseUntil && now < e.pulseUntil;
          return (
            <g key={`e-${i}`}>
              <line
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={edgeColor(e)}
                strokeOpacity={pulsing ? 0.9 : 0.35}
                strokeWidth={pulsing ? 1.8 : 1.0}
                strokeDasharray={e.status === 'running' ? '4 4' : undefined}
              />
              {pulsing && (
                <circle
                  cx={a.x + (b.x - a.x) * (((now - (e.pulseUntil! - 900)) / 900) % 1)}
                  cy={a.y + (b.y - a.y) * (((now - (e.pulseUntil! - 900)) / 900) % 1)}
                  r={3}
                  fill={edgeColor(e)}
                />
              )}
            </g>
          );
        })}
        {nodes.map((n) => {
          const pulsing = n.pulseUntil && now < n.pulseUntil;
          const r = radius(n);
          return (
            <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
              {n.kind === 'meta' && (
                <circle r={r + 22} fill="url(#meta-glow)" opacity={pulsing ? 1 : 0.45} />
              )}
              {pulsing && (
                <circle r={r + 10} fill="none" stroke={nodeColor(n)} strokeOpacity={0.5} strokeWidth={1.2} />
              )}
              <circle r={r} fill={nodeColor(n)} fillOpacity={n.status === 'idle' ? 0.4 : 0.92} stroke="#0f172a" strokeWidth={1.5} />
              {n.kind !== 'tool' && (
                <text
                  y={r + 14}
                  textAnchor="middle"
                  fontSize={n.kind === 'meta' ? 12 : 10}
                  fill={n.status === 'idle' ? '#475569' : '#e2e8f0'}
                  fontWeight={n.kind === 'meta' ? 700 : 500}
                  style={{ pointerEvents: 'none' }}
                >
                  {n.label}
                </text>
              )}
              {n.kind === 'tool' && (
                <text
                  y={r + 10}
                  textAnchor="middle"
                  fontSize={8}
                  fill="#94a3b8"
                  style={{ pointerEvents: 'none' }}
                >
                  {n.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
