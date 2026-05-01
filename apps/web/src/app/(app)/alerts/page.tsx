'use client';

import { useState } from 'react';
import {
  AlertTriangle, Bell, ChevronDown, ChevronRight, ExternalLink,
  RefreshCw, Activity,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';

interface FailureGroup {
  failure_code: string;
  count: number;
  latest_at: string | null;
  agent_ids: string[];
  sample_message: string;
}

interface LiveStats {
  active_executions: number;
  today_failed: number;
  today_executions: number;
  today_total_tokens: number;
  today_cost: number;
  success_rate: number;
}

const CODE_DESCRIPTIONS: Record<string, string> = {
  LLM_RATE_LIMIT: 'Provider returned 429 Too Many Requests. Add backoff or raise account limits.',
  LLM_PROVIDER_ERROR: 'Anthropic/OpenAI/Google API errored. Often transient — check provider status page.',
  LLM_INVALID_RESPONSE: 'LLM returned a response we couldn\u2019t parse as JSON. Check the agent\u2019s output_schema or temperature.',
  SANDBOX_TIMEOUT: 'Sandbox pod hit activeDeadlineSeconds. Increase timeout_seconds or shrink the workload.',
  SANDBOX_NONZERO_EXIT: 'User code exited non-zero. Check the execution detail page for stderr.',
  SANDBOX_OOM: 'Container OOM-killed. Bump memory_mb on the sandbox call.',
  SANDBOX_IMAGE_BLOCKED: 'Requested image not in the sandbox allow-list. Add it in Settings → Sandbox.',
  TOOL_NOT_FOUND: 'Agent tried to call a tool that isn\u2019t registered. Check the palette/catalog wiring.',
  TOOL_ERROR: 'A registered tool raised. Look at the agent\u2019s tool_calls trace for which one.',
  BUDGET_EXCEEDED: 'Tenant or per-execution cost cap was hit. Raise the cap or lower temperature.',
  RATE_LIMITED: 'Per-user request rate limit triggered. Tune RATE_LIMIT_USER_REQ_PER_MIN.',
  STALE_SWEEP: 'Execution was stuck in RUNNING; sweeper marked it FAILED. Owning pod likely crashed.',
  INFRA_CRASH: 'Connection refused / reset / disconnect. Usually a downstream service is down.',
  INFRA_AUTH_ERROR: '401/403 against an internal service (k8s API, S3, etc.). Check service-account RBAC.',
  MODERATION_BLOCKED: 'Tenant moderation policy blocked the request or response. Check /moderation for policy + recent events.',
  UNKNOWN_ERROR: 'Couldn\u2019t classify this exception. Open the execution to see the raw error.',
};

const CODE_SEVERITY: Record<string, 'high' | 'med' | 'low'> = {
  LLM_RATE_LIMIT: 'med',
  LLM_PROVIDER_ERROR: 'high',
  LLM_INVALID_RESPONSE: 'low',
  SANDBOX_TIMEOUT: 'med',
  SANDBOX_NONZERO_EXIT: 'low',
  SANDBOX_OOM: 'high',
  SANDBOX_IMAGE_BLOCKED: 'low',
  TOOL_NOT_FOUND: 'med',
  TOOL_ERROR: 'med',
  BUDGET_EXCEEDED: 'high',
  RATE_LIMITED: 'med',
  STALE_SWEEP: 'high',
  INFRA_CRASH: 'high',
  INFRA_AUTH_ERROR: 'high',
  MODERATION_BLOCKED: 'med',
  UNKNOWN_ERROR: 'med',
};

const SEV_STYLES: Record<string, string> = {
  high: 'bg-red-500/10 border-red-500/40 text-red-300',
  med:  'bg-amber-500/10 border-amber-500/40 text-amber-300',
  low:  'bg-slate-500/10 border-slate-500/40 text-slate-300',
};

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function AlertsPage() {
  const [hours, setHours] = useState(24);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: stats, mutate: refreshStats } =
    useApi<LiveStats>('/api/analytics/live-stats');
  const { data: groups, mutate: refreshGroups } =
    useApi<FailureGroup[]>(`/api/analytics/failures?hours=${hours}`);

  const totalFailures = (groups || []).reduce((s, g) => s + g.count, 0);
  const failureRate = stats && stats.today_executions > 0
    ? Math.round(100 * stats.today_failed / stats.today_executions)
    : 0;

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-red-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">Alerts</h1>
              <p className="text-sm text-slate-400">
                Failures grouped by structured code so you can spot bursts and
                fix root causes instead of acknowledging one-by-one.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={hours}
              onChange={e => setHours(parseInt(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
            >
              <option value="1">Last hour</option>
              <option value="6">Last 6h</option>
              <option value="24">Last 24h</option>
              <option value="72">Last 3 days</option>
              <option value="168">Last week</option>
            </select>
            <button
              onClick={() => { refreshStats(); refreshGroups(); }}
              className="px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:text-white flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-4">
          <SummaryCard
            label={`Failures (${hours}h)`}
            value={String(totalFailures)}
            tone={totalFailures > 0 ? 'red' : 'green'}
            icon={<AlertTriangle className="w-4 h-4" />}
          />
          <SummaryCard
            label="Active runs"
            value={String(stats?.active_executions ?? 0)}
            tone={stats && stats.active_executions > 50 ? 'amber' : 'slate'}
            icon={<Activity className="w-4 h-4" />}
          />
          <SummaryCard
            label="Failure rate today"
            value={`${failureRate}%`}
            tone={failureRate > 20 ? 'red' : failureRate > 5 ? 'amber' : 'green'}
            icon={<Bell className="w-4 h-4" />}
          />
          <SummaryCard
            label="Distinct codes"
            value={String((groups || []).length)}
            tone="slate"
            icon={<Bell className="w-4 h-4" />}
          />
        </div>

        {/* Failure groups */}
        <div className="space-y-2">
          {(!groups || groups.length === 0) && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
              <Bell className="w-10 h-10 text-emerald-400/50 mx-auto mb-3" />
              <p className="text-sm text-slate-300">No failures in the last {hours} hour{hours === 1 ? '' : 's'}.</p>
              <p className="text-xs text-slate-500 mt-1">Your platform is healthy. The Grafana dashboard at /grafana has the full picture.</p>
            </div>
          )}

          {(groups || []).map(g => {
            const sev = CODE_SEVERITY[g.failure_code] || 'med';
            const isOpen = expanded === g.failure_code;
            return (
              <div key={g.failure_code} className={`rounded-xl border ${SEV_STYLES[sev]} overflow-hidden`}>
                <button
                  onClick={() => setExpanded(isOpen ? null : g.failure_code)}
                  className="w-full flex items-center gap-3 p-4 text-left hover:bg-white/5 transition-colors"
                >
                  {isOpen ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold">{g.failure_code}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 uppercase tracking-wider">
                        {sev}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {CODE_DESCRIPTIONS[g.failure_code] || 'No description.'}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-2xl font-bold tabular-nums">{g.count}</div>
                    <div className="text-[10px] text-slate-500 uppercase">latest {relTime(g.latest_at)}</div>
                  </div>
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 pt-2 border-t border-white/5 space-y-2 bg-black/20">
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-1">Sample error message</p>
                      <pre className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700/40 rounded p-2 overflow-x-auto whitespace-pre-wrap">{g.sample_message || '(empty)'}</pre>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-1">Affected agents ({g.agent_ids.length})</p>
                      <div className="flex flex-wrap gap-1.5">
                        {g.agent_ids.slice(0, 8).map(aid => (
                          <a key={aid} href={`/agents/${aid}`}
                             className="text-[11px] font-mono px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 inline-flex items-center gap-1">
                            {aid.slice(0, 8)} <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        ))}
                        {g.agent_ids.length > 8 && (
                          <span className="text-[11px] text-slate-500 px-2 py-1">+{g.agent_ids.length - 8} more</span>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer note */}
        <div className="text-xs text-slate-500 text-center py-4">
          Real-time metrics + 60 days of history at{' '}
          <a href="http://localhost:3030/d/abenix-overview" target="_blank" rel="noopener" className="text-cyan-400 hover:underline">
            Grafana → Abenix Operations
          </a>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, tone, icon }: {
  label: string; value: string; tone: 'red' | 'amber' | 'green' | 'slate';
  icon: React.ReactNode;
}) {
  const toneStyles = {
    red:    'bg-red-500/10 border-red-500/30 text-red-300',
    amber:  'bg-amber-500/10 border-amber-500/30 text-amber-300',
    green:  'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
    slate:  'bg-slate-700/20 border-slate-600/40 text-slate-300',
  }[tone];
  return (
    <div className={`rounded-xl border ${toneStyles} p-4`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider opacity-70">{label}</span>
        {icon}
      </div>
      <div className="text-3xl font-bold tabular-nums">{value}</div>
    </div>
  );
}
