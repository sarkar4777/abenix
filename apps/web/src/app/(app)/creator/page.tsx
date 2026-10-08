'use client';

import { useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  LazyAreaChart as AreaChart,
  LazyArea as Area,
  LazyXAxis as XAxis,
  LazyYAxis as YAxis,
  LazyTooltip as Tooltip,
  LazyResponsiveContainer as ResponsiveContainer,
} from '@/components/ui/LazyCharts';
import {
  Activity,
  BookOpen,
  Bot,
  CheckCircle2,
  Clock,
  DollarSign,
  Download,
  ExternalLink,
  FlaskConical,
  Info,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldCheck,
  Star,
  Store,
  XCircle,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import { usePlatformFeatures, plainError } from '@/hooks/usePlatformFeatures';
import MarketplaceOffNotice from '@/components/marketplace/MarketplaceOffNotice';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonStatCard, SkeletonChartCard } from '@/components/ui/Skeleton';
import { toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';

interface Listing {
  id: string;
  name: string;
  description?: string | null;
  category?: string | null;
  state: 'live' | 'pending' | 'rejected';
  rejection_reason?: string | null;
  installs: number;
  runs_30d: number;
  users_30d: number;
  avg_rating: number;
  review_count: number;
  price?: number;
}

interface ListingsData {
  can_list: boolean;
  monetization: boolean;
  listings: Listing[];
  eligible: { id: string; name: string; category?: string | null }[];
  totals: { live: number; pending: number; installs: number; runs_30d: number };
}

interface CreatorStatus {
  is_onboarded: boolean;
  stripe_connect_id: string | null;
}

// field names as GET /api/creator/dashboard sends them
interface DashboardData {
  creator_earnings: number;
  balance: {
    available: { amount: number; currency: string }[];
    pending: { amount: number; currency: string }[];
  };
  revenue_by_day: { date: string; earnings: number; count: number }[];
  top_agents: { agent_id: string; agent_name: string; earnings: number; revenue: number; transactions: number }[];
  recent_payouts: { id: string; agent_id: string; amount_total: number; creator_amount: number; platform_fee: number; status: string; created_at: string }[];
}

const CATEGORIES = ['productivity', 'research', 'engineering', 'communication', 'analytics', 'legal', 'other'];
const PERIODS = ['7d', '30d', '90d'] as const;

const STATE_BADGE: Record<Listing['state'], { label: string; cls: string }> = {
  live: { label: 'Live in the store', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' },
  pending: { label: 'Waiting for review', cls: 'bg-amber-500/10 text-amber-300 border-amber-500/20' },
  rejected: { label: 'Not approved', cls: 'bg-red-500/10 text-red-300 border-red-500/20' },
};

function ListAgentForm({ data, onListed }: { data: ListingsData; onListed: (agent: { id: string; name: string }) => void }) {
  const [agentId, setAgentId] = useState('');
  const [category, setCategory] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');
  const resubmittable = data.listings.filter((l) => l.state === 'rejected');
  const options = [...data.eligible, ...resubmittable.map((l) => ({ id: l.id, name: `${l.name} (submit again)`, category: l.category }))];

  const submit = async () => {
    if (!agentId) {
      setErr('Pick the agent you want to list.');
      return;
    }
    setSubmitting(true);
    setErr('');
    const res = await apiFetch(`/api/agents/${agentId}/publish`, {
      method: 'POST',
      body: JSON.stringify({ visibility: 'public', ...(category ? { category } : {}) }),
      throwOnError: false,
    });
    setSubmitting(false);
    if (res.error) {
      setErr(plainError(res.error, res.errorDetail?.error_code));
      return;
    }
    const listed = options.find((o) => o.id === agentId);
    setAgentId('');
    setCategory('');
    toastSuccess('Submitted for review', 'An admin reviews it, then it shows in the Marketplace.');
    onListed({ id: agentId, name: listed?.name || 'Your agent' });
  };

  let blocked = '';
  if (!data.can_list) blocked = 'role';
  else if (options.length === 0) blocked = 'empty';

  return (
    <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6" data-testid="creator-list-form">
      <h2 className="text-sm font-semibold text-white">List an agent</h2>
      <p className="text-xs text-slate-400 mt-1">
        Listing costs nothing. An admin reviews the agent first, then anyone on this platform can find and install it.
        {!data.monetization && ' Installing is free too.'}
      </p>

      {blocked === 'role' && (
        <p className="mt-3 flex items-start gap-2 text-xs text-slate-300" data-testid="creator-list-blocked">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-cyan-400" />
          Your role cannot list agents. Ask an admin to make you a Creator in Settings, Team.
        </p>
      )}
      {blocked === 'empty' && (
        <p className="mt-3 flex items-start gap-2 text-xs text-slate-300" data-testid="creator-list-blocked">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-cyan-400" />
          <span>
            You have no agents that can be listed yet.{' '}
            <Link href="/builder" className="text-cyan-400 hover:underline">Build one in the Agent Builder</Link>, then come back.
          </span>
        </p>
      )}

      {!blocked && (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-[1fr_200px_auto] gap-3 items-end">
          <div>
            <label htmlFor="list-agent" className="block text-[11px] font-medium text-slate-400 mb-1">Agent</label>
            <select
              id="list-agent"
              data-testid="creator-list-agent"
              value={agentId}
              onChange={(e) => {
                setAgentId(e.target.value);
                setErr('');
                const picked = options.find((o) => o.id === e.target.value);
                if (picked?.category && !category) setCategory(picked.category);
              }}
              className="w-full px-3 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white focus:border-cyan-500 focus:outline-none"
            >
              <option value="">Choose one of your agents</option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="list-category" className="block text-[11px] font-medium text-slate-400 mb-1">Category (optional)</label>
            <select
              id="list-category"
              data-testid="creator-list-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white focus:border-cyan-500 focus:outline-none"
            >
              <option value="">No category</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
              ))}
            </select>
          </div>
          <button
            onClick={submit}
            disabled={submitting}
            data-testid="creator-list-submit"
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 disabled:opacity-50"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {submitting ? 'Submitting...' : 'Submit for review'}
          </button>
        </div>
      )}
      {err && (
        <p role="alert" data-testid="creator-list-error" className="mt-3 text-sm text-red-400">{err}</p>
      )}
    </section>
  );
}

function Revenue() {
  const [period, setPeriod] = useState<string>('30d');
  const [onboarding, setOnboarding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { data: status, mutate: mutateStatus } = useApi<CreatorStatus>('/api/creator/status');
  const { data: dashboard, isLoading, error, mutate: mutateDash } = useApi<DashboardData>(`/api/creator/dashboard?period=${period}`);

  const handleOnboard = async () => {
    setOnboarding(true);
    setErr(null);
    const res = await apiFetch<{ onboarding_url: string; mode: string }>('/api/creator/onboard', {
      method: 'POST',
      body: JSON.stringify({
        refresh_url: `${window.location.origin}/creator?refresh=true`,
        return_url: `${window.location.origin}/creator?onboarded=true`,
      }),
      throwOnError: false,
    });
    setOnboarding(false);
    if (res.data?.onboarding_url) {
      if (res.data.mode === 'mock') {
        mutateStatus();
        mutateDash();
      } else {
        window.location.href = res.data.onboarding_url;
      }
    } else {
      setErr(res.error || 'Stripe did not return a sign-up link. Try again in a minute.');
    }
  };

  const openStripe = async () => {
    const res = await apiFetch<{ url: string }>('/api/creator/login-link', { throwOnError: false });
    if (res.data?.url) window.open(res.data.url, '_blank');
    else setErr(res.error || 'Stripe did not return a dashboard link.');
  };

  const fmt = (n: number) => `$${n.toFixed(2)}`;
  const fmtCents = (n: number) => `$${(n / 100).toFixed(2)}`;

  return (
    <section className="space-y-4" data-testid="creator-revenue">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-white">Revenue and payouts</h2>
        <div className="flex items-center gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              aria-pressed={period === p}
              className={`px-3 py-1.5 text-xs rounded-lg ${period === p ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' : 'text-slate-400 hover:text-white'}`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {status && !status.is_onboarded && (
        <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4">
          <p className="text-sm text-white font-medium">Get paid for paid listings</p>
          <p className="text-xs text-slate-400 mt-1">Connect a Stripe account to receive payouts. Free listings do not need it.</p>
          <button
            onClick={handleOnboard}
            disabled={onboarding}
            className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg disabled:opacity-50"
          >
            {onboarding && <Loader2 className="w-4 h-4 animate-spin" />}
            {onboarding ? 'Connecting...' : 'Connect with Stripe'}
          </button>
        </div>
      )}

      {(err || error) && (
        <div role="alert" data-testid="creator-error" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {err || `Could not load revenue. ${plainError(error)}`}
        </div>
      )}

      {isLoading ? (
        <SkeletonChartCard />
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-4">
              <p className="text-2xl font-bold text-emerald-400">{fmt(dashboard?.creator_earnings || 0)}</p>
              <p className="text-xs text-slate-500 mt-1">Earnings</p>
            </div>
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
              <p className="text-2xl font-bold text-amber-400">{fmtCents(dashboard?.balance?.pending?.[0]?.amount || 0)}</p>
              <p className="text-xs text-slate-500 mt-1">Pending balance</p>
            </div>
            <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-4">
              <p className="text-2xl font-bold text-cyan-400">{fmtCents(dashboard?.balance?.available?.[0]?.amount || 0)}</p>
              <p className="text-xs text-slate-500 mt-1">Available balance</p>
            </div>
          </div>
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6">
            <h3 className="text-sm font-semibold text-white mb-4">Earnings over time</h3>
            {(dashboard?.revenue_by_day || []).length === 0 ? (
              <p className="text-sm text-slate-500">No earnings in this period.</p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={dashboard?.revenue_by_day || []}>
                    <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f1f5f9', fontSize: '12px' }}
                      formatter={(value: unknown) => [`$${Number(value).toFixed(2)}`, 'Earnings']}
                    />
                    <Area type="monotone" dataKey="earnings" stroke="#06b6d4" strokeWidth={2} fill="#06b6d433" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Recent payouts</h3>
              {status?.is_onboarded && (
                <button onClick={openStripe} className="inline-flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300">
                  <ExternalLink className="w-3.5 h-3.5" /> Stripe dashboard
                </button>
              )}
            </div>
            {dashboard?.recent_payouts?.length ? (
              <ul className="divide-y divide-slate-700/30">
                {dashboard.recent_payouts.map((p) => (
                  <li key={p.id} className="py-2 flex items-center justify-between gap-2 text-sm">
                    <span className="text-slate-300 truncate">
                      {dashboard.top_agents.find((t) => t.agent_id === p.agent_id)?.agent_name || 'Subscription payout'}
                      <span className="text-xs text-slate-500 ml-2">{new Date(p.created_at).toLocaleDateString()}</span>
                    </span>
                    <span className="text-emerald-400 font-medium">{fmt(p.creator_amount)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No payouts yet.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export default function CreatorHub() {
  usePageTitle('Creator Hub');
  const switches = usePlatformFeatures();
  const { data, isLoading, error, mutate } = useApi<ListingsData>(switches.marketplace ? '/api/creator/listings' : null);
  const [listed, setListed] = useState<{ id: string; name: string } | null>(null);

  if (switches.loaded && !switches.marketplace) {
    return (
      <div className="space-y-6" data-testid="creator-off">
        <PageHeader
          title="Creator Hub"
          icon={Store}
          purpose="List your agents in the Marketplace and see who installs and runs them. For agent creators."
          storageKey="creator"
        />
        <MarketplaceOffNotice what="Listings, installs and usage come back when it is on again." />
      </div>
    );
  }

  const loading = !switches.loaded || (isLoading && !data);
  const totals = data?.totals;
  const kpis = [
    { label: 'Live listings', value: totals?.live ?? 0, icon: CheckCircle2, color: 'text-emerald-400' },
    { label: 'Waiting for review', value: totals?.pending ?? 0, icon: Clock, color: 'text-amber-400' },
    { label: 'Installs', value: totals?.installs ?? 0, icon: Download, color: 'text-cyan-400' },
    { label: 'Runs, last 30 days', value: totals?.runs_30d ?? 0, icon: Activity, color: 'text-purple-400' },
  ];

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-6" data-testid="creator-hub">
      <PageHeader
        title="Creator Hub"
        icon={Store}
        purpose={`List your agents in the Marketplace for free and see who installs and runs them. For agent creators.${switches.monetization ? ' Revenue and payouts are at the bottom.' : ''}`}
        primaryAction={{
          label: 'List an agent',
          icon: Send,
          onClick: () => document.querySelector('[data-testid="creator-list-form"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
          disabled: !data,
        }}
        secondaryAction={{ label: 'Open the store', href: '/marketplace', icon: Store }}
        steps={[
          'Pick one of your agents and submit it. Listing is free.',
          'An admin reviews it. Until then it shows here as waiting for review.',
          'Once approved, anyone on the platform can find and install it. Installs and runs show up here.',
          'If it is not approved, read the reviewer note, fix the agent and submit again.',
        ]}
        docSlug="08-howto/14-marketplace-and-monetization"
        storageKey="creator"
      />

      {listed && (
        <NextSteps
          title={`${listed.name} is waiting for review. Meanwhile`}
          testId="creator-listed-next"
          onDismiss={() => setListed(null)}
          steps={[
            { id: 'chat', label: 'Try it in chat', hint: 'Check it answers the way a new user expects.', icon: MessageSquare, href: `/agents/${listed.id}/chat` },
            { id: 'evals', label: 'Add tests', hint: 'A test suite keeps it working after you change it.', icon: FlaskConical, href: '/evals' },
            { id: 'knowledge', label: 'Give it knowledge', hint: 'Upload documents it can search.', icon: BookOpen, href: '/knowledge' },
            { id: 'autonomy', label: 'Enrol its actions', hint: 'Let it act alone once it earns trust.', icon: ShieldCheck, href: '/autonomy' },
          ]}
        />
      )}

      {error && !loading && (
        <div role="alert" data-testid="creator-error" className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          <span>Could not load your listings. {plainError(error)}</span>
          <button onClick={() => mutate()} className="inline-flex items-center gap-1.5 text-cyan-400 hover:underline">
            <RefreshCw className="w-3.5 h-3.5" /> Try again
          </button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonStatCard key={i} />
          ))}
        </div>
      ) : (
        data && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="creator-kpis">
              {kpis.map((k) => (
                <div key={k.label} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
                  <k.icon className={`w-5 h-5 ${k.color}`} />
                  <p className={`text-2xl font-bold mt-2 ${k.color}`}>{k.value}</p>
                  <p className="text-xs text-slate-500 mt-1">{k.label}</p>
                </div>
              ))}
            </div>

            <ListAgentForm data={data} onListed={(a) => { setListed(a); mutate(); }} />

            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6" data-testid="creator-listings">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h2 className="text-sm font-semibold text-white">Your listings</h2>
                <Link href="/marketplace" className="text-xs text-cyan-400 hover:underline">Open the store</Link>
              </div>
              {data.listings.length === 0 ? (
                <EmptyState
                  icon={Bot}
                  title="Nothing listed yet"
                  description="Pick one of your agents above and submit it. It shows here while it waits for review."
                />
              ) : (
                <ul className="divide-y divide-slate-700/30">
                  {data.listings.map((l) => (
                    <li key={l.id} className="py-3" data-testid="creator-listing" data-state={l.state} data-name={l.name}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm text-white font-medium break-words min-w-0">{l.name}</span>
                        <span className={`text-[11px] px-2 py-0.5 rounded-full border ${STATE_BADGE[l.state].cls}`}>
                          {STATE_BADGE[l.state].label}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                        <span data-testid="listing-installs">{l.installs} install{l.installs === 1 ? '' : 's'}</span>
                        <span>
                          {l.runs_30d === 0
                            ? 'No runs in the last 30 days'
                            : `${l.runs_30d} run${l.runs_30d === 1 ? '' : 's'} by ${l.users_30d} ${l.users_30d === 1 ? 'person' : 'people'} in the last 30 days`}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Star className="w-3 h-3 text-amber-400" />
                          {l.review_count ? `${l.avg_rating} (${l.review_count})` : 'No reviews'}
                        </span>
                        {switches.monetization && typeof l.price === 'number' && (
                          <span className="inline-flex items-center gap-1">
                            <DollarSign className="w-3 h-3" />
                            {l.price > 0 ? `$${l.price}/mo` : 'Free'}
                          </span>
                        )}
                        {l.state === 'live' && (
                          <Link href={`/marketplace/${l.id}`} className="text-cyan-400 hover:underline">View in the store</Link>
                        )}
                      </div>
                      {l.state === 'rejected' && (
                        <p className="mt-1 flex items-start gap-1.5 text-xs text-red-300">
                          <XCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                          {l.rejection_reason ? `Reviewer note: ${l.rejection_reason}` : 'The reviewer left no note.'} Fix it and submit
                          again from the form above.
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )
      )}

      {switches.monetization && <Revenue />}
    </motion.div>
  );
}
