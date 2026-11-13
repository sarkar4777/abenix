'use client';

import { useState } from 'react';
import {
  CheckCircle2, ExternalLink, Eye, EyeOff, Loader2, Lock, MessageSquareMore, Pencil, RefreshCw,
  Send, ShieldAlert, Undo2,
} from 'lucide-react';

import { Dialog } from '@/components/Dialog';
import { api, refreshAll, type Draft, type Email, type EmailText } from '@/lib/api';
import { clock } from '@/lib/format';
import { toastError, toastSuccess } from '@/stores/toastStore';

type Fields = Omit<EmailText, 'to'>;
const FIELDS: (keyof Fields)[] = ['subject', 'greeting', 'body', 'closing'];

function EmailView({ text, muted = false }: { text: EmailText; muted?: boolean }) {
  return (
    <div className={`rounded-lg ring-1 ring-slate-800 bg-slate-950/50 text-sm ${muted ? 'opacity-70' : ''}`}>
      <div className="px-4 py-2 border-b border-slate-800 text-xs space-y-0.5">
        <div><span className="text-slate-500 w-16 inline-block">To</span><span className="text-slate-200">{text.to}</span></div>
        <div><span className="text-slate-500 w-16 inline-block">Subject</span><span className="text-slate-200">{text.subject}</span></div>
      </div>
      <div className="px-4 py-3 whitespace-pre-wrap text-slate-200 leading-relaxed [overflow-wrap:anywhere]">
        {text.greeting}{'\n\n'}{text.body}{'\n\n'}{text.closing}
      </div>
    </div>
  );
}

function Editor({ value, onChange }: { value: Fields; onChange: (v: Fields) => void }) {
  const input = 'w-full rounded-lg bg-slate-950 ring-1 ring-slate-700 focus:ring-sky-500/60 outline-none px-3 py-2 text-sm text-slate-100';
  return (
    <div className="space-y-2" data-testid="draft-editor">
      {FIELDS.map((f) => (
        <label key={f} className="block">
          <span className="text-[11px] uppercase tracking-wider text-slate-500">{f}</span>
          {f === 'body' || f === 'closing' ? (
            <textarea className={`${input} font-[inherit]`} rows={f === 'body' ? 16 : 2} value={value[f]}
              onChange={(e) => onChange({ ...value, [f]: e.target.value })} data-testid={`edit-${f}`} />
          ) : (
            <input className={input} value={value[f]} onChange={(e) => onChange({ ...value, [f]: e.target.value })}
              data-testid={`edit-${f}`} />
          )}
        </label>
      ))}
    </div>
  );
}

const KIND_LABEL: Record<Draft['kind'], string> = {
  quote: 'Quote email',
  clarification: 'Clarification email',
  redraft: 'Clarification email, redrafted from a note',
};

/** The current draft and everything the reviewer can do with it. */
export function DraftPanel({ email, draft }: { email: Email; draft: Draft }) {
  const [editing, setEditing] = useState<Fields | null>(null);
  const [showAi, setShowAi] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'ask' | 'escalate' | null>(null);

  const current = draft.edited ?? draft.ai;
  const open = email.review === 'awaiting_review' && draft.approval?.status === 'pending';
  const approvalsUrl = `${email.abenix_web_url}/approvals`;

  const run = async (label: string, work: () => Promise<{ error: string | null }>, done?: string) => {
    setBusy(label);
    const r = await work();
    setBusy(null);
    if (r.error) {
      toastError(r.error);
      refreshAll();
      return false;
    }
    if (done) toastSuccess(done);
    refreshAll();
    return true;
  };

  const save = async () => {
    if (!editing) return;
    if (await run('save', () => api.saveDraft(email.id, editing))) setEditing(null);
  };

  const review = async (action: 'send' | 'ask' | 'escalate', note = '') => {
    const done = {
      send: 'Sent. The approval is signed in Abenix.',
      ask: 'Returned in Abenix. A new clarification is being drafted from your note.',
      escalate: 'Escalated. Nothing was sent.',
    }[action];
    if (await run(action, () => api.review(email.id, action, note), done)) setDialog(null);
  };

  return (
    <div className="space-y-3" data-testid="draft-panel">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-sm font-semibold text-white">{KIND_LABEL[draft.kind]}</span>
        {draft.edited && <span className="rounded px-1.5 py-0.5 bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30" data-testid="edited-badge">Edited</span>}
        <span className="text-slate-500 inline-flex items-center gap-1">
          <Lock className="w-3 h-3" /> To {draft.ai.to}, from the email's headers
        </span>
        {draft.run_url && (
          <a href={draft.run_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-sky-300/80 hover:text-sky-200">
            Drafting run <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>
      {draft.kind === 'redraft' && draft.note && (
        <p className="text-xs text-slate-400">Your note: “{draft.note}”</p>
      )}

      {editing ? <Editor value={editing} onChange={setEditing} /> : <EmailView text={current} />}

      {draft.edited && !editing && (
        <button onClick={() => setShowAi((s) => !s)} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200" data-testid="toggle-ai">
          {showAi ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          {showAi ? 'Hide the AI draft' : 'Show the AI draft'}
        </button>
      )}
      {showAi && draft.edited && !editing && <EmailView text={draft.ai} muted />}

      {open && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {editing ? (
            <>
              <button onClick={() => void save()} disabled={busy !== null} data-testid="save-edits"
                className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 px-3 py-1.5 text-sm font-medium disabled:opacity-50">
                {busy === 'save' && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save edits
              </button>
              <button onClick={() => setEditing(null)} disabled={busy !== null}
                className="rounded-lg px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing({ subject: current.subject, greeting: current.greeting, body: current.body, closing: current.closing })}
                disabled={busy !== null} data-testid="edit"
                className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800">
                <Pencil className="w-3.5 h-3.5" /> Edit
              </button>
              {draft.edited && (
                <button onClick={() => void run('revert', () => api.revertDraft(email.id), 'Back to the AI draft.')}
                  disabled={busy !== null} data-testid="revert"
                  className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800">
                  <Undo2 className="w-3.5 h-3.5" /> Revert to AI draft
                </button>
              )}
              <span className="flex-1" />
              <button onClick={() => void review('send')} disabled={busy !== null} data-testid="send"
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-3 py-1.5 text-sm font-semibold disabled:opacity-50">
                {busy === 'send' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Send
              </button>
              <button onClick={() => setDialog('ask')} disabled={busy !== null} data-testid="ask"
                className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-amber-500/50 text-amber-200 hover:bg-amber-500/10 px-3 py-1.5 text-sm">
                <MessageSquareMore className="w-3.5 h-3.5" /> Ask the customer…
              </button>
              <button onClick={() => setDialog('escalate')} disabled={busy !== null} data-testid="escalate"
                className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-violet-500/50 text-violet-200 hover:bg-violet-500/10 px-3 py-1.5 text-sm">
                <ShieldAlert className="w-3.5 h-3.5" /> Escalate…
              </button>
            </>
          )}
        </div>
      )}

      {open && !editing && (
        <p className="text-[11px] text-slate-500">
          The review is open in Abenix
          {draft.approval?.expires_at && <> until {clock(draft.approval.expires_at)}</>}. Deciding there counts too:
          Approve sends, Return for changes asks the customer, Deny escalates.{' '}
          <a href={approvalsUrl} target="_blank" rel="noreferrer" className="text-sky-300/80 hover:text-sky-200">Abenix approvals ↗</a>
        </p>
      )}

      {(email.review === 'review_expired' || (email.review === 'awaiting_review' && !draft.approval)) && (
        <div className="rounded-lg bg-slate-800/50 ring-1 ring-slate-700 p-3 text-sm flex flex-wrap items-center gap-3" data-testid="raise-again">
          <span className="text-slate-300 flex-1 min-w-[12rem]">
            {email.review === 'review_expired'
              ? 'The review expired in Abenix before anyone decided. Nothing was sent.'
              : draft.approval_error ?? 'The review could not be raised in Abenix.'}
          </span>
          <button onClick={() => void run('raise', () => api.raiseReview(email.id), 'Review raised in Abenix.')}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 px-3 py-1.5 text-sm font-medium disabled:opacity-50">
            {busy === 'raise' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Raise review again
          </button>
        </div>
      )}

      {dialog === 'ask' && (
        <Dialog
          title="Ask the customer"
          body="Say what to ask, or what to change in this clarification. QuoteIQ drafts a new clarification from your note, and it comes back here for review."
          noteLabel="What to ask (required)"
          notePlaceholder="For example: ask which colour they need, and whether 1.1 mm OD is a hard limit"
          confirm="Redraft"
          tone="amber"
          onConfirm={(note) => review('ask', note)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'escalate' && (
        <Dialog
          title="Escalate to staff"
          body="Nothing is sent to the customer. Say why, for the staff who take it over."
          noteLabel="Why (required)"
          notePlaceholder="For example: full specification, but we can't make this OD"
          confirm="Escalate"
          tone="violet"
          onConfirm={(note) => review('escalate', note)}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

/** A draft that was sent: the text as sent, when and by whom. */
export function SentPanel({ draft }: { draft: Draft }) {
  const sent = draft.sent!;
  return (
    <div className="space-y-3" data-testid="sent-panel">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        <span className="text-sm font-semibold text-white">{KIND_LABEL[draft.kind]}, sent</span>
        {sent.edited && <span className="rounded px-1.5 py-0.5 bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30">Edited</span>}
        <span className="text-slate-400">
          by {sent.by} at {clock(sent.at)}{draft.decision && !draft.decision.in_app ? ', approved in Abenix' : ''}
        </span>
      </div>
      <EmailView text={sent} />
      <p className="text-[11px] text-slate-500">QuoteIQ is an example: the email is recorded as sent, not mailed.</p>
    </div>
  );
}
