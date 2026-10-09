'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Check, Loader2, Sprout, ThumbsDown, ThumbsUp } from 'lucide-react';
import NextSteps from '@/components/shared/NextSteps';
import { improvementsApi, type FeedbackTarget } from '@/lib/improvements';

export const THANKS = "Thanks, this goes into the agent's lessons";
const MAX = 8000;

interface Props extends FeedbackTarget {
  className?: string;
  testId?: string;
}

// Thumbs up or down on an answer, with an optional "what should it have said" box after a thumbs down.
export default function FeedbackBar({ executionId, messageId, conversationId, agentId, className = '', testId = 'feedback' }: Props) {
  const target = { executionId, messageId, conversationId, agentId };
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [boxOpen, setBoxOpen] = useState(false);
  const [correction, setCorrection] = useState('');
  const [sentCorrection, setSentCorrection] = useState(false);
  const [lessonsFor, setLessonsFor] = useState<string | null>(null);
  const [nextShut, setNextShut] = useState(false);

  if (!executionId && !messageId && !agentId) return null;

  async function rate(r: 1 | -1, text?: string) {
    setBusy(true);
    setError(null);
    const res = await improvementsApi.feedback(target, r, text);
    setBusy(false);
    if (res.error || !res.data) {
      setError(res.status === 403
        ? 'Your account cannot give feedback here. An admin can grant feedback.give under Admin, Permissions.'
        : 'Your feedback was not saved. Check your connection and try again.');
      return false;
    }
    setRating(r);
    setLessonsFor(res.data.can_view_lessons ? res.data.agent_id : null);
    return true;
  }

  // the box opens at once, the thumbs down saves behind it
  async function down() {
    if (busy) return;
    setBoxOpen(true);
    if (!(await rate(-1))) setBoxOpen(false);
  }

  async function sendCorrection() {
    const text = correction.trim();
    if (!text || busy) return;
    if (await rate(-1, text)) {
      setSentCorrection(true);
      setBoxOpen(false);
    }
  }

  const btn = 'inline-flex h-7 w-7 items-center justify-center rounded-md border transition disabled:opacity-50';
  return (
    <div className={`mt-2 ${className}`} data-testid={testId}>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          aria-label="Good answer"
          aria-pressed={rating === 1}
          title="Good answer"
          disabled={busy}
          onClick={() => rate(1)}
          className={`${btn} ${rating === 1 ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300' : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200'}`}
          data-testid={`${testId}-up`}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Not right"
          aria-pressed={rating === -1}
          title="Not right"
          disabled={busy}
          onClick={down}
          className={`${btn} ${rating === -1 ? 'border-rose-500/60 bg-rose-500/15 text-rose-300' : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200'}`}
          data-testid={`${testId}-down`}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" aria-label="Saving" />}
        {rating !== null && !busy && !boxOpen && (
          <span className="inline-flex flex-wrap items-center gap-1 text-[11px] text-slate-400" role="status" data-testid={`${testId}-thanks`}>
            <Check className="h-3 w-3 text-emerald-400" />
            {THANKS}
            {sentCorrection ? ', with your correction' : ''}.
            {lessonsFor && (
              <Link href={`/agents/${encodeURIComponent(lessonsFor)}/improvements`} className="text-cyan-300 hover:underline" data-testid={`${testId}-lessons-link`}>
                See lessons
              </Link>
            )}
          </span>
        )}
      </div>
      {sentCorrection && lessonsFor && !nextShut && (
        <NextSteps
          title="Correction saved. What next?"
          testId={`${testId}-next`}
          className="mt-2 max-w-xl"
          onDismiss={() => setNextShut(true)}
          steps={[
            {
              id: 'lesson',
              label: 'See the lesson',
              hint: 'Your correction is a lesson now. Similar ones are grouped within two minutes and a fix can be proposed.',
              icon: Sprout,
              href: `/agents/${encodeURIComponent(lessonsFor)}/improvements`,
            },
          ]}
        />
      )}
      {error && (
        <p className="mt-1 text-[11px] text-rose-300" role="alert" data-testid={`${testId}-error`}>{error}</p>
      )}
      {boxOpen && (
        <div className="mt-2 w-full max-w-xl rounded-lg border border-slate-700 bg-slate-900/60 p-2.5" data-testid={`${testId}-box`}>
          <label htmlFor={`${testId}-correction`} className="block text-xs text-slate-300">
            What should it have said or done? <span className="text-slate-500">Optional</span>
          </label>
          <textarea
            id={`${testId}-correction`}
            value={correction}
            maxLength={MAX}
            onChange={(e) => setCorrection(e.target.value)}
            rows={3}
            placeholder="For example: it should have used today's price, 8,240 dollars."
            className="mt-1.5 w-full resize-y rounded-md border border-slate-700 bg-slate-950/60 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none"
            data-testid={`${testId}-correction`}
          />
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] text-slate-500">
              {rating === -1 ? 'Your thumbs down is already saved.' : 'Saving your thumbs down.'} A correction helps the agent learn the right answer.
            </span>
            <div className="flex gap-2">
              <button type="button" onClick={() => setBoxOpen(false)} className="rounded-md px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200" data-testid={`${testId}-skip`}>
                Skip
              </button>
              <button
                type="button"
                onClick={sendCorrection}
                disabled={!correction.trim() || busy}
                className="rounded-md bg-cyan-500 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
                data-testid={`${testId}-send`}
              >
                Send correction
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
