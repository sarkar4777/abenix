'use client';

import Link from 'next/link';
import { CheckCircle2, Circle, ArrowRight } from 'lucide-react';
import { requirementProgress, type Requirement } from '@/lib/autonomy';

export default function RequirementList({ requirements }: { requirements: Requirement[] | undefined }) {
  const list = requirements || [];
  if (list.length === 0) {
    return (
      <p className="text-sm text-slate-400" data-testid="autonomy-requirements-empty">
        There are no checks for this step.
      </p>
    );
  }
  return (
    <ul className="space-y-3" data-testid="autonomy-requirements">
      {list.map((r) => {
        const pct = requirementProgress(r);
        return (
          <li key={r.key} data-testid={`autonomy-requirement-${r.key}`} data-met={r.met ? 'true' : 'false'}>
            <div className="flex items-start gap-2">
              {r.met ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" aria-label="Met" />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-label="Not met yet" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className={`text-sm ${r.met ? 'text-slate-200' : 'text-white'}`}>{r.label}</span>
                  {!r.met && r.fix && (
                    <Link
                      href={r.fix.href}
                      className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:underline"
                      data-testid={`autonomy-requirement-fix-${r.key}`}
                    >
                      {r.fix.label} <ArrowRight className="h-3 w-3" />
                    </Link>
                  )}
                </div>
                <div
                  className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={pct}
                  aria-label={r.label}
                >
                  <div className={`h-full rounded-full ${r.met ? 'bg-emerald-400' : 'bg-amber-400'}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
