'use client';

import { LEVELS, levelMeta } from '@/lib/autonomy';

// Five steps, the ones up to the current level filled.
export default function LevelPill({
  level,
  ceiling,
  showLabel = true,
  size = 'md',
  testId = 'autonomy-level-pill',
}: {
  level: number;
  ceiling?: number | null;
  showLabel?: boolean;
  size?: 'sm' | 'md';
  testId?: string;
}) {
  const m = levelMeta(level);
  const seg = size === 'sm' ? 'h-1.5 w-3' : 'h-2 w-4';
  return (
    <span
      className="inline-flex items-center gap-2"
      data-testid={testId}
      data-level={m.level}
      title={`${m.label}: ${m.help}`}
      aria-label={`Level: ${m.label}`}
    >
      <span className="inline-flex items-center gap-0.5" aria-hidden>
        {LEVELS.slice(1).map((l) => {
          const filled = m.level >= l.level;
          const capped = typeof ceiling === 'number' && l.level > ceiling;
          return (
            <span
              key={l.level}
              className={`${seg} rounded-sm ${filled ? m.fill : capped ? 'bg-slate-800 border border-dashed border-slate-600' : 'bg-slate-700'}`}
            />
          );
        })}
      </span>
      {showLabel && <span className={`text-xs font-medium ${m.text}`}>{m.label}</span>}
    </span>
  );
}
