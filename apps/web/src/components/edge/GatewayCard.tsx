'use client';

import { AlertTriangle, ChevronRight, Clock, Database, Radio, Send } from 'lucide-react';
import { count, duration, isCollecting, statusOf, timeAgo, type Gateway } from './model';
import { pluralShown } from '@/lib/plural';

export function StatusChip({ status, testId }: { status: string; testId?: string }) {
  const s = statusOf(status);
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] ${s.chip}`} title={s.help} data-testid={testId}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden /> {s.label}
    </span>
  );
}

export default function GatewayCard({ g, onOpen, onDeploy, canManage }: { g: Gateway; onOpen: () => void; onDeploy?: () => void; canManage: boolean }) {
  const collecting = isCollecting(g);
  const bad = (g.collector_health || []).filter((c) => c.status === 'error');
  const depth = g.buffer?.depth ?? 0;
  const age = g.buffer?.oldest_age_s ?? 0;
  const backlog = depth > 0 && age > 120;
  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-slate-700/60 bg-slate-800/30 p-4" data-testid="edge-gateway-card" data-gateway={g.gateway_id}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-medium text-white" title={g.name}>{g.name || g.gateway_id}</h3>
          <p className="truncate font-mono text-[11px] text-slate-500">{g.gateway_id}</p>
        </div>
        <StatusChip status={g.status} testId="edge-gateway-status" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px] text-slate-300">
        <span className="flex items-center gap-1.5"><Clock className="h-3 w-3 text-slate-500" /> {g.status === 'waiting' || g.status === 'expired' ? 'Not started yet' : `Seen ${timeAgo(g.last_seen_at)}`}</span>
        <span className="flex items-center gap-1.5"><Radio className="h-3 w-3 text-slate-500" /> {collecting ? `${g.collector_count} ${g.collector_count === 1 ? 'collector' : 'collectors'}` : 'Agents only'}</span>
        {collecting && g.enrolled_at && (
          <span className={`col-span-2 flex items-center gap-1.5 ${backlog ? 'text-amber-200' : ''}`}>
            <Database className="h-3 w-3 text-slate-500" /> {!depth ? 'Buffer empty, all sent' : age >= 1 ? `${pluralShown(depth, count(depth), 'reading')} waiting, oldest ${duration(age)}` : `${pluralShown(depth, count(depth), 'reading')} about to be sent`}
          </span>
        )}
        {(g.roles || []).includes('agents') && (
          <span className="col-span-2 flex items-center gap-1.5"><Send className="h-3 w-3 text-slate-500" /> {pluralShown(g.deployed_agents?.length || 0, (g.deployed_agents?.length || 0).toLocaleString('en-US'), 'agent')} deployed</span>
        )}
      </div>
      {(bad.length > 0 || g.problem || g.config_pending) && (
        <div className="mt-3 space-y-1">
          {bad.slice(0, 2).map((c) => (
            <p key={c.id} className="flex items-start gap-1.5 text-[11px] text-rose-200"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /><span className="min-w-0 break-words"><strong>{c.name}:</strong> {c.error}</span></p>
          ))}
          {g.problem && <p className="flex items-start gap-1.5 text-[11px] text-rose-200"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /><span className="min-w-0 break-words">{g.problem}</span></p>}
          {g.config_pending && <p className="text-[11px] text-sky-200">Changes are waiting for the next heartbeat.</p>}
        </div>
      )}
      <div className="mt-auto flex flex-wrap gap-2 pt-3">
        <button type="button" onClick={onOpen} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-700/50" data-testid="edge-gateway-open">
          Details <ChevronRight className="h-3.5 w-3.5" />
        </button>
        {canManage && onDeploy && (g.roles || []).includes('agents') && (
          <button type="button" onClick={onDeploy} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/15 px-3 py-1.5 text-xs text-cyan-200 hover:bg-cyan-500/25" data-testid="edge-gateway-deploy">
            <Send className="h-3.5 w-3.5" /> Deploy agent
          </button>
        )}
      </div>
    </div>
  );
}
