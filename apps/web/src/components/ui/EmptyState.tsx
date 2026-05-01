'use client';

import { type LucideIcon } from 'lucide-react';
import Link from 'next/link';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}

export default function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  actionHref,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-2xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
        <Icon className="w-7 h-7 text-slate-600" />
      </div>
      <p className="text-sm text-slate-400 mt-4">{title}</p>
      <p className="text-xs text-slate-600 mt-1 max-w-xs">{description}</p>
      {actionLabel && actionHref && (
        <Link
          href={actionHref}
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          {actionLabel}
        </Link>
      )}
      {actionLabel && !actionHref && onAction && (
        <button
          onClick={onAction}
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
