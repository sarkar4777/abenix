'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertTriangle, BellRing, CheckCircle2, ExternalLink, Loader2, Lock } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useAuth } from '@/contexts/AuthContext';
import { holds, useMyPermissions } from '@/lib/capabilities';
import {
  INBOX_TABS,
  badgeText,
  isInboxTab,
  refreshInboxCounts,
  useInboxCounts,
  type InboxTab,
} from '@/lib/inbox';
import ApprovalsPanel from '@/components/inbox/ApprovalsPanel';
import AlertsPanel from '@/components/inbox/AlertsPanel';
import ReviewQueue from '@/components/autonomy/ReviewQueue';
import HeldInbox from '@/components/moderation/HeldInbox';
import MarketplaceSubmissions from '../review-queue/MarketplaceSubmissions';

const NOT_FOR_YOU: Record<InboxTab, string> = {
  approvals: 'Signing approvals needs the creator or admin role, or the Sign approvals permission.',
  watching: 'Answering watching reviews needs the Review agent actions permission.',
  held: 'Reviewing held content needs the Review held content permission.',
  marketplace: 'Marketplace submissions are for admins, and only while the marketplace is turned on.',
  alerts: 'Alerts are not turned on for your role.',
};

function Inbox() {
  usePageTitle('Needs you');
  const { user } = useAuth();
  const { perms } = useMyPermissions();
  const { counts, loading, error } = useInboxCounts();
  const router = useRouter();
  const params = useSearchParams();
  const [local, setLocal] = useState<Partial<Record<InboxTab, number>>>({});

  const available = useMemo(() => counts?.available ?? [], [counts]);
  const countOf = (t: InboxTab) => local[t] ?? counts?.counts[t] ?? 0;
  const total = available.reduce((s, t) => s + countOf(t), 0);
  const asked = params.get('tab');
  const busiest = available.find((t) => (counts?.counts[t] ?? 0) > 0) ?? available[0];
  const tab: InboxTab | undefined = isInboxTab(asked) ? asked : busiest;
  const allowed = !!tab && available.includes(tab);
  const empty = !!counts && total === 0 && !isInboxTab(asked);

  // a reused panel saw a different number, so the cached count is stale
  const reported = useCallback(
    (t: InboxTab) => (n: number) => {
      setLocal((prev) => (prev[t] === n ? prev : { ...prev, [t]: n }));
    },
    [],
  );
  const onApprovals = useMemo(() => reported('approvals'), [reported]);
  const onWatching = useMemo(() => reported('watching'), [reported]);
  const onHeld = useMemo(() => reported('held'), [reported]);
  const onMarket = useMemo(() => reported('marketplace'), [reported]);
  const onAlerts = useMemo(() => reported('alerts'), [reported]);

  // only when a panel reports in
  useEffect(() => {
    if (!counts) return;
    const stale = (Object.keys(local) as InboxTab[]).some((t) => local[t] !== (counts.counts[t] ?? 0));
    if (stale) refreshInboxCounts();
  }, [local]);

  const me = useMemo(() => ({ id: user?.id ?? '', role: user?.role }), [user?.id, user?.role]);
  const caps = perms?.capabilities;
  const isAdmin = user?.role === 'admin' || !!perms?.is_admin;
  const select = (t: InboxTab) => router.replace(`/inbox?tab=${t}`, { scroll: false });

  const header = (
    <PageHeader
      title="Needs you"
      icon={BellRing}
      purpose="Everything waiting on you in one place: approvals to sign, agent reviews, held content, submissions and alerts. Act here, or open the full page for more detail."
      primaryAction={
        tab && allowed && !empty
          ? { label: `Open full ${INBOX_TABS[tab].short.toLowerCase()} page`, href: INBOX_TABS[tab].href, icon: ExternalLink, testId: 'inbox-open-full' }
          : { label: 'Go to Home', href: '/dashboard', testId: 'inbox-go-home' }
      }
      steps={[
        { title: 'Pick a tab', body: 'Each tab shows how many things are waiting. The busiest one opens first.' },
        { title: 'Act inline', body: 'Approve, answer or release right here. The count updates as you go.' },
        { title: 'Need more?', body: 'Open the full page for history, filters and settings.' },
      ]}
      storageKey="inbox"
    />
  );

  if (loading && !counts) {
    return (
      <div className="mx-auto max-w-5xl space-y-5">
        {header}
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking what is waiting on you
        </div>
      </div>
    );
  }

  if (!counts) {
    return (
      <div className="mx-auto max-w-5xl space-y-5">
        {header}
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert" data-testid="inbox-error">
          <AlertTriangle className="h-4 w-4" /> {error ? 'We could not check what is waiting on you. Check your connection and try again.' : 'Nothing loaded yet.'}
          <button type="button" onClick={() => refreshInboxCounts()} className="ml-auto text-xs underline">Try again</button>
        </div>
      </div>
    );
  }

  if (empty) {
    return (
      <div className="mx-auto max-w-5xl space-y-5">
        {header}
        <section className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-6 sm:p-8" data-testid="inbox-empty">
          <div className="text-center">
            <CheckCircle2 className="mx-auto mb-2 h-10 w-10 text-emerald-400/50" />
            <h2 className="text-lg font-semibold text-white">Nothing needs you right now</h2>
            <p className="mt-1 text-sm text-slate-400">When something is waiting on you it shows up here, and the count next to Needs you in the sidebar goes up.</p>
          </div>
          <ul className="mx-auto mt-5 max-w-xl space-y-2 text-sm">
            {available.map((t) => (
              <li key={t} className="flex flex-col gap-1 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 sm:flex-row sm:items-center sm:gap-3">
                <span className="font-medium text-slate-200 sm:w-48 sm:shrink-0">{INBOX_TABS[t].label}</span>
                <span className="min-w-0 flex-1 text-xs text-slate-400">{INBOX_TABS[t].hint}</span>
                <Link href={INBOX_TABS[t].href} className="text-xs text-cyan-300 hover:underline">Open</Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5" data-testid="inbox">
      {header}

      <div role="tablist" aria-label="What is waiting" className="-mx-1 flex gap-1 overflow-x-auto border-b border-slate-800 px-1">
        {available.map((t) => {
          const n = countOf(t);
          return (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              data-testid={`inbox-tab-${t}`}
              onClick={() => select(t)}
              className={`-mb-px inline-flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === t ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}
            >
              <span className="hidden sm:inline">{INBOX_TABS[t].label}</span>
              <span className="sm:hidden">{INBOX_TABS[t].short}</span>
              <span
                data-testid={`inbox-count-${t}`}
                className={`min-w-[20px] rounded-full px-1.5 py-0.5 text-center text-[10px] ${n > 0 ? 'bg-amber-500/20 text-amber-200' : 'bg-slate-800 text-slate-500'}`}
              >
                {badgeText(n)}
              </span>
            </button>
          );
        })}
      </div>

      {tab && (
        <div role="tabpanel" data-testid={`inbox-panel-${tab}`} className="min-w-0">
          <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
            <p className="min-w-0 flex-1 text-sm text-slate-400">{INBOX_TABS[tab].hint}</p>
            {allowed && (
              <Link href={INBOX_TABS[tab].href} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" data-testid="inbox-panel-full">
                Open full page <ExternalLink className="h-3 w-3" />
              </Link>
            )}
          </div>
          {!allowed ? (
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 text-sm text-slate-300" data-testid="inbox-not-for-you">
              <Lock className="mb-2 h-5 w-5 text-slate-500" />
              <p>{NOT_FOR_YOU[tab]}</p>
              <p className="mt-2 text-xs text-slate-400">
                Ask an admin to grant it under Admin, Permissions, or <Link href="/settings/team" className="text-cyan-300 hover:underline">see who the admins are</Link>.
              </p>
            </div>
          ) : tab === 'approvals' ? (
            <ApprovalsPanel me={me} caps={caps} onCount={onApprovals} />
          ) : tab === 'watching' ? (
            <ReviewQueue canReview={holds(caps, 'actions.review')} onCountChange={onWatching} />
          ) : tab === 'held' ? (
            <HeldInbox isAdmin={isAdmin} onCount={onHeld} />
          ) : tab === 'marketplace' ? (
            <MarketplaceSubmissions onCount={onMarket} />
          ) : (
            <AlertsPanel onCount={onAlerts} />
          )}
        </div>
      )}
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={null}>
      <Inbox />
    </Suspense>
  );
}
