'use client';

import { ChevronRight, RotateCcw } from 'lucide-react';
import ReplicaSparkline from './ReplicaSparkline';
import {
  STATUS_STYLE, agoText, fmtAge, fmtBytes, fmtCores, metricText, scalingText, secondsSince,
  type PodSummary, type Workload,
} from '@/lib/cluster';

function PodRow({ pod, onOpen }: { pod: PodSummary; onOpen: (name: string) => void }) {
  const bad = !pod.ready && pod.phase !== 'Succeeded';
  return (
    <button
      type="button"
      onClick={() => onOpen(pod.name)}
      className="w-full text-left flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 rounded-lg border border-slate-800 bg-slate-950/40 hover:border-cyan-500/40 hover:bg-slate-900 min-h-[44px]"
      data-testid="pod-row"
      data-pod={pod.name}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${bad ? 'bg-amber-400' : 'bg-emerald-400'}`} />
      <span className="font-mono text-xs text-slate-200 break-all flex-1 min-w-[12rem]">{pod.name}</span>
      <span className={`text-[11px] ${bad ? 'text-amber-300' : 'text-slate-400'}`}>{pod.status}</span>
      <span className="text-[11px] text-slate-500">
        {pod.containers_ready}/{pod.containers_total} ready · {pod.restarts} restarts · {fmtAge(pod.age_seconds)}
        {pod.cpu_used_cores != null && ` · ${fmtCores(pod.cpu_used_cores)} CPU · ${fmtBytes(pod.mem_used_bytes)}`}
      </span>
      <span className="text-[11px] text-cyan-300 inline-flex items-center gap-0.5">Logs and events <ChevronRight className="w-3 h-3" /></span>
    </button>
  );
}

export default function ServiceRow({
  w, open, onToggle, onOpenPod, highlight,
}: { w: Workload; open: boolean; onToggle: () => void; onOpenPod: (name: string) => void; highlight?: boolean }) {
  const st = STATUS_STYLE[w.status];
  const last = w.last_restart;
  const lastAgo = last?.at ? secondsSince(last.at) : null;
  const s = w.scaling;
  return (
    <div
      id={`svc-${w.name}`}
      className={`rounded-xl border bg-slate-900/40 ${w.status === 'down' ? 'border-red-500/40' : w.status === 'degraded' ? 'border-amber-500/30' : 'border-slate-700/60'} ${highlight ? 'ring-2 ring-cyan-400/60' : ''}`}
      data-testid="service-row"
      data-service={w.name}
      data-display={w.display}
      data-group={w.group}
      data-status={w.status}
      data-ready={w.ready}
      data-desired={w.desired}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full text-left p-3 md:px-4 grid grid-cols-[1fr_auto] md:grid-cols-[minmax(0,2.2fr)_minmax(0,0.8fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1.6fr)_auto] gap-x-4 gap-y-2 items-center"
        data-testid="service-toggle"
      >
        <div className="min-w-0 col-span-1">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${st.dot}`} aria-hidden />
            <span className="text-sm font-medium text-white truncate" title={w.name}>{w.display}</span>
            {w.critical && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 shrink-0" title="The platform stops working if this is down">core</span>}
          </div>
          <div className={`text-[11px] mt-0.5 ${st.text} line-clamp-2`}>{w.status_text}</div>
        </div>

        <div className="col-start-2 row-start-1 md:col-start-auto md:row-start-auto text-right md:text-left">
          <div className="text-sm font-semibold text-white tabular-nums" data-testid="service-ready">
            {w.ready}/{w.desired}
          </div>
          <div className="text-[10px] text-slate-500">{w.kind === 'StatefulSet' ? 'stateful' : 'ready'}</div>
        </div>

        <div className="min-w-0 flex md:block items-center gap-2">
          <code className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 truncate inline-block max-w-full" title={w.images.map((i) => i.image).join('\n')} data-testid="service-image">
            {w.image_tag || '—'}
          </code>
          <div className="text-[10px] text-slate-500 md:mt-0.5">up {fmtAge(w.age_seconds)}</div>
        </div>

        <div className="min-w-0 text-[11px] text-right md:text-left">
          <div className={`inline-flex items-center gap-1 ${w.restarts ? 'text-amber-300' : 'text-slate-400'}`}>
            <RotateCcw className="w-3 h-3" /> {w.restarts} restart{w.restarts === 1 ? '' : 's'}
          </div>
          {last && (
            <div className="text-[10px] text-slate-500 truncate" title={`${last.container || ''} exit ${last.exit_code ?? '?'}`}>
              last: {last.reason || 'exited'}{lastAgo != null ? `, ${agoText(lastAgo)}` : ''}
            </div>
          )}
        </div>

        <div className="min-w-0 col-span-2 md:col-span-1 flex items-center gap-3 border-t border-slate-800/60 pt-2 md:border-0 md:pt-0">
          <div className="min-w-0 flex-1">
            <div className="text-[11px] text-slate-300 truncate">{scalingText(s)}</div>
            {s && s.metrics.length > 0 && (
              <div className="text-[10px] text-slate-500 truncate" title={s.metrics.map(metricText).join('\n')} data-testid="service-scaling-metric">
                {metricText(s.metrics[0])}
              </div>
            )}
            {s && s.current != null && (
              <div className="text-[10px] text-slate-500">now {s.current}{s.desired != null && s.desired !== s.current ? `, heading to ${s.desired}` : ''}</div>
            )}
          </div>
          <ReplicaSparkline history={w.history} />
        </div>

        <ChevronRight className={`hidden md:block w-4 h-4 text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {open && (
        <div className="px-3 md:px-4 pb-3 space-y-2" data-testid="service-pods">
          {s && s.metrics.length > 1 && (
            <div className="flex flex-wrap gap-2 text-[11px]">
              {s.metrics.map((m) => (
                <span key={m.name} className="px-2 py-1 rounded-md border border-slate-700/60 bg-slate-950/40 text-slate-300">{metricText(m)}</span>
              ))}
            </div>
          )}
          {w.pods.length ? (
            w.pods.map((p) => <PodRow key={p.name} pod={p} onOpen={onOpenPod} />)
          ) : (
            <div className="text-xs text-slate-500 px-1 py-2">
              {w.desired === 0 ? 'No pods right now. This service is scaled to zero and starts when work arrives.' : 'No pods found for this service yet.'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
