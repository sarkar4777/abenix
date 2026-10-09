'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Check, Loader2, MessageSquareWarning } from 'lucide-react';
import { improvementsApi } from '@/lib/improvements';

const MAX_NOTE = 4000;

// "This was wrong because" on a run: a note, and what it should have done if known.
export default function WrongBecause({ executionId, agentId }: { executionId: string; agentId: string }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [expected, setExpected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    const text = note.trim();
    if (!text) { setError('Say what was wrong, in a sentence or two.'); return; }
    setBusy(true);
    setError(null);
    const r = await improvementsApi.note({
      agent_id: agentId,
      execution_id: executionId,
      note: text,
      expected: expected.trim() || undefined,
    });
    setBusy(false);
    if (r.error) {
      setError(r.status === 403
        ? 'Your account cannot add notes. An admin can grant feedback.give under Admin, Permissions.'
        : `The note was not saved: ${r.error}`);
      return;
    }
    setSaved(true);
    setOpen(false);
  }

  if (saved) {
    return (
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400" role="status" data-testid="wrong-because-saved">
        <Check className="h-3.5 w-3.5 text-emerald-400" /> Thanks, this goes into the agent&apos;s lessons.
        <Link href={`/agents/${encodeURIComponent(agentId)}/improvements`} className="text-cyan-300 hover:underline">See lessons</Link>
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:border-slate-500 hover:text-white"
        data-testid="wrong-because-open"
      >
        <MessageSquareWarning className="h-3.5 w-3.5 text-amber-300" /> This was wrong because…
      </button>
    );
  }

  return (
    <div className="w-full space-y-2 rounded-lg border border-slate-700 bg-slate-900/60 p-3" data-testid="wrong-because-form">
      <div>
        <label htmlFor="wrong-because-note" className="block text-xs text-slate-300">This was wrong because</label>
        <textarea
          id="wrong-because-note"
          value={note}
          maxLength={MAX_NOTE}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="For example: it quoted last month's price instead of today's."
          className="mt-1 w-full resize-y rounded-md border border-slate-700 bg-slate-950/60 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none"
          data-testid="wrong-because-note"
        />
      </div>
      <div>
        <label htmlFor="wrong-because-expected" className="block text-xs text-slate-300">
          What it should have said or done <span className="text-slate-500">Optional</span>
        </label>
        <textarea
          id="wrong-because-expected"
          value={expected}
          onChange={(e) => setExpected(e.target.value)}
          rows={2}
          className="mt-1 w-full resize-y rounded-md border border-slate-700 bg-slate-950/60 px-2.5 py-1.5 text-sm text-slate-100 focus:border-cyan-500 focus:outline-none"
          data-testid="wrong-because-expected"
        />
      </div>
      {error && <p className="text-xs text-rose-300" role="alert" data-testid="wrong-because-error">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={() => { setOpen(false); setError(null); }} className="rounded-md px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !note.trim()}
          className="inline-flex items-center gap-1.5 rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="wrong-because-save"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save the lesson
        </button>
      </div>
    </div>
  );
}
