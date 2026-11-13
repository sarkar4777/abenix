import { CheckCircle2, Clock, Loader2, RotateCcw, TimerOff } from 'lucide-react';

import type { Review, Status } from '@/lib/api';
import { REVIEW_LABEL, STATUS_SHORT, STATUS_TONE } from '@/lib/format';

/** The email's status, with where its review stands. */
export function StatusBadge({ status, review, long = false }: {
  status: Status; review: Review; long?: boolean;
}) {
  const tone = STATUS_TONE[status];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs whitespace-nowrap ${tone.text}`} data-testid="status-badge">
      {status === 'processing'
        ? <Loader2 className="w-3 h-3 animate-spin" />
        : <span className={`w-2 h-2 rounded-full ${tone.dot}`} />}
      <span className="font-medium">
        {long && status === 'clarification' ? 'Need customer clarification' : STATUS_SHORT[status]}
      </span>
      {review && <ReviewMark review={review} />}
    </span>
  );
}

export function ReviewMark({ review }: { review: Exclude<Review, null> }) {
  const icon = {
    awaiting_review: <Clock className="w-3 h-3" />,
    sent: <CheckCircle2 className="w-3 h-3" />,
    redrafting: <RotateCcw className="w-3 h-3 animate-spin [animation-duration:2s]" />,
    review_expired: <TimerOff className="w-3 h-3" />,
  }[review];
  return (
    <span className="inline-flex items-center gap-1 text-slate-400 font-normal">
      · {icon} {REVIEW_LABEL[review]}
    </span>
  );
}
