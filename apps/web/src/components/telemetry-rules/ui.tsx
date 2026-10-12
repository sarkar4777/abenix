'use client';

import type { ReactNode } from 'react';

export const inputCls =
  'min-h-[40px] w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-60';

export function cls(err?: string | null) {
  return `${inputCls} ${err ? 'border-rose-500/70 focus:border-rose-400' : 'border-slate-700 focus:border-cyan-500'}`;
}

export function Field({
  label, help, error, children, htmlFor, testId, className = '',
}: { label: ReactNode; help?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string; testId?: string; className?: string }) {
  return (
    <div className={`min-w-0 ${className}`} data-testid={testId}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-slate-300">{label}</label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-rose-300" role="alert" data-testid={testId ? `${testId}-error` : undefined}>{error}</p>
      ) : help ? (
        <p className="mt-1 text-xs text-slate-500">{help}</p>
      ) : null}
    </div>
  );
}

export function Section({ n, title, help, children, testId }: { n: number; title: string; help?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4" data-testid={testId}>
      <div className="mb-3 flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-cyan-500/15 text-xs font-semibold text-cyan-300">{n}</span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {help && <p className="mt-0.5 text-xs text-slate-400">{help}</p>}
        </div>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export function Choice({
  active, onClick, title, help, disabled, testId, why,
}: { active: boolean; onClick: () => void; title: string; help?: string; disabled?: boolean; testId?: string; why?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? why : undefined}
      aria-pressed={active}
      className={`min-h-[44px] w-full rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
        active ? 'border-cyan-500/70 bg-cyan-500/10' : 'border-slate-700 bg-slate-900/60 hover:border-slate-500'
      }`}
      data-testid={testId}
    >
      <span className={`block text-sm font-medium ${active ? 'text-cyan-200' : 'text-slate-200'}`}>{title}</span>
      {help && <span className="mt-0.5 block text-xs text-slate-400">{help}</span>}
    </button>
  );
}

export function Badge({ tone = 'slate', children, testId }: { tone?: 'slate' | 'cyan' | 'amber' | 'rose' | 'emerald'; children: ReactNode; testId?: string }) {
  const map = {
    slate: 'border-slate-600 bg-slate-800/60 text-slate-300',
    cyan: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200',
    amber: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    rose: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    emerald: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  } as const;
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${map[tone]}`} data-testid={testId}>
      {children}
    </span>
  );
}

export function severityTone(s: string): 'slate' | 'amber' | 'rose' {
  return s === 'critical' ? 'rose' : s === 'warning' ? 'amber' : 'slate';
}
