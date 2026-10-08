'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft, Check, CheckCircle2, ChevronLeft, ChevronRight, Clock, Eraser, Hand, History,
  Inbox, Keyboard, Loader2, RotateCcw, ShieldAlert, UserMinus, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useNotificationStore } from '@/stores/notificationStore';
import { useIsMobile } from '@/hooks/useMediaQuery';
import ConfirmModal from '@/components/ui/ConfirmModal';
import EmptyState from '@/components/ui/EmptyState';
import MaskedText from './MaskedText';
import {
  PRIORITY_STYLE, SHORTCUTS, ago, categoryLabel, maskAll, maskRange, segments, slaText, type Span,
} from '@/lib/moderation-review';

interface Person { id: string; name: string; email: string }

export interface Review {
  id: string;
  status: string;
  status_label: string;
  source: string;
  source_label: string;
  priority: number;
  priority_label: string;
  categories: string[];
  category_scores: Record<string, number>;
  preview: string;
  content_length: number;
  created_at: string | null;
  expires_at: string | null;
  timeout_action: string;
  assigned_to: Person | null;
  assigned_to_me: boolean;
  decided_by: Person | null;
  decided_at: string | null;
  decision_reason: string | null;
  delivered: boolean;
  author: Person | null;
  agent: { id: string; name: string } | null;
  execution_id: string | null;
  conversation_id: string | null;
  content_available: boolean;
  redaction_mask: string;
}

interface ReviewDetail extends Review {
  content: string | null;
  masked_content: string | null;
  spans: Span[];
  released_content: string | null;
  history: Array<{ at: string; by: string | null; by_name: string | null; action: string; note: string }>;
}

interface Counts { pending: number; mine: number; unassigned: number; due_soon: number; high: number }

const PAGE = 25;
const HISTORY_LABEL: Record<string, string> = {
  held: 'Held by the policy',
  claimed: 'Claimed',
  unassigned: 'Unassigned',
  released: 'Released',
  redacted: 'Redacted and released',
  rejected: 'Rejected',
  auto_released: 'Released when the time ran out',
  auto_rejected: 'Rejected when the time ran out',
};

type Pending = { kind: 'release' | 'reject' | 'redact'; ids: string[] } | null;

export default function HeldInbox({ isAdmin, onCount }: { isAdmin: boolean; onCount?: (n: number) => void }) {
  const isMobile = useIsMobile();
  const tick = useNotificationStore((s) => s.moderationQueueTick);
  const [status, setStatus] = useState<'pending' | 'decided' | 'all'>('pending');
  const [assigned, setAssigned] = useState<'any' | 'me' | 'unassigned'>('any');
  const [priority, setPriority] = useState<string>('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Review[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState('');
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [showKeys, setShowKeys] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    const qs = new URLSearchParams({ status, assigned, page: String(page), limit: String(PAGE) });
    if (priority) qs.set('priority', priority);
    const r = await apiFetch<Review[]>(`/api/moderation/reviews?${qs}`, { silent: true });
    setLoading(false);
    if (r.error || !r.data) {
      setLoadError(r.errorDetail?.message || 'The inbox could not be loaded. Check your connection and try again.');
      return;
    }
    setLoadError(null);
    setItems(r.data);
    const meta = (r.meta || {}) as { total?: number; counts?: Counts };
    setTotal(Number(meta.total || 0));
    if (meta.counts) {
      setCounts(meta.counts);
      onCount?.(meta.counts.pending);
    }
  }, [status, assigned, priority, page, onCount]);

  useEffect(() => { load(); }, [load]);

  // the socket says the queue changed, one refresh however many changes arrive together
  useEffect(() => {
    if (!tick) return;
    const t = setTimeout(load, 800);
    return () => clearTimeout(t);
  }, [tick, load]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const openDetail = useCallback(async (id: string) => {
    setActiveId(id);
    setEditing(false);
    setActionError(null);
    setDetailLoading(true);
    const r = await apiFetch<ReviewDetail>(`/api/moderation/reviews/${id}`, { silent: true });
    setDetailLoading(false);
    if (r.data) setDetail(r.data);
    else {
      setDetail(null);
      setActionError(r.errorDetail?.message || 'This item could not be opened.');
    }
  }, []);

  const act = useCallback(async (id: string, action: string, body: Record<string, unknown> = {}) => {
    setBusy(true);
    setActionError(null);
    const r = await apiFetch<ReviewDetail>(`/api/moderation/reviews/${id}/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
      throwOnError: false,
      silent: true,
    });
    setBusy(false);
    if (r.data) {
      if (activeId === id) setDetail(r.data);
      setEditing(false);
      await load();
      return true;
    }
    setActionError(r.errorDetail?.message || 'That did not work. Try again.');
    return false;
  }, [activeId, load]);

  const bulk = useCallback(async (action: string, ids: string[], why?: string) => {
    setBusy(true);
    setActionError(null);
    const r = await apiFetch<{ done: string[]; failed: Array<{ id: string; message: string }> }>('/api/moderation/reviews/bulk', {
      method: 'POST',
      body: JSON.stringify({ action, ids, reason: why }),
      throwOnError: false,
      silent: true,
    });
    setBusy(false);
    if (!r.data) {
      setActionError(r.errorDetail?.message || 'That did not work. Try again.');
      return false;
    }
    const { done, failed } = r.data;
    setNotice(
      `${done.length} ${done.length === 1 ? 'item' : 'items'} done.` +
        (failed.length ? ` ${failed.length} skipped: ${failed[0].message}` : ''),
    );
    setSelected(new Set());
    await load();
    if (activeId && ids.includes(activeId)) openDetail(activeId);
    return true;
  }, [activeId, load, openDetail]);

  const confirmPending = async () => {
    if (!pending) return;
    const { kind, ids } = pending;
    let ok = false;
    if (kind === 'redact') ok = await act(ids[0], 'redact', { content: draft });
    else if (ids.length === 1) ok = await act(ids[0], kind, kind === 'reject' ? { reason } : {});
    else ok = await bulk(kind, ids, kind === 'reject' ? reason : undefined);
    if (ok) {
      setPending(null);
      setReason('');
    }
  };

  const selectedIds = useMemo(() => Array.from(selected), [selected]);
  const targetIds = useCallback(() => (selectedIds.length ? selectedIds : activeId ? [activeId] : []), [selectedIds, activeId]);
  const activeIndex = items.findIndex((i) => i.id === activeId);

  // why the reviewer cannot act on the open item, or null
  const blockedReason = useMemo(() => {
    if (!detail) return null;
    if (detail.status !== 'pending') return `Already decided: ${detail.status_label.toLowerCase()}.`;
    if (detail.assigned_to && !detail.assigned_to_me && !isAdmin) {
      return `${detail.assigned_to.name} claimed this. Ask them, or an admin, to unassign it.`;
    }
    return null;
  }, [detail, isAdmin]);

  const startRedact = useCallback(() => {
    if (!detail || blockedReason) return;
    const base = detail.content ?? detail.masked_content ?? '';
    setDraft(detail.content ? maskAll(detail.content, detail.spans, detail.redaction_mask) : base);
    setEditing(true);
    setTimeout(() => editorRef.current?.focus(), 0);
  }, [detail, blockedReason]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      if (pending || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '?') { setShowKeys((v) => !v); return; }
      if (e.key === 'j' || e.key === 'k') {
        if (!items.length) return;
        const next = activeIndex < 0 ? 0 : Math.min(items.length - 1, Math.max(0, activeIndex + (e.key === 'j' ? 1 : -1)));
        openDetail(items[next].id);
        return;
      }
      if (!activeId) return;
      if (e.key === 'x') {
        setSelected((s) => { const n = new Set(s); if (n.has(activeId)) n.delete(activeId); else n.add(activeId); return n; });
      } else if (e.key === 'c') act(activeId, 'claim');
      else if (e.key === 'u') act(activeId, 'unassign');
      else if (e.key === 'r' && !blockedReason) setPending({ kind: 'release', ids: targetIds() });
      else if (e.key === 'd' && !blockedReason) setPending({ kind: 'reject', ids: targetIds() });
      else if (e.key === 'e') startRedact();
      else if (e.key === 'Escape') { setActiveId(null); setDetail(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [items, activeIndex, activeId, pending, blockedReason, act, openDetail, startRedact, targetIds]);

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const allOnPage = items.length > 0 && items.every((i) => selected.has(i.id));

  const showList = !isMobile || !activeId;
  const showDetail = !isMobile || !!activeId;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="space-y-4" data-testid="held-inbox">
      {counts && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="held-counts">
          <Chip label="Waiting" value={counts.pending} />
          <Chip label="Claimed by me" value={counts.mine} />
          <Chip label="Unclaimed" value={counts.unassigned} />
          <Chip label="Time runs out within 10 min" value={counts.due_soon} warn={counts.due_soon > 0} />
          <Chip label="High priority" value={counts.high} warn={counts.high > 0} />
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <Select label="Show" value={status} onChange={(v) => { setStatus(v as typeof status); setPage(1); }} testId="held-filter-status"
          options={[['pending', 'Waiting for review'], ['decided', 'Decided'], ['all', 'Everything']]} />
        <Select label="Claimed" value={assigned} onChange={(v) => { setAssigned(v as typeof assigned); setPage(1); }} testId="held-filter-assigned"
          options={[['any', 'By anyone or no one'], ['me', 'By me'], ['unassigned', 'Not claimed']]} />
        <Select label="Priority" value={priority} onChange={(v) => { setPriority(v); setPage(1); }} testId="held-filter-priority"
          options={[['', 'Any'], ['3', 'High'], ['2', 'Medium'], ['1', 'Low']]} />
        <button type="button" onClick={() => setShowKeys((v) => !v)} className="ml-auto hidden sm:inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-2 py-1.5 rounded-md border border-slate-700/60" aria-expanded={showKeys}>
          <Keyboard className="w-3.5 h-3.5" /> Shortcuts
        </button>
      </div>

      {showKeys && (
        <div className="rounded-lg border border-slate-700/60 bg-slate-900/60 p-3 grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs text-slate-300" data-testid="held-shortcuts">
          {SHORTCUTS.map(([k, v]) => (
            <div key={k} className="flex gap-2"><kbd className="min-w-[44px] text-center rounded bg-slate-800 border border-slate-600 px-1.5 font-mono text-[11px]">{k}</kbd><span>{v}</span></div>
          ))}
        </div>
      )}

      {notice && (
        <div role="status" className="flex items-start gap-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 text-sm text-emerald-200">
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /><span className="flex-1">{notice}</span>
          <button onClick={() => setNotice(null)} aria-label="Dismiss" className="text-emerald-300/70 hover:text-white"><X className="w-4 h-4" /></button>
        </div>
      )}

      {selectedIds.length > 0 && (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-cyan-500/30 bg-slate-900/95 px-3 py-2 text-sm" data-testid="held-bulk-bar">
          <span className="text-slate-200">{selectedIds.length} selected</span>
          <button disabled={busy} onClick={() => bulk('claim', selectedIds)} className="px-2.5 py-1 rounded-md text-xs border border-slate-600 text-slate-200 hover:bg-slate-800 disabled:opacity-50">Claim</button>
          <button disabled={busy} onClick={() => setPending({ kind: 'release', ids: selectedIds })} className="px-2.5 py-1 rounded-md text-xs border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50" data-testid="held-bulk-release">Release</button>
          <button disabled={busy} onClick={() => setPending({ kind: 'reject', ids: selectedIds })} className="px-2.5 py-1 rounded-md text-xs border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 disabled:opacity-50" data-testid="held-bulk-reject">Reject</button>
          <button onClick={() => setSelected(new Set())} className="ml-auto text-xs text-slate-400 hover:text-white">Clear selection</button>
        </div>
      )}

      {loadError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-rose-500/10 border border-rose-500/30 px-3 py-2 text-sm text-rose-200" data-testid="held-error">
          <span className="flex-1 min-w-0">{loadError}</span>
          <button onClick={() => { setLoading(true); load(); }} className="text-xs underline">Try again</button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        {showList && (
          <section aria-label="Held items" className="min-w-0">
            {loading ? (
              <div className="space-y-2" aria-busy="true">
                {[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-lg bg-slate-800/40 animate-pulse" />)}
              </div>
            ) : items.length === 0 ? (
              <EmptyState
                icon={Inbox}
                title={status === 'pending' ? 'Nothing is waiting for review' : 'No decided items match these filters'}
                description={status === 'pending'
                  ? 'Content lands here when a moderation policy set to Hold for review stops a message or a reply. You get a notification when it does.'
                  : 'Change the filters above to see more.'}
                actionLabel={isAdmin && status === 'pending' ? 'Set up a hold policy' : undefined}
                actionHref={isAdmin && status === 'pending' ? '/moderation' : undefined}
              />
            ) : (
              <>
                <label className="flex items-center gap-2 px-1 pb-2 text-xs text-slate-400">
                  <input type="checkbox" checked={allOnPage} onChange={() => setSelected(allOnPage ? new Set() : new Set(items.map((i) => i.id)))} aria-label="Select every item on this page" />
                  Select all on this page
                </label>
                <ul className="space-y-2" data-testid="held-list">
                  {items.map((r) => {
                    const sla = r.status === 'pending' ? slaText(r.expires_at, r.timeout_action, now) : null;
                    return (
                      <li key={r.id}>
                        <div
                          data-testid="held-row"
                          data-review-id={r.id}
                          className={`flex gap-2 rounded-lg border p-3 transition-colors ${activeId === r.id ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-700/50 bg-slate-800/30 hover:border-slate-600'}`}
                        >
                          <input type="checkbox" className="mt-1" checked={selected.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Select item from ${r.author?.name || 'someone'}`} />
                          <button type="button" onClick={() => openDetail(r.id)} className="flex-1 min-w-0 text-left">
                            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                              <span className={`px-1.5 py-0.5 rounded ring-1 ${PRIORITY_STYLE[r.priority] || PRIORITY_STYLE[1]}`}>{r.priority_label}</span>
                              <span className="text-slate-300">{r.source_label}</span>
                              <span className="text-slate-500">·</span>
                              <span className="text-slate-400 truncate">{r.author?.name || 'Unknown person'}</span>
                              <span className="text-slate-500 ml-auto">{ago(r.created_at, now)}</span>
                            </div>
                            <p className="mt-1 text-sm text-slate-200 line-clamp-2 break-words">{r.preview ? <MaskedText text={r.preview} mask={r.redaction_mask} /> : '(empty)'}</p>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                              {r.categories.slice(0, 3).map((c) => <span key={c} className="px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-300">{categoryLabel(c)}</span>)}
                              {r.status !== 'pending' && <span className="text-slate-400">{r.status_label}</span>}
                              {sla?.text && <span className={sla.urgent ? 'text-rose-300' : 'text-slate-400'}><Clock className="inline w-3 h-3 mr-0.5" />{sla.text}</span>}
                              {r.assigned_to && <span className="text-cyan-300">{r.assigned_to_me ? 'Claimed by you' : `Claimed by ${r.assigned_to.name}`}</span>}
                            </div>
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {total > PAGE && (
                  <div className="flex items-center justify-between pt-3 text-xs text-slate-400">
                    <span>{(page - 1) * PAGE + 1} to {Math.min(total, page * PAGE)} of {total}</span>
                    <div className="flex gap-1">
                      <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="p-1.5 rounded border border-slate-700 disabled:opacity-40" aria-label="Previous page"><ChevronLeft className="w-4 h-4" /></button>
                      <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="p-1.5 rounded border border-slate-700 disabled:opacity-40" aria-label="Next page"><ChevronRight className="w-4 h-4" /></button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {showDetail && (
          <section aria-label="Item details" className="min-w-0 rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="held-detail">
            {isMobile && (
              <button onClick={() => { setActiveId(null); setDetail(null); }} className="mb-3 inline-flex items-center gap-1 text-xs text-slate-300">
                <ArrowLeft className="w-3.5 h-3.5" /> Back to the list
              </button>
            )}
            {!activeId ? (
              <p className="text-sm text-slate-400">Pick an item to see the full text, what matched and the actions. Press j to open the first one.</p>
            ) : detailLoading && !detail ? (
              <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Opening…</div>
            ) : !detail ? (
              <p role="alert" className="text-sm text-rose-300">{actionError || 'This item could not be opened.'}</p>
            ) : (
              <Detail
                d={detail}
                now={now}
                busy={busy}
                blockedReason={blockedReason}
                isAdmin={isAdmin}
                actionError={actionError}
                editing={editing}
                draft={draft}
                editorRef={editorRef}
                onDraft={setDraft}
                onClaim={() => act(detail.id, 'claim')}
                onUnassign={() => act(detail.id, 'unassign')}
                onRelease={() => setPending({ kind: 'release', ids: [detail.id] })}
                onReject={() => setPending({ kind: 'reject', ids: [detail.id] })}
                onStartRedact={startRedact}
                onCancelRedact={() => setEditing(false)}
                onSubmitRedact={() => setPending({ kind: 'redact', ids: [detail.id] })}
              />
            )}
          </section>
        )}
      </div>

      <ConfirmModal
        open={pending?.kind === 'release'}
        onClose={() => setPending(null)}
        onConfirm={confirmPending}
        loading={busy}
        variant="warning"
        icon={CheckCircle2}
        title={pending && pending.ids.length > 1 ? `Release ${pending.ids.length} items?` : 'Release it as written?'}
        description="A released message goes on to the agent, a released reply goes to the person. This cannot be undone."
        confirmLabel="Release"
        confirmTestId="held-confirm-release"
      />
      <ConfirmModal
        open={pending?.kind === 'redact'}
        onClose={() => setPending(null)}
        onConfirm={confirmPending}
        loading={busy}
        variant="warning"
        icon={Eraser}
        title="Release the redacted text?"
        description="Only your edited text goes out. The person sees it, and the original stays with this review until its retention period ends."
        confirmLabel="Release redacted"
        confirmTestId="held-confirm-redact"
      />
      <ConfirmModal
        open={pending?.kind === 'reject'}
        onClose={() => { setPending(null); setReason(''); }}
        onConfirm={confirmPending}
        loading={busy}
        icon={ShieldAlert}
        title={pending && pending.ids.length > 1 ? `Reject ${pending.ids.length} items?` : 'Reject it?'}
        description="It will not be sent. The person who wrote it sees your reason, so keep it plain and kind."
        confirmLabel="Reject"
        confirmDisabled={!reason.trim()}
        confirmTestId="held-confirm-reject"
      >
        <label htmlFor="held-reject-reason" className="block text-xs text-slate-400 mb-1">Reason (required)</label>
        <textarea
          id="held-reject-reason"
          data-testid="held-reject-reason"
          value={reason}
          maxLength={1000}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="For example: it shares a customer's account number"
          className="w-full rounded-lg bg-slate-900/60 border border-slate-700 px-3 py-2 text-sm text-white placeholder-slate-500"
        />
        {!reason.trim() && <p className="mt-1 text-[11px] text-slate-500">Write a reason to enable Reject.</p>}
        {actionError && <p role="alert" className="mt-1 text-xs text-rose-300">{actionError}</p>}
      </ConfirmModal>
    </div>
  );
}

function Chip({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ring-1 ${warn ? 'bg-amber-500/10 ring-amber-500/30 text-amber-200' : 'bg-slate-800/60 ring-slate-700 text-slate-300'}`}>
      <b className="font-semibold">{value}</b> {label}
    </span>
  );
}

function Select({ label, value, onChange, options, testId }: { label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]>; testId: string }) {
  return (
    <label className="text-xs text-slate-400 flex flex-col gap-1">
      {label}
      <select data-testid={testId} value={value} onChange={(e) => onChange(e.target.value)} className="bg-slate-900/60 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

interface DetailProps {
  d: ReviewDetail;
  now: number;
  busy: boolean;
  blockedReason: string | null;
  isAdmin: boolean;
  actionError: string | null;
  editing: boolean;
  draft: string;
  editorRef: React.RefObject<HTMLTextAreaElement>;
  onDraft: (v: string) => void;
  onClaim: () => void;
  onUnassign: () => void;
  onRelease: () => void;
  onReject: () => void;
  onStartRedact: () => void;
  onCancelRedact: () => void;
  onSubmitRedact: () => void;
}

function Detail(p: DetailProps) {
  const { d } = p;
  const sla = d.status === 'pending' ? slaText(d.expires_at, d.timeout_action, p.now) : null;
  const text = d.content ?? d.masked_content ?? '';
  const parts = d.content ? segments(d.content, d.spans) : [{ text }];
  const pendingItem = d.status === 'pending';
  const canUnassign = pendingItem && !!d.assigned_to && (d.assigned_to_me || p.isAdmin);
  const releaseBlocked = p.blockedReason || (!d.content ? 'The full text is no longer stored, so it can only be redacted or rejected.' : null);

  const maskSelection = () => {
    const el = p.editorRef.current;
    if (!el) return;
    p.onDraft(maskRange(p.draft, el.selectionStart, el.selectionEnd, d.redaction_mask));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-2 py-0.5 rounded text-xs ring-1 ${PRIORITY_STYLE[d.priority] || PRIORITY_STYLE[1]}`}>{d.priority_label} priority</span>
        <span className="text-sm text-white font-medium">{d.source_label}</span>
        <span className="text-xs text-slate-400" data-testid="held-detail-status">{d.status_label}</span>
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <Meta label="From" value={d.author ? d.author.name : 'Unknown person'} />
        <Meta label="Agent" value={d.agent?.name || 'Not recorded'} />
        <Meta label="Held" value={ago(d.created_at, p.now)} />
        <Meta label={pendingItem ? 'Time limit' : 'Decided'} value={pendingItem ? (sla?.text || '') : `${ago(d.decided_at, p.now)}${d.decided_by ? ` by ${d.decided_by.name}` : ''}`} urgent={sla?.urgent} />
        <Meta label="Claimed by" value={d.assigned_to ? (d.assigned_to_me ? 'You' : d.assigned_to.name) : 'No one yet'} />
        {d.execution_id && (
          <div className="rounded-md border border-slate-700/40 bg-slate-900/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Run</dt>
            <dd><Link href={`/executions/${d.execution_id}`} className="text-cyan-300 hover:underline">Open the run</Link></dd>
          </div>
        )}
      </dl>

      <div>
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-1.5">What matched</h3>
        <div className="flex flex-wrap gap-1.5">
          {d.categories.map((c) => (
            <span key={c} className="text-[11px] px-2 py-0.5 rounded bg-rose-500/10 text-rose-200 ring-1 ring-rose-500/30">
              {categoryLabel(c)}{d.category_scores[c] !== undefined ? ` · ${Math.round(d.category_scores[c] * 100)}% sure` : ''}
            </span>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-1.5">
          {d.content ? 'Full text, matched parts highlighted' : 'Masked text'}
        </h3>
        {!d.content && (
          <p className="text-[11px] text-slate-400 mb-1">The full text is gone after its retention period or because the decision is final. The record keeps the masked text.</p>
        )}
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-slate-700/50 bg-slate-950/50 p-3 text-sm text-slate-200" data-testid="held-detail-content">
          {parts.map((s, i) => ('category' in s && s.category
            ? <mark key={i} title={s.category.split(',').map(categoryLabel).join(', ')} className="rounded bg-rose-500/30 text-rose-50 px-0.5">{s.text}</mark>
            : <span key={i}><MaskedText text={s.text} mask={d.redaction_mask} /></span>))}
        </pre>
        {d.released_content && d.status === 'redacted' && (
          <div className="mt-2">
            <h4 className="text-[11px] text-slate-500 mb-1">What was released</h4>
            <pre className="whitespace-pre-wrap break-words rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs text-emerald-100"><MaskedText text={d.released_content} mask={d.redaction_mask} /></pre>
          </div>
        )}
        {d.decision_reason && (
          <p className="mt-2 text-xs text-slate-300"><span className="text-slate-500">Reason:</span> {d.decision_reason}</p>
        )}
      </div>

      {p.editing && (
        <div className="rounded-lg border border-cyan-500/30 bg-slate-900/60 p-3 space-y-2" data-testid="held-redact-editor">
          <label htmlFor="held-redact-text" className="block text-xs text-slate-300">
            Edit what goes out. Matched parts start masked. Select more text and press Mask selection to hide it too.
          </label>
          <textarea
            id="held-redact-text"
            ref={p.editorRef}
            data-testid="held-redact-text"
            value={p.draft}
            onChange={(e) => p.onDraft(e.target.value)}
            rows={6}
            className="w-full rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-2 text-sm text-white font-mono"
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={maskSelection} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs border border-slate-600 text-slate-200 hover:bg-slate-800" data-testid="held-mask-selection">
              <Eraser className="w-3.5 h-3.5" /> Mask selection
            </button>
            {d.content && (
              <button type="button" onClick={() => p.onDraft(maskAll(d.content || '', d.spans, d.redaction_mask))} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs border border-slate-600 text-slate-200 hover:bg-slate-800">
                <RotateCcw className="w-3.5 h-3.5" /> Start over
              </button>
            )}
            <span className="flex-1" />
            <button type="button" onClick={p.onCancelRedact} className="px-2.5 py-1.5 rounded-md text-xs text-slate-300 hover:text-white">Cancel</button>
            <button type="button" disabled={!p.draft.trim() || p.busy} onClick={p.onSubmitRedact} className="px-3 py-1.5 rounded-md text-xs bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50" data-testid="held-redact-submit">
              Release redacted text
            </button>
          </div>
          {!p.draft.trim() && <p className="text-[11px] text-slate-500">The text is empty. Keep what can go out, or reject it instead.</p>}
        </div>
      )}

      {pendingItem && !p.editing && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {!d.assigned_to_me && (
              <button type="button" disabled={p.busy || (!!d.assigned_to && !p.isAdmin)} onClick={p.onClaim} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border border-slate-600 text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="held-claim">
                <Hand className="w-3.5 h-3.5" /> {d.assigned_to ? 'Take over' : 'Claim'}
              </button>
            )}
            {canUnassign && (
              <button type="button" disabled={p.busy} onClick={p.onUnassign} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border border-slate-600 text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="held-unassign">
                <UserMinus className="w-3.5 h-3.5" /> Unassign
              </button>
            )}
            <button type="button" disabled={p.busy || !!releaseBlocked} title={releaseBlocked || undefined} onClick={p.onRelease} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50" data-testid="held-release">
              <Check className="w-3.5 h-3.5" /> Release
            </button>
            <button type="button" disabled={p.busy || !!p.blockedReason} title={p.blockedReason || undefined} onClick={p.onStartRedact} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/10 disabled:opacity-50" data-testid="held-redact">
              <Eraser className="w-3.5 h-3.5" /> Redact and release
            </button>
            <button type="button" disabled={p.busy || !!p.blockedReason} title={p.blockedReason || undefined} onClick={p.onReject} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border border-rose-500/40 text-rose-200 hover:bg-rose-500/10 disabled:opacity-50" data-testid="held-reject">
              <X className="w-3.5 h-3.5" /> Reject
            </button>
          </div>
          {(p.blockedReason || releaseBlocked) && (
            <p className="text-[11px] text-slate-400" data-testid="held-blocked-reason">
              {p.blockedReason || releaseBlocked}
              {p.blockedReason && !p.isAdmin && <> <Link href="/settings/team" className="text-cyan-300 hover:underline">See who the admins are</Link></>}
            </p>
          )}
        </div>
      )}
      {p.actionError && !p.editing && <p role="alert" className="text-xs text-rose-300" data-testid="held-action-error">{p.actionError}</p>}

      <details className="text-xs" data-testid="held-history">
        <summary className="cursor-pointer text-slate-400 inline-flex items-center gap-1"><History className="w-3.5 h-3.5" /> History ({d.history.length})</summary>
        <ol className="mt-2 space-y-1 border-l border-slate-700 pl-3">
          {d.history.map((h, i) => (
            <li key={i} className="text-slate-300">
              <span className="text-slate-500">{h.at ? new Date(h.at).toLocaleString() : ''}</span>{' '}
              {HISTORY_LABEL[h.action] || h.action}
              {h.by_name ? ` by ${h.by_name}` : h.by ? '' : h.action === 'held' ? '' : ' automatically'}
              {h.note ? `: ${h.note}` : ''}
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function Meta({ label, value, urgent }: { label: string; value: string; urgent?: boolean }) {
  return (
    <div className="rounded-md border border-slate-700/40 bg-slate-900/40 px-2.5 py-1.5 min-w-0">
      <dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className={`truncate ${urgent ? 'text-rose-300' : 'text-slate-200'}`} title={value}>{value || '—'}</dd>
    </div>
  );
}
