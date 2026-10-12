'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';
import { Crosshair, Eraser, Plus, Trash2, Undo2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { boundsOf, pointInPolygon, roundCoord, type Bounds, type Condition, type Scope, type SignalRow } from './lib';

const W = 600;
const H = 420;

interface Track { key: string; label: string; points: number[][]; now: number[] | null }

function fetcher(url: string) {
  return apiFetch<{ series?: Array<{ metric: string; points: Array<{ t: number; avg: number | null }> }> }>(url, { silent: true });
}

// history of both coordinates for one asset, joined on time
function useTrack(a: { group: string; node: string; device: string } | null, xs: string, ys: string) {
  const url = a && xs && ys
    ? `/api/telemetry/history?group=${encodeURIComponent(a.group)}&node=${encodeURIComponent(a.node)}&device=${encodeURIComponent(a.device)}&metric=${encodeURIComponent(`${xs},${ys}`)}&from=-1h&step=10s`
    : null;
  const res = useSWR(url, fetcher, { revalidateOnFocus: false, refreshInterval: 30_000 });
  return useMemo(() => {
    const series = res.data?.data?.series || [];
    const bx = new Map<number, number>();
    const out: number[][] = [];
    for (const p of series.find((s) => s.metric === xs)?.points || []) if (p.avg !== null) bx.set(p.t, p.avg);
    for (const p of series.find((s) => s.metric === ys)?.points || []) {
      const x = bx.get(p.t);
      if (x !== undefined && p.avg !== null) out.push([x, p.avg]);
    }
    return out;
  }, [res.data, xs, ys]);
}

// keeps what is typed, like a lone minus sign, until it is a number
function CornerInput({ label, value, disabled, onCommit }: { label: string; value: number; disabled?: boolean; onCommit: (v: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    if (Number(text) !== value) setText(String(value));
    // only an outside change resets the text
  }, [value]);
  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      value={text}
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value.trim() !== '' && Number.isFinite(v)) onCommit(v);
      }}
      className="min-h-[34px] w-full min-w-0 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs text-white"
    />
  );
}

export default function GeofenceEditor({
  cond, scope, signals, onChange, error, disabled, assetNames,
}: {
  cond: Condition;
  scope: Scope;
  signals: SignalRow[] | null;
  onChange: (poly: number[][]) => void;
  error?: string | null;
  disabled?: boolean;
  assetNames: Record<string, string>;
}) {
  const gnss = cond.frame === 'gnss';
  const poly = useMemo(() => cond.polygon || [], [cond.polygon]);
  const xs = cond.x_signal || '';
  const ys = cond.y_signal || '';

  // where the assets in scope are now, from the live signal list
  const xRow = signals?.find((s) => s.signal === xs);
  const yRow = signals?.find((s) => s.signal === ys);
  const live = useMemo(() => {
    const out: Track[] = [];
    for (const a of xRow?.assets || []) {
      const b = yRow?.assets.find((y) => y.group === a.group && y.node === a.node && y.device === a.device);
      const x = Number(a.value), y = Number(b?.value);
      const key = `${a.group}/${a.node}/${a.device}`;
      out.push({ key, label: assetNames[`${a.group}/${a.node}/`] || a.node, points: [], now: Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null });
    }
    return out.slice(0, 8);
  }, [xRow, yRow, assetNames]);
  const first = live[0] ? { group: live[0].key.split('/')[0], node: live[0].key.split('/')[1], device: live[0].key.split('/').slice(2).join('/') } : scope.kind === 'asset' && scope.group && scope.node ? { group: scope.group, node: scope.node, device: scope.device && scope.device !== '*' ? scope.device : '' } : null;
  const track = useTrack(first, xs, ys);

  const k = useMemo(() => {
    if (!gnss) return 1;
    const lat = poly[0]?.[1] ?? live.find((l) => l.now)?.now?.[1] ?? track[0]?.[1] ?? 0;
    return Math.cos((lat * Math.PI) / 180) || 1;
  }, [gnss, poly, live, track]);

  const plane = (p: number[]) => [p[0] * k, p[1]];
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const fit = () => {
    const pts = [...track, ...poly, ...live.flatMap((l) => (l.now ? [l.now] : []))].map(plane);
    setBounds(boundsOf(pts, 0.15));
  };
  // fit once when data first arrives
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current) return;
    if (track.length || poly.length || live.some((l) => l.now)) {
      fitted.current = true;
      fit();
    }
  }, [track.length, poly.length, live]);

  const b = bounds ?? { minX: -50, maxX: 50, minY: -50, maxY: 50 };
  const sx = (p: number[]) => ((plane(p)[0] - b.minX) / (b.maxX - b.minX)) * W;
  const sy = (p: number[]) => H - ((p[1] - b.minY) / (b.maxY - b.minY)) * H;
  const toWorld = (px: number, py: number): number[] => {
    const x = (b.minX + (px / W) * (b.maxX - b.minX)) / k;
    const y = b.minY + ((H - py) / H) * (b.maxY - b.minY);
    return [roundCoord(x, gnss), roundCoord(y, gnss)];
  };

  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const eventPoint = (e: { clientX: number; clientY: number }) => {
    const r = svg.current!.getBoundingClientRect();
    return toWorld(((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H);
  };

  const setCorner = (i: number, p: number[]) => onChange(poly.map((q, j) => (j === i ? p : q)));
  const nowInside = live.filter((l) => l.now && poly.length >= 3 && pointInPolygon(l.now[0], l.now[1], poly));

  return (
    <div className="space-y-2" data-testid="geofence-editor">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span className="min-w-0 flex-1">
          {disabled ? 'The zone this rule watches.' : 'Click the map to add corners, drag a corner to move it. The track is the last hour of the first asset.'}
        </span>
        <button type="button" onClick={fit} className="inline-flex min-h-[32px] items-center gap-1 rounded-md border border-slate-700 px-2 text-slate-300 hover:bg-slate-800" data-testid="geofence-fit">
          <Crosshair className="h-3.5 w-3.5" /> Fit
        </button>
        {!disabled && (
          <>
            <button type="button" disabled={!poly.length} onClick={() => onChange(poly.slice(0, -1))} className="inline-flex min-h-[32px] items-center gap-1 rounded-md border border-slate-700 px-2 text-slate-300 hover:bg-slate-800 disabled:opacity-50" data-testid="geofence-undo">
              <Undo2 className="h-3.5 w-3.5" /> Undo
            </button>
            <button type="button" disabled={!poly.length} onClick={() => { onChange([]); setSel(null); }} className="inline-flex min-h-[32px] items-center gap-1 rounded-md border border-slate-700 px-2 text-slate-300 hover:bg-slate-800 disabled:opacity-50" data-testid="geofence-clear">
              <Eraser className="h-3.5 w-3.5" /> Clear
            </button>
          </>
        )}
      </div>
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        className={`block w-full touch-none select-none rounded-lg border bg-slate-950 ${error ? 'border-rose-500/70' : 'border-slate-700'} ${disabled ? '' : 'cursor-crosshair'}`}
        role="img"
        aria-label={`Zone with ${poly.length} corners`}
        data-testid="geofence-canvas"
        onPointerDown={(e) => {
          if (disabled || drag !== null) return;
          if ((e.target as Element).getAttribute('data-corner')) return;
          onChange([...poly, eventPoint(e)]);
          setSel(poly.length);
        }}
        onPointerMove={(e) => { if (drag !== null) setCorner(drag, eventPoint(e)); }}
        onPointerUp={() => setDrag(null)}
        onPointerLeave={() => setDrag(null)}
      >
        <defs>
          <pattern id="gf-grid" width="30" height="30" patternUnits="userSpaceOnUse">
            <path d="M 30 0 L 0 0 0 30" fill="none" stroke="#1e293b" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#gf-grid)" />
        {track.length > 1 && (
          <polyline points={track.map((p) => `${sx(p)},${sy(p)}`).join(' ')} fill="none" stroke="#475569" strokeWidth={1.5} strokeDasharray="3 3" />
        )}
        {poly.length >= 2 && (
          <polygon
            points={poly.map((p) => `${sx(p)},${sy(p)}`).join(' ')}
            fill={poly.length >= 3 ? 'rgba(34,211,238,0.12)' : 'none'}
            stroke="#22d3ee"
            strokeWidth={2}
          />
        )}
        {live.map((l) => l.now && (
          <g key={l.key}>
            <circle cx={sx(l.now)} cy={sy(l.now)} r={6} fill="#f59e0b" stroke="#0f172a" strokeWidth={2} />
            <text x={sx(l.now) + 9} y={sy(l.now) + 4} fill="#fbbf24" fontSize={12}>{l.label}</text>
          </g>
        ))}
        {poly.map((p, i) => (
          <circle
            key={i}
            data-corner="1"
            cx={sx(p)}
            cy={sy(p)}
            r={sel === i ? 8 : 6}
            fill={sel === i ? '#22d3ee' : '#0f172a'}
            stroke="#22d3ee"
            strokeWidth={2}
            className={disabled ? '' : 'cursor-move'}
            onPointerDown={(e) => { if (disabled) return; e.stopPropagation(); (e.target as Element).setPointerCapture?.(e.pointerId); setDrag(i); setSel(i); }}
            data-testid="geofence-corner"
          />
        ))}
        {!poly.length && (
          <text x={W / 2} y={H / 2} textAnchor="middle" fill="#64748b" fontSize={14}>
            {disabled ? 'No zone drawn' : track.length || live.some((l) => l.now) ? 'Click to place the first corner' : 'No positions yet, you can still draw or type corners below'}
          </text>
        )}
      </svg>
      {error && <p className="text-xs text-rose-300" role="alert">{error}</p>}
      {poly.length >= 3 && live.some((l) => l.now) && (
        <p className="text-xs text-slate-400" data-testid="geofence-inside-now">
          {nowInside.length ? `Inside the zone now: ${nowInside.map((l) => l.label).join(', ')}.` : 'No asset is inside the zone now.'}
        </p>
      )}
      <details className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-2 text-xs text-slate-300" data-testid="geofence-numbers">
        <summary className="cursor-pointer select-none text-slate-300" data-testid="geofence-numbers-toggle">Corners as numbers ({poly.length})</summary>
        <div className="mt-2 space-y-1.5">
          {poly.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-6 text-right text-slate-500">{i + 1}</span>
              {[0, 1].map((j) => (
                <CornerInput
                  key={j}
                  label={`Corner ${i + 1} ${gnss ? (j ? 'latitude' : 'longitude') : j ? 'y' : 'x'}`}
                  value={p[j]}
                  disabled={disabled}
                  onCommit={(v) => setCorner(i, j ? [p[0], v] : [v, p[1]])}
                />
              ))}
              {!disabled && (
                <button type="button" onClick={() => onChange(poly.filter((_, j) => j !== i))} aria-label={`Remove corner ${i + 1}`} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
          {!disabled && (
            <button
              type="button"
              onClick={() => {
                const c = live.find((l) => l.now)?.now ?? track[track.length - 1] ?? [0, 0];
                onChange([...poly, [roundCoord(c[0], gnss), roundCoord(c[1], gnss)]]);
              }}
              className="inline-flex min-h-[32px] items-center gap-1 rounded-md border border-slate-700 px-2 text-slate-300 hover:bg-slate-800"
              data-testid="geofence-add-corner"
            >
              <Plus className="h-3.5 w-3.5" /> Add a corner
            </button>
          )}
          <p className="text-slate-500">{gnss ? 'Each corner is a longitude, then a latitude.' : 'Each corner is a site x, then a site y, in the same units the asset reports.'}</p>
        </div>
      </details>
    </div>
  );
}
