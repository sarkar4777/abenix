'use client';

import Link from 'next/link';
import { Milestone } from 'lucide-react';
import { autonomyBadgeHref, autonomyBadgeText, levelMeta, type AutonomyMeta } from '@/lib/autonomy';

// Small badge for a tool step that went through the autonomy gate.
export default function ActionBadge({ meta, testId = 'autonomy-step-badge' }: { meta: AutonomyMeta; testId?: string }) {
  const m = levelMeta(meta.level ?? 0);
  const tone = meta.status === 'blocked' || meta.status === 'rejected'
    ? 'bg-rose-500/10 text-rose-300 border-rose-500/40'
    : `${m.bg} ${m.text} ${m.border}`;
  return (
    <Link
      href={autonomyBadgeHref(meta)}
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium hover:brightness-125 ${tone}`}
      data-testid={testId}
      data-status={meta.status || ''}
      title="Open in Autonomy"
    >
      <Milestone className="h-3 w-3 shrink-0" />
      <span className="truncate">{autonomyBadgeText(meta)}</span>
    </Link>
  );
}
