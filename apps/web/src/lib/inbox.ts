'use client';

import { useEffect, useRef } from 'react';
import { mutate as swrMutate } from 'swr';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { holds } from '@/lib/capabilities';
import { useNotificationStore } from '@/stores/notificationStore';

export type InboxTab = 'approvals' | 'watching' | 'held' | 'marketplace' | 'alerts';

export interface InboxCounts {
  total: number;
  counts: Partial<Record<InboxTab, number>>;
  available: InboxTab[];
  unavailable?: InboxTab[];
  cached?: boolean;
}

export const INBOX_COUNTS_KEY = '/api/me/inbox-counts';
export const INBOX_POLL_MS = 60_000;

export const INBOX_TABS: Record<InboxTab, { label: string; short: string; href: string; hint: string; empty: string }> = {
  approvals: {
    label: 'Approvals',
    short: 'Approvals',
    href: '/approvals',
    hint: 'Agent actions, promotions, rule changes and agent gates you can sign.',
    empty: 'No approvals waiting on you.',
  },
  watching: {
    label: 'Watching reviews',
    short: 'Watching',
    href: '/approvals?tab=reviews',
    hint: 'Agents in Watching ask whether you would have done the same.',
    empty: 'No watching reviews to answer.',
  },
  held: {
    label: 'Held content',
    short: 'Held',
    href: '/review-queue?tab=held',
    hint: 'Messages a moderation policy stopped until someone checks them.',
    empty: 'Nothing is held for review.',
  },
  marketplace: {
    label: 'Marketplace submissions',
    short: 'Marketplace',
    href: '/review-queue?tab=marketplace',
    hint: 'Agents published to the marketplace, waiting for an admin.',
    empty: 'No submissions waiting.',
  },
  alerts: {
    label: 'Alerts',
    short: 'Alerts',
    href: '/alerts',
    hint: 'Failure causes that are new today or happening more than yesterday.',
    empty: 'No new or rising failures.',
  },
};

export function isInboxTab(v: string | null | undefined): v is InboxTab {
  return !!v && v in INBOX_TABS;
}

export function badgeText(n: number): string {
  return n > 99 ? '99+' : String(n);
}

// skips the server cache, used after a socket event or an inline decision
export async function refreshInboxCounts(): Promise<void> {
  const fresh = await apiFetch<InboxCounts>(`${INBOX_COUNTS_KEY}?fresh=1`, { silent: true });
  if (fresh.data) await swrMutate(INBOX_COUNTS_KEY, fresh, { revalidate: false });
}

const LIVE_TYPES = /approval|review|moderation|autonomy|promotion|marketplace|agent_(submitted|approved|rejected)/i;

// SWR polls only while the tab is visible, the socket nudges it sooner
export function useInboxCounts(enabled = true) {
  const { data, isLoading, error } = useApi<InboxCounts>(enabled ? INBOX_COUNTS_KEY : null, {
    refreshInterval: INBOX_POLL_MS,
    refreshWhenHidden: false,
    dedupingInterval: 10_000,
  });
  const tick = useNotificationStore((s) => s.moderationQueueTick);
  const latest = useNotificationStore((s) => s.notifications[0]);
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (enabled && tick) refreshInboxCounts();
  }, [tick, enabled]);

  useEffect(() => {
    if (!enabled || !latest || latest.id === seen.current) return;
    const first = seen.current === null;
    seen.current = latest.id;
    if (!first && LIVE_TYPES.test(latest.type || '')) refreshInboxCounts();
  }, [latest, enabled]);

  return { counts: data, loading: isLoading, error };
}

// ---- sidebar mode

export type SidebarMode = 'essentials' | 'all';
export const SIDEBAR_MODE_KEY = 'abenix.sidebar.mode';

export function readCachedMode(): SidebarMode | null {
  try {
    const v = window.localStorage.getItem(SIDEBAR_MODE_KEY);
    return v === 'all' || v === 'essentials' ? v : null;
  } catch {
    return null;
  }
}

export function cacheMode(mode: SidebarMode): void {
  try {
    window.localStorage.setItem(SIDEBAR_MODE_KEY, mode);
  } catch {
    /* private window */
  }
}

export async function saveSidebarMode(mode: SidebarMode): Promise<string | null> {
  cacheMode(mode);
  const r = await apiFetch<{ sidebar_mode: SidebarMode }>('/api/me/ui-prefs', {
    method: 'PUT',
    body: JSON.stringify({ sidebar_mode: mode }),
    silent: true,
    throwOnError: false,
  });
  return r.error ?? null;
}

// ---- approvals the caller can sign, the same rules the counts endpoint uses

export interface SignableRow {
  id: string;
  requested_by?: string | null;
  policy?: { exclude_requester?: boolean; capability?: string } | null;
  gate_kind?: string | null;
  signoffs?: Array<{ user_id: string }>;
  payload?: Record<string, unknown> | null;
}

export function canSign(row: SignableRow, me: { id: string; role?: string }, caps: readonly string[] | undefined): boolean {
  const signer = me.role === 'admin' || me.role === 'creator' || holds(caps, 'approvals.sign');
  if (row.id.startsWith('hitl:')) return signer;
  if ((row.signoffs || []).some((s) => String(s.user_id) === me.id)) return false;
  if (row.gate_kind === 'decision_publish' && !holds(caps, 'decisions.review')) return false;
  const p = row.payload || {};
  if (row.gate_kind === 'autonomy.promote' && String(p.agent_creator_id ?? '') === me.id && !p.self_approval) return false;
  if (row.policy) {
    if (!holds(caps, row.policy.capability || 'approvals.sign')) return false;
    return !(row.policy.exclude_requester && String(row.requested_by ?? '') === me.id);
  }
  return signer;
}
