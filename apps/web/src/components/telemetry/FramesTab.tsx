'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { List, useListRef, type RowComponentProps } from 'react-window';
import { ArrowDownToLine, Binary, Loader2, Pause, Play, Search, Trash2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { BamAssembler, KNOWN_ACRONYMS, decodeFrame, hexOf, idHex, normalizeFrame, type DecodedFrame } from '@/lib/telemetry/j1939';
import { clock, rate } from '@/lib/telemetry/format';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import type { NodeEntry } from '@/lib/telemetry/store';
import { useIsMobile } from '@/hooks/useMediaQuery';

export const FRAME_CAP = 2000;
const POLL_MS = 500;

export function frameKey(f: { t: number; id: number; data: number[] }): string {
  return `${f.t}|${f.id}|${f.data.join(',')}`;
}

// new frames from a poll of the newest ring, oldest first, never one twice
export function freshFrames(raw: unknown, seen: Set<string>): ReturnType<typeof normalizeFrame>[] {
  const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' && Array.isArray((raw as { frames?: unknown[] }).frames) ? (raw as { frames: unknown[] }).frames : [];
  const out = list.map(normalizeFrame).filter((f): f is NonNullable<typeof f> => !!f && !seen.has(frameKey(f)));
  out.sort((a, b) => a!.t - b!.t);
  return out;
}

export function matchesFrame(f: DecodedFrame, pgn: string, q: string): boolean {
  if (pgn === 'other' && f.acronym && KNOWN_ACRONYMS.includes(f.acronym)) return false;
  if (pgn && pgn !== 'other' && f.acronym !== pgn) return false;
  const s = q.trim().toLowerCase();
  if (!s) return true;
  const sa = f.sa.toString(16).padStart(2, '0');
  return idHex(f.id).toLowerCase().includes(s) || String(f.pgn).includes(s) || sa === s.replace(/^0x/, '') || f.summary.toLowerCase().includes(s) || (f.acronym ?? '').toLowerCase() === s;
}

interface RowProps { items: DecodedFrame[]; selected: number; onPick: (i: number) => void; mobile: boolean }

function FrameRow({ index, style, items, selected, onPick, mobile }: RowComponentProps<RowProps>) {
  const f = items[index];
  const on = index === selected;
  const pgnCls = f.acronym === 'DM1' && f.dm1?.dtcs.length ? 'bg-rose-500/15 text-rose-200' : f.acronym && KNOWN_ACRONYMS.includes(f.acronym) ? 'bg-cyan-500/10 text-cyan-200' : 'bg-slate-800 text-slate-400';
  if (mobile) {
    return (
      <button type="button" style={style} onClick={() => onPick(index)} className={`block w-full border-b border-slate-800/80 px-3 py-1.5 text-left font-mono text-[11px] ${on ? 'bg-cyan-500/10' : ''}`} data-testid="tel-frame-row" data-pgn={f.acronym ?? f.pgn}>
        <span className="flex items-center gap-2">
          <span className="text-slate-500">{clock(f.ms, true)}</span>
          <span className={`rounded px-1 ${pgnCls}`}>{f.acronym ?? f.pgn}</span>
          <span className="text-slate-400">SA {f.sa.toString(16).toUpperCase().padStart(2, '0')}</span>
          <span className="ml-auto text-slate-500">{idHex(f.id)}</span>
        </span>
        <span className="mt-0.5 block truncate font-sans text-slate-300">{f.summary}</span>
      </button>
    );
  }
  return (
    <button type="button" style={style} onClick={() => onPick(index)} className={`grid w-full grid-cols-[7.5rem_6.5rem_7.5rem_3.5rem_13.5rem_minmax(0,1fr)] items-center gap-2 border-b border-slate-800/80 px-3 text-left font-mono text-xs ${on ? 'bg-cyan-500/10' : 'hover:bg-slate-800/40'}`} data-testid="tel-frame-row" data-pgn={f.acronym ?? f.pgn}>
      <span className="tabular-nums text-slate-500">{clock(f.ms, true)}</span>
      <span className="text-slate-300">{idHex(f.id)}</span>
      <span className="flex items-center gap-1.5"><span className={`rounded px-1 ${pgnCls}`}>{f.acronym ?? '—'}</span><span className="text-slate-500">{f.pgn}</span></span>
      <span className="text-slate-300">{f.sa.toString(16).toUpperCase().padStart(2, '0')}</span>
      <span className="truncate text-slate-200">{hexOf(f.data)}</span>
      <span className="truncate font-sans text-slate-300">{f.summary}</span>
    </button>
  );
}

export default function FramesTab({ nodes, group, node, setNode, canManage, openConnections, active }: {
  nodes: NodeEntry[]; group: string; node: string; setNode: (g: string, n: string) => void; canManage: boolean; openConnections: () => void; active: boolean;
}) {
  const mobile = useIsMobile();
  const [frames, setFrames] = useState<DecodedFrame[]>([]);
  const [paused, setPaused] = useState(false);
  const [pgn, setPgn] = useState('');
  const [q, setQ] = useState('');
  const [follow, setFollow] = useState(true);
  const [selected, setSelected] = useState(-1);
  const [fps, setFps] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  const bam = useRef(new BamAssembler());
  const listRef = useListRef(null);

  const target = nodes.find((n) => n.node === node && (!group || n.group === group)) ?? null;

  useEffect(() => {
    setFrames([]);
    setSelected(-1);
    setLoading(true);
    setErr(null);
    seen.current = new Set();
    bam.current = new BamAssembler();
  }, [group, node]);

  useEffect(() => {
    if (!active || paused || !target) return;
    let stop = false;
    let last = Date.now();
    const tick = async () => {
      const res = await apiFetch<unknown>(`/api/telemetry/frames/${encodeURIComponent(target.group)}/${encodeURIComponent(target.node)}?limit=500`, { silent: true });
      if (stop) return;
      setLoading(false);
      if (res.error) {
        setErr(explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'frames'));
        return;
      }
      setErr(null);
      const fresh = freshFrames(res.data, seen.current);
      const now = Date.now();
      setFps(fresh.length / Math.max(0.25, (now - last) / 1000));
      last = now;
      if (!fresh.length) return;
      const decoded = fresh.map((f) => bam.current.push(decodeFrame(f!)));
      for (const f of fresh) seen.current.add(frameKey(f!));
      if (seen.current.size > FRAME_CAP * 3) seen.current = new Set(Array.from(seen.current).slice(-FRAME_CAP * 2));
      setFrames((prev) => {
        const next = prev.concat(decoded);
        return next.length > FRAME_CAP ? next.slice(next.length - FRAME_CAP) : next;
      });
    };
    void tick();
    const h = setInterval(tick, POLL_MS);
    return () => {
      stop = true;
      clearInterval(h);
    };
  }, [active, paused, target?.group, target?.node]);

  const shown = useMemo(() => frames.filter((f) => matchesFrame(f, pgn, q)), [frames, pgn, q]);

  useEffect(() => {
    if (!follow || !shown.length) return;
    try { listRef.current?.scrollToRow({ index: shown.length - 1, align: 'end' }); } catch { /* list not mounted yet */ }
  }, [shown.length, follow, listRef]);

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setFollow(atEnd);
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of frames) c[f.acronym && KNOWN_ACRONYMS.includes(f.acronym) ? f.acronym : 'other'] = (c[f.acronym && KNOWN_ACRONYMS.includes(f.acronym) ? f.acronym : 'other'] ?? 0) + 1;
    return c;
  }, [frames]);

  const sel = selected >= 0 ? shown[selected] : null;
  const rowH = mobile ? 52 : 34;

  if (!nodes.length) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300" data-testid="tel-frames-no-nodes">
        <Binary className="mx-auto h-8 w-8 text-cyan-400" />
        <p className="mt-2 font-medium text-white">No assets yet, so there is no CAN bus to show.</p>
        <p className="mt-1">Assets appear on the Assets tab with their first message. Raw CAN frames show here for sources that carry them.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" data-testid="tel-frames-toolbar">
        <label className="min-w-[10rem]">
          <span className="sr-only">Asset</span>
          <select
            value={target ? `${target.group}/${target.node}` : ''}
            onChange={(e) => { const [g, ...rest] = e.target.value.split('/'); setNode(g, rest.join('/')); }}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 font-mono text-sm text-slate-200"
            data-testid="tel-frames-node"
          >
            {!target && <option value="">Pick an asset</option>}
            {nodes.map((n) => <option key={n.key} value={`${n.group}/${n.node}`}>{n.node} ({n.group})</option>)}
          </select>
        </label>
        <button type="button" onClick={() => setPaused((p) => !p)} disabled={!target} className={`inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm ${paused ? 'border-amber-500/50 bg-amber-500/10 text-amber-100' : 'border-slate-700 text-slate-200 hover:bg-slate-800'}`} data-testid="tel-frames-pause" title={!target ? 'Pick an asset first' : undefined}>
          {paused ? <><Play className="h-4 w-4" /> Resume</> : <><Pause className="h-4 w-4" /> Pause</>}
        </button>
        <button type="button" onClick={() => { setFrames([]); setSelected(-1); }} disabled={!frames.length} title={!frames.length ? 'Nothing to clear yet' : 'Clear the trace on screen, the asset keeps sending'} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40" data-testid="tel-frames-clear">
          <Trash2 className="h-4 w-4" /> Clear trace
        </button>
        <label className="relative min-w-[10rem] flex-1 sm:max-w-xs">
          <span className="sr-only">Find in frames</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="CAN id, PGN, source or text" className="w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-7 text-sm text-white placeholder:text-slate-500" data-testid="tel-frames-search" />
          {q && <button type="button" aria-label="Clear the search" onClick={() => setQ('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-white"><X className="h-3.5 w-3.5" /></button>}
        </label>
        <span className="ml-auto text-xs tabular-nums text-slate-400" data-testid="tel-frames-rate">
          {paused ? `Paused, ${frames.length} frames kept` : `${rate(fps)} frames/s, ${frames.length} kept`}
        </span>
      </div>

      <div className="scrollbar-none -mx-1 flex gap-1 overflow-x-auto px-1" role="group" aria-label="Show only">
        {['', ...KNOWN_ACRONYMS, 'other'].map((a) => (
          <button key={a || 'all'} type="button" onClick={() => setPgn(a)} aria-pressed={pgn === a} className={`shrink-0 rounded-md border px-2 py-1 font-mono text-[11px] ${pgn === a ? 'border-cyan-400 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-300 hover:border-slate-500'}`} data-testid={`tel-pgn-${a || 'all'}`}>
            {a === '' ? 'All' : a === 'other' ? 'Other' : a}
            {a && counts[a] ? <span className="ml-1 text-slate-500">{counts[a]}</span> : null}
          </button>
        ))}
      </div>

      <div className="relative overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950/60" data-testid="tel-frames">
        {!mobile && (
          <div className="grid grid-cols-[7.5rem_6.5rem_7.5rem_3.5rem_13.5rem_minmax(0,1fr)] gap-2 border-b border-slate-700 px-3 py-2 text-[10px] uppercase tracking-wide text-slate-500">
            <span>Time</span><span>CAN id</span><span>PGN</span><span>Source</span><span>Data</span><span>Decoded</span>
          </div>
        )}
        {err && !frames.length ? (
          <p className="p-4 text-sm text-rose-200" role="alert" data-testid="tel-frames-error">{err}</p>
        ) : loading && target ? (
          <p className="flex items-center gap-2 p-4 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Reading the newest frames from {target.node}</p>
        ) : !frames.length ? (
          <div className="p-5 text-sm text-slate-300" data-testid="tel-frames-empty">
            <p className="font-medium text-white">No CAN frames from {target?.node ?? 'this asset'} yet.</p>
            <p className="mt-1">Frames come from the raw topics set on the broker connection, for example <code className="rounded bg-slate-800 px-1 text-xs">groundwork/+/can/raw</code>. Each message is JSON with t, id, data and dlc.</p>
            {canManage ? (
              <button type="button" onClick={openConnections} className="mt-2 text-cyan-300 hover:underline" data-testid="tel-frames-add-raw">Add raw topics to a connection</button>
            ) : (
              <p className="mt-1 text-slate-400">An admin sets the raw topics under Telemetry, Connections.</p>
            )}
          </div>
        ) : !shown.length ? (
          <p className="p-4 text-sm text-slate-300" data-testid="tel-frames-no-match">No frames match. <button type="button" className="text-cyan-300 hover:underline" onClick={() => { setPgn(''); setQ(''); }}>Show all frames</button></p>
        ) : (
          <List
            listRef={listRef}
            rowCount={shown.length}
            rowHeight={rowH}
            rowComponent={FrameRow}
            rowProps={{ items: shown, selected, onPick: setSelected, mobile }}
            overscanCount={10}
            onScroll={onScroll}
            defaultHeight={420}
            style={{ height: 420 }}
          />
        )}
        {!follow && shown.length > 0 && (
          <button type="button" onClick={() => setFollow(true)} className="absolute bottom-3 right-3 inline-flex items-center gap-1.5 rounded-full bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white shadow-lg hover:bg-cyan-400" data-testid="tel-frames-follow">
            <ArrowDownToLine className="h-3.5 w-3.5" /> Jump to newest
          </button>
        )}
      </div>

      {sel && (
        <section className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3 text-sm" data-testid="tel-frame-detail">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="font-mono font-semibold text-white">{sel.acronym ?? `PGN ${sel.pgn}`}</h3>
            <span className="text-xs text-slate-400">{sel.name ?? 'Not a PGN Abenix decodes'}</span>
            <span className="ml-auto font-mono text-xs text-slate-500">id {idHex(sel.id)} · priority {sel.priority} · source {sel.sa} · {sel.dlc} bytes</span>
            <button type="button" onClick={() => setSelected(-1)} aria-label="Close the frame detail" className="p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
          </div>
          {sel.signals.length > 0 && (
            <table className="mt-2 w-full text-xs">
              <thead><tr className="text-left text-[10px] uppercase tracking-wide text-slate-500"><th className="py-1 font-normal">Signal</th><th className="py-1 text-right font-normal">Value</th></tr></thead>
              <tbody>
                {sel.signals.map((s) => (
                  <tr key={s.key} className="border-t border-slate-800">
                    <td className="py-1 text-slate-300">{s.label}</td>
                    <td className="py-1 text-right tabular-nums text-white">{s.text}{s.unit && s.value !== null ? ` ${s.unit}` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {sel.dm1 && (
            <div className="mt-2 text-xs text-slate-300">
              {sel.dm1.dtcs.length ? (
                <ul className="space-y-1">
                  {sel.dm1.dtcs.map((d, i) => <li key={i}><span className="font-mono text-rose-200">SPN {d.spn} FMI {d.fmi}</span> {d.spnText}, {d.fmiText.toLowerCase()}, seen {d.oc} time{d.oc === 1 ? '' : 's'}</li>)}
                </ul>
              ) : <p>No active fault codes.</p>}
            </div>
          )}
          {!sel.signals.length && !sel.dm1 && <p className="mt-2 text-xs text-slate-400">{sel.summary}</p>}
        </section>
      )}
    </div>
  );
}
