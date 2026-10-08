'use client';

import { useState } from 'react';
import { ChevronDown, Server } from 'lucide-react';
import { fmtAge, fmtBytes, fmtCores, pct, usageTone, type ClusterNode } from '@/lib/cluster';

const PRESSURE_TEXT: Record<string, string> = {
  MemoryPressure: 'Low memory',
  DiskPressure: 'Low disk',
  PIDPressure: 'Out of process slots',
  NetworkUnavailable: 'No network',
};

export function UsageBar({ label, value, detail, testid }: { label: string; value: number | null; detail: string; testid?: string }) {
  const tone = usageTone(value);
  const fill = tone === 'bad' ? 'bg-red-500' : tone === 'warn' ? 'bg-amber-400' : 'bg-cyan-400';
  return (
    <div data-testid={testid}>
      <div className="flex items-baseline justify-between gap-2 text-[11px] mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300 tabular-nums text-right truncate">{detail}</span>
      </div>
      <div
        className="h-2 w-full rounded-full bg-slate-800 overflow-hidden"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value == null ? undefined : Math.round(value)}
      >
        {value != null && <div className={`h-full ${fill} transition-[width] duration-500`} style={{ width: `${Math.max(2, value)}%` }} />}
      </div>
    </div>
  );
}

export default function NodeCard({ node, metricsAvailable, highlight, wide }: { node: ClusterNode; metricsAvailable: boolean; highlight?: boolean; wide?: boolean }) {
  const [open, setOpen] = useState(false);
  const usedCpu = node.cpu_used_cores;
  const usedMem = node.mem_used_bytes;
  const cpuPct = usedCpu != null ? pct(usedCpu, node.cpu_allocatable_cores) : pct(node.cpu_requested_cores, node.cpu_allocatable_cores);
  const memPct = usedMem != null ? pct(usedMem, node.mem_allocatable_bytes) : pct(node.mem_requested_bytes, node.mem_allocatable_bytes);
  const podPct = pct(node.pods_here, node.pods_capacity);
  const healthy = node.ready && node.pressure.length === 0;
  const meta = [node.roles.join(', '), node.pool && `pool ${node.pool}`, node.zone, node.instance_type].filter(Boolean).join(' · ');

  return (
    <div
      id={`node-${node.name}`}
      className={`rounded-xl border bg-slate-900/40 p-4 min-w-0 transition-shadow ${healthy ? 'border-slate-700/60' : 'border-amber-500/40'} ${highlight ? 'ring-2 ring-cyan-400/60' : ''}`}
      data-testid="node-card"
      data-node={node.name}
      data-ready={node.ready ? 'true' : 'false'}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Server className="w-4 h-4 text-slate-400 shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white truncate" title={node.name}>{node.name}</div>
            <div className="text-[11px] text-slate-500 truncate">{meta || 'worker'}</div>
          </div>
        </div>
        <span
          className={`shrink-0 inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full border ${node.ready ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-red-500/40 bg-red-500/10 text-red-300'}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${node.ready ? 'bg-emerald-400' : 'bg-red-400'}`} />
          {node.ready ? 'Ready' : 'Not ready'}
        </span>
      </div>

      {(node.pressure.length > 0 || node.unschedulable) && (
        <div className="flex flex-wrap gap-1.5 mb-3" data-testid="node-flags">
          {node.pressure.map((p) => (
            <span key={p} className="text-[11px] px-2 py-0.5 rounded-md border border-red-500/40 bg-red-500/10 text-red-300">
              {PRESSURE_TEXT[p] || p}
            </span>
          ))}
          {node.unschedulable && (
            <span className="text-[11px] px-2 py-0.5 rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-300" title="New pods will not be scheduled here">
              Cordoned
            </span>
          )}
        </div>
      )}

      <div className={wide ? 'grid grid-cols-1 md:grid-cols-3 gap-3 md:gap-6' : 'space-y-3'}>
        <UsageBar
          label={usedCpu != null ? 'CPU in use' : 'CPU requested'}
          value={cpuPct}
          detail={`${fmtCores(usedCpu ?? node.cpu_requested_cores)} of ${fmtCores(node.cpu_allocatable_cores)} cores`}
          testid="node-cpu"
        />
        <UsageBar
          label={usedMem != null ? 'Memory in use' : 'Memory requested'}
          value={memPct}
          detail={`${fmtBytes(usedMem ?? node.mem_requested_bytes)} of ${fmtBytes(node.mem_allocatable_bytes)}`}
          testid="node-mem"
        />
        <UsageBar label="Pods from this platform" value={podPct} detail={`${node.pods_here} of ${node.pods_capacity} slots`} />
      </div>
      {!metricsAvailable && (
        <p className="text-[11px] text-slate-500 mt-2">Live use needs metrics-server, so these bars show what pods asked for.</p>
      )}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="mt-3 w-full flex items-center justify-between text-[11px] text-slate-400 hover:text-slate-200 min-h-[32px]"
        aria-expanded={open}
      >
        <span>
          {fmtCores(node.cpu_cores)} cores · {fmtBytes(node.mem_bytes)} · {node.kubelet_version || 'kubelet ?'} · up {fmtAge(node.age_seconds)}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="mt-2 border-t border-slate-800 pt-2 space-y-2 text-[11px]">
          <div className="grid grid-cols-1 gap-1">
            {node.conditions.map((c) => {
              const bad = c.type === 'Ready' ? c.status !== 'True' : c.status === 'True';
              return (
                <div key={c.type} className="flex items-start justify-between gap-2">
                  <span className="text-slate-400">{c.type}</span>
                  <span className={`text-right ${bad ? 'text-red-300' : 'text-slate-300'}`} title={c.message || ''}>
                    {c.status === 'True' ? 'yes' : c.status === 'False' ? 'no' : c.status}
                    {c.reason ? ` · ${c.reason}` : ''}
                  </span>
                </div>
              );
            })}
          </div>
          <div>
            <div className="text-slate-400 mb-1">Taints</div>
            {node.taints.length ? (
              <div className="flex flex-wrap gap-1">
                {node.taints.map((t, i) => (
                  <code key={i} className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 break-all">
                    {t.key}{t.value ? `=${t.value}` : ''}:{t.effect}
                  </code>
                ))}
              </div>
            ) : (
              <div className="text-slate-500">None, any pod can land here.</div>
            )}
          </div>
          {(node.os_image || node.container_runtime) && (
            <div className="text-slate-500 break-words">{[node.os_image, node.container_runtime].filter(Boolean).join(' · ')}</div>
          )}
        </div>
      )}
    </div>
  );
}
