'use client';

export default function ConfigWarnings({ warnings, onDismiss }: { warnings: string[]; onDismiss: () => void }) {
  return (
    <div role="status" data-testid="builder-config-warnings" className="mx-3 mt-2 flex items-start justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      <div className="min-w-0 space-y-1">
        <p className="font-semibold">Saved, but check this before you run it</p>
        {warnings.map((w) => <p key={w} className="break-words">{w}</p>)}
      </div>
      <button onClick={onDismiss} aria-label="Dismiss warnings" className="text-amber-300 hover:text-white">×</button>
    </div>
  );
}
