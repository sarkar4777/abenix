'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Flag, HelpCircle, Loader2,
  PencilLine, RotateCcw, Target, ThumbsUp, Undo2, XCircle,
} from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import LevelPill from './LevelPill';
import ArgumentForm, { initialDrafts, parseDrafts } from './ArgumentForm';
import {
  autonomyApi, fmtDuration, fmtNum, MODE_LABEL, predictionText, relTime, statusMeta,
  type ActionCardData, type ActionRow,
} from '@/lib/autonomy';

export type ActionCardContext = 'approval' | 'review' | 'timeline' | 'readonly';
export type ReviewAnswer = 'agree' | 'different' | 'unsure';

interface Props {
  card: ActionCardData;
  action?: ActionRow | null;
  context?: ActionCardContext;
  busy?: boolean;
  error?: string | null;
  onApprove?: (edited?: Record<string, unknown>) => unknown;
  onReject?: (note: string) => unknown;
  onReview?: (answer: ReviewAnswer, alternative?: string) => unknown;
  // flag harm and enter outcome, for people holding actions.review
  canFollowUp?: boolean;
  onChanged?: (row: ActionRow) => void;
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-[120px_1fr] sm:gap-3">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-sm text-slate-200">{children}</dd>
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  agent_stated: 'Stated by the agent',
  decision: 'Decision model',
  ml_model: 'ML model',
  none: 'None',
};

export default function ActionCard({
  card, action, context = 'readonly', busy = false, error, onApprove, onReject, onReview, canFollowUp = false, onChanged,
}: Props) {
  const args = useMemo(() => (card.arguments && typeof card.arguments === 'object' ? card.arguments : action?.arguments || {}), [card.arguments, action?.arguments]);
  const [mode, setMode] = useState<'idle' | 'edit' | 'reject' | 'different' | 'outcome'>('idle');
  const [drafts, setDrafts] = useState<Record<string, string>>(() => initialDrafts(args));
  const [note, setNote] = useState('');
  const [alt, setAlt] = useState('');
  const [outcomeValue, setOutcomeValue] = useState('');
  const [showDetails, setShowDetails] = useState(false);
  const [harmOpen, setHarmOpen] = useState(false);
  const [harmNote, setHarmNote] = useState('');
  const [followBusy, setFollowBusy] = useState(false);
  const [followErr, setFollowErr] = useState<string | null>(null);

  const parsed = useMemo(() => parseDrafts(args, drafts), [args, drafts]);
  const editErrors = mode === 'edit' ? parsed.errors : {};
  const hasEditErrors = Object.keys(parsed.errors).length > 0;

  const label = card.action_type?.label || action?.action_type?.label || action?.tool_name || 'take an action';
  const agentName = card.agent?.name || action?.agent?.name || 'The agent';
  const level = typeof card.level === 'number' ? card.level : action?.level_at_time ?? null;
  const status = action?.status;
  const sm = status ? statusMeta(status) : null;
  const limits = card.limits;
  const pred = card.prediction ?? action?.prediction ?? null;
  const reversible = card.action_type?.reversible;
  const outcome = action?.outcome;
  const score = action?.score;
  const harmed = Boolean(action?.harm || score?.harm);
  const isDone = status === 'executed';
  const allowHarm = canFollowUp && !!action?.id && isDone && !harmed;
  const allowOutcome = canFollowUp && !!action?.id && isDone && action?.outcome_status !== 'observed' && action?.outcome_status !== 'manual';
  const editable = card.editable_arguments !== false && Object.keys(args).length > 0;

  async function submitOutcome() {
    if (!action?.id) return;
    const raw = outcomeValue.trim();
    if (!raw) return;
    const n = Number(raw);
    setFollowBusy(true);
    setFollowErr(null);
    const r = await autonomyApi.outcome(action.id, Number.isFinite(n) ? n : raw);
    setFollowBusy(false);
    if (r.error) return setFollowErr(r.error);
    setMode('idle');
    setOutcomeValue('');
    if (r.data) onChanged?.(r.data);
  }

  async function submitHarm() {
    if (!action?.id || !harmNote.trim()) return;
    setFollowBusy(true);
    setFollowErr(null);
    const r = await autonomyApi.harm(action.id, harmNote.trim());
    setFollowBusy(false);
    setHarmOpen(false);
    if (r.error) return setFollowErr(r.error);
    setHarmNote('');
    if (r.data) onChanged?.(r.data);
  }

  const btn = 'inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <article
      className={`rounded-xl border bg-slate-800/40 p-4 ${harmed ? 'border-rose-500/50' : 'border-slate-700/50'}`}
      data-testid="action-card"
      data-action-id={card.action_id || action?.id || ''}
      data-status={status || ''}
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-white">
            {agentName} {context === 'approval' || status === 'pending' ? 'wants to' : status === 'watching' ? 'would' : 'chose to'} {label.charAt(0).toLowerCase() + label.slice(1)}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            {level !== null && <LevelPill level={level} size="sm" testId="action-card-level" />}
            {action?.mode && <span>{MODE_LABEL[action.mode] || action.mode}</span>}
            {action?.created_at && <span>{relTime(action.created_at)}</span>}
          </div>
        </div>
        {sm && (
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${sm.tone}`} data-testid="action-card-status">{sm.label}</span>
        )}
        {harmed && (
          <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/50 bg-rose-500/15 px-2 py-0.5 text-[10px] font-medium text-rose-300" data-testid="action-card-harm">
            <Flag className="h-3 w-3" /> Harm flagged
          </span>
        )}
      </header>

      {card.fallback_reason && (
        <p className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200" data-testid="action-card-fallback">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>Asking first because {card.fallback_reason.charAt(0).toLowerCase() + card.fallback_reason.slice(1)}</span>
        </p>
      )}

      <dl className="mt-3 space-y-2">
        {(card.target || action?.target) && <Line label="On">{card.target || action?.target}</Line>}
        <Line label="Why">{card.intent || action?.intent || <span className="text-slate-500">The agent gave no reason.</span>}</Line>
        <Line label="Expects">
          <span data-testid="action-card-prediction">{predictionText(pred)}</span>
          {pred?.note && <span className="block text-xs text-slate-500">{pred.note}</span>}
        </Line>
        <Line label="Limits">
          {!limits || (!limits.decision_key && !(limits.reasons || []).length && limits.ok === undefined) ? (
            <span className="text-slate-500">No hard limits set for this action.</span>
          ) : limits.ok ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-300" data-testid="action-card-limits-ok">
              <CheckCircle2 className="h-3.5 w-3.5" /> Inside every limit
            </span>
          ) : (
            <ul className="space-y-0.5" data-testid="action-card-limits-breach">
              {(limits.reasons?.length ? limits.reasons : ['Outside a hard limit']).map((r, i) => (
                <li key={i} className="flex items-start gap-1.5 text-rose-300">
                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {r}
                </li>
              ))}
            </ul>
          )}
        </Line>
        <Line label="Can undo">
          {reversible === undefined ? <span className="text-slate-500">Not stated</span> : reversible ? (
            <span className="inline-flex items-center gap-1"><Undo2 className="h-3.5 w-3.5 text-emerald-400" /> Yes, it can be reversed</span>
          ) : (
            <span className="inline-flex items-center gap-1 text-amber-200"><AlertTriangle className="h-3.5 w-3.5" /> No, it cannot be undone</span>
          )}
        </Line>
        <Line label="Track record">
          <span data-testid="action-card-record">
            {card.record?.text || (card.record?.scored ? `Held ${card.record.held ?? 0} of ${card.record.scored} times` : 'No track record yet')}
          </span>
        </Line>
        {Object.keys(args).length > 0 && mode !== 'edit' && (
          <Line label="Details">
            <span className="flex flex-wrap gap-1.5">
              {Object.entries(args).slice(0, 8).map(([k, v]) => (
                <span key={k} className="rounded border border-slate-700 bg-slate-900/60 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
                  {k}: {typeof v === 'object' && v !== null ? JSON.stringify(v).slice(0, 40) : fmtNum(v)}
                </span>
              ))}
            </span>
          </Line>
        )}
      </dl>

      {/* what happened afterwards */}
      {action && (outcome || action.outcome_status === 'pending' || action.outcome_status === 'unknown') && (
        <div className="mt-3 rounded-lg border border-slate-700/60 bg-slate-900/40 p-2.5 text-sm" data-testid="action-card-outcome">
          {outcome && outcome.value !== undefined && outcome.value !== null ? (
            <p className="flex flex-wrap items-center gap-1.5">
              <Target className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-slate-300">Actual {outcome.metric ? outcome.metric.replace(/_/g, ' ') + ' ' : ''}{fmtNum(outcome.value)}.</span>
              {score?.within_band === true && <span className="text-emerald-300">Inside the predicted band.</span>}
              {score?.within_band === false && <span className="text-rose-300">Outside the predicted band.</span>}
              {score?.band_ok === false && <span className="text-amber-300">The band was too wide to count.</span>}
              {outcome.source === 'manual' && <span className="text-xs text-slate-500">Entered by a person</span>}
            </p>
          ) : action.outcome_status === 'pending' ? (
            <p className="text-slate-400">Result due {action.outcome_due_at ? relTime(action.outcome_due_at) : 'soon'}.</p>
          ) : (
            <p className="text-amber-200">The result never arrived, so this action counts as unknown.</p>
          )}
        </div>
      )}

      {action?.result_preview && (status === 'executed' || status === 'failed') && (
        <div className={`mt-3 rounded-lg border p-2.5 text-xs ${status === 'failed' ? 'border-rose-500/40 bg-rose-500/5 text-rose-200' : 'border-emerald-500/30 bg-emerald-500/5 text-slate-300'}`} data-testid="action-card-result">
          <p className="mb-1 font-medium text-slate-200">{status === 'failed' ? 'It ran and failed' : 'It ran'}{action.executed_at ? ` ${relTime(action.executed_at)}` : ''}. The tool answered:</p>
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px]">{action.result_preview}</pre>
        </div>
      )}

      {action?.reviewer_answer && (
        <p className="mt-2 text-xs text-slate-400" data-testid="action-card-review-answer">
          Reviewer: {action.reviewer_answer === 'agree' ? 'agreed' : action.reviewer_answer === 'different' ? `did something else${action.reviewer_alternative ? `: "${action.reviewer_alternative}"` : ''}` : 'not sure'}
        </p>
      )}
      {(action?.decided_by_name || action?.decision_note) && (
        <p className="mt-1 text-xs text-slate-400">
          {action.decided_by_name ? `Decided by ${action.decided_by_name}` : 'Decided'}{action.decision_note ? `: "${action.decision_note}"` : ''}
        </p>
      )}
      {harmed && action?.harm_note && <p className="mt-1 text-xs text-rose-300">Harm: {action.harm_note}</p>}

      {/* approval buttons */}
      {context === 'approval' && mode === 'idle' && (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <button type="button" disabled={busy} onClick={() => onApprove?.()} className={`${btn} border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25`} data-testid="action-card-approve">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} Approve
          </button>
          <button
            type="button"
            disabled={busy || !editable}
            title={editable ? undefined : 'This action has nothing that can be changed'}
            onClick={() => { setDrafts(initialDrafts(args)); setMode('edit'); }}
            className={`${btn} border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20`}
            data-testid="action-card-edit"
          >
            <PencilLine className="h-3.5 w-3.5" /> Edit and approve
          </button>
          <button type="button" disabled={busy} onClick={() => setMode('reject')} className={`${btn} border-rose-500/40 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25`} data-testid="action-card-reject">
            <XCircle className="h-3.5 w-3.5" /> Reject
          </button>
        </div>
      )}

      {context === 'approval' && mode === 'edit' && (
        <div className="mt-4 rounded-lg border border-cyan-500/30 bg-slate-900/50 p-3">
          <p className="mb-3 text-xs text-slate-400">Change what the agent will do, then approve. The change counts as a partial agreement on its record.</p>
          <ArgumentForm args={args} drafts={drafts} errors={editErrors} onChange={(k, v) => setDrafts((d) => ({ ...d, [k]: v }))} />
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              disabled={busy || hasEditErrors}
              title={hasEditErrors ? 'Fix the fields marked in red first' : undefined}
              onClick={() => onApprove?.(parsed.value)}
              className={`${btn} border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25`}
              data-testid="action-card-edit-submit"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} Approve with changes
            </button>
            <button type="button" onClick={() => setMode('idle')} className={`${btn} border-slate-600 text-slate-300 hover:bg-slate-700/50`}>
              Cancel
            </button>
          </div>
          {hasEditErrors && <p className="mt-2 text-xs text-rose-300">Fix the fields marked in red first.</p>}
        </div>
      )}

      {context === 'approval' && mode === 'reject' && (
        <div className="mt-4 rounded-lg border border-rose-500/30 bg-slate-900/50 p-3">
          <label htmlFor={`reject-${card.action_id}`} className="text-xs font-medium text-slate-300">Why are you rejecting it?</label>
          <textarea
            id={`reject-${card.action_id}`}
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="The agent is told this, and it is kept on the record"
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-rose-500/60"
            data-testid="action-card-reject-note"
          />
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              disabled={busy || !note.trim()}
              title={!note.trim() ? 'Say why first, so the agent and its record know' : undefined}
              onClick={() => onReject?.(note.trim())}
              className={`${btn} border-rose-500/40 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25`}
              data-testid="action-card-reject-submit"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />} Reject
            </button>
            <button type="button" onClick={() => setMode('idle')} className={`${btn} border-slate-600 text-slate-300 hover:bg-slate-700/50`}>Cancel</button>
          </div>
          {!note.trim() && <p className="mt-1 text-[11px] text-slate-500">A short reason is needed to reject.</p>}
        </div>
      )}

      {/* watching review buttons */}
      {context === 'review' && mode !== 'different' && (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <button type="button" disabled={busy} onClick={() => onReview?.('agree')} className={`${btn} border-emerald-500/40 bg-emerald-500/15 text-emerald-300`} data-testid="autonomy-review-agree">
            <ThumbsUp className="h-3.5 w-3.5" /> Agree <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">A</kbd>
          </button>
          <button type="button" disabled={busy} onClick={() => setMode('different')} className={`${btn} border-amber-500/40 bg-amber-500/10 text-amber-300`} data-testid="autonomy-review-different">
            <RotateCcw className="h-3.5 w-3.5" /> I did something else <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">D</kbd>
          </button>
          <button type="button" disabled={busy} onClick={() => onReview?.('unsure')} className={`${btn} border-slate-600 text-slate-300`} data-testid="autonomy-review-unsure">
            <HelpCircle className="h-3.5 w-3.5" /> Not sure <kbd className="ml-1 rounded bg-slate-900/60 px-1 text-[10px]">N</kbd>
          </button>
        </div>
      )}
      {context === 'review' && mode === 'different' && (
        <div className="mt-4">
          <label className="text-xs font-medium text-slate-300" htmlFor={`alt-${card.action_id}`}>What did you do instead?</label>
          <textarea id={`alt-${card.action_id}`} rows={2} value={alt} onChange={(e) => setAlt(e.target.value)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="autonomy-review-alternative" autoFocus />
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={busy || !alt.trim()} title={!alt.trim() ? 'Say what you did first' : undefined} onClick={() => onReview?.('different', alt.trim())} className={`${btn} border-amber-500/40 bg-amber-500/10 text-amber-300`} data-testid="autonomy-review-different-submit">Save answer</button>
            <button type="button" onClick={() => setMode('idle')} className={`${btn} border-slate-600 text-slate-300`}>Cancel</button>
          </div>
        </div>
      )}

      {/* afterwards */}
      {(allowHarm || allowOutcome) && mode !== 'outcome' && (
        <div className="mt-3 flex flex-wrap gap-2">
          {allowOutcome && (
            <button type="button" onClick={() => setMode('outcome')} className={`${btn} border-slate-600 text-slate-300 hover:bg-slate-700/50`} data-testid="action-card-enter-outcome">
              <Target className="h-3.5 w-3.5" /> Enter outcome
            </button>
          )}
          {allowHarm && (
            <button type="button" onClick={() => setHarmOpen(true)} className={`${btn} border-rose-500/40 text-rose-300 hover:bg-rose-500/10`} data-testid="action-card-flag-harm">
              <Flag className="h-3.5 w-3.5" /> Flag harm
            </button>
          )}
        </div>
      )}
      {mode === 'outcome' && (
        <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <label htmlFor={`outcome-${action?.id}`} className="text-xs font-medium text-slate-300">
            What actually happened{pred?.metric ? ` to ${pred.metric.replace(/_/g, ' ')}` : ''}?
          </label>
          <input id={`outcome-${action?.id}`} value={outcomeValue} onChange={(e) => setOutcomeValue(e.target.value)} placeholder="For example 4.35" className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="action-card-outcome-value" />
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={followBusy || !outcomeValue.trim()} title={!outcomeValue.trim() ? 'Enter the value first' : undefined} onClick={submitOutcome} className={`${btn} border-cyan-500/40 bg-cyan-500/10 text-cyan-300`} data-testid="action-card-outcome-submit">
              {followBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save outcome
            </button>
            <button type="button" onClick={() => setMode('idle')} className={`${btn} border-slate-600 text-slate-300`}>Cancel</button>
          </div>
        </div>
      )}

      {(error || followErr) && <p className="mt-2 text-xs text-rose-300" role="alert" data-testid="action-card-error">{error || followErr}</p>}

      <button type="button" onClick={() => setShowDetails((v) => !v)} className="mt-3 flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300" data-testid="action-card-details-toggle">
        {showDetails ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Details
      </button>
      {showDetails && (
        <div className="mt-2 space-y-1 text-[11px] text-slate-400" data-testid="action-card-details">
          {(card.action_id || action?.id) && <p>Action id <span className="font-mono">{card.action_id || action?.id}</span></p>}
          {card.action_type?.key && <p>Action type <span className="font-mono">{card.action_type.key}</span></p>}
          {action?.tool_name && <p>Tool <span className="font-mono">{action.tool_name}</span></p>}
          {pred?.source && <p>Prediction from {SOURCE_LABEL[pred.source] || pred.source}{pred.source_ref ? ` (${pred.source_ref})` : ''}{pred.horizon_s ? `, checked after ${fmtDuration(pred.horizon_s)}` : ''}</p>}
          {limits?.decision_key && (
            <p>Limits from <Link href={`/decisions/${encodeURIComponent(limits.decision_key)}`} className="text-cyan-300 hover:underline">{limits.decision_key}</Link></p>
          )}
          {action?.execution_id && (
            <p>Run <Link href={`/executions/${action.execution_id}`} className="font-mono text-cyan-300 hover:underline">{action.execution_id.slice(0, 8)}</Link></p>
          )}
          {score && <p>Score <span className="font-mono">{JSON.stringify(score)}</span></p>}
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[10px] text-slate-400">{JSON.stringify(args, null, 2)}</pre>
        </div>
      )}

      <ConfirmModal
        open={harmOpen}
        onClose={() => setHarmOpen(false)}
        onConfirm={submitHarm}
        title="Flag this action as harmful?"
        description="The agent drops to Asks first for this action straight away and its owners are told. This stays on its record."
        confirmLabel="Flag harm"
        loading={followBusy}
        confirmDisabled={!harmNote.trim()}
        confirmTestId="action-card-harm-confirm"
        icon={Flag}
      >
        <label htmlFor={`harm-${action?.id}`} className="text-xs font-medium text-slate-300">What went wrong?</label>
        <textarea id={`harm-${action?.id}`} rows={3} value={harmNote} onChange={(e) => setHarmNote(e.target.value)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="action-card-harm-note" />
      </ConfirmModal>
    </article>
  );
}
