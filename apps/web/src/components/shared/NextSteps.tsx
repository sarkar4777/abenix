'use client';

import Link from 'next/link';
import { ArrowRight, PartyPopper, X, type LucideIcon } from 'lucide-react';

export interface NextStep {
  id: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  href?: string;
  onClick?: () => void;
}

interface Props {
  title?: string;
  steps: NextStep[];
  onDismiss?: () => void;
  testId?: string;
  className?: string;
}

// Shown right after something worked, so the person knows where to go next.
export default function NextSteps({ title = 'Done. What next?', steps, onDismiss, testId = 'next-steps', className = '' }: Props) {
  // a short list, more than four reads like a menu
  const shown = steps.slice(0, 4);
  if (shown.length === 0) return null;
  return (
    <section
      className={`min-w-0 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 ${className}`}
      data-testid={testId}
      aria-label={title}
    >
      <div className="mb-3 flex items-center gap-2">
        <PartyPopper className="h-4 w-4 shrink-0 text-emerald-300" aria-hidden />
        <h2 className="flex-1 text-sm font-semibold text-emerald-100">{title}</h2>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Hide next steps"
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
            data-testid={`${testId}-dismiss`}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <ul className={`grid gap-2 ${shown.length > 1 ? 'sm:grid-cols-2' : ''} ${shown.length === 3 ? 'lg:grid-cols-3' : shown.length === 4 ? 'xl:grid-cols-4' : ''}`}>
        {shown.map((s) => {
          const body = (
            <>
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-800/80">
                <s.icon className="h-4 w-4 text-cyan-300" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1 text-sm font-medium text-white">
                  <span className="break-words">{s.label}</span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform group-hover:translate-x-0.5" />
                </span>
                <span className="mt-0.5 block break-words text-xs text-slate-400">{s.hint}</span>
              </span>
            </>
          );
          const cls = 'group flex w-full min-w-0 items-start gap-3 rounded-lg border border-slate-700/50 bg-slate-900/40 p-3 text-left hover:border-cyan-500/40 hover:bg-slate-900';
          return (
            <li key={s.id} className="min-w-0">
              {s.href ? (
                <Link href={s.href} className={cls} data-testid={`${testId}-${s.id}`}>
                  {body}
                </Link>
              ) : (
                <button type="button" onClick={s.onClick} className={cls} data-testid={`${testId}-${s.id}`}>
                  {body}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
