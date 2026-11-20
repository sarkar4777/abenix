'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';

/**
 * A small modal: a confirmation, or a required note. The note must have
 * text of its own; the API puts the reviewer's name in front of it.
 */
export function Dialog({
  title, body, confirm, tone = 'sky', noteLabel, notePlaceholder, onConfirm, onClose,
}: {
  title: string;
  body?: React.ReactNode;
  confirm: string;
  tone?: 'sky' | 'amber' | 'violet' | 'rose';
  noteLabel?: string;
  notePlaceholder?: string;
  onConfirm: (note: string) => Promise<void>;
  onClose: () => void;
}) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    field.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const needsNote = Boolean(noteLabel);
  const ready = !needsNote || note.trim().length > 0;
  const buttonTone = {
    sky: 'bg-sky-500 hover:bg-sky-400',
    amber: 'bg-amber-500 hover:bg-amber-400',
    violet: 'bg-violet-500 hover:bg-violet-400',
    rose: 'bg-rose-500 hover:bg-rose-400',
  }[tone];

  const submit = async () => {
    if (!ready || busy) return;
    setBusy(true);
    try {
      await onConfirm(note.trim());
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/70 p-4" role="dialog" aria-modal="true"
      aria-label={title} onClick={() => !busy && onClose()}>
      <div className="w-full max-w-md rounded-xl bg-slate-900 ring-1 ring-slate-700 p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        {body && <div className="text-sm text-slate-400">{body}</div>}
        {needsNote && (
          <label className="block space-y-1.5">
            <span className="text-xs text-slate-400">{noteLabel}</span>
            <textarea
              ref={field}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit(); }}
              rows={4}
              placeholder={notePlaceholder}
              data-testid="dialog-note"
              className="w-full rounded-lg bg-slate-950 ring-1 ring-slate-700 focus:ring-sky-500/60 outline-none px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
            />
          </label>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={busy}
            className="px-3 py-1.5 rounded-lg text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={() => void submit()} disabled={!ready || busy} data-testid="dialog-confirm"
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-slate-950 ${buttonTone} disabled:opacity-40 disabled:cursor-not-allowed`}>
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} {confirm}
          </button>
        </div>
      </div>
    </div>
  );
}
