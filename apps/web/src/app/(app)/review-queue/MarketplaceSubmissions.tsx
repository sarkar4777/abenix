'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  Check,
  Clock,
  Eye,
  ShieldCheck,
  Wrench,
  X,
  User as UserIcon,
  Cpu,
  Thermometer,
  Hash,
  Zap,
  AlertTriangle,
  FileText,
  Activity,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import MarketplaceOffNotice from '@/components/marketplace/MarketplaceOffNotice';
import { SkeletonAgentCard } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';

interface Agent {
  id: string;
  name: string;
  slug: string;
  description: string;
  system_prompt: string;
  agent_type: string;
  status: string;
  category: string | null;
  creator_id: string;
  creator_email?: string | null;
  creator_name?: string | null;
  version?: string | null;
  mode?: string | null;
  example_prompts?: string[] | null;
  model_config: {
    model?: string;
    temperature?: number;
    max_iterations?: number;
    max_tokens?: number;
    cache?: boolean | string;
    tools?: string[];
    output_schema?: any;
  } | null;
  created_at: string;
  updated_at?: string | null;
}

interface ExecPreview {
  id: string;
  status: string;
  duration_ms: number | null;
  cost: number | null;
  created_at: string;
  output_preview?: string | null;
}

// agents published to the marketplace, waiting for an admin to approve them
export default function MarketplaceSubmissions({ onCount }: { onCount?: (n: number) => void }) {
  // ask for the pending ones, a plain first page misses them once the tenant has many agents
  const { data: allAgents, isLoading, error: loadError, mutate } = useApi<Agent[]>('/api/agents?status=pending_review&limit=100');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const pendingAgents = (allAgents ?? []).filter(
    (a) => a.status === 'pending_review',
  );

  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading) onCount?.(pendingAgents.length);
  }, [isLoading, pendingAgents.length, onCount]);

  const handleApprove = async (agentId: string) => {
    setActionLoading(agentId);
    setActionError(null);
    try {
      await apiFetch(`/api/agents/${agentId}/review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'approve' }),
      });
      setExpandedId(null);
    } catch (e: any) {
      setActionError(`Could not approve. ${e?.message || ''}`.trim());
    }
    setActionLoading(null);
    mutate();
  };

  const handleReject = async (agentId: string) => {
    setActionLoading(agentId);
    setActionError(null);
    try {
      await apiFetch(`/api/agents/${agentId}/review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'reject', reason: rejectReason }),
      });
      setRejectingId(null);
      setRejectReason('');
      setExpandedId(null);
    } catch (e: any) {
      setActionError(`Could not reject. ${e?.message || ''}`.trim());
    }
    setActionLoading(null);
    mutate();
  };

  return (
    <div className="space-y-6" data-testid="marketplace-submissions">
      <p className="text-sm text-slate-400">
        Approve or reject agents submitted to the public marketplace. Approved agents show in the Marketplace for every organisation.
      </p>

      <MarketplaceOffNotice what="Nothing new arrives in this queue while it is off." />

      {(loadError || actionError) && (
        <div role="alert" data-testid="review-error" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {actionError || `Could not load the queue. ${loadError}`}
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {[1, 2, 3].map((i) => (
            <SkeletonAgentCard key={i} />
          ))}
        </div>
      ) : pendingAgents.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No agents pending review"
          description="Agents land here when their owner publishes them with Marketplace visibility from the builder."
        />
      ) : (
        <div className="space-y-4">
          <AnimatePresence mode="popLayout">
            {pendingAgents.map((agent) => (
              <motion.div
                key={agent.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -100 }}
                transition={{ duration: 0.3 }}
                className="bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl overflow-hidden"
              >
                <div className="p-5">
                  <div className="flex items-start justify-between">
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
                        <Bot className="w-6 h-6 text-amber-400" />
                      </div>
                      <div>
                        <h3 className="text-base font-semibold text-white">
                          {agent.name}
                        </h3>
                        <p className="text-xs text-slate-400 mt-0.5">
                          {agent.slug} &middot;{' '}
                          {agent.category || 'uncategorized'} &middot;{' '}
                          submitted {formatDate(agent.created_at)}
                        </p>
                        {agent.description && (
                          <p className="text-sm text-slate-400 mt-2 line-clamp-2">
                            {agent.description}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-3 flex-wrap">
                          {agent.model_config?.model && (
                            <span className="text-[10px] font-mono text-slate-300 bg-slate-800/50 border border-slate-700/30 px-2 py-0.5 rounded">
                              {agent.model_config.model.replace(
                                /-\d{8}$/,
                                '',
                              )}
                            </span>
                          )}
                          {agent.model_config?.tools?.map((tool) => (
                            <span
                              key={tool}
                              className="flex items-center gap-1 text-[10px] text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-1.5 py-0.5 rounded"
                            >
                              <Wrench className="w-2.5 h-2.5" />
                              {tool}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        onClick={() =>
                          setExpandedId(
                            expandedId === agent.id ? null : agent.id,
                          )
                        }
                        className="p-2 text-slate-400 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
                        title="Preview details"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleApprove(agent.id)}
                        disabled={actionLoading === agent.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium rounded-lg hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                      >
                        <Check className="w-3.5 h-3.5" />
                        {actionLoading === agent.id
                          ? 'Approving...'
                          : 'Approve'}
                      </button>
                      <button
                        onClick={() =>
                          setRejectingId(
                            rejectingId === agent.id ? null : agent.id,
                          )
                        }
                        disabled={actionLoading === agent.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-medium rounded-lg hover:bg-red-500/20 transition-colors disabled:opacity-50"
                      >
                        <X className="w-3.5 h-3.5" />
                        Reject
                      </button>
                    </div>
                  </div>

                  <AnimatePresence>
                    {expandedId === agent.id && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="mt-4 pt-4 border-t border-slate-700/30 space-y-4">
                          {/* Submission metadata */}
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                            <Field icon={UserIcon} label="Submitted by" value={agent.creator_email || agent.creator_name || agent.creator_id?.slice(0, 8) || '—'} />
                            <Field icon={Clock} label="Submitted at" value={formatDate(agent.created_at)} />
                            <Field icon={Hash} label="Version" value={agent.version || '1.0.0'} />
                            <Field icon={Activity} label="Mode" value={agent.mode || agent.agent_type || '—'} />
                          </div>

                          {/* Model config — what an admin needs to assess cost & risk */}
                          <div>
                            <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Model & runtime</h4>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                              <Field icon={Cpu} label="Model" value={agent.model_config?.model || '—'} mono />
                              <Field icon={Thermometer} label="Temperature" value={agent.model_config?.temperature?.toString() ?? '—'} />
                              <Field icon={Zap} label="Max iterations" value={agent.model_config?.max_iterations?.toString() ?? '—'} />
                              <Field icon={FileText} label="Max tokens" value={agent.model_config?.max_tokens?.toString() ?? '—'} />
                            </div>
                          </div>

                          {/* Tools — full list, not truncated */}
                          {agent.model_config?.tools && agent.model_config.tools.length > 0 && (
                            <div>
                              <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                                Tools ({agent.model_config.tools.length})
                              </h4>
                              <div className="flex flex-wrap gap-1.5">
                                {agent.model_config.tools.map((t) => (
                                  <span key={t} className="text-[11px] text-cyan-300 bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.5 rounded inline-flex items-center gap-1">
                                    <Wrench className="w-2.5 h-2.5" /> {t}
                                  </span>
                                ))}
                              </div>
                              <p className="text-[11px] text-amber-300/70 mt-2 inline-flex items-start gap-1">
                                <AlertTriangle className="w-3 h-3 mt-0.5" />
                                Verify each tool's data scope matches the agent's intended audience before approving.
                              </p>
                            </div>
                          )}

                          {/* Description */}
                          {agent.description && (
                            <div>
                              <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Description</h4>
                              <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">{agent.description}</p>
                            </div>
                          )}

                          {/* System prompt */}
                          <div>
                            <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                              System prompt ({(agent.system_prompt || '').length} chars)
                            </h4>
                            <pre className="text-xs text-slate-300 bg-slate-900/50 border border-slate-700/30 rounded-lg p-3 whitespace-pre-wrap max-h-72 overflow-y-auto leading-relaxed">
                              {agent.system_prompt || '(empty)'}
                            </pre>
                          </div>

                          {/* Example prompts */}
                          {agent.example_prompts && agent.example_prompts.length > 0 && (
                            <div>
                              <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                                Example prompts ({agent.example_prompts.length})
                              </h4>
                              <ul className="space-y-1 text-xs text-slate-300">
                                {agent.example_prompts.slice(0, 6).map((p, i) => (
                                  <li key={i} className="border-l-2 border-slate-700 pl-2 truncate" title={p}>{p}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {/* Recent executions for context */}
                          <RecentExecs agentId={agent.id} />
                        </div>
                      </motion.div>
                    )}

                    {rejectingId === agent.id && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="mt-4 pt-4 border-t border-slate-700/30">
                          <label className="text-xs uppercase tracking-wider text-slate-500 mb-2 block">
                            Rejection Reason
                          </label>
                          <textarea
                            value={rejectReason}
                            onChange={(e) => setRejectReason(e.target.value)}
                            placeholder="Explain why this agent is being rejected..."
                            className="w-full bg-slate-800/50 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500/30 resize-none"
                            rows={3}
                          />
                          <div className="flex justify-end gap-2 mt-2">
                            <button
                              onClick={() => {
                                setRejectingId(null);
                                setRejectReason('');
                              }}
                              className="px-3 py-1.5 text-xs text-slate-400 hover:text-white transition-colors"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => handleReject(agent.id)}
                              disabled={actionLoading === agent.id}
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500 text-white text-xs font-medium rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50"
                            >
                              <X className="w-3.5 h-3.5" />
                              {actionLoading === agent.id
                                ? 'Rejecting...'
                                : 'Confirm Reject'}
                            </button>
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

function Field({ icon: Icon, label, value, mono }: { icon: any; label: string; value: string; mono?: boolean }) {
  return (
    <div className="bg-slate-900/40 border border-slate-700/40 rounded-md px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        <Icon className="w-3 h-3" /> {label}
      </div>
      <p className={`text-[12px] text-slate-100 truncate ${mono ? 'font-mono' : ''}`} title={value}>{value}</p>
    </div>
  );
}

function RecentExecs({ agentId }: { agentId: string }) {
  const [execs, setExecs] = useState<ExecPreview[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const r = await apiFetch<any>(`/api/agents/${agentId}/executions?limit=5`);
      if (cancelled) return;
      if (r.data) {
        const items = Array.isArray(r.data) ? r.data : (r.data.items || r.data.executions || []);
        setExecs(items.slice(0, 5).map((e: any) => ({
          id: e.id,
          status: e.status,
          duration_ms: e.duration_ms ?? e.duration,
          cost: e.cost,
          created_at: e.created_at,
          output_preview: typeof e.output === 'string' ? e.output.slice(0, 200) : null,
        })));
      } else {
        setError(r.error || 'No execution history available');
      }
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [agentId]);

  return (
    <div>
      <h4 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Recent test executions</h4>
      {loading && <p className="text-[11px] text-slate-500">Loading…</p>}
      {!loading && error && <p className="text-[11px] text-slate-500">No execution history yet — agent has not been tested.</p>}
      {!loading && execs && execs.length === 0 && <p className="text-[11px] text-slate-500">No executions recorded.</p>}
      {!loading && execs && execs.length > 0 && (
        <ul className="space-y-1.5">
          {execs.map(e => (
            <li key={e.id} className="border border-slate-700/40 bg-slate-900/40 rounded-md px-2.5 py-1.5 text-[11px]">
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-px rounded text-[10px] uppercase tracking-wider ${
                  e.status === 'completed' ? 'bg-emerald-500/15 text-emerald-300' :
                  e.status === 'failed' ? 'bg-rose-500/15 text-rose-300' :
                  'bg-slate-500/15 text-slate-300'
                }`}>{e.status}</span>
                <span className="text-slate-400">{e.duration_ms ? `${e.duration_ms}ms` : '—'}</span>
                <span className="text-emerald-300">{typeof e.cost === 'number' ? `$${e.cost.toFixed(4)}` : '—'}</span>
                <span className="text-slate-600 ml-auto">{formatDate(e.created_at)}</span>
              </div>
              {e.output_preview && (
                <p className="text-slate-400 mt-1 truncate" title={e.output_preview}>{e.output_preview}…</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
