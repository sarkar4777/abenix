import { LEVELS } from '@/lib/autonomy';

export const AUTONOMY_STEPS = [
  'An agent earns the right to act one kind of action at a time.',
  'It starts by watching. It says what it would do and nothing runs.',
  'As people agree with it and its predictions hold, it can move up. Any harm drops it back at once.',
];

export function AutonomyLevels() {
  return (
    <>
      <ol className="grid gap-2 sm:grid-cols-5">
        {LEVELS.map((l) => (
          <li key={l.level} className={`min-w-0 rounded-lg border ${l.border} ${l.bg} p-2`}>
            <p className={`text-xs font-semibold ${l.text}`}>{l.label}</p>
            <p className="mt-0.5 break-words text-[11px] text-slate-400">{l.help}</p>
          </li>
        ))}
      </ol>
      <p className="text-xs text-slate-400">
        Kill switches and hard limits apply at every level. Moving up always needs a person who did not build the agent.
        Moving down never needs an approval.
      </p>
    </>
  );
}
