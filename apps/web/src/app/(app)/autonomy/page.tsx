'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Activity, AlertTriangle, ArrowRight, Flag, Loader2, Milestone, Plus, RefreshCw, Rocket, ShieldCheck, Sparkles, TrendingDown, Zap,
} from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { toast } from '@/stores/toastStore';
import LevelPill from '@/components/autonomy/LevelPill';
import Sparkline from '@/components/autonomy/Sparkline';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import { AUTONOMY_STEPS, AutonomyLevels } from './AutonomyHow';
import EnrolWizard from '@/components/autonomy/EnrolWizard';
import { autonomyApi, levelLabel, scopeText, type GrantRow, type Overview } from '@/lib/autonomy';

type Filter = 'all' | 'auto' | 'harm';
const ENROLLED_KEY = 'autonomy.justEnrolled';

function accuracyText(g: GrantRow): string {
  const s = g.stats;
  if (!s) return 'No results yet';
  if (g.level <= 1) {
    if (!s.reviews) return 'No reviews yet';
    return `${s.agreement_pct ?? 0}% agreed, ${s.reviews} review${s.reviews === 1 ? '' : 's'}`;
  }
  if (!s.scored) return 'No results yet';
  return `${s.accuracy_pct ?? 0}% held, ${s.scored} scored`;
}

function readyReason(g: GrantRow): string {
  const to = g.next?.next_level;
  return typeof to === 'number' ? `Met every check to move up to ${levelLabel(to)}.` : 'Met every check for the next step.';
}

export default function AutonomyPage() {
  usePageTitle('Autonomy');
  const router = useRouter();
  const { perms, loading: permLoading } = useMyPermissions();
  const canView = holds(perms?.capabilities, 'autonomy.view');
  const canManage = holds(perms?.capabilities, 'autonomy.manage');
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>('all');
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleErr, setSampleErr] = useState<string | null>(null);
  const [wizard, setWizard] = useState<{ agent?: { id: string; name: string }; tool?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await autonomyApi.overview();
    setLoading(false);
    if (r.error) { setError(r.error); return; }
    setError(null);
    setData(r.data);
  }, []);

  useEffect(() => {
    if (!permLoading && canView) load();
    if (!permLoading && !canView) setLoading(false);
  }, [permLoading, canView, load]);

  async function startSample() {
    setSampleBusy(true);
    setSampleErr(null);
    const r = await autonomyApi.sample();
    setSampleBusy(false);
    if (r.error || !r.data?.grant?.id) {
      setSampleErr(r.status === 403 ? 'Installing the sample needs the autonomy.manage permission. Ask an admin to grant it under Admin, Permissions.' : r.error || 'The sample did not install. Try again.');
      return;
    }
    toast({ type: 'success', title: 'Sample plant installed', message: 'Run the sample agent to see its first proposal.' });
    router.push(`/autonomy/${encodeURIComponent(r.data.grant.id)}`);
  }

  const grants = useMemo(() => {
    const all = data?.grants || [];
    if (filter === 'auto') return all.filter((g) => g.level >= 3);
    if (filter === 'harm') return all.filter((g) => (g.stats?.harm_30d || 0) > 0);
    return all;
  }, [data, filter]);

  // agents by action type for the wide grid
  const matrix = useMemo(() => {
    const agents = new Map<string, string>();
    const types = new Map<string, string>();
    const cells = new Map<string, GrantRow[]>();
    for (const g of grants) {
      agents.set(g.agent.id, g.agent.name);
      types.set(g.action_type.id, g.action_type.label);
      const k = `${g.agent.id}|${g.action_type.id}`;
      cells.set(k, [...(cells.get(k) || []), g]);
    }
    return { agents: [...agents.entries()], types: [...types.entries()], cells };
  }, [grants]);

  if (!permLoading && !canView) {
    return (
      <NoAccess
        testId="autonomy-no-access"
        title="Autonomy"
        purpose="Agents earn the right to act, one kind of action at a time, from their track record. For the people who decide how far an agent may go alone."
        icon={Milestone}
        need={{ capability: 'autonomy.view', label: 'View autonomy' }}
        role={perms?.role}
        instead={{ text: 'Approvals lists any agent action waiting for a decision from you.', href: '/approvals', label: 'Open Approvals' }}
      />
    );
  }

  const counts = data?.counts;
  const empty = !!data && (data.grants || []).length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6" data-testid="autonomy-page">
      <PageHeader
        title="Autonomy"
        purpose="Agents earn the right to act, one kind of action at a time, from their track record. For the people who decide how far an agent may go alone."
        icon={Milestone}
        storageKey="autonomy"
        docSlug="08-howto/13-earned-autonomy"
        howTestId="autonomy-how-it-works"
        howToggleTestId="autonomy-how-toggle"
        steps={AUTONOMY_STEPS}
        howItWorks={<AutonomyLevels />}
        primaryAction={{
          label: 'Enrol an agent',
          onClick: () => setWizard({}),
          icon: Plus,
          disabled: !canManage,
          title: canManage ? undefined : 'Enrolling needs the autonomy.manage permission. An admin can grant it under Admin, Permissions.',
          testId: 'autonomy-enrol-open',
        }}
        extraActions={
          <button type="button" onClick={load} className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800" aria-label="Refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        }
      >
        {!canManage && !permLoading && (
          <p className="text-xs text-slate-500">
            You can look but not enrol. Enrolling needs autonomy.manage. <Link href="/admin/permissions" className="text-cyan-300 hover:underline">Permissions</Link>
          </p>
        )}
      </PageHeader>

      {error ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert" data-testid="autonomy-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>Could not load autonomy: {error}. Check your connection and try again.</span>
          <button type="button" onClick={load} className="ml-auto rounded border border-rose-500/40 px-2 py-1 text-xs hover:bg-rose-500/20">Try again</button>
        </div>
      ) : loading && !data ? (
        <div className="space-y-3" data-testid="autonomy-loading">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-slate-800/40" />)}</div>
          <div className="h-48 animate-pulse rounded-xl bg-slate-800/40" />
        </div>
      ) : data ? (
        <>
          {/* the three numbers */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="autonomy-counts">
            {([
              { f: 'all' as Filter, label: 'Actions this week', value: counts?.actions_7d, icon: Activity, tone: 'text-cyan-300', id: 'actions' },
              { f: 'auto' as Filter, label: 'Run without asking', value: counts?.auto_7d, icon: Zap, tone: 'text-emerald-300', id: 'auto' },
              { f: 'harm' as Filter, label: 'Harm flags', value: counts?.harm_7d, icon: Flag, tone: (counts?.harm_7d || 0) > 0 ? 'text-rose-300' : 'text-slate-300', id: 'harm' },
            ]).map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setFilter(filter === c.f && c.f !== 'all' ? 'all' : c.f)}
                aria-pressed={filter === c.f}
                className={`rounded-xl border p-4 text-left transition ${filter === c.f ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-700/50 bg-slate-800/30 hover:border-slate-600'}`}
                data-testid={`autonomy-count-${c.id}`}
              >
                <div className="flex items-center gap-2 text-xs text-slate-400"><c.icon className={`h-4 w-4 ${c.tone}`} /> {c.label}</div>
                <div className={`mt-1 text-2xl font-semibold ${c.tone}`}>{typeof c.value === 'number' ? c.value : 'No data'}</div>
                <div className="mt-0.5 text-[11px] text-slate-500">{c.f === 'all' ? 'Show every enrolled action' : c.f === 'auto' ? 'Show actions that run alone' : 'Show actions with harm in 30 days'}</div>
              </button>
            ))}
          </div>
          {((counts?.pending_reviews || 0) > 0 || (counts?.pending_approvals || 0) > 0) && (
            <div className="flex flex-wrap gap-2 text-sm">
              {(counts?.pending_reviews || 0) > 0 && (
                <Link href="/approvals?tab=reviews" className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-sky-200 hover:bg-sky-500/20" data-testid="autonomy-pending-reviews">
                  {counts?.pending_reviews} watching review{counts?.pending_reviews === 1 ? '' : 's'} to answer <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
              {(counts?.pending_approvals || 0) > 0 && (
                <Link href="/approvals" className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-amber-200 hover:bg-amber-500/20" data-testid="autonomy-pending-approvals">
                  {counts?.pending_approvals} action{counts?.pending_approvals === 1 ? '' : 's'} waiting for approval <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          )}

          {empty ? (
            <section className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/10 to-slate-900/40 p-6" data-testid="autonomy-empty">
              <Sparkles className="h-7 w-7 text-cyan-300" />
              <h2 className="mt-3 text-lg font-semibold text-white">No agent is earning autonomy yet</h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
                Pick an action an agent takes, like publishing a command or sending an email. It starts by watching: it says what
                it would do and nothing runs. As people agree and its predictions hold, it can ask first, then act within limits.
                The sample plant shows the whole ladder in a few minutes with nothing to connect.
              </p>
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  disabled={!canManage || sampleBusy}
                  title={canManage ? undefined : 'Needs the autonomy.manage permission'}
                  onClick={startSample}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="autonomy-sample-start"
                >
                  {sampleBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} Try it with the sample plant
                </button>
                <button
                  type="button"
                  disabled={!canManage}
                  title={canManage ? undefined : 'Needs the autonomy.manage permission'}
                  onClick={() => setWizard({})}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Enrol your own agent
                </button>
              </div>
              {!canManage && <p className="mt-2 text-xs text-slate-400">Both need the autonomy.manage permission. <Link href="/admin/permissions" className="text-cyan-300 hover:underline">Ask an admin</Link>.</p>}
              {sampleErr && <p className="mt-2 text-sm text-rose-300" role="alert" data-testid="autonomy-sample-error">{sampleErr}</p>}
            </section>
          ) : (
            <section data-testid="autonomy-grid-section">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-white">Agents and actions</h2>
                {filter !== 'all' && (
                  <button type="button" onClick={() => setFilter('all')} className="text-xs text-cyan-300 hover:underline">Show all</button>
                )}
              </div>
              {grants.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400" data-testid="autonomy-grid-empty">
                  {filter === 'auto' ? 'No action runs without asking yet.' : 'No harm flagged in the last 30 days.'}
                </p>
              ) : (
                <>
                  {/* phones: a list */}
                  <ul className="space-y-2 md:hidden" data-testid="autonomy-list">
                    {grants.map((g) => (
                      <li key={g.id}>
                        <Link href={`/autonomy/${g.id}`} className="block rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 hover:border-slate-600" data-testid="autonomy-grant-row">
                          <div className="flex items-start gap-2">
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-sm font-medium text-white">{g.action_type.label}</p>
                              <p className="truncate text-xs text-slate-400">{g.agent.name}{g.scope?.param ? ` · ${scopeText(g.scope)}` : ''}</p>
                            </div>
                            {g.attention && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-400" title={g.attention} aria-label={g.attention} />}
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-3">
                            <LevelPill level={g.level} ceiling={g.ceiling} size="sm" />
                            <Sparkline values={g.spark} />
                            <span className="text-[11px] text-slate-500">{accuracyText(g)}</span>
                          </div>
                          {g.attention && <p className="mt-1 text-[11px] text-amber-200">{g.attention}</p>}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  {/* wider: agents by action type */}
                  <div className="hidden overflow-x-auto rounded-xl border border-slate-700/50 md:block" data-testid="autonomy-grid">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-800/50 text-left text-[11px] uppercase tracking-wide text-slate-400">
                        <tr>
                          <th className="px-3 py-2 font-medium">Agent</th>
                          {matrix.types.map(([id, label]) => <th key={id} className="px-3 py-2 font-medium">{label}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {matrix.agents.map(([aid, aname]) => (
                          <tr key={aid} className="border-t border-slate-800">
                            <td className="px-3 py-3 align-top text-white">{aname}</td>
                            {matrix.types.map(([tid]) => {
                              const cell = matrix.cells.get(`${aid}|${tid}`) || [];
                              return (
                                <td key={tid} className="px-3 py-3 align-top">
                                  {cell.length === 0 ? (
                                    <span className="text-xs text-slate-600">Not enrolled</span>
                                  ) : (
                                    <div className="space-y-2">
                                      {cell.map((g) => (
                                        <Link key={g.id} href={`/autonomy/${g.id}`} className="block rounded-lg border border-transparent p-1.5 hover:border-slate-700 hover:bg-slate-800/40" data-testid="autonomy-grid-cell">
                                          <div className="flex items-center gap-2">
                                            <LevelPill level={g.level} ceiling={g.ceiling} size="sm" />
                                            {g.attention && <span className="h-2 w-2 rounded-full bg-amber-400" title={g.attention} aria-label={g.attention} />}
                                          </div>
                                          <div className="mt-1 flex items-center gap-2">
                                            <Sparkline values={g.spark} />
                                            <span className="text-[11px] text-slate-500">{accuracyText(g)}</span>
                                          </div>
                                          {g.scope?.param && <p className="mt-0.5 text-[10px] text-slate-500">{scopeText(g.scope)}</p>}
                                          {g.state === 'paused' && <p className="mt-0.5 text-[10px] text-amber-300">Paused</p>}
                                        </Link>
                                      ))}
                                    </div>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}

          {!empty && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-ready">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white"><Rocket className="h-4 w-4 text-emerald-400" /> Ready to promote</h2>
                {data.ready_to_promote.length === 0 ? (
                  <p className="text-sm text-slate-400">Nothing is ready yet. Each action page shows what is still missing.</p>
                ) : (
                  <ul className="space-y-2">
                    {data.ready_to_promote.map((g) => (
                      <li key={g.id} className="flex flex-col gap-2 rounded-lg bg-slate-900/40 p-3 sm:flex-row sm:items-center" data-testid="autonomy-ready-row">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-white">{g.agent.name} · {g.action_type.label}</p>
                          <p className="text-xs text-slate-400">{readyReason(g)}</p>
                        </div>
                        <Link href={`/autonomy/${g.id}`} className="inline-flex shrink-0 items-center justify-center gap-1 rounded-md bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/25">
                          Review and promote <ArrowRight className="h-3 w-3" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-demoted">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white"><TrendingDown className="h-4 w-4 text-rose-400" /> Recently demoted</h2>
                {data.recently_demoted.length === 0 ? (
                  <p className="text-sm text-slate-400">No demotions recently.</p>
                ) : (
                  <ul className="space-y-2">
                    {data.recently_demoted.map(({ grant: g, change }) => (
                      <li key={`${g.id}-${change.created_at}`} className="flex flex-col gap-2 rounded-lg bg-slate-900/40 p-3 sm:flex-row sm:items-center" data-testid="autonomy-demoted-row">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-white">{g.agent.name} · {g.action_type.label}</p>
                          <p className="text-xs text-slate-400">
                            Dropped from {levelLabel(change.from_level)} to {levelLabel(change.to_level)}{change.reason ? `: ${change.reason}` : '.'}
                          </p>
                        </div>
                        <Link href={`/autonomy/${g.id}`} className="inline-flex shrink-0 items-center justify-center gap-1 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">
                          See why <ArrowRight className="h-3 w-3" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}

          <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-unmanaged">
            <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-white"><ShieldCheck className="h-4 w-4 text-slate-400" /> Unmanaged actions</h2>
            <p className="mb-3 text-xs text-slate-500">Actions agents took this week that no one has enrolled. They run as before and are recorded.</p>
            {data.unmanaged.length === 0 ? (
              <p className="text-sm text-slate-400">Every action agents took this week is enrolled, or none were taken.</p>
            ) : (
              <ul className="space-y-2">
                {data.unmanaged.map((u) => (
                  <li key={`${u.agent_id}-${u.tool_name}`} className="flex flex-col gap-2 rounded-lg bg-slate-900/40 p-3 sm:flex-row sm:items-center" data-testid="autonomy-unmanaged-row">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-white">{u.suggested_action_type?.label || u.tool_name}</p>
                      <p className="text-xs text-slate-400">{u.agent_name} · {u.count_7d} time{u.count_7d === 1 ? '' : 's'} this week · <span className="font-mono">{u.tool_name}</span></p>
                    </div>
                    <button
                      type="button"
                      disabled={!canManage}
                      title={canManage ? undefined : 'Enrolling needs the autonomy.manage permission'}
                      onClick={() => setWizard({ agent: { id: u.agent_id, name: u.agent_name }, tool: u.tool_name })}
                      className="shrink-0 rounded-md bg-cyan-500/15 px-3 py-1.5 text-xs font-medium text-cyan-300 hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid="autonomy-unmanaged-enrol"
                    >
                      Enrol
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}

      <EnrolWizard
        open={wizard !== null}
        onClose={() => setWizard(null)}
        presetAgent={wizard?.agent || null}
        presetTool={wizard?.tool || null}
        onEnrolled={(g) => {
          // the grant page shows what to do next once
          try { sessionStorage.setItem(ENROLLED_KEY, g.id); } catch { /* storage blocked */ }
          load();
        }}
      />
    </div>
  );
}
