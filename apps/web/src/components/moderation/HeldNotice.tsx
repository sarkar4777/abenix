'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CheckCircle2, Clock, Loader2, ShieldAlert, Send } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useNotificationStore } from '@/stores/notificationStore';
import type { HoldBlock } from '@/stores/chatStore';
import MaskedText from './MaskedText';

export interface HoldView {
  id: string;
  status: string;
  status_label: string;
  source: string;
  expires_at: string | null;
  timeout_action: 'reject' | 'release';
  decided_at: string | null;
  reason: string | null;
  delivered: boolean;
  conversation_id: string | null;
  content: string | null;
}

export const RELEASED = ['released', 'redacted', 'auto_released'];
export const REJECTED = ['rejected', 'auto_rejected'];
// only a backstop while the live channel is down, decisions arrive over the socket
const SLOW_POLL_MS = 60_000;
// about 45 seconds of retries before a missing review counts as gone
const RECORD_RETRIES = 8;

export function timeLeft(iso: string | null, now: number): string {
  if (!iso) return '';
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms)) return '';
  if (ms <= 0) return 'any moment now';
  const min = Math.ceil(ms / 60_000);
  if (min < 60) return `in ${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h < 48) return m ? `in ${h} h ${m} min` : `in ${h} h`;
  return `in ${Math.round(h / 24)} days`;
}

interface Props {
  block: HoldBlock;
  // a released message of theirs goes on to the agent, the chat decides how
  onReleased?: (view: HoldView) => void;
}

export default function HeldNotice({ block, onReleased }: Props) {
  const [view, setView] = useState<HoldView | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const pushed = useNotificationStore((s) => s.moderationReview);
  const resumed = useRef(false);
  const [sent, setSent] = useState(false);
  const isUserSide = block.source === 'pre_llm';

  const misses = useRef(0);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    const r = await apiFetch<HoldView>(`/api/moderation/holds/${block.review_id}`, { silent: true });
    if (r.data) {
      misses.current = 0;
      setView(r.data);
      setMissing(false);
      setLoading(false);
    } else if (r.errorDetail?.code === 404) {
      // the run records the review a moment after the chat hears about it
      misses.current += 1;
      if (misses.current <= RECORD_RETRIES) {
        if (retry.current) clearTimeout(retry.current);
        retry.current = setTimeout(load, Math.min(1000 * 2 ** (misses.current - 1), 8000));
      } else {
        setMissing(true);
        setLoading(false);
      }
    } else {
      setLoading(false);
    }
  }, [block.review_id]);

  useEffect(() => () => { if (retry.current) clearTimeout(retry.current); }, []);

  useEffect(() => { load(); }, [load]);

  // a decision pushed over the socket refreshes this card at once
  useEffect(() => {
    if (pushed && pushed.id === block.review_id) load();
  }, [pushed, block.review_id, load]);

  const pending = !view || view.status === 'pending';
  useEffect(() => {
    if (!pending) return;
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    const poll = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') load();
    }, SLOW_POLL_MS);
    return () => { clearInterval(tick); clearInterval(poll); };
  }, [pending, load]);

  useEffect(() => {
    if (!view || resumed.current || !onReleased) return;
    if (view.source === 'pre_llm' && RELEASED.includes(view.status) && !view.delivered && view.content) {
      resumed.current = true;
      setSent(true);
      onReleased(view);
    }
  }, [view, onReleased]);

  const what = isUserSide ? 'Your message' : 'The reply';

  if (loading && !view && !block.timeout_minutes && !block.text) {
    return (
      <div data-testid="held-notice" data-status="loading" className="flex items-center gap-2 text-xs text-slate-400">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking the review status…
      </div>
    );
  }

  if (missing && !view) {
    return (
      <div data-testid="held-notice" data-status="gone" className="text-xs text-slate-400">
        {what} was held for review. The review record is no longer kept, so its outcome cannot be shown.
      </div>
    );
  }

  if (!view || view.status === 'pending') {
    const minutes = block.timeout_minutes;
    const after = (view?.timeout_action || block.timeout_action) === 'release' ? 'be sent anyway' : 'not be sent';
    const own = view?.content || block.text;
    return (
      <div data-testid="held-notice" data-status="pending" role="status" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
        <div className="flex items-center gap-2 font-medium">
          <Clock className="w-4 h-4 text-amber-300 shrink-0" />
          <span>{what} is waiting for review</span>
        </div>
        <p className="mt-1 text-xs text-amber-100/80 leading-relaxed">
          Your organisation asks a person to check content like this before it goes{isUserSide ? ' to the agent' : ' out'}.
          {view?.expires_at
            ? ` If nobody decides, it will ${after} ${timeLeft(view.expires_at, now)}.`
            : minutes
              ? ` If nobody decides within ${minutes} minutes it will ${after}.`
              : ''}
          {' '}You can keep chatting, this card updates by itself.
        </p>
        {own && isUserSide && (
          <p className="mt-2 text-xs text-slate-300 whitespace-pre-wrap break-words border-l-2 border-amber-500/40 pl-2 line-clamp-4">{own}</p>
        )}
      </div>
    );
  }

  if (REJECTED.includes(view.status)) {
    return (
      <div data-testid="held-notice" data-status="rejected" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-100">
        <div className="flex items-center gap-2 font-medium">
          <ShieldAlert className="w-4 h-4 text-rose-300 shrink-0" />
          <span>{what} was not sent</span>
        </div>
        <p className="mt-1 text-xs text-rose-100/80" data-testid="held-notice-reason">
          {view.status === 'auto_rejected' ? 'Nobody reviewed it in time. ' : 'A reviewer withheld it. '}
          {view.reason && view.status !== 'auto_rejected' ? `Reason: ${view.reason}` : ''}
        </p>
      </div>
    );
  }

  const label = view.status === 'redacted'
    ? 'Released after review, with parts removed'
    : view.status === 'auto_released'
      ? 'Released when the review time ran out'
      : 'Released after review';
  return (
    <div
      data-testid="held-notice"
      data-status="released"
      className={`space-y-1.5 p-4 border ${isUserSide ? 'bg-cyan-600/20 border-cyan-500/20 rounded-2xl rounded-br-sm' : 'bg-slate-800/50 border-slate-700/50 rounded-2xl rounded-bl-sm'}`}
    >
      {view.content ? (
        isUserSide ? (
          <p className="text-sm text-white whitespace-pre-wrap break-words" data-testid="held-notice-content"><MaskedText text={view.content} /></p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none text-slate-200" data-testid="held-notice-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{view.content}</ReactMarkdown>
          </div>
        )
      ) : (
        <p className="text-xs text-slate-400">The released text is no longer kept.</p>
      )}
      <p className="inline-flex items-center gap-1 text-[11px] text-emerald-300">
        <CheckCircle2 className="w-3 h-3" /> {label}
      </p>
      {isUserSide && sent && (
        <p className="inline-flex items-center gap-1 text-[11px] text-slate-400 ml-2">
          <Send className="w-3 h-3" /> Sent to the agent
        </p>
      )}
    </div>
  );
}
