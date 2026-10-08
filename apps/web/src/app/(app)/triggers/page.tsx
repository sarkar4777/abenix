'use client';

import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { useState, useCallback, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Webhook, Clock, Plus, Trash2, Copy, Check, ExternalLink,
  Play, Pause, ToggleLeft, ToggleRight, Loader2, Zap, Search, History, Radio,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { apiFetch } from '@/lib/api-client';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import { apiErrorText, looksLikeCron } from '@/lib/nav-walk';
import { failureLabel } from '@/lib/monitor-format';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';

const RUN_DOT: Record<string, string> = {
  completed: 'bg-emerald-400',
  failed: 'bg-red-400',
  running: 'bg-cyan-400 animate-pulse',
  cancelled: 'bg-slate-500',
};

function ago(iso: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function RecentRuns({ trigger }: { trigger: Trigger }) {
  const runs = trigger.recent_runs || [];
  return (
    <div className="mt-3 border-t border-slate-700/40 pt-2" data-testid={`trigger-recent-runs-${trigger.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <p className="text-[11px] font-medium text-slate-400">Recent runs</p>
        {runs.length > 0 && (
          <Link
            href={`/executions?trigger=${trigger.id}`}
            data-testid={`trigger-all-runs-${trigger.id}`}
            className="text-[11px] text-cyan-400 hover:text-cyan-300 hover:underline"
          >
            All runs from this trigger
          </Link>
        )}
      </div>
      {runs.length === 0 ? (
        <p className="text-[11px] text-slate-500" data-testid={`trigger-no-runs-${trigger.id}`}>
          No runs yet. {trigger.trigger_type === 'schedule' ? 'It runs at the next scheduled time, or use Run now.' : 'It runs when the webhook is called, or use Run now.'}
        </p>
      ) : (
        <ul className="space-y-1">
          {runs.map((r) => (
            <li key={r.id} data-testid="trigger-recent-run" data-status={r.status} data-execution-id={r.id}>
              <Link
                href={`/executions/${r.id}`}
                className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-300 hover:text-white"
              >
                <span className={`w-1.5 h-1.5 rounded-full ${RUN_DOT[r.status] || 'bg-slate-500'}`} aria-hidden />
                <span className="capitalize">{r.status}</span>
                <span className="text-slate-500">{ago(r.created_at)}</span>
                {r.trigger_kind === 'manual' && <span className="text-slate-500">run now</span>}
                {typeof r.duration_ms === 'number' && r.status !== 'running' && (
                  <span className="text-slate-500">{r.duration_ms >= 1000 ? `${(r.duration_ms / 1000).toFixed(1)}s` : `${r.duration_ms}ms`}</span>
                )}
                {r.failure_code && <span className="text-red-300">{failureLabel(r.failure_code)}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const CRON_PRESETS = [
  { label: 'Every 5 minutes', value: '*/5 * * * *' },
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Daily 09:00', value: '0 9 * * *' },
  { label: 'Weekdays 09:00', value: '0 9 * * 1-5' },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface TriggerRun {
  id: string;
  status: string;
  trigger_kind?: string | null;
  created_at: string | null;
  duration_ms?: number | null;
  failure_code?: string | null;
}

interface Trigger {
  id: string;
  name?: string;
  recent_runs?: TriggerRun[];
  agent_id: string;
  agent_name?: string;
  trigger_type: 'webhook' | 'schedule';
  webhook_url?: string;
  webhook_token?: string;
  cron_expression?: string;
  default_message?: string;
  default_context?: Record<string, unknown>;
  is_active: boolean;
  run_count: number;
  last_status?: string;
  last_run_at?: string;
  next_run_at?: string;
  created_at: string;
}

interface AgentOption {
  id: string;
  name: string;
  slug: string;
}

function CreateTriggerModal({
  open,
  onClose,
  onCreated,
  agents,
  defaultAgentId,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (t: { id: string } | null) => void;
  agents: AgentOption[];
  defaultAgentId?: string | null;
}) {
  const [triggerType, setTriggerType] = useState<'webhook' | 'schedule'>('webhook');
  const [agentId, setAgentId] = useState(defaultAgentId || '');
  const [cronExpression, setCronExpression] = useState('');
  const [defaultMessage, setDefaultMessage] = useState('');
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  useEscapeToClose(open, onClose);
  useEffect(() => { if (open) setFormError(null); }, [open]);
  const cronShape = looksLikeCron(cronExpression);

  const handleCreate = async () => {
    if (!agentId) return;
    if (triggerType === 'schedule' && !cronShape) {
      setFormError('Pick a preset or enter five cron fields: minute hour day month weekday.');
      return;
    }
    const token = localStorage.getItem('access_token');
    if (!token) return;

    setCreating(true);
    try {
      const res = await fetch(`${API_URL}/api/triggers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          agent_id: agentId,
          trigger_type: triggerType,
          name: name.trim() || undefined,
          cron_expression: triggerType === 'schedule' ? cronExpression.trim() : undefined,
          default_message: defaultMessage || 'Triggered execution',
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.error) {
        setFormError(apiErrorText(json.error, `Could not create the trigger (${res.status})`));
      } else {
        toastSuccess('Trigger created');
        onCreated(json.data?.id ? { id: String(json.data.id) } : null);
        onClose();
      }
    } catch {
      setFormError('Could not reach the server. Try again.');
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="trigger-create-title">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl w-full max-w-lg p-6 max-h-[92vh] overflow-y-auto">
        <h3 id="trigger-create-title" className="text-lg font-semibold text-white mb-4">Create Trigger</h3>

        {/* Type toggle */}
        <div className="flex bg-slate-800 rounded-lg border border-slate-700 p-0.5 mb-4">
          <button
            aria-pressed={triggerType === 'webhook'}
            onClick={() => setTriggerType('webhook')}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
              triggerType === 'webhook' ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Webhook className="w-4 h-4" />
            Webhook
          </button>
          <button
            aria-pressed={triggerType === 'schedule'}
            onClick={() => setTriggerType('schedule')}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
              triggerType === 'schedule' ? 'bg-purple-500/20 text-purple-400' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Clock className="w-4 h-4" />
            Schedule (Cron)
          </button>
        </div>

        {/* Agent selector */}
        <div className="mb-4">
          <label htmlFor="trigger-agent" className="block text-xs text-slate-400 mb-1.5">Agent</label>
          <select
            id="trigger-agent"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
          >
            <option value="">Select an agent...</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <label htmlFor="trigger-name" className="block text-xs text-slate-400 mb-1.5">Name</label>
          <input
            id="trigger-name"
            type="text"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            placeholder={`${agents.find((a) => a.id === agentId)?.name || 'Agent'} trigger`}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
          <p className="text-[10px] text-slate-500 mt-1">Each run it starts says Started by this name. Leave it empty to use the name shown.</p>
        </div>

        {/* Cron expression (schedule only) */}
        {triggerType === 'schedule' && (
          <div className="mb-4">
            <label htmlFor="trigger-cron" className="block text-xs text-slate-400 mb-1.5">Cron Expression</label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setCronExpression(p.value)}
                  aria-pressed={cronExpression === p.value}
                  className={`px-2 py-1 rounded text-[11px] border ${cronExpression === p.value ? 'border-purple-400 text-purple-200 bg-purple-500/10' : 'border-slate-700 text-slate-400 hover:text-white'}`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <input
              id="trigger-cron"
              type="text"
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="*/5 * * * * (every 5 minutes)"
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
            <p className="text-[10px] text-slate-500 mt-1">
              Standard cron format: minute hour day month weekday, in UTC. Use Run now on the trigger to try it straight away.
            </p>
          </div>
        )}

        {/* Default message */}
        <div className="mb-6">
          <label htmlFor="trigger-message" className="block text-xs text-slate-400 mb-1.5">Default Message</label>
          <textarea
            id="trigger-message"
            value={defaultMessage}
            onChange={(e) => setDefaultMessage(e.target.value)}
            placeholder="Message sent to the agent when triggered"
            rows={3}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500"
          />
        </div>

        {formError && <p role="alert" data-testid="trigger-form-error" className="text-xs text-red-300 -mt-3 mb-4">{formError}</p>}
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!agentId || creating}
            title={!agentId ? 'Pick an agent first' : undefined}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-all"
          >
            {creating && <Loader2 className="w-4 h-4 animate-spin" />}
            Create Trigger
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TriggersPage() {
  usePageTitle('Triggers');
  const searchParams = useSearchParams();
  const preselectedAgentId = searchParams.get('agent');
  const [focusId, setFocusId] = useState<string | null>(searchParams.get('focus'));
  const [showCreate, setShowCreate] = useState(false);
  const [created, setCreated] = useState<{ id: string } | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [page, setPage] = useState(0);
  const [running, setRunning] = useState<string | null>(null);
  const [manualRuns, setManualRuns] = useState<Record<string, string>>({});
  const LIMIT = 20;

  // ?agent= narrows the list to that agent until the user clears it
  const [agentFilter, setAgentFilter] = useState<string | null>(preselectedAgentId);
  const apiUrl = `/api/triggers?search=${encodeURIComponent(search)}&trigger_type=${typeFilter}${agentFilter ? `&agent_id=${agentFilter}` : ''}${focusId ? `&trigger_id=${focusId}` : ''}&limit=${LIMIT}&offset=${page * LIMIT}`;
  // keep polling while a run is still going, so its status settles on screen
  const [polling, setPolling] = useState(false);
  const { data: triggers, meta, mutate, error: listError } = useApi<Trigger[]>(apiUrl, { refreshInterval: polling ? 4000 : 0 });
  useEffect(() => {
    setPolling((triggers || []).some((t) => (t.recent_runs || []).some((r) => r.status === 'running')));
  }, [triggers]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    // every agent the user can pick, not just the first page
    fetchAllAgents<AgentOption>().then(({ agents: all }) => { if (!cancelled) setAgents(all); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const total = (meta?.total as number) || (triggers || []).length;
  const filterName = agentFilter ? agents.find((a) => a.id === agentFilter)?.name : null;

  // open the create dialog only when the agent has no triggers yet
  const [autoOpened, setAutoOpened] = useState(false);
  useEffect(() => {
    if (autoOpened || !preselectedAgentId || triggers === undefined || agents.length === 0) return;
    setAutoOpened(true);
    if ((triggers || []).length === 0) setShowCreate(true);
  }, [preselectedAgentId, triggers, agents.length, autoOpened]);

  const copyUrl = useCallback((url: string, id: string) => {
    navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const toggleTrigger = useCallback(async (triggerId: string, isActive: boolean) => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/triggers/${triggerId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_active: !isActive }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        toastError('Could not update the trigger', apiErrorText(j.error, `status ${res.status}`));
        return;
      }
      mutate();
      toastSuccess(isActive ? 'Trigger paused' : 'Trigger activated');
    } catch {
      toastError('Failed to update trigger');
    }
  }, [mutate]);

  const runNow = useCallback(async (triggerId: string) => {
    setRunning(triggerId);
    try {
      const res = await apiFetch<{ execution_id: string }>(`/api/triggers/${triggerId}/run`, {
        method: 'POST',
        throwOnError: false,
      });
      const execId = res.data?.execution_id;
      if (execId) {
        setManualRuns((prev) => ({ ...prev, [triggerId]: execId }));
        toastSuccess('Trigger started', `Execution ${execId.slice(0, 8)}, open it from View run on the row`);
        mutate();
      } else {
        toastError('Run failed', res.error || undefined);
      }
    } finally {
      setRunning(null);
    }
  }, [mutate]);

  const deleteTrigger = useCallback(async (triggerId: string) => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    if (!window.confirm('Delete this trigger? Its agent stops running on this schedule or webhook.')) return;
    try {
      const res = await fetch(`${API_URL}/api/triggers/${triggerId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        toastError('Could not delete the trigger', apiErrorText(j.error, `status ${res.status}`));
        return;
      }
      mutate();
      toastSuccess('Trigger deleted');
    } catch {
      toastError('Failed to delete trigger');
    }
  }, [mutate]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <PageHeader
        className="mb-6"
        title="Event Triggers"
        purpose="Run an agent on a schedule or when another system calls a webhook, with no one in chat. For builders automating agents."
        icon={Zap}
        storageKey="triggers"
        docSlug="02-runtime/14-connectors-and-triggers"
        primaryAction={{ label: 'New Trigger', onClick: () => setShowCreate(true), icon: Plus }}
        steps={[
          'Pick an agent and choose webhook or schedule.',
          'A webhook gives you a URL to call from another system. A schedule runs at the times you set.',
          'Each run is a normal agent run. Recent runs show on the card and under Executions.',
          'Pause a trigger to stop it without losing its setup. Run now tests it straight away.',
        ]}
      />
      {created && (
        <NextSteps
          className="mb-4"
          title="Trigger created. What next?"
          onDismiss={() => setCreated(null)}
          testId="trigger-next-steps"
          steps={[
            { id: 'run-now', label: 'Run it now', hint: 'Fire it once to check the agent answers.', icon: Play, onClick: () => { runNow(created.id); setFocusId(created.id); setPage(0); } },
            { id: 'runs', label: 'See its runs', hint: 'Every run this trigger starts, newest first.', icon: History, href: `/executions?trigger=${created.id}` },
            { id: 'live', label: 'Watch it live', hint: 'See the next run step by step as it happens.', icon: Radio, href: '/executions/live' },
          ]}
        />
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search triggers..."
            aria-label="Search triggers"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(0); }}
          className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">All Types</option>
          <option value="webhook">Webhook</option>
          <option value="schedule">Schedule</option>
        </select>
        {focusId && (
          <span className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-200" data-testid="trigger-focus-filter">
            {(triggers || [])[0]?.name ? `Trigger ${(triggers || [])[0]?.name}` : 'One trigger'}
            <button onClick={() => { setFocusId(null); setPage(0); }} className="text-cyan-300 hover:text-white" aria-label="Show every trigger">Show all</button>
          </span>
        )}
        {agentFilter && (
          <span className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-200" data-testid="trigger-agent-filter">
            Triggers for {filterName || 'this agent'}
            <button onClick={() => { setAgentFilter(null); setPage(0); }} className="text-cyan-300 hover:text-white" aria-label="Show triggers for all agents">Show all</button>
          </span>
        )}
      </div>

      {/* Triggers list */}
      <div className="space-y-3">
        {listError && !triggers && (
          <div role="alert" className="text-center py-10 text-sm text-red-300" data-testid="triggers-error">
            Could not load triggers. {listError}
          </div>
        )}
        {triggers && triggers.length === 0 && (
          <div className="text-center py-16 bg-slate-800/30 border border-slate-700/50 rounded-xl" data-testid="triggers-empty">
            <Zap className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-1">
              {focusId ? 'That trigger is gone' : search || typeFilter || agentFilter ? 'No triggers match' : 'No triggers yet'}
            </h3>
            <p className="text-sm text-slate-500">
              {focusId
                ? 'It was deleted, or you cannot manage it. Its runs keep its name.'
                : search || typeFilter || agentFilter
                  ? 'Clear the search or filters, or create a trigger for this agent.'
                  : 'Create a webhook or schedule trigger to automate agent execution.'}
            </p>
          </div>
        )}
        {!triggers && !listError && (
          <div className="space-y-3" aria-label="Loading triggers">
            {[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-slate-800/40 animate-pulse" />)}
          </div>
        )}

        {(triggers || []).map((trigger) => {
          const webhookUrl = trigger.webhook_token
            ? `${API_URL}/api/triggers/webhook/${trigger.webhook_token}`
            : '';

          return (
            <div
              key={trigger.id}
              data-testid={`trigger-row-${trigger.id}`}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4"
            >
              <div className="flex flex-wrap sm:flex-nowrap items-start gap-4">
                {/* Icon */}
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
                  trigger.trigger_type === 'webhook'
                    ? 'bg-cyan-500/10'
                    : 'bg-purple-500/10'
                }`}>
                  {trigger.trigger_type === 'webhook' ? (
                    <Webhook className="w-5 h-5 text-cyan-400" />
                  ) : (
                    <Clock className="w-5 h-5 text-purple-400" />
                  )}
                </div>

                {/* Details */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className="text-sm font-semibold text-white break-words" data-testid={`trigger-name-${trigger.id}`}>
                      {trigger.name || 'Unnamed trigger'}
                    </span>
                    <span className="text-xs text-slate-400 break-words">
                      runs {trigger.agent_name || 'an agent'}
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                      trigger.trigger_type === 'webhook'
                        ? 'bg-cyan-500/10 text-cyan-400'
                        : 'bg-purple-500/10 text-purple-400'
                    }`}>
                      {trigger.trigger_type}
                    </span>
                    <span data-testid={`trigger-state-${trigger.id}`} className={`text-[10px] px-2 py-0.5 rounded-full ${
                      trigger.is_active
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : trigger.last_status === 'agent deleted'
                          ? 'bg-red-500/10 text-red-300'
                          : 'bg-slate-700 text-slate-500'
                    }`} title={!trigger.is_active && trigger.last_status === 'agent deleted' ? 'Its agent was deleted. Restoring the agent switches this back on.' : undefined}>
                      {trigger.is_active ? 'Active' : trigger.last_status === 'agent deleted' ? 'Off · agent deleted' : 'Paused'}
                    </span>
                  </div>

                  {/* Webhook URL */}
                  {trigger.trigger_type === 'webhook' && webhookUrl && (
                    <div className="flex items-center gap-2 mb-2">
                      <code className="text-[10px] font-mono text-slate-400 bg-slate-900/50 px-2 py-1 rounded truncate max-w-[400px]">
                        POST {webhookUrl}
                      </code>
                      <button
                        onClick={() => copyUrl(webhookUrl, trigger.id)}
                        className="p-1 text-slate-500 hover:text-cyan-400 transition-colors"
                        title="Copy URL"
                      >
                        {copiedId === trigger.id ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            const res = await fetch(webhookUrl, {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ message: 'Test webhook fire', context: {} }),
                            });
                            if (res.ok) {
                              toastSuccess('Webhook fired successfully');
                              mutate();
                            } else {
                              toastError(`Webhook returned ${res.status}`);
                            }
                          } catch {
                            toastError('Failed to reach webhook URL');
                          }
                        }}
                        className="px-2 py-0.5 text-[10px] text-cyan-400 bg-cyan-500/10 rounded hover:bg-cyan-500/20 transition-colors"
                      >
                        Test
                      </button>
                    </div>
                  )}

                  {/* Cron expression */}
                  {trigger.trigger_type === 'schedule' && trigger.cron_expression && (
                    <div className="mb-2">
                      <code className="text-[10px] font-mono text-purple-400 bg-purple-500/10 px-2 py-1 rounded">
                        {trigger.cron_expression}
                      </code>
                      {trigger.next_run_at && (
                        <span className="text-[10px] text-slate-500 ml-2">
                          Next: {new Date(trigger.next_run_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Stats */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-500">
                    <span>{trigger.run_count} execution{trigger.run_count === 1 ? '' : 's'}</span>
                    {trigger.last_run_at && (
                      <span>Last run: {new Date(trigger.last_run_at).toLocaleString()}</span>
                    )}
                    {trigger.last_status && (
                      <span className={
                        trigger.last_status === 'completed' ? 'text-emerald-400' :
                        trigger.last_status === 'failed' ? 'text-red-400' : 'text-slate-400'
                      }>
                        {trigger.last_status}
                      </span>
                    )}
                    {manualRuns[trigger.id] && (
                      <Link
                        href={`/executions/${manualRuns[trigger.id]}`}
                        data-testid={`trigger-run-link-${trigger.id}`}
                        className="text-cyan-400 hover:text-cyan-300 hover:underline"
                      >
                        View run
                      </Link>
                    )}
                    {trigger.run_count > 0 && (
                      <Link
                        href={`/executions?agent=${trigger.agent_id}`}
                        data-testid={`trigger-runs-link-${trigger.id}`}
                        className="text-cyan-400 hover:text-cyan-300 hover:underline"
                      >
                        All runs of this agent
                      </Link>
                    )}
                  </div>
                  <RecentRuns trigger={trigger} />
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => runNow(trigger.id)}
                    disabled={running === trigger.id}
                    data-testid={`trigger-run-${trigger.id}`}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 rounded-lg transition-colors disabled:opacity-50"
                    title="Run this trigger once now"
                  >
                    {running === trigger.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Zap className="w-3.5 h-3.5" />
                    )}
                    Run now
                  </button>
                  <button
                    onClick={() => toggleTrigger(trigger.id, trigger.is_active)}
                    aria-label={trigger.is_active ? 'Pause trigger' : 'Activate trigger'}
                    className="p-2 text-slate-400 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
                    title={trigger.is_active ? 'Pause' : 'Activate'}
                  >
                    {trigger.is_active ? (
                      <Pause className="w-4 h-4" />
                    ) : (
                      <Play className="w-4 h-4" />
                    )}
                  </button>
                  <button
                    onClick={() => deleteTrigger(trigger.id)}
                    aria-label="Delete trigger"
                    className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      {(triggers || []).length > 0 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-slate-500">
            Showing {page * LIMIT + 1}&ndash;{Math.min((page + 1) * LIMIT, total)} of {total}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={(page + 1) * LIMIT >= total}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      <CreateTriggerModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(t) => { mutate(); if (t?.id) setCreated(t); }}
        agents={agents}
        defaultAgentId={preselectedAgentId}
      />
    </motion.div>
  );
}
