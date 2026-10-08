'use client';

import { useState } from 'react';
import Link from 'next/link';
import { mutate as globalMutate } from 'swr';
import { AlertTriangle, CreditCard, Inbox, Loader2, RefreshCw, Store } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import { PLATFORM_FEATURES_PATH, plainError, usePlatformFeatures, type PlatformFeatures } from '@/hooks/usePlatformFeatures';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import { toastError, toastSuccess } from '@/stores/toastStore';

type Switch = 'marketplace' | 'monetization';

const COPY: Record<Switch, { title: string; on: string; off: string; offWarning: string; icon: typeof Store }> = {
  marketplace: {
    title: 'Marketplace',
    on: 'People can browse the store, list their agents for free and install what others listed. An admin reviews every listing first.',
    off: 'The store, Creator Hub and listing from the builder are hidden for everyone. Agents already installed keep working.',
    offWarning:
      'The store, Creator Hub and marketplace publishing disappear for every user. Pending submissions stay in the review inbox but cannot be approved until you turn it back on.',
    icon: Store,
  },
  monetization: {
    title: 'Monetization',
    on: 'Paid listings, Stripe checkout, creator payouts and revenue, the Billing page and plan limits are on.',
    off: 'Everything is free. No prices, no Stripe, no payouts or revenue, no Billing page and no plan caps or upgrade prompts.',
    offWarning:
      'Paid listings leave the store, Stripe checkout and payouts stop, and the Billing page is hidden. Existing installs keep working.',
    icon: CreditCard,
  },
};

function Toggle({ id, on, busy, onClick }: { id: Switch; on: boolean; busy: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={COPY[id].title}
      data-testid={`switch-${id}`}
      disabled={busy}
      onClick={onClick}
      className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors disabled:opacity-60 ${
        on ? 'bg-cyan-500/80 border-cyan-400/60' : 'bg-slate-700 border-slate-600'
      }`}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${on ? 'translate-x-6' : 'translate-x-1'}`}
      />
    </button>
  );
}

export default function AdminMarketplacePage() {
  usePageTitle('Marketplace & Billing');
  const { user } = useAuth();
  const { features, loaded, error, isLoading, mutate } = usePlatformFeatures();
  const [busy, setBusy] = useState<Switch | null>(null);
  const [confirmOff, setConfirmOff] = useState<Switch | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const save = async (which: Switch, value: boolean) => {
    setBusy(which);
    setSaveError(null);
    const res = await apiFetch<PlatformFeatures>('/api/admin/platform-features', {
      method: 'PUT',
      body: JSON.stringify({ [which]: value }),
      throwOnError: false,
    });
    setBusy(null);
    setConfirmOff(null);
    if (res.error || !res.data) {
      const msg = plainError(res.error, res.errorDetail?.error_code, 'The change was not saved. Try again.');
      setSaveError(msg);
      toastError('Could not save', msg);
      return;
    }
    // every hook reading the switches updates at once
    await globalMutate(PLATFORM_FEATURES_PATH);
    mutate();
    toastSuccess(`${COPY[which].title} turned ${value ? 'on' : 'off'}`);
  };

  const flip = (which: Switch) => {
    if (features?.[which]) setConfirmOff(which);
    else save(which, true);
  };

  if (user && user.role !== 'admin') {
    return (
      <NoAccess
        testId="admin-marketplace-denied"
        title="Marketplace & Billing"
        purpose="Turn the agent marketplace and paid listings on or off for everyone in this workspace. For admins."
        icon={Store}
        need={{ admin: true }}
        role={user.role}
      />
    );
  }

  return (
    <div className="space-y-6 max-w-3xl" data-testid="admin-marketplace">
      <PageHeader
        title="Marketplace & Billing"
        purpose="Turn the agent marketplace and paid listings on or off for everyone in this workspace. For admins."
        icon={Store}
        storageKey="admin-marketplace"
        docSlug="08-howto/14-marketplace-and-monetization"
        primaryAction={{ label: 'Open review inbox', icon: Inbox, href: '/review-queue' }}
        steps={[
          'The marketplace lets people list their agents for free and install what others listed.',
          'Monetization adds prices, Stripe checkout, creator payouts and the Billing page on top.',
          'The two switches are separate. Changes reach everyone within a few seconds, with no redeploy.',
          'Every new listing waits in the review inbox until an admin approves it.',
        ]}
      />

      {saveError && (
        <div
          role="alert"
          data-testid="admin-marketplace-error"
          className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm"
        >
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{saveError}</span>
        </div>
      )}

      {!loaded && !error && (
        <div className="space-y-4" aria-busy="true" data-testid="admin-marketplace-loading">
          {[0, 1].map((i) => (
            <div key={i} className="h-32 rounded-xl bg-slate-800/40 border border-slate-700/50 animate-pulse" />
          ))}
        </div>
      )}

      {!loaded && !isLoading && error && (
        <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          <p>Could not read the current settings. Check your connection and try again.</p>
          <button onClick={() => mutate()} className="mt-2 inline-flex items-center gap-1.5 text-cyan-400 hover:underline">
            <RefreshCw className="w-3.5 h-3.5" /> Try again
          </button>
        </div>
      )}

      {loaded && features && (
        <div className="space-y-4">
          {(['marketplace', 'monetization'] as Switch[]).map((which) => {
            const c = COPY[which];
            const on = !!features[which];
            const fromAdmin = features.source?.[which] === 'admin';
            const deflt = features.defaults?.[which];
            return (
              <section
                key={which}
                data-testid={`feature-${which}`}
                className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4 sm:p-5"
              >
                <div className="flex items-start gap-4">
                  <div className="hidden sm:flex w-10 h-10 rounded-lg bg-cyan-500/10 items-center justify-center shrink-0">
                    <c.icon className="w-5 h-5 text-cyan-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-3">
                      <h2 className="text-base font-semibold text-white">{c.title}</h2>
                      <div className="flex items-center gap-2">
                        {busy === which && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
                        <span
                          className={`text-xs font-medium ${on ? 'text-cyan-300' : 'text-slate-400'}`}
                          data-testid={`state-${which}`}
                        >
                          {on ? 'On' : 'Off'}
                        </span>
                        <Toggle id={which} on={on} busy={busy !== null} onClick={() => flip(which)} />
                      </div>
                    </div>
                    <p className="text-sm text-slate-400 mt-1">{on ? c.on : c.off}</p>
                    <p className="text-[11px] text-slate-500 mt-2">
                      {fromAdmin ? 'Set by an admin here.' : 'Using the deployment default.'} Deployment default:{' '}
                      {deflt ? 'on' : 'off'}.
                    </p>
                    {which === 'monetization' && on && !features.marketplace && (
                      <p className="text-[11px] text-amber-300 mt-2">
                        Paid listings need the marketplace too. Billing and plans still work on their own.
                      </p>
                    )}
                  </div>
                </div>
              </section>
            );
          })}

          <div className="rounded-xl border border-slate-700/50 bg-slate-900/30 p-4 text-sm text-slate-400">
            Submissions to the marketplace wait for an admin in the{' '}
            <Link href="/review-queue" className="text-cyan-400 hover:underline">
              review inbox
            </Link>
            .
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirmOff !== null}
        onClose={() => setConfirmOff(null)}
        onConfirm={() => {
          if (confirmOff) save(confirmOff, false);
        }}
        title={confirmOff ? `Turn off ${COPY[confirmOff].title.toLowerCase()}?` : ''}
        description={confirmOff ? COPY[confirmOff].offWarning : ''}
        confirmLabel="Turn off"
        variant="warning"
        loading={busy !== null}
        confirmTestId="confirm-turn-off"
      />
    </div>
  );
}
