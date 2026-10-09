'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  AlertTriangle, Bot, Check, GitPullRequest,
  Loader2, RotateCcw, ShieldCheck, Sparkles, X,
} from 'lucide-react';
import { toastError, toastSuccess } from '@/stores/toastStore';
import { describePatch } from '@/lib/patchDiff';
import PageHeader from '@/components/layout/PageHeader';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface DiffRow {
  id: string;
  execution_id: string;
  node_id: string;
  node_kind: string;
  node_target: string | null;
  error_class: string;
  error_message: string;
  expected_shape: unknown;
  observed_shape: unknown;
  recent_success_count: number;
  recent_failure_count: number;
  created_at: string;
}

interface PatchRow {
  id: string;
  title: string;
  rationale: string;
  confidence: number;
  risk_level: 'low' | 'medium' | 'high';
  status: 'pending' | 'accepted' | 'rejected' | 'superseded';
  json_patch: unknown;
  dsl_before: unknown;
  dsl_after: unknown;
  triggering_diff_id: string | null;
  triggering_execution_id: string | null;
  decided_at: string | null;
  decided_by: string | null;
  rolled_back_at: string | null;
  created_at: string;
}

interface Envelope<T> {
  data: T | null;
  error: { message?: string; code?: number } | null;
  meta: { can_edit?: boolean; user_id?: string } | null;
}

async function readEnvelope<T>(res: Response): Promise<Envelope<T>> {
  let json: Envelope<T> | null = null;
  try {
    json = (await res.json()) as Envelope<T>;
  } catch {
    json = null;
  }
  if (!res.ok) {
    const msg = json?.error?.message || `${res.status} ${res.statusText}`.trim();
    throw new Error(msg || 'Request failed');
  }
  if (!json) throw new Error('Empty response');
  return json;
}

function authHeaders(): HeadersInit {
  const t = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function relTime(iso: string | null): string {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

function riskColor(r: string): string {
  if (r === 'high') return 'bg-red-500/10 text-red-400 border-red-500/30';
  if (r === 'medium') return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
  return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
}

function statusColor(s: string): string {
  if (s === 'pending') return 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30';
  if (s === 'accepted') return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  if (s === 'rejected') return 'bg-slate-700/30 text-slate-400 border-slate-700/50';
  if (s === 'superseded') return 'bg-slate-700/30 text-slate-500 border-slate-700/50';
  return '';
}

export default function HealingPage() {
  const params = useParams();
  const pipelineId = params.id as string;

  const [diffs, setDiffs] = useState<DiffRow[]>([]);
  const [patches, setPatches] = useState<PatchRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [diagnosing, setDiagnosing] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [expandedPatch, setExpandedPatch] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [gateBlock, setGateBlock] = useState<{ message: string; link: string } | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [dRes, pRes] = await Promise.all([
        fetch(`${API_URL}/api/pipelines/${pipelineId}/diffs?limit=15`, { headers: authHeaders() }),
        fetch(`${API_URL}/api/pipelines/${pipelineId}/patches`, { headers: authHeaders() }),
      ]);
      const dJson = await readEnvelope<DiffRow[]>(dRes);
      const pJson = await readEnvelope<PatchRow[]>(pRes);
      setDiffs(Array.isArray(dJson.data) ? dJson.data : []);
      setPatches(Array.isArray(pJson.data) ? pJson.data : []);
      setCanEdit(Boolean(pJson.meta?.can_edit));
      setUserId(pJson.meta?.user_id ?? null);
    } catch (e: unknown) {
      setDiffs([]);
      setPatches([]);
      setCanEdit(false);
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [pipelineId]);

  const canRollback = (p: PatchRow) => canEdit || (!!userId && p.decided_by === userId);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const diagnose = async () => {
    setDiagnosing(true);
    try {
      const res = await fetch(`${API_URL}/api/pipelines/${pipelineId}/diagnose`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const json = await readEnvelope<{ title?: string }>(res);
      toastSuccess('Patch drafted', json.data?.title || 'New proposal added');
      await loadAll();
    } catch (e: unknown) {
      toastError('Surgeon failed', e instanceof Error ? e.message : String(e));
    } finally {
      setDiagnosing(false);
    }
  };

  const act = async (patchId: string, action: 'apply' | 'reject' | 'rollback') => {
    setActing(patchId);
    setGateBlock(null);
    try {
      const res = await fetch(`${API_URL}/api/pipelines/${pipelineId}/patches/${patchId}/${action}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (res.status === 409) {
        const j = await res.clone().json().catch(() => null);
        const link = j?.error?.details?.link;
        if (link) setGateBlock({ message: j.error.message || 'The eval gate refused this patch.', link });
      }
      await readEnvelope<unknown>(res);
      toastSuccess(
        `Patch ${action === 'apply' ? 'applied' : action === 'reject' ? 'rejected' : 'rolled back'}`,
        action === 'apply' ? 'Run the pipeline again from the builder to confirm the fix.' : undefined,
      );
      await loadAll();
    } catch (e: unknown) {
      toastError(`${action} failed`, e instanceof Error ? e.message : String(e));
    } finally {
      setActing(null);
    }
  };

  const pendingPatches = patches.filter(p => p.status === 'pending');
  const acceptedPatches = patches.filter(p => p.status === 'accepted');
  const otherPatches = patches.filter(p => p.status === 'rejected' || p.status === 'superseded');

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto">
      <PageHeader
        title="Self-healing"
        icon={Sparkles}
        purpose="Review fixes drafted for this pipeline's failed steps and apply the ones you trust. For pipeline owners."
        back={{ href: `/agents/${pipelineId}/info`, label: 'Back to pipeline' }}
        primaryAction={{
          label: 'Diagnose latest failure',
          onClick: diagnose,
          icon: diagnosing ? Loader2 : Bot,
          busy: diagnosing,
          disabled: diffs.length === 0 || !canEdit || !!loadError,
          title: canEdit ? undefined : 'Only admins or the pipeline owner can run the surgeon',
        }}
        steps={[
          'When a step fails, the failure is recorded with what the step expected and what it got.',
          'Press Diagnose and the Pipeline Surgeon agent drafts the smallest fix, like a fallback value or a skip on error.',
          'Nothing changes until you press Apply. Every applied fix can be rolled back in one click.',
        ]}
        docSlug="02-runtime/10-pipeline-healing-drift"
        storageKey="agent-healing"
        className="mb-6"
      />

      {loadError && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-medium">Could not load healing data</div>
            <div className="text-red-400/80 mt-0.5">{loadError}</div>
            <button onClick={() => void loadAll()} className="mt-2 underline hover:text-red-200">Retry</button>
          </div>
        </div>
      )}

      {gateBlock && (
        <div role="alert" data-testid="healing-gate-block" className="mb-6 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <div className="font-medium">The patch was not applied</div>
            <div className="text-amber-200/80 mt-0.5 break-words">{gateBlock.message}</div>
            <div className="mt-2 flex gap-3">
              <a href={gateBlock.link} className="underline hover:text-white">See the failing run</a>
              <button onClick={() => setGateBlock(null)} className="underline hover:text-white">Dismiss</button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-6 empty:hidden">
        {diffs.length === 0 && !loading && !loadError && (
          <span className="text-xs text-slate-500">No failures recorded yet — run the pipeline first.</span>
        )}
        {!canEdit && !loading && !loadError && (
          <span className="text-xs text-slate-500">Read-only: only admins or the pipeline owner can act on patches.</span>
        )}
      </div>

      {/* Pending proposals */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Pending proposals ({pendingPatches.length})
        </h2>
        {pendingPatches.length === 0 ? (
          <div className="text-xs text-slate-500 py-3">No pending patches.</div>
        ) : (
          <div className="space-y-3">
            {pendingPatches.map(p => (
              <div key={p.id} className="bg-slate-900/40 border border-cyan-500/30 rounded-xl overflow-hidden">
                <div className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <GitPullRequest className="w-4 h-4 text-cyan-400 shrink-0" />
                        <h3 className="text-sm font-semibold text-white truncate">{p.title}</h3>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskColor(p.risk_level)}`}>
                          {p.risk_level} risk
                        </span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusColor(p.status)}`}>
                          {p.status}
                        </span>
                        <span className="text-[10px] text-slate-500">
                          conf {(p.confidence * 100).toFixed(0)}%
                        </span>
                        <span className="text-[10px] text-slate-500">{relTime(p.created_at)}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">{p.rationale}</p>
                      {describePatch(p.json_patch, p.dsl_before).length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {describePatch(p.json_patch, p.dsl_before).map((c, i) => (
                            <li key={i} data-testid="patch-change" className="text-[11px] font-mono bg-slate-950/50 border border-slate-800 rounded px-2 py-1 break-all">
                              <span className="text-slate-400">{c.where}</span>{' '}
                              <span className="text-red-300 line-through decoration-red-400/60">{c.before}</span>{' '}
                              <span className="text-slate-500">→</span>{' '}
                              <span className="text-emerald-300">{c.after}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {canEdit && (
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => act(p.id, 'apply')}
                        disabled={!!acting}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-medium rounded-md disabled:opacity-50"
                      >
                        {acting === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                        Apply
                      </button>
                      <button
                        onClick={() => act(p.id, 'reject')}
                        disabled={!!acting}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-700 hover:bg-slate-800 text-slate-300 text-xs rounded-md"
                      >
                        <X className="w-3 h-3" /> Reject
                      </button>
                    </div>
                    )}
                  </div>
                  <button
                    onClick={() => setExpandedPatch(expandedPatch === p.id ? null : p.id)}
                    className="text-[11px] text-cyan-400 hover:text-cyan-300 mt-2"
                  >
                    {expandedPatch === p.id ? 'Hide' : 'Show'} JSON-Patch
                  </button>
                  {expandedPatch === p.id && (
                    <pre className="mt-2 text-[11px] text-slate-300 bg-slate-950/60 border border-slate-800 rounded-lg p-3 overflow-x-auto max-h-64">
                      {JSON.stringify(p.json_patch, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Accepted (with rollback) */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Applied patches ({acceptedPatches.length})
        </h2>
        {acceptedPatches.length === 0 ? (
          <div className="text-xs text-slate-500 py-3">None yet.</div>
        ) : (
          <div className="space-y-2">
            {acceptedPatches.map(p => (
              <div key={p.id} className="bg-slate-900/40 border border-slate-800 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span className="text-sm text-white truncate">{p.title}</span>
                    {p.rolled_back_at ? (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/30 text-slate-500 border border-slate-700/50">
                        rolled back · {relTime(p.rolled_back_at)}
                      </span>
                    ) : (
                      <span className="text-[10px] text-emerald-400">{relTime(p.decided_at)}</span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{p.rationale}</p>
                  {!p.rolled_back_at && (
                    <Link
                      href={`/builder?agent=${pipelineId}`}
                      data-testid="healing-rerun"
                      className="inline-block mt-1 text-[11px] text-cyan-400 hover:text-cyan-300"
                    >
                      Open in the builder and run it again →
                    </Link>
                  )}
                </div>
                {!p.rolled_back_at && canRollback(p) && (
                  <button
                    onClick={() => act(p.id, 'rollback')}
                    disabled={!!acting}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-700 hover:bg-slate-800 text-slate-300 text-xs rounded-md shrink-0"
                  >
                    <RotateCcw className="w-3 h-3" /> Roll back
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Recent failures */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Recent failures ({diffs.length})
        </h2>
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
          </div>
        ) : loadError ? (
          <div className="text-xs text-red-400 py-3">Failures could not be loaded.</div>
        ) : diffs.length === 0 ? (
          <div className="text-xs text-slate-500 py-3">No failures recorded.  Run the pipeline to populate.</div>
        ) : (
          <div className="space-y-2">
            {diffs.map(d => (
              <div key={d.id} className="bg-slate-900/40 border border-red-500/20 rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                  <span className="text-sm text-white">{d.node_id}</span>
                  <span className="text-[10px] text-slate-500 font-mono">{d.node_kind}{d.node_target ? `:${d.node_target}` : ''}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/30 font-mono">
                    {d.error_class}
                  </span>
                  <span className="text-[10px] text-slate-500 ml-auto">{relTime(d.created_at)}</span>
                </div>
                <p className="text-xs text-slate-400 mt-1 truncate">{d.error_message}</p>
                <div className="text-[10px] text-slate-600 mt-1">
                  Last 24h on this pipeline: {d.recent_success_count} ok · {d.recent_failure_count} fail
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Rejected + superseded (collapsed) */}
      {otherPatches.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
            History ({otherPatches.length})
          </h2>
          <div className="space-y-1">
            {otherPatches.map(p => (
              <div key={p.id} className="text-xs text-slate-500 px-4 py-2 border border-slate-800 rounded-lg flex items-center gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusColor(p.status)}`}>{p.status}</span>
                <span>{p.title}</span>
                <span className="ml-auto">{relTime(p.created_at)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="mt-10 text-[11px] text-slate-600 text-center">
        Surgeon model is configured under{' '}
        <Link href="/admin/settings" className="text-cyan-400 hover:underline">Admin → Settings</Link>{' '}
        (key <code>pipeline_surgeon.model</code>).
      </div>
    </div>
  );
}
