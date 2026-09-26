'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Activity, BrainCircuit, Cpu, ChevronRight, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useContractIQExecutions } from './ContractIQExecutionsProvider';

import { authFetch } from './authFetch';

// Routes that benefit from the rail narrating progress — auto-open here.
// Anywhere else, default to collapsed to reduce visual noise.
const AUTO_OPEN_PREFIXES = ['/recommendations', '/commodities/forward', '/insights/stress-test'];

function shouldAutoOpen(pathname: string | null): boolean {
  if (!pathname) return false;
  return AUTO_OPEN_PREFIXES.some(p => pathname === p || pathname.startsWith(p + '/'));
}

interface LiveAgent {
  id: string;
  agent_slug: string;
  agent_name: string;
  status: 'running' | 'pending' | 'completed' | 'failed';
  started_at: number;
  cost_so_far?: number;
  tokens_in?: number;
  tokens_out?: number;
  current_tool?: string;
}

interface LiveModel {
  id: string;
  model_slug: string;
  model_family: string;
  status: 'running' | 'completed' | 'failed';
  started_at: number;
  predictions_count?: number;
}

function fmtAgo(ts: number) {
  const dt = Date.now() - ts;
  if (dt < 1000) return 'now';
  if (dt < 60_000) return `${Math.floor(dt / 1000)}s`;
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)}m`;
  return `${Math.floor(dt / 3_600_000)}h`;
}

const STATUS_TONE: Record<string, string> = {
  running:   'border-cyan-500/40 bg-cyan-500/10 text-cyan-200',
  pending:   'border-slate-700 bg-slate-800/30 text-slate-400',
  completed: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  failed:    'border-rose-500/40 bg-rose-500/10 text-rose-200',
};

export default function LiveActivityRail() {
  const { selectExecutionForDrawer, drawerExecutionId } = useContractIQExecutions();
  const pathname = usePathname();
  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const [models, setModels] = useState<LiveModel[]>([]);
  // Default collapsed; auto-open only on narrative-heavy routes.
  const [collapsed, setCollapsed] = useState(true);
  const [userToggled, setUserToggled] = useState(false);
  const [loading, setLoading] = useState(true);

  // Apply route-based default collapse unless the user has explicitly toggled.
  useEffect(() => {
    if (userToggled) return;
    setCollapsed(!shouldAutoOpen(pathname));
  }, [pathname, userToggled]);

  useEffect(() => {
    let cancelled = false;
    const fetchAll = async () => {
      try {
        const [a, m] = await Promise.all([
          authFetch('/api/contractiq-executions?status=running&limit=20', { cache: 'no-store' }).then(r => r.ok ? r.json() : { data: [] }),
          authFetch('/api/contractiq-executions/ml-models?status=running&limit=10', { cache: 'no-store' }).then(r => r.ok ? r.json() : { data: [] }),
        ]);
        if (cancelled) return;
        const rawA = Array.isArray(a?.data) ? a.data : [];
        const rawM = Array.isArray(m?.data) ? m.data : [];
        setAgents(rawA.map((row: any) => ({
          id: row.id || row.execution_id,
          agent_slug: row.agent_slug || row.agent_id || 'agent',
          agent_name: row.agent_name || row.agent_slug || row.agent_id || 'Agent',
          status: (String(row.status || 'pending').toLowerCase() as any),
          started_at: row.started_at ? new Date(row.started_at).getTime() : Date.now(),
          cost_so_far: row.cost,
          tokens_in: row.input_tokens,
          tokens_out: row.output_tokens,
          current_tool: row.current_tool,
        })));
        setModels(rawM.map((row: any) => ({
          id: row.id || row.invocation_id,
          model_slug: row.model_slug || row.model_id,
          model_family: row.family || 'ML',
          status: (String(row.status || 'pending').toLowerCase() as any),
          started_at: row.started_at ? new Date(row.started_at).getTime() : Date.now(),
          predictions_count: row.predictions_count,
        })));
      } catch {
        if (!cancelled) { setAgents([]); setModels([]); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchAll();
    const t = setInterval(fetchAll, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const totalCount = agents.length + models.length;

  const openRail = () => { setUserToggled(true); setCollapsed(false); };
  const closeRail = () => { setUserToggled(true); setCollapsed(true); };

  if (collapsed) {
    return (
      <button
        onClick={openRail}
        className="fixed top-1/2 right-3 -translate-y-1/2 z-30 bg-slate-900/95 border border-emerald-500/30 text-emerald-300 px-2 py-3 rounded-l-lg shadow-lg hover:bg-slate-800 transition-colors flex flex-col items-center gap-2"
        title="Show live activity"
      >
        <Activity className="w-3.5 h-3.5 animate-pulse" />
        <span className="text-[9px] uppercase tracking-wider" style={{ writingMode: 'vertical-rl' }}>Live · {totalCount}</span>
        <ChevronRight className="w-3 h-3 rotate-180" />
      </button>
    );
  }

  return (
    <aside className="w-72 shrink-0 bg-slate-900/40 border-l border-slate-800/50 flex flex-col h-screen sticky top-0 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
          <span className="text-[11px] text-emerald-200 font-semibold">
            Live agents ({agents.length}) <span className="text-slate-500">·</span> Live models ({models.length})
          </span>
        </div>
        <button onClick={closeRail} className="text-slate-500 hover:text-white p-1" title="Collapse">
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-3 text-[11px]">
        <Section icon={BrainCircuit} title="Agents in flight" count={agents.length}>
          {loading && agents.length === 0 ? (
            <p className="text-slate-600 italic px-2 py-2">connecting…</p>
          ) : agents.length === 0 ? (
            <p className="text-slate-600 italic px-2 py-2">No agents running on Abenix.</p>
          ) : agents.map(a => (
            <button
              key={a.id}
              onClick={() => selectExecutionForDrawer(a.id)}
              className={`w-full text-left p-2 rounded-md border transition-colors ${STATUS_TONE[a.status] || STATUS_TONE.pending} ${drawerExecutionId === a.id ? 'ring-1 ring-emerald-400' : ''}`}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-mono text-[10px] truncate flex items-center gap-1.5">
                  <StatusDot status={a.status} />
                  {a.agent_name}
                </span>
                <span className="text-[9px] uppercase tracking-wider opacity-70 shrink-0">{a.status}</span>
              </div>
              <p className="text-[9px] opacity-70 truncate font-mono">#{String(a.id).slice(0, 8)} · {fmtAgo(a.started_at)} ago</p>
              {a.current_tool && (
                <p className="text-[9px] opacity-70 truncate mt-0.5">→ {a.current_tool}</p>
              )}
              {(a.cost_so_far != null || a.tokens_in != null) && (
                <p className="text-[9px] opacity-60 truncate mt-0.5 font-mono">
                  {a.cost_so_far != null && <span>${(a.cost_so_far || 0).toFixed(4)}</span>}
                  {a.tokens_in != null && <span className="ml-1.5">· {a.tokens_in?.toLocaleString?.()}→{a.tokens_out?.toLocaleString?.()} tok</span>}
                </p>
              )}
            </button>
          ))}
        </Section>

        <Section icon={Cpu} title="ML models invoking" count={models.length}>
          {loading && models.length === 0 ? (
            <p className="text-slate-600 italic px-2 py-2">connecting…</p>
          ) : models.length === 0 ? (
            <p className="text-slate-600 italic px-2 py-2">No ML models firing right now.</p>
          ) : models.map(m => (
            <div
              key={m.id}
              className={`p-2 rounded-md border ${STATUS_TONE[m.status] || STATUS_TONE.pending}`}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-mono text-[10px] truncate flex items-center gap-1.5">
                  <StatusDot status={m.status} />
                  {m.model_slug}
                </span>
                <span className="text-[9px] uppercase tracking-wider opacity-70 shrink-0">{m.status}</span>
              </div>
              <p className="text-[9px] opacity-70 truncate font-mono">{m.model_family} · {fmtAgo(m.started_at)} ago</p>
              {m.predictions_count != null && (
                <p className="text-[9px] opacity-60 mt-0.5">{m.predictions_count} prediction{m.predictions_count === 1 ? '' : 's'}</p>
              )}
            </div>
          ))}
        </Section>

        <p className="text-[9px] text-slate-600 italic px-2 pt-1">Polls every 5 s · click any agent for live DAG</p>
      </div>
    </aside>
  );
}

function Section({ icon: Icon, title, count, children }: { icon: any; title: string; count?: number; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 px-2 mb-1.5">
        <Icon className="w-3 h-3 text-slate-500" />
        <span className="text-[9px] uppercase tracking-[0.12em] text-slate-500 font-semibold">{title}</span>
        {count != null && count > 0 && (
          <span className="text-[9px] text-slate-400 font-mono ml-auto">{count}</span>
        )}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  if (status === 'running') return <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />;
  if (status === 'completed') return <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
  if (status === 'failed') return <AlertCircle className="w-3 h-3 text-rose-400" />;
  return <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />;
}
