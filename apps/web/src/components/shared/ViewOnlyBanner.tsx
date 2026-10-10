'use client';

import type { ReactNode } from 'react';
import { Eye } from 'lucide-react';

// says plainly that this page is for looking, who can act, and how to get the right
export default function ViewOnlyBanner({ children, testId = 'view-only' }: { children: ReactNode; testId?: string }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-xl border border-slate-600/60 bg-slate-800/40 px-3 py-2 text-sm text-slate-200" role="note" data-testid={testId}>
      <Eye className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
      <p className="min-w-0"><span className="font-semibold text-white">View only.</span> {children}</p>
    </div>
  );
}
