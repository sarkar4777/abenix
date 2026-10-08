'use client';

export type ArgKind = 'number' | 'boolean' | 'string' | 'json' | 'null';

export function argKind(v: unknown): ArgKind {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'number') return 'number';
  if (typeof v === 'boolean') return 'boolean';
  if (typeof v === 'string') return 'string';
  return 'json';
}

export function initialDrafts(args: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(args)) {
    const kind = argKind(v);
    out[k] = kind === 'json' ? JSON.stringify(v, null, 2) : kind === 'null' ? '' : String(v);
  }
  return out;
}

// Turns the drafts back into values of the original types, or says what is wrong.
export function parseDrafts(
  args: Record<string, unknown>,
  drafts: Record<string, string>,
): { value: Record<string, unknown>; errors: Record<string, string> } {
  const value: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const [k, orig] of Object.entries(args)) {
    const raw = drafts[k] ?? '';
    const kind = argKind(orig);
    if (kind === 'number') {
      const n = Number(raw);
      if (raw.trim() === '' || !Number.isFinite(n)) errors[k] = 'Enter a number';
      else value[k] = n;
    } else if (kind === 'boolean') {
      value[k] = raw === 'true';
    } else if (kind === 'json') {
      try {
        value[k] = JSON.parse(raw);
      } catch {
        errors[k] = 'This is not valid JSON';
      }
    } else if (kind === 'null') {
      value[k] = raw === '' ? null : raw;
    } else {
      value[k] = raw;
    }
  }
  return { value, errors };
}

export default function ArgumentForm({
  args,
  drafts,
  errors,
  onChange,
}: {
  args: Record<string, unknown>;
  drafts: Record<string, string>;
  errors: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  const entries = Object.entries(args);
  if (entries.length === 0) {
    return <p className="text-xs text-slate-400">This action has no arguments to change.</p>;
  }
  const field = 'w-full rounded-md border bg-slate-950/60 px-2 py-1.5 text-sm text-white focus:outline-none focus:border-cyan-500/60';
  return (
    <div className="space-y-3" data-testid="action-card-edit-form">
      {entries.map(([k, orig]) => {
        const kind = argKind(orig);
        const id = `arg-${k}`;
        const err = errors[k];
        const border = err ? 'border-rose-500/60' : 'border-slate-700';
        return (
          <div key={k}>
            <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-300">
              {k.replace(/_/g, ' ')}
              <span className="ml-1.5 font-normal text-slate-500">({kind === 'json' ? 'JSON' : kind === 'null' ? 'text' : kind})</span>
            </label>
            {kind === 'boolean' ? (
              <select id={id} value={drafts[k]} onChange={(e) => onChange(k, e.target.value)} className={`${field} ${border}`} data-testid={`action-card-arg-${k}`}>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : kind === 'json' ? (
              <textarea
                id={id}
                rows={4}
                value={drafts[k]}
                onChange={(e) => onChange(k, e.target.value)}
                className={`${field} ${border} font-mono text-xs`}
                data-testid={`action-card-arg-${k}`}
              />
            ) : (
              <input
                id={id}
                type={kind === 'number' ? 'number' : 'text'}
                step="any"
                inputMode={kind === 'number' ? 'decimal' : undefined}
                value={drafts[k]}
                onChange={(e) => onChange(k, e.target.value)}
                className={`${field} ${border}`}
                data-testid={`action-card-arg-${k}`}
              />
            )}
            {err && <p className="mt-1 text-xs text-rose-300" role="alert">{err}</p>}
          </div>
        );
      })}
    </div>
  );
}
