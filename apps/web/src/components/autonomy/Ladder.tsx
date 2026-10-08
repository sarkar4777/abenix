'use client';

import { Lock } from 'lucide-react';
import { LEVELS } from '@/lib/autonomy';

export default function Ladder({ level, ceiling }: { level: number; ceiling?: number | null }) {
  return (
    <ol className="grid grid-cols-1 sm:grid-cols-5 gap-2" data-testid="autonomy-ladder">
      {LEVELS.map((l) => {
        const current = l.level === level;
        const passed = l.level < level;
        const above = typeof ceiling === 'number' && l.level > ceiling;
        return (
          <li
            key={l.level}
            data-testid={`autonomy-ladder-step-${l.key}`}
            data-current={current ? 'true' : 'false'}
            aria-current={current ? 'step' : undefined}
            className={`relative rounded-lg border p-3 ${
              current
                ? `${l.bg} ${l.border} ring-1 ring-inset ring-white/10`
                : passed
                  ? 'border-slate-700 bg-slate-800/40'
                  : 'border-slate-800 bg-slate-900/40'
            } ${above ? 'opacity-50' : ''}`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                  current ? `${l.fill} text-slate-900` : passed ? 'bg-slate-600 text-slate-200' : 'bg-slate-800 text-slate-500'
                }`}
              >
                {l.level}
              </span>
              <span className={`text-sm font-medium ${current ? l.text : passed ? 'text-slate-300' : 'text-slate-500'}`}>{l.label}</span>
              {above && <Lock className="ml-auto h-3 w-3 text-slate-500" aria-label="Above the ceiling" />}
            </div>
            <p className={`mt-1 text-[11px] leading-snug ${current ? 'text-slate-300' : 'text-slate-500'}`}>{l.help}</p>
            {current && <span className="sr-only">Current level</span>}
          </li>
        );
      })}
    </ol>
  );
}
