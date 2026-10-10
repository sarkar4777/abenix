'use client';

import Link from 'next/link';
import { ArrowRight, Check, Compass } from 'lucide-react';
import { docHref } from '@/components/layout/PageHeader';
import { tierName, type Problem, type RuleDoc, type Validation, type VersionFull } from '@/lib/decisions';
import { namesText, type SignOffInfo } from './SignOff';

export type GuideStep = 'rules' | 'try' | 'tests' | 'check' | 'signoff' | 'publish';

const STEPS: { id: GuideStep; label: string }[] = [
  { id: 'rules', label: 'Rules' },
  { id: 'try', label: 'Try it' },
  { id: 'tests', label: 'Tests' },
  { id: 'check', label: 'Check' },
  { id: 'signoff', label: 'Sign-off' },
  { id: 'publish', label: 'Publish' },
];

export const DOC = '08-howto/09-decisions';
export const docSection = (id: string) => `${docHref(DOC)}#${id}`;

export interface GuideAction { label: string; onClick?: () => void; href?: string; testId?: string }
export interface Guide { step: GuideStep; done: GuideStep[]; text: string; action?: GuideAction; more?: GuideAction[]; tone?: 'wait' | 'warn' | 'ok' }

export interface GuideInput {
  version: VersionFull;
  doc: RuleDoc | null;
  errors: Problem[];
  testCount: number;
  validation: Validation | null;
  signoff: SignOffInfo | null;
  canAuthor: boolean;
  canPublish: boolean;
  isAdmin: boolean;
  liveVersion: number | null;
  agentHref: string;
  meId?: string | null;
  decisionKey?: string;
  reattest?: { approval_id: string; version: number; from_tier: string; to_tier: string } | null;
}

export interface GuideHandlers {
  openTable: () => void;
  openTry: () => void;
  openTests: () => void;
  showProblem: () => void;
  check: () => void;
  propose: () => void;
  publish: () => void;
  sole: () => void;
  newDraft: () => void;
  openVersion: (n: number) => void;
}

const uptoDone = (step: GuideStep): GuideStep[] => STEPS.slice(0, STEPS.findIndex((s) => s.id === step)).map((s) => s.id);

// what the person should do next on this version, and why, in one sentence
export function nextStep(g: GuideInput, h: GuideHandlers): Guide {
  const { version: v, doc, errors, testCount, validation, signoff } = g;
  const need = signoff?.required ?? 0;
  const approvers = signoff?.eligible_approvers ?? [];
  if (v.state === 'draft') {
    if (!g.canAuthor) return { step: 'rules', done: [], text: 'This is a draft someone is working on. You can read it and use Try it. Changing it needs Author decisions, which an admin can give you.' };
    if (validation?.returned) {
      return { step: 'rules', done: [], tone: 'warn', text: `The reviewer sent it back: ${validation.returned.note || 'no reason given'}. Make the changes, run Check, then propose it again.`, action: { label: 'Check', onClick: h.check, testId: 'guide-action' } };
    }
    if (doc && doc.rules.length === 0) {
      return { step: 'rules', done: [], text: 'Start with the rules. Paste them from Excel with their header row, or add the first rule one condition at a time.', action: { label: 'Paste from Excel', onClick: h.openTable, testId: 'guide-action' } };
    }
    if (errors.length) {
      return { step: 'rules', done: [], tone: 'warn', text: `${errors.length} thing${errors.length === 1 ? '' : 's'} to fix in the rules before they can be checked. The list above says where each one is.`, action: { label: 'Show the first one', onClick: h.showProblem, testId: 'guide-action' } };
    }
    if (testCount === 0) {
      return { step: 'try', done: ['rules'], text: 'Add a golden test so every later change is checked against it. Fill in the facts in Try it, check the answer, then press Keep as test.', action: { label: 'Open Try it', onClick: h.openTry, testId: 'guide-action' } };
    }
    if (!validation || !validation.summary) {
      return { step: 'check', done: ['rules', 'try', 'tests'], text: `Run Check. It runs your ${testCount} golden test${testCount === 1 ? '' : 's'} and looks for gaps and overlaps between rules.`, action: { label: 'Check', onClick: h.check, testId: 'guide-action' } };
    }
    if (!validation.ok) {
      return { step: 'check', done: ['rules', 'try', 'tests'], tone: 'warn', text: `Check found something to fix: ${validation.summary.replace(/\.$/, '')}. Failing golden tests show what was expected and what came out.`, action: { label: 'See the golden tests', onClick: h.openTests, testId: 'guide-action' } };
    }
    const done: GuideStep[] = ['rules', 'try', 'tests', 'check'];
    if (!need) return { step: 'signoff', done, text: `Ready. ${signoff?.policy_text || 'This tier needs no sign-off.'} Propose it and it is approved straight away, then publish it.`, action: { label: 'Propose', onClick: h.propose, testId: 'guide-action' } };
    if (!approvers.length && !signoff?.sole_operator_available) {
      return { step: 'signoff', done, tone: 'warn', text: `Ready, but nobody else in this workspace can approve it, and ${signoff?.policy_text?.replace(/\.$/, '').toLowerCase() || 'this tier needs a second person'}. Invite someone who can approve first.`, action: g.isAdmin ? { label: 'Invite an approver', href: `/settings/team?invite=1&approver=1&from=${encodeURIComponent(g.decisionKey ?? '')}`, testId: 'guide-action' } : undefined };
    }
    const who = approvers.length ? `${namesText(approvers)} can approve it.` : 'You are the only approver, so you sign it yourself with a reason once it is proposed.';
    return { step: 'signoff', done, text: `Ready. Propose it for sign-off. ${signoff?.policy_text || ''} ${who}`.replace(/\s+/g, ' '), action: { label: 'Propose for sign-off', onClick: h.propose, testId: 'guide-action' } };
  }
  if (v.state === 'proposed') {
    const done: GuideStep[] = ['rules', 'try', 'tests', 'check'];
    if (signoff?.sole_operator_available) {
      return { step: 'signoff', done, tone: 'wait', text: 'Nobody else can approve this. Sign it yourself with a written reason, which goes on the audit log, or invite an approver.', action: { label: 'Approve as the only approver', onClick: h.sole, testId: 'guide-action' }, more: g.isAdmin ? [{ label: 'Invite an approver', href: `/settings/team?invite=1&approver=1&from=${encodeURIComponent(g.decisionKey ?? '')}` }] : undefined };
    }
    const approvalsHref = signoff?.approval_id ? `/approvals#${signoff.approval_id}` : '/approvals';
    if (g.meId && approvers.some((a) => String(a.id) === String(g.meId))) {
      return { step: 'signoff', done, tone: 'wait', text: 'You can approve this. Read the rules and the golden tests here, then approve it, send it back with a reason, or deny it on Approvals.', action: { label: 'Approve or send back on Approvals', href: approvalsHref, testId: 'guide-action' } };
    }
    const names = approvers.length ? namesText(approvers) : 'an approver';
    return { step: 'signoff', done, tone: 'wait', text: `Waiting for ${names} to approve. They see it in Needs you and on Approvals, and you are told when it is decided.`, action: { label: 'Open Approvals', href: approvalsHref, testId: 'guide-action' } };
  }
  if (v.state === 'approved') {
    const by = (signoff?.signoffs || []).filter((s) => (s.decision ?? 'approve') === 'approve').map((s) => s.name);
    if (!g.canPublish) return { step: 'publish', done: ['rules', 'try', 'tests', 'check', 'signoff'], tone: 'wait', text: `Approved${by.length ? ` by ${by.join(', ')}` : ''}. Publishing needs publish rights, which you don't have, so ask someone who has it${by.length ? `, such as ${by[0]}` : ''} or an admin. They publish it from this page.` };
    return { step: 'publish', done: ['rules', 'try', 'tests', 'check', 'signoff'], text: `Approved${by.length ? ` by ${by.join(', ')}` : ''}. Publish it to make it the version agents and apps use. You see what it replaces before anything changes.`, action: { label: 'Publish', onClick: h.publish, testId: 'guide-action' } };
  }
  if (v.state === 'rejected') {
    return { step: 'signoff', done: ['rules', 'try', 'tests', 'check'], tone: 'warn', text: g.canAuthor ? 'This version was denied and can no longer change. Start a new draft from it, make the changes, then propose again.' : 'This version was denied and can no longer change. Someone who can author decisions can start a new draft from it.', action: g.canAuthor ? { label: 'New draft from it', onClick: h.newDraft, testId: 'guide-action' } : undefined };
  }
  if (v.state === 'published' && g.reattest && g.reattest.version === v.version) {
    const r = g.reattest;
    return {
      step: 'signoff', done: ['rules', 'try', 'tests', 'check'], tone: 'wait',
      text: `Version ${v.version} keeps answering, but the tier was raised from ${tierName(r.from_tier)} to ${tierName(r.to_tier)}, so it needs a ${tierName(r.to_tier)}-risk review. Someone who can approve signs it in Needs you or on Approvals.`,
      action: { label: 'Open the review', href: `/approvals#${r.approval_id}`, testId: 'guide-action' },
    };
  }
  if (v.state === 'published') {
    return {
      step: 'publish', done: STEPS.map((s) => s.id), tone: 'ok',
      text: `Version ${v.version} is in force. Agents, pipelines and apps ask it for an answer by its key. ${g.canAuthor ? 'To change the rules, start a new draft.' : 'Changing the rules needs Author decisions, which an admin can give you.'}`,
      action: { label: 'Use in an agent', href: g.agentHref, testId: 'guide-action' },
      more: [
        { label: 'From a pipeline', href: docSection('from-a-pipeline') },
        { label: 'From the SDK', href: docSection('from-an-app-with-the-sdk') },
        { label: 'Over REST', href: docSection('over-rest') },
      ],
    };
  }
  return {
    step: 'publish', done: STEPS.map((s) => s.id),
    text: `Version ${v.version} is ${v.state === 'retired' ? 'retired' : 'replaced'} and no longer answers.${g.liveVersion ? ` Version ${g.liveVersion} is the one in force.` : ' Nothing is in force now.'}`,
    action: g.liveVersion ? { label: `Open version ${g.liveVersion}`, onClick: () => h.openVersion(g.liveVersion!), testId: 'guide-action' } : g.canAuthor ? { label: 'New draft from it', onClick: h.newDraft, testId: 'guide-action' } : undefined,
  };
}

function ActionButton({ a, primary }: { a: GuideAction; primary?: boolean }) {
  const cls = primary
    ? 'inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400'
    : 'inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline';
  if (a.href) return <Link href={a.href} className={cls} data-testid={a.testId}>{a.label}{primary && <ArrowRight className="w-3.5 h-3.5" />}</Link>;
  return <button type="button" onClick={a.onClick} className={cls} data-testid={a.testId}>{a.label}{primary && <ArrowRight className="w-3.5 h-3.5" />}</button>;
}

export default function DecisionGuide({ guide }: { guide: Guide }) {
  const tone = guide.tone === 'warn' ? 'border-amber-500/30 bg-amber-500/5' : guide.tone === 'ok' ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-cyan-500/30 bg-cyan-500/5';
  return (
    <section className={`mb-3 rounded-xl border px-3 py-2.5 ${tone}`} aria-label="What to do next" data-testid="decision-guide" data-step={guide.step}>
      <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="Steps">
        {STEPS.map((s, i) => {
          const done = guide.done.includes(s.id);
          // a finished step is ticked, the last one too once it is in force
          const here = guide.step === s.id && !done;
          return (
            <li key={s.id} className="inline-flex items-center gap-1">
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${here ? 'border-cyan-400 bg-cyan-500/15 text-white font-medium' : done ? 'border-emerald-500/40 text-emerald-300' : 'border-slate-700 text-slate-500'}`}
                aria-current={here ? 'step' : undefined}
                data-testid={`guide-step-${s.id}`}
                data-state={here ? 'current' : done ? 'done' : 'todo'}
              >
                {done ? <Check className="w-3 h-3" /> : <span className="tabular-nums">{i + 1}</span>} {s.label}
              </span>
              {i < STEPS.length - 1 && <span className="text-slate-600" aria-hidden="true">›</span>}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Compass className="w-4 h-4 text-cyan-300 shrink-0" />
        <p className="flex-1 min-w-[220px] text-sm text-slate-200" data-testid="guide-text">{guide.text}</p>
        {guide.action && <ActionButton a={guide.action} primary />}
        {guide.more?.map((m) => <ActionButton key={m.label} a={m} />)}
      </div>
    </section>
  );
}
