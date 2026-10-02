'use client';

import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { useState, useCallback, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Webhook, Clock, Plus, Trash2, Copy, Check, ExternalLink,
  Play, Pause, ToggleLeft, ToggleRight, Loader2, Zap, Search,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { apiFetch } from '@/lib/api-client';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Trigger {
  id: string;
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
  onCreated: () => void;
  agents: AgentOption[];
  defaultAgentId?: string | null;
}) {
  const [triggerType, setTriggerType] = useState<'webhook' | 'schedule'>('webhook');
  const [agentId, setAgentId] = useState(defaultAgentId || '');
  const [cronExpression, setCronExpression] = useState('');
  const [defaultMessage, setDefaultMessage] = useState('');
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!agentId) return;
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
          cron_expression: triggerType === 'schedule' ? cronExpression : undefined,
          default_message: defaultMessage || 'Triggered execution',
        }),
      });
      const json = await res.json();
      if (json.error) {
        toastError(json.error);
      } else {
        toastSuccess('Trigger created');
        onCreated();
        onClose();
      }
    } catch {
      toastError('Failed to create trigger');
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Create Trigger</h3>

        {/* Type toggle */}
        <div className="flex bg-slate-800 rounded-lg border border-slate-700 p-0.5 mb-4">
          <button
            onClick={() => setTriggerType('webhook')}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
              triggerType === 'webhook' ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Webhook className="w-4 h-4" />
            Webhook
          </button>
          <button
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
          <label className="block text-xs text-slate-400 mb-1.5">Agent</label>
          <select
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

        {/* Cron expression (schedule only) */}
        {triggerType === 'schedule' && (
          <div className="mb-4">
            <label className="block text-xs text-slate-400 mb-1.5">Cron Expression</label>
            <input
              type="text"
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="*/5 * * * * (every 5 minutes)"
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
            <p className="text-[10px] text-slate-600 mt-1">
              Standard cron format: minute hour day month weekday
            </p>
          </div>
        )}

        {/* Default message */}
        <div className="mb-6">
          <label className="block text-xs text-slate-400 mb-1.5">Default Message</label>
          <textarea
            value={defaultMessage}
            onChange={(e) => setDefaultMessage(e.target.value)}
            placeholder="Message sent to the agent when triggered"
            rows={3}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500"
          />
        </div>

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
  const [showCreate, setShowCreate] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [page, setPage] = useState(0);
  const [running, setRunning] = useState<string | null>(null);
  const [manualRuns, setManualRuns] = useState<Record<string, string>>({});
  const LIMIT = 20;

  // ?agent= narrows the list to that agent until the user clears it
  const [agentFilter, setAgentFilter] = useState<string | null>(preselectedAgentId);
  const apiUrl = `/api/triggers?search=${encodeURIComponent(search)}&trigger_type=${typeFilter}${agentFilter ? `&agent_id=${agentFilter}` : ''}&limit=${LIMIT}&offset=${page * LIMIT}`;
  const { data: triggers, meta, mutate } = useApi<Trigger[]>(apiUrl);
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
      await fetch(`${API_URL}/api/triggers/${triggerId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_active: !isActive }),
      });
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
    try {
      await fetch(`${API_URL}/api/triggers/${triggerId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      mutate();
      toastSuccess('Trigger deleted');
    } catch {
      toastError('Failed to delete trigger');
    }
  }, [mutate]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Event Triggers</h1>
          <p className="text-sm text-slate-400 mt-1">
            Automate agent execution via webhooks or cron schedules
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          New Trigger
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search triggers..."
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
        {agentFilter && (
          <span className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-200" data-testid="trigger-agent-filter">
            Triggers for {filterName || 'this agent'}
            <button onClick={() => { setAgentFilter(null); setPage(0); }} className="text-cyan-300 hover:text-white" aria-label="Show triggers for all agents">Show all</button>
          </span>
        )}
      </div>

      {/* Triggers list */}
      <div className="space-y-3">
        {(!triggers || triggers.length === 0) && (
          <div className="text-center py-16 bg-slate-800/30 border border-slate-700/50 rounded-xl">
            <Zap className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-1">No triggers yet</h3>
            <p className="text-sm text-slate-500">
              Create a webhook or schedule trigger to automate agent execution.
            </p>
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
              <div className="flex items-start gap-4">
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
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-semibold text-white">
                      {trigger.agent_name || 'Agent'}
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
                  <div className="flex items-center gap-4 text-[10px] text-slate-500">
                    <span>{trigger.run_count} executions</span>
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
                  </div>
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
        onCreated={() => mutate()}
        agents={agents}
        defaultAgentId={preselectedAgentId}
      />
    </motion.div>
  );
}
