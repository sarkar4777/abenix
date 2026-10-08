'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Inbox, Loader2, ShieldCheck, Store } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/contexts/AuthContext';
import { holds, useMyPermissions } from '@/lib/capabilities';
import HeldInbox from '@/components/moderation/HeldInbox';
import MarketplaceSubmissions from './MarketplaceSubmissions';
import PageHeader from '@/components/layout/PageHeader';

type Tab = 'held' | 'marketplace';

function ReviewInbox() {
  usePageTitle('Review inbox');
  const { user } = useAuth();
  const { perms, loading } = useMyPermissions();
  const router = useRouter();
  const params = useSearchParams();
  const isAdmin = user?.role === 'admin' || !!perms?.is_admin;
  const canReview = holds(perms?.capabilities, 'moderation.review');
  const canMarketplace = isAdmin;
  const asked = params.get('tab') as Tab | null;
  const tab: Tab = asked === 'marketplace' && canMarketplace ? 'marketplace' : canReview ? 'held' : 'marketplace';
  const [heldCount, setHeldCount] = useState<number | null>(null);
  const [marketSeen, setMarketSeen] = useState<number | null>(null);
  // the same request the marketplace tab makes, so its badge shows before it is opened
  const { data: pendingAgents } = useApi<Array<{ status: string }>>(canMarketplace ? '/api/agents?status=pending_review&limit=100' : null);
  const marketCount = marketSeen ?? (pendingAgents ? pendingAgents.filter((a) => a.status === 'pending_review').length : null);
  const onHeldCount = useCallback((n: number) => setHeldCount(n), []);
  const onMarketCount = useCallback((n: number) => setMarketSeen(n), []);

  // only once permissions are in, before that every tab looks unavailable
  useEffect(() => {
    if (!perms) return;
    if (asked && asked !== tab) router.replace(`/review-queue?tab=${tab}`, { scroll: false });
  }, [perms, asked, tab, router]);

  if (loading && !perms) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 p-6">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading your review inbox…
      </div>
    );
  }

  if (!canReview && !canMarketplace) {
    return (
      <div className="max-w-xl mx-auto py-16 text-center" data-testid="review-no-access">
        <ShieldCheck className="w-12 h-12 text-slate-600 mx-auto mb-3" />
        <h1 className="text-lg font-semibold text-white mb-1">Nothing here for you to review yet</h1>
        <p className="text-sm text-slate-400">
          This inbox is for people who review content held by moderation policies, and for admins approving
          marketplace submissions. To review held content you need the Review held content permission.
          An admin can add you to a permission set under Admin, Permissions.
        </p>
        <Link href="/settings/team" className="inline-block mt-4 text-sm text-cyan-300 hover:underline">See who the admins are</Link>
      </div>
    );
  }

  const tabs: Array<{ id: Tab; label: string; short: string; icon: typeof Inbox; count: number | null; show: boolean }> = [
    { id: 'held', label: 'Held content', short: 'Held', icon: Inbox, count: heldCount, show: canReview },
    { id: 'marketplace', label: 'Marketplace submissions', short: 'Marketplace', icon: Store, count: marketCount, show: canMarketplace },
  ];

  return (
    <div className="space-y-5" data-testid="review-inbox">
      <PageHeader
        title="Review inbox"
        purpose="Everything waiting on a person: content a moderation policy held, and agents asking to join the marketplace. For reviewers and admins."
        icon={Inbox}
        storageKey="review-queue"
        docSlug="02-runtime/13-moderation-gate"
        primaryAction={isAdmin
          ? { label: 'Moderation policies', href: '/moderation', icon: ShieldCheck }
          : { label: 'Agent approvals', href: '/approvals', icon: ShieldCheck }}
        steps={[
          'Held content is a message or answer a moderation policy stopped until someone checks it.',
          'Open an item, read why it was held, then release it, redact and release it, or reject it.',
          'Admins also approve or reject agents submitted to the marketplace on the second tab.',
        ]}
      />

      <div role="tablist" aria-label="What to review" className="flex gap-1 border-b border-slate-800 overflow-x-auto">
        {tabs.filter((t) => t.show).map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            data-testid={`review-tab-${t.id}`}
            onClick={() => router.replace(`/review-queue?tab=${t.id}`, { scroll: false })}
            className={`inline-flex items-center gap-2 px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${tab === t.id ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-slate-400 hover:text-white'}`}
          >
            <t.icon className="w-4 h-4" /> <span className="hidden sm:inline">{t.label}</span><span className="sm:hidden">{t.short}</span>
            {t.count !== null && t.count > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-200">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === 'held' && canReview && <HeldInbox isAdmin={isAdmin} onCount={onHeldCount} />}
        {tab === 'marketplace' && canMarketplace && <MarketplaceSubmissions onCount={onMarketCount} />}
      </div>
    </div>
  );
}

export default function ReviewQueuePage() {
  return (
    <Suspense fallback={null}>
      <ReviewInbox />
    </Suspense>
  );
}
