'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  AlertTriangle, Bell, ChevronDown, ChevronRight, ExternalLink,
  RefreshCw, Activity,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import PageHeader from '@/components/layout/PageHeader';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { LLM_AUTH_FOR_USERS, adviceCode, failureTitle } from '@/components/alerts/failureAdvice';

const GRAFANA_URL = (process.env.NEXT_PUBLIC_GRAFANA_URL || 'http://localhost:3010').replace(/\/$/, '');

interface FailureGroup {
  failure_code: string;
  count: number;
  latest_at: string | null;
  agent_ids: string[];
  sample_message: string;
}

interface PlatformAlert {
  name: string;
  state: 'firing' | 'pending' | 'inactive' | 'silenced' | 'inhibited' | string;
  severity: string;
  active_since: string | null;
  ends_at?: string | null;
  summary: string | null;
  description: string | null;
  runbook: string | null;
  labels: Record<string, string>;
  fingerprint?: string | null;
  silenced?: boolean;
  inhibited?: boolean;
}

interface PlatformAlertsResponse {
  alerts: PlatformAlert[];
  counts: Record<string, number>;
  source: 'alertmanager' | 'prometheus' | string;
  prometheus_url: string;
  alertmanager_url?: string;
}

const SOURCE_LABEL: Record<string, string> = {
  alertmanager: 'Alertmanager',
  prometheus: 'Prometheus (Alertmanager unreachable)',
};

interface Permissions {
  is_admin: boolean;
}

const ALERT_SEV_STYLES: Record<string, string> = {
  critical: 'bg-red-500/10 border-red-500/40 text-red-300',
  error: 'bg-red-500/10 border-red-500/40 text-red-300',
  warning: 'bg-amber-500/10 border-amber-500/40 text-amber-300',
  info: 'bg-slate-500/10 border-slate-500/40 text-slate-300',
};

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
  LLM_AUTH_ERROR: 'The LLM provider rejected the credential. A rotated Claude subscription token is the usual cause: run scripts/sync-claude-subscription.sh, or update the provider key under Admin -> Tool Configuration.',
  CONFIG_UNKNOWN_MODEL: 'The agent names a model the platform does not know. Pick a model from the list in the agent settings.',
  INFRA_AUTH_ERROR: '401/403 against an internal service (k8s API, S3, etc.). Check service-account RBAC.',
  MODERATION_BLOCKED: 'Tenant moderation policy blocked the request or response. Check /moderation for policy + recent events.',
  KILL_SWITCH: 'A kill switch stopped the agent, pipeline, tool or model. Resume it under Admin, Risk and Controls.',
  MODEL_NOT_ALLOWED: 'The model is not on the allowed list for the run\u2019s risk tier. Change the model or the tier policy under Admin, Risk and Controls.',
  PIPELINE_NODE_FAILED: 'A pipeline step failed and stopped the run. Open the run to see which step, then use Diagnose and fix on the agent\u2019s Healing page.',
  REQUIRED_TOOLS_VIOLATION: 'The agent finished without calling a tool it is required to use. Check its prompt asks for the tool, or remove the requirement in the agent settings.',
  GROUNDING_REQUIRED_VIOLATION: 'The agent answered without searching its knowledge base, which it is required to do. Check the knowledge base is bound to the agent and the prompt asks it to search first.',
  CLIENT_DISCONNECTED: 'The browser or caller left before the run finished. The run stopped with it. Retry, or run it in the background from the SDK or a trigger.',
  VALIDATION_FAILED: 'The output did not match the agent\u2019s output schema. Open the run to see which field failed, then adjust the prompt or the schema.',
  RUNTIME_TIMEOUT: 'The run took longer than its time limit. Raise the limit under Settings, Sandbox, or split the work into smaller steps.',
  REQUEST_TIMEOUT: 'A call the run made did not answer in time. Often a slow external service. Retry, or raise that tool\u2019s timeout.',
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
  LLM_AUTH_ERROR: 'high',
  INFRA_AUTH_ERROR: 'high',
  MODERATION_BLOCKED: 'med',
  KILL_SWITCH: 'med',
  MODEL_NOT_ALLOWED: 'low',
  CONFIG_UNKNOWN_MODEL: 'med',
  PIPELINE_NODE_FAILED: 'med',
  REQUIRED_TOOLS_VIOLATION: 'med',
  GROUNDING_REQUIRED_VIOLATION: 'med',
  CLIENT_DISCONNECTED: 'low',
  VALIDATION_FAILED: 'low',
  RUNTIME_TIMEOUT: 'med',
  REQUEST_TIMEOUT: 'med',
  UNKNOWN_ERROR: 'med',
};

const SEV_STYLES: Record<string, string> = {
  high: 'bg-red-500/10 border-red-500/40 text-red-300',
  med:  'bg-amber-500/10 border-amber-500/40 text-amber-300',
  low:  'bg-slate-500/10 border-slate-500/40 text-slate-300',
};

function describeCode(code: string, isAdmin: boolean): string {
  if (code === 'LLM_AUTH_ERROR' && !isAdmin) return LLM_AUTH_FOR_USERS;
  return CODE_DESCRIPTIONS[code] || 'No description for this cause yet. Open it to see a sample error.';
}

interface AgentRow { id: string; name?: string }

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
  const { data: groups, error: groupsError, isLoading: groupsLoading, mutate: refreshGroups } =
    useApi<FailureGroup[]>(`/api/analytics/failures?hours=${hours}`);
  const [agentNames, setAgentNames] = useState<Record<string, string> | null>(null);
  const needNames = (groups || []).some(g => g.agent_ids.length > 0);
  useEffect(() => {
    if (!needNames || agentNames) return;
    const ctl = new AbortController();
    fetchAllAgents<AgentRow>({ signal: ctl.signal })
      .then(({ agents }) => setAgentNames(Object.fromEntries(agents.map(a => [a.id, a.name || '']))))
      .catch(() => { if (!ctl.signal.aborted) setAgentNames({}); });
    return () => ctl.abort();
  }, [needNames, agentNames]);
  const { data: perms } = useApi<Permissions>('/api/me/permissions', { dedupingInterval: 60_000 });
  const isAdmin = Boolean(perms?.is_admin);
  // Only admins may read /api/admin/alerts, a null key skips the fetch.
  const { data: platform, error: platformError, mutate: refreshPlatform } =
    useApi<PlatformAlertsResponse>(isAdmin ? '/api/admin/alerts' : null, { refreshInterval: 60_000 });
  const firing = (platform?.alerts || []).filter(a => a.state === 'firing');
  // Alertmanager also reports silenced / inhibited alerts, Prometheus never does.
  const muted = (platform?.alerts || []).filter(a => a.state === 'silenced' || a.state === 'inhibited');
  const platformSource = platform?.source || 'prometheus';

  const totalFailures = (groups || []).reduce((s, g) => s + g.count, 0);
  const failureRate = stats && stats.today_executions > 0
    ? Math.round(100 * stats.today_failed / stats.today_executions)
    : stats ? 0 : null;

  return (
    <div className="min-h-screen bg-[#0B0F19] p-4 sm:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <PageHeader
          title="Alerts"
          purpose="Failed runs grouped by cause, so you can spot a burst and fix the root cause once. For builders and admins."
          icon={AlertTriangle}
          iconClassName="text-red-400"
          storageKey="alerts"
          docSlug="06-deployment/04-observability"
          primaryAction={{
            label: 'Refresh',
            icon: RefreshCw,
            onClick: () => { refreshStats(); refreshGroups(); refreshPlatform(); },
          }}
          extraActions={
            <select
              aria-label="Time window"
              value={hours}
              onChange={e => setHours(parseInt(e.target.value))}
              className="min-h-[40px] bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
            >
              <option value="1">Last hour</option>
              <option value="6">Last 6h</option>
              <option value="24">Last 24h</option>
              <option value="72">Last 3 days</option>
              <option value="168">Last week</option>
            </select>
          }
          steps={[
            'Pick a time window. The cards and the cause list follow it.',
            'Click a cause to see a sample error, what usually fixes it and the agents it hit.',
            'Admins also see platform alerts, the same ones sent to Slack as they fire and clear.',
          ]}
        />

        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <SummaryCard
            label={`Failures (${hours}h)`}
            value={groups ? String(totalFailures) : '\u2014'}
            tone={!groups ? 'slate' : totalFailures > 0 ? 'red' : 'green'}
            icon={<AlertTriangle className="w-4 h-4" />}
          />
          <SummaryCard
            label="Active runs"
            value={stats ? String(stats.active_executions) : '\u2014'}
            tone={stats && stats.active_executions > 50 ? 'amber' : 'slate'}
            icon={<Activity className="w-4 h-4" />}
          />
          <SummaryCard
            label="Failure rate today"
            value={failureRate === null ? '\u2014' : `${failureRate}%`}
            tone={failureRate === null ? 'slate' : failureRate > 20 ? 'red' : failureRate > 5 ? 'amber' : 'green'}
            icon={<Bell className="w-4 h-4" />}
          />
          <SummaryCard
            label="Distinct causes"
            value={groups ? String(groups.length) : '\u2014'}
            tone="slate"
            icon={<Bell className="w-4 h-4" />}
          />
        </div>

        {/* Platform alerts (admin only) */}
        {isAdmin && (
          <section className="space-y-2" data-testid="platform-alerts">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-white">Platform alerts</h2>
                <p className="text-xs text-slate-500">
                  Prometheus rules routed through Alertmanager. Admins get these in-app and on Slack as they fire and resolve.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {platform && (
                  <span
                    data-testid="platform-alerts-source"
                    title={platformSource === 'alertmanager' ? platform.alertmanager_url : platform.prometheus_url}
                    className={`text-xs px-2 py-0.5 rounded-full border ${platformSource === 'alertmanager' ? 'bg-slate-700/30 border-slate-600/40 text-slate-300' : 'bg-amber-500/10 border-amber-500/40 text-amber-300'}`}
                  >
                    source: {SOURCE_LABEL[platformSource] || platformSource}
                  </span>
                )}
                {muted.length > 0 && (
                  <span data-testid="platform-alerts-muted" className="text-xs px-2 py-0.5 rounded-full border bg-slate-500/10 border-slate-500/40 text-slate-300">
                    {muted.length} silenced
                  </span>
                )}
                <span data-testid="platform-alerts-firing" className={`text-xs px-2 py-0.5 rounded-full border ${firing.length > 0 ? 'bg-red-500/10 border-red-500/40 text-red-300' : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'}`}>
                  {firing.length} firing
                </span>
              </div>
            </div>
            {platformError && (
              <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
                Alert backends unavailable: {platformError}
              </div>
            )}
            {!platformError && firing.length === 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 text-xs text-slate-400">
                No platform alerts firing.
              </div>
            )}
            {[...firing, ...muted].map(a => {
              const sev = (a.severity || 'info').toLowerCase();
              const isMuted = a.state === 'silenced' || a.state === 'inhibited';
              return (
                <div
                  key={a.fingerprint || `${a.name}-${JSON.stringify(a.labels)}`}
                  data-testid="platform-alert-row"
                  data-state={a.state}
                  className={`rounded-xl border ${ALERT_SEV_STYLES[sev] || ALERT_SEV_STYLES.info} p-4 flex flex-wrap items-start gap-3 ${isMuted ? 'opacity-60' : ''}`}
                >
                  <div className="flex-1 min-w-[200px]">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold">{a.name}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 uppercase tracking-wider">{sev}</span>
                      {isMuted && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-slate-500/20 uppercase tracking-wider">{a.state}</span>
                      )}
                    </div>
                    {(a.summary || a.description) && (
                      <p className="text-xs text-slate-400 mt-0.5">{a.summary || a.description}</p>
                    )}
                  </div>
                  <div className="sm:text-right shrink-0 text-[11px] text-slate-400">
                    <div>since {relTime(a.active_since)}</div>
                    {a.ends_at && <div>resolves {relTime(a.ends_at)}</div>}
                    {a.runbook && (
                      <a href={a.runbook} target="_blank" rel="noopener" className="text-cyan-400 hover:underline inline-flex items-center gap-1">
                        runbook <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </section>
        )}

        {/* Failure groups */}
        <div className="space-y-2">
          {groupsError && !groups && (
            <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200 flex flex-wrap items-center justify-between gap-2">
              <span>Failures could not be loaded: {groupsError}</span>
              <button type="button" onClick={() => refreshGroups()} className="text-xs underline">Try again</button>
            </div>
          )}
          {groupsLoading && !groups && (
            <div className="space-y-2" aria-busy="true">
              {[0, 1, 2].map(i => <div key={i} className="h-16 rounded-xl bg-slate-800/40 animate-pulse" />)}
            </div>
          )}
          {groups && groups.length === 0 && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-8 sm:p-12 text-center">
              <Bell className="w-10 h-10 text-emerald-400/50 mx-auto mb-3" />
              <p className="text-sm text-slate-300">No failed runs in the {hours === 1 ? 'last hour' : `last ${hours} hours`}.</p>
              <p className="text-xs text-slate-500 mt-1">
                When a run fails it shows up here grouped by cause. Pick a longer window above to look further back.
                {isAdmin && <> <a href={GRAFANA_URL} target="_blank" rel="noopener" className="text-cyan-400 hover:underline">Open Grafana</a> for the full picture.</>}
              </p>
            </div>
          )}

          {(groups || []).map(g => {
            const code = adviceCode(g);
            const sev = CODE_SEVERITY[code] || 'med';
            const isOpen = expanded === g.failure_code;
            return (
              <div key={g.failure_code} className={`rounded-xl border ${SEV_STYLES[sev]} overflow-hidden`}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setExpanded(isOpen ? null : g.failure_code)}
                  className="w-full flex items-center gap-3 p-4 text-left hover:bg-white/5 transition-colors"
                >
                  {isOpen ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold" data-testid="failure-title">{failureTitle(code)}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 uppercase tracking-wider">
                        {sev}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {describeCode(code, isAdmin)}
                    </p>
                    <p className="mt-1 text-[10px] text-slate-500">
                      Reference <code className="break-all font-mono text-slate-400" data-testid="failure-code">{g.failure_code}</code>
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
                        {g.agent_ids.slice(0, 8).map(aid => {
                          if (!agentNames) {
                            return <span key={aid} className="h-6 w-24 rounded bg-slate-800 animate-pulse" aria-label="Loading agent name" />;
                          }
                          const name = agentNames[aid];
                          if (name === undefined) {
                            return (
                              <span key={aid} title={`Agent ${aid}`} className="text-[11px] px-2 py-1 rounded bg-slate-800/60 text-slate-500">
                                An agent not shared with you
                              </span>
                            );
                          }
                          return (
                            <Link key={aid} href={`/agents/${aid}`} title={aid}
                               className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 inline-flex items-center gap-1">
                              {name || 'Untitled agent'} <ExternalLink className="w-2.5 h-2.5" />
                            </Link>
                          );
                        })}
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

        {isAdmin && (
          <div className="text-xs text-slate-500 text-center py-4">
            Real-time metrics and 60 days of history at{' '}
            <a href={`${GRAFANA_URL}/d/abenix-overview`} target="_blank" rel="noopener" className="text-cyan-400 hover:underline">
              Grafana → Abenix Operations
            </a>
          </div>
        )}
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
    <div className={`rounded-xl border ${toneStyles} p-3 sm:p-4 min-w-0`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[11px] sm:text-xs uppercase tracking-wider opacity-70 min-w-0">{label}</span>
        <span className="shrink-0">{icon}</span>
      </div>
      <div className="text-2xl sm:text-3xl font-bold tabular-nums">{value}</div>
    </div>
  );
}
