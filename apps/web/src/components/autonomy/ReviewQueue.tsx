'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, HelpCircle, Keyboard, Loader2, RefreshCw, RotateCcw, ThumbsUp } from 'lucide-react';
import ActionCard, { type ReviewAnswer } from './ActionCard';
import { autonomyApi, relTime, reviewItemsOf, type ActionRow } from '@/lib/autonomy';

function isTyping(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

export default function ReviewQueue({ canReview, onCountChange }: { canReview: boolean; onCountChange?: (n: number) => void }) {
  const [items, setItems] = useState<ActionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [answerErr, setAnswerErr] = useState<string | null>(null);
  const [different, setDifferent] = useState(false);
  const [alt, setAlt] = useState('');
  const [last, setLast] = useState<ActionRow | null>(null);
  const [done, setDone] = useState(0);
  const altRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    if (!canReview) { setLoading(false); return; }
    setLoading(true);
    const r = await autonomyApi.reviews(50);
    setLoading(false);
    if (r.error) { setError(r.error); return; }
    setError(null);
    const { items: list, total: t } = reviewItemsOf(r.data);
    setItems(list);
    setTotal(t);
  }, [canReview]);

  useEffect(() => { load(); }, [load]);

  const left = Math.max(0, total - done);
  useEffect(() => { onCountChange?.(left); }, [left]);

  const current = items[0];

  const answer = useCallback(async (a: ReviewAnswer, alternative?: string) => {
    if (!current || busy) return;
    setBusy(true);
    setAnswerErr(null);
    const r = await autonomyApi.review(current.id, a, alternative);
    setBusy(false);
    if (r.error) { setAnswerErr(r.error); return; }
    setLast(r.data ? { ...current, ...r.data, reviewer_answer: a, reviewer_alternative: alternative ?? null } : { ...current, reviewer_answer: a });
    setDifferent(false);
    setAlt('');
    setDone((d) => d + 1);
    const rest = items.slice(1);
    setItems(rest);
    if (rest.length === 0) { setDone(0); load(); }
  }, [current, busy, load, items]);

  useEffect(() => {
    if (!canReview) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target) || !current || busy) return;
      const k = e.key.toLowerCase();
      if (k === 'a') { e.preventDefault(); answer('agree'); }
      else if (k === 'n') { e.preventDefault(); answer('unsure'); }
      else if (k === 'd') { e.preventDefault(); setDifferent(true); setTimeout(() => altRef.current?.focus(), 0); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canReview, current, busy, answer]);

  if (!canReview) {
    return (
      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 text-sm text-slate-300" data-testid="autonomy-reviews-no-access">
        Answering watching reviews needs the <code className="text-cyan-300">actions.review</code> permission.{' '}
        <Link href="/admin/permissions" className="text-cyan-300 hover:underline">An admin can grant it under Permissions</Link>.
      </div>
    );
  }

  return (
    <div data-testid="autonomy-reviews">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-400">
          Agents in Watching say what they would do. Tell us if you would have done the same. Each answer builds their record.
        </p>
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-500"><Keyboard className="h-3.5 w-3.5" /> A agree, D different, N not sure</span>
        <button type="button" onClick={load} className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:text-white">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {error ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
          <AlertTriangle className="h-4 w-4" /> Could not load reviews: {error}
          <button type="button" onClick={load} className="ml-auto text-xs underline">Try again</button>
        </div>
      ) : loading && items.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading reviews</div>
      ) : !current ? (
        <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center" data-testid="autonomy-reviews-empty">
          <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400/40" />
          <p className="text-sm text-slate-400">Nothing to review. When an agent in Watching proposes an action it shows here.</p>
          <Link href="/autonomy" className="mt-2 inline-block text-xs text-cyan-300 hover:underline">Go to Autonomy</Link>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs font-medium text-cyan-300" data-testid="autonomy-reviews-left">{left} left</p>
          <section className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-4" data-testid="autonomy-review-situation" data-action-id={current.id}>
              <p className="text-[11px] uppercase tracking-wide text-slate-500">
                {current.agent?.name || 'An agent'} · {current.action_type?.label || current.tool_name || 'an action'} · {relTime(current.created_at)}
              </p>
              {current.card ? (
                <>
                  <h3 className="mt-1 text-sm font-semibold text-white">Would you have done the same?</h3>
                  {current.situation && <p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{current.situation}</p>}
                  <div className="mt-2"><ActionCard key={current.id} card={current.card} action={current} context="readonly" /></div>
                </>
              ) : (
                <>
                  <h3 className="mt-1 text-sm font-semibold text-white">What would you do here?</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{current.situation || 'The agent gave no summary of what it saw.'}</p>
                  <p className="mt-2 text-xs text-slate-500">Answer from what you did or would do. The agent's proposal shows after you answer, so it does not sway you.</p>
                </>
              )}
              {!different ? (
                <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <button type="button" disabled={busy} onClick={() => answer('agree')} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-300 disabled:opacity-50" data-testid="autonomy-review-agree">
                    <ThumbsUp className="h-3.5 w-3.5" /> Agree <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">A</kbd>
                  </button>
                  <button type="button" disabled={busy} onClick={() => { setDifferent(true); setTimeout(() => altRef.current?.focus(), 0); }} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 disabled:opacity-50" data-testid="autonomy-review-different">
                    <RotateCcw className="h-3.5 w-3.5" /> I did something else <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">D</kbd>
                  </button>
                  <button type="button" disabled={busy} onClick={() => answer('unsure')} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 disabled:opacity-50" data-testid="autonomy-review-unsure">
                    <HelpCircle className="h-3.5 w-3.5" /> Not sure <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">N</kbd>
                  </button>
                </div>
              ) : (
                <div className="mt-4">
                  <label htmlFor="review-alt" className="text-xs font-medium text-slate-300">What did you do?</label>
                  <textarea
                    id="review-alt"
                    ref={altRef}
                    rows={2}
                    value={alt}
                    onChange={(e) => setAlt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey && alt.trim()) { e.preventDefault(); answer('different', alt.trim()); }
                      if (e.key === 'Escape') setDifferent(false);
                    }}
                    placeholder="For example: set it to 4.5 bar"
                    className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white"
                    data-testid="autonomy-review-alternative"
                  />
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={busy || !alt.trim()} title={!alt.trim() ? 'Say what you did first' : undefined} onClick={() => answer('different', alt.trim())} className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 disabled:opacity-50" data-testid="autonomy-review-different-submit">
                      {busy ? 'Saving' : 'Save answer'}
                    </button>
                    <button type="button" onClick={() => setDifferent(false)} className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-300">Cancel</button>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">Enter saves, Escape cancels.</p>
                </div>
              )}
              {answerErr && <p className="mt-2 text-xs text-rose-300" role="alert">{answerErr}</p>}
            </section>

          {last?.card && (
            <div data-testid="autonomy-review-revealed">
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-500">Your last answer, and what the agent proposed</p>
              <ActionCard key={`last-${last.id}`} card={last.card} action={last} context="readonly" />
            </div>
          )}
        </div>
      )}
      {!current && last?.card && !loading && (
        <div className="mt-4" data-testid="autonomy-review-revealed">
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-500">Your last answer, and what the agent proposed</p>
          <ActionCard key={`last-${last.id}`} card={last.card} action={last} context="readonly" />
        </div>
      )}
    </div>
  );
}
