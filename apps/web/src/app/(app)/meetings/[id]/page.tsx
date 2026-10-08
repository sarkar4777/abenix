'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertCircle, Bot, CheckCircle2, FlaskConical, Loader2, LogOut, MessageSquare,
  Play, Plus, Radio, Send, Shield, Square, Trash2, User, Users, Video, X, XCircle,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import MeetingReadiness, { useMeetingReadiness } from '@/components/meetings/MeetingReadiness';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps, { type NextStep } from '@/components/shared/NextSteps';
import { withPending } from '@/lib/nav-walk';
import {
  ENDED, joinBlockReason, rehearseBlockReason, startBlockReason, summaryState,
} from '@/components/meetings/meeting-logic';

interface Line { participant: string; text: string; ts_ms: number; bot?: boolean; via?: string; addressed?: boolean; latency_ms?: number | null }
interface Decision { kind: string; summary: string; ts_ms: number; detail?: any }
interface Deferral { id: string; question: string; context: string | null; answer: string | null; status: string; created_at: string | null; answered_at?: string | null }

interface Meeting {
  id: string;
  title: string;
  provider: string;
  room: string;
  join_url: string | null;
  status: string;
  scope_allow: string[];
  scope_defer: string[];
  persona_scopes: string[];
  display_name: string;
  transcript_count: number;
  decision_count: number;
  deferral_count: number;
  summary: string | null;
  bot_status?: string | null;
  finalized?: boolean;
  ended_at?: string | null;
  transcript?: Line[];
  decisions?: Decision[];
  deferrals?: Deferral[];
}

interface Participants { available: boolean; participants: { identity: string; name: string; is_bot: boolean; is_you: boolean }[]; message: string | null }

type Confirm = null | 'delete' | 'kick' | 'end';

const KIND_STYLE: Record<string, string> = {
  answer: 'bg-emerald-500/10 text-emerald-300',
  defer: 'bg-amber-500/10 text-amber-300',
  decline: 'bg-slate-500/10 text-slate-300',
  leave: 'bg-purple-500/10 text-purple-300',
  error: 'bg-red-500/10 text-red-300',
  notice: 'bg-sky-500/10 text-sky-300',
  cite: 'bg-cyan-500/10 text-cyan-300',
};

export default function MeetingDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id as string;
  usePageTitle('Meeting');
  const router = useRouter();
  const { data: readiness } = useMeetingReadiness();
  const [m, setM] = useState<Meeting | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editingScope, setEditingScope] = useState(false);
  const [savingScope, setSavingScope] = useState(false);
  const [allowInput, setAllowInput] = useState<string[]>([]);
  const [deferInput, setDeferInput] = useState<string[]>([]);
  const [personaInput, setPersonaInput] = useState<string[]>(['self']);
  const [newAllow, setNewAllow] = useState('');
  const [newDefer, setNewDefer] = useState('');
  const [newPersona, setNewPersona] = useState('');
  const [knownScopes, setKnownScopes] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [deferralAnswers, setDeferralAnswers] = useState<Record<string, string>>({});
  const [showSteps, setShowSteps] = useState(false);
  const [people, setPeople] = useState<Participants | null>(null);
  const [connect, setConnect] = useState<{ url: string; token: string; identity: string } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [next, setNext] = useState<null | 'created' | 'scope'>(null);
  const editingRef = useRef(false);
  editingRef.current = editingScope;

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await apiFetch<Meeting>(`/api/meetings/${id}`, { silent: true });
    if (r.error) {
      if (!quiet) setLoadErr(r.errorDetail?.code === 404 ? 'This meeting does not exist or is not yours.' : `Could not load the meeting. ${r.error}`);
    } else {
      setLoadErr(null);
      setM(r.data);
      if (r.data && !editingRef.current) {
        setAllowInput(r.data.scope_allow || []);
        setDeferInput(r.data.scope_defer || []);
        setPersonaInput(r.data.persona_scopes?.length ? r.data.persona_scopes : ['self']);
      }
    }
    if (!quiet) setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // arriving straight from New meeting
  useEffect(() => {
    try {
      if (sessionStorage.getItem('meeting-created') !== id) return;
      sessionStorage.removeItem('meeting-created');
      setNext('created');
    } catch { /* storage blocked */ }
  }, [id]);

  useEffect(() => {
    if (!editingScope) return;
    apiFetch<string[]>('/api/persona/scopes', { silent: true }).then(r => setKnownScopes(r.data || []));
  }, [editingScope]);

  const isLive = m?.status === 'live';
  const summaryWait = m ? summaryState(m) === 'writing' : false;

  // the stream needs a header token, so the live view polls instead
  useEffect(() => {
    if (!isLive && !summaryWait) return;
    const t = setInterval(() => load(true), 2000);
    return () => clearInterval(t);
  }, [isLive, summaryWait, load]);

  useEffect(() => {
    if (!isLive || m?.provider !== 'livekit') { setPeople(null); return; }
    const tick = () => apiFetch<Participants>(`/api/meetings/${id}/participants`, { silent: true }).then(r => r.data && setPeople(r.data));
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, [isLive, m?.provider, id]);

  const act = async (key: string, fn: () => Promise<unknown>, fail: string) => {
    setBusy(key);
    setErr(null);
    try {
      await fn();
      await load(true);
    } catch (e: any) {
      setErr(`${fail} ${e?.message || ''}`.trim());
    }
    setBusy(null);
  };

  const saveScope = async () => {
    setSavingScope(true);
    setErr(null);
    try {
      const persona = withPending(personaInput, newPersona);
      await apiFetch(`/api/meetings/${id}/authorize`, {
        method: 'PUT',
        // text typed but not yet added still counts
        body: JSON.stringify({
          scope_allow: withPending(allowInput, newAllow),
          scope_defer: withPending(deferInput, newDefer),
          persona_scopes: persona.length ? persona : ['self'],
        }),
      });
      setEditingScope(false);
      setNewAllow('');
      setNewDefer('');
      setNewPersona('');
      await load(true);
      setNext('scope');
    } catch (e: any) {
      setErr(`The scope was not saved. ${e?.message || ''}`.trim());
    }
    setSavingScope(false);
  };

  const startBot = () => act('start', () => apiFetch(`/api/meetings/${id}/start`, { method: 'POST', body: '{}' }), 'The bot could not start.');
  const restartBot = () => act('restart', () => apiFetch(`/api/meetings/${id}/redispatch`, { method: 'POST', body: '{}' }), 'The bot could not be restarted.');

  const runConfirmed = async () => {
    const which = confirm;
    if (which === 'delete') {
      setBusy('delete');
      try {
        await apiFetch(`/api/meetings/${id}`, { method: 'DELETE' });
        router.push('/meetings');
        return;
      } catch (e: any) {
        setErr(`Could not delete the meeting. ${e?.message || ''}`.trim());
      }
      setBusy(null);
    } else if (which === 'kick') {
      await act('kick', () => apiFetch(`/api/meetings/${id}/kill`, { method: 'POST', body: '{}' }), 'Could not remove the bot.');
    } else if (which === 'end') {
      await act('end', () => apiFetch(`/api/meetings/${id}/end`, { method: 'POST', body: '{}' }), 'Could not end the meeting.');
    }
    setConfirm(null);
  };

  const openOtherClient = async () => {
    if (!m) return;
    setErr(null);
    const r = await apiFetch<any>(`/api/meetings/livekit-token?room=${encodeURIComponent(m.room)}`, { silent: true });
    if (r.error) {
      setErr(r.error);
      return;
    }
    setConnect({ url: r.data?.browser_url || r.data?.url || '', token: r.data?.token || '', identity: r.data?.identity || '' });
  };

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 1200);
    } catch {
      setErr('Copy failed. Select the text and copy it by hand.');
    }
  };

  const answerDeferral = async (deferralId: string) => {
    const answer = deferralAnswers[deferralId]?.trim();
    if (!answer) return;
    await act(`answer-${deferralId}`, async () => {
      await apiFetch(`/api/meetings/${id}/deferrals/${deferralId}/answer`, { method: 'POST', body: JSON.stringify({ answer }) });
      setDeferralAnswers(prev => ({ ...prev, [deferralId]: '' }));
    }, 'Your answer was not delivered.');
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-cyan-500" /></div>;
  }

  if (!m) {
    return (
      <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-200 space-y-2 max-w-xl">
        <p>{loadErr || 'Meeting not found.'}</p>
        <div className="flex gap-3 text-xs">
          <button onClick={() => load()} className="underline">Try again</button>
          <Link href="/meetings" className="underline">All meetings</Link>
        </div>
      </div>
    );
  }

  const isDone = ENDED.includes(m.status);
  const startBlock = startBlockReason(m, readiness);
  const joinBlock = joinBlockReason(m, readiness);
  const rehearseBlock = rehearseBlockReason(m);
  const canStart = ['authorized', 'scheduled'].includes(m.status);
  const pending = (m.deferrals || []).filter(d => d.status === 'pending');
  const resolved = (m.deferrals || []).filter(d => d.status !== 'pending');
  const decisions = (m.decisions || []).filter(d => showSteps || d.kind !== 'step');
  const sum = summaryState(m);
  const joinedAt = [...(m.decisions || [])].reverse().find(d => /^Bot joined/.test(d.summary))?.ts_ms || 0;
  // give the room list a moment to catch up after a join
  const botGone = isLive && !!joinedAt && Date.now() - joinedAt > 15_000 && !!people?.available && !people.participants.some(p => p.is_bot);
  const btn = 'flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border disabled:opacity-50 disabled:cursor-not-allowed';
  const createdSteps: NextStep[] = [
    { id: 'scope', label: 'Set the topics', hint: 'Say what the bot may answer and what it hands back.', icon: Shield, onClick: () => { setNext(null); setEditingScope(true); } },
    { id: 'persona', label: 'Add persona notes', hint: 'Give the bot facts it can quote in meetings.', icon: User, href: '/persona' },
    { id: 'rehearse', label: 'Rehearse the bot', hint: 'Type questions at it before the real call.', icon: FlaskConical, href: `/meetings/${id}/rehearse` },
  ];
  const scopeSteps: NextStep[] = [
    ...(rehearseBlock ? [] : [{ id: 'rehearse', label: 'Rehearse the bot', hint: 'Check it answers inside the new scope.', icon: FlaskConical, href: `/meetings/${id}/rehearse` }]),
    ...(canStart && !startBlock ? [{ id: 'start', label: 'Start the bot', hint: 'Send it into the room now.', icon: Play, onClick: () => { setNext(null); startBot(); } }] : []),
    ...(joinBlock ? [] : [{ id: 'join', label: 'Join the room', hint: 'Talk to the bot yourself in this browser.', icon: Video, href: `/meetings/${id}/join` }]),
  ];

  return (
    <div className="space-y-6 max-w-5xl">
      <PageHeader
        title={m.title}
        titleTestId="meeting-title"
        purpose="Set what the bot may say in this meeting, try it out, then send it into the room and follow along. For the meeting owner."
        icon={Video}
        storageKey="meeting-detail"
        docSlug="08-howto/15-meetings"
        back={{ href: '/meetings', label: 'Back to meetings' }}
        meta={
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="uppercase">{m.provider}</span>
            <span>·</span>
            <span className="font-mono break-all">{m.room}</span>
            <span>·</span>
            <span data-testid="meeting-status" className={`px-1.5 py-0.5 rounded ${
              m.status === 'live' ? 'bg-emerald-500/10 text-emerald-300'
                : m.status === 'done' ? 'bg-purple-500/10 text-purple-300'
                  : m.status === 'killed' || m.status === 'failed' ? 'bg-red-500/10 text-red-300'
                    : 'bg-slate-500/10 text-slate-300'
            }`}>{m.status}</span>
          </div>
        }
        primaryAction={
          canStart
            ? {
                label: busy === 'start' ? 'Starting…' : 'Start bot',
                icon: Play,
                onClick: startBot,
                disabled: busy === 'start' || !!startBlock,
                title: startBlock || 'Send the bot into the room',
                testId: 'start-bot',
              }
            : isLive || isDone
              ? {
                  label: busy === 'restart' ? 'Restarting…' : isLive ? 'Restart bot' : 'Bring the bot back',
                  icon: Play,
                  onClick: restartBot,
                  disabled: busy === 'restart' || !!startBlock,
                  title: startBlock || (isLive ? 'Start a fresh bot in the room. The transcript is kept.' : 'Send the bot back in. The transcript is kept.'),
                  testId: 'redispatch-bot',
                }
              : undefined
        }
        extraActions={
          <div className="flex min-w-0 flex-wrap gap-2">
            <Link
              href={rehearseBlock ? '#' : `/meetings/${id}/rehearse`}
              aria-disabled={!!rehearseBlock}
              title={rehearseBlock || 'Try the bot with typed turns. No room, no voice credits.'}
              onClick={e => rehearseBlock && e.preventDefault()}
              data-testid="rehearse-meeting"
              className={`${btn} border-violet-500/40 bg-violet-600/20 text-violet-100 hover:bg-violet-600/30 ${rehearseBlock ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <FlaskConical className="w-3 h-3" /> Rehearse
            </Link>
            <Link
              href={joinBlock ? '#' : `/meetings/${id}/join`}
              aria-disabled={!!joinBlock}
              title={joinBlock || 'Join the room yourself, in this browser'}
              onClick={e => joinBlock && e.preventDefault()}
              data-testid="join-meeting"
              className={`${btn} border-cyan-500/40 text-cyan-100 hover:bg-cyan-600/20 ${joinBlock ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <Video className="w-3 h-3" /> Join the room
            </Link>
            {isLive && (
              <>
                <button onClick={() => setConfirm('end')} data-testid="end-meeting" className={`${btn} bg-purple-600/20 border-purple-500/40 text-purple-100 hover:bg-purple-600/30`}>
                  <Square className="w-3 h-3" /> End meeting
                </button>
                <button onClick={() => setConfirm('kick')} data-testid="kick-bot" className={`${btn} bg-red-600/20 border-red-500/40 text-red-200 hover:bg-red-600/30`}>
                  <LogOut className="w-3 h-3" /> Remove bot now
                </button>
              </>
            )}
            <button
              onClick={() => setConfirm('delete')}
              disabled={isLive}
              title={isLive ? 'End the meeting first' : 'Delete this meeting'}
              data-testid="delete-meeting"
              className={`${btn} border-red-500/30 text-red-300 hover:bg-red-500/10`}
            >
              <Trash2 className="w-3 h-3" /> Delete
            </button>
          </div>
        }
        steps={[
          { title: 'Set the scope', body: 'Pick the topics the bot may answer and the ones it hands back to you.' },
          { title: 'Rehearse', body: 'Type questions at it first to see how it answers. Nothing is said in a real room.' },
          { title: 'Start the bot', body: 'It joins the room. Join yourself to talk to it, or let it run.' },
          { title: 'Answer hand-backs', body: 'Questions outside its scope show up here. Your reply is said to the room.' },
        ]}
      >
        {canStart && startBlock && <p className="text-xs text-amber-300" data-testid="start-blocked">{startBlock}</p>}
      </PageHeader>

      {next && (
        <NextSteps
          title={next === 'created' ? 'Meeting created. What next?' : 'Scope saved. What next?'}
          testId="meeting-next-steps"
          onDismiss={() => setNext(null)}
          steps={next === 'created' ? createdSteps : scopeSteps}
        />
      )}

      <MeetingReadiness />

      {err && (
        <div role="alert" data-testid="meeting-error" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-start justify-between gap-2">
          <span className="break-words min-w-0">{err}</span>
          <button onClick={() => setErr(null)} aria-label="Dismiss"><X className="w-3 h-3" /></button>
        </div>
      )}

      {isLive && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-emerald-100 space-y-2" data-testid="live-panel">
          <p>
            The bot is live. To talk to it, use <strong>Join the room</strong> and speak, or type in the room chat. Questions it
            hands back to you appear here.
          </p>
          {people && (
            <div data-testid="room-participants">
              <p className="text-emerald-200/80 flex items-center gap-1"><Users className="w-3 h-3" /> In the room</p>
              {people.available ? (
                people.participants.length ? (
                  <ul className="flex flex-wrap gap-1.5 mt-1">
                    {people.participants.map(p => (
                      <li key={p.identity} data-testid="room-participant" data-bot={p.is_bot ? 'true' : 'false'} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-900/60 border border-slate-700">
                        {p.is_bot ? <Bot className="w-3 h-3 text-cyan-300" /> : <User className="w-3 h-3 text-slate-400" />}
                        {p.is_you ? 'You' : p.name}
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-emerald-200/70 mt-1">Nobody is in the room yet, not even the bot.</p>
              ) : <p className="text-amber-200 mt-1">{people.message}</p>}
            </div>
          )}
          {(m.decisions || []).length === 0 && <p className="text-amber-200">The bot is starting. If nothing shows within about 15 seconds, use Restart bot.</p>}
          {botGone && (
            <div className="flex flex-wrap items-center gap-2 text-amber-100 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5" role="alert" data-testid="bot-gone">
              <span>The bot joined but is no longer in the room. Its server may have restarted. The transcript so far is kept.</span>
              <button onClick={restartBot} disabled={busy === 'restart'} className="underline disabled:opacity-50">Restart bot</button>
            </div>
          )}
        </div>
      )}

      {connect && (
        <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 space-y-2" data-testid="connect-panel">
          <div className="flex items-center justify-between">
            <h3 className="text-sm text-white">Join from another LiveKit app</h3>
            <button onClick={() => setConnect(null)} className="text-xs text-slate-500 hover:text-white">Close</button>
          </div>
          <CopyRow label="Server URL" value={connect.url} copied={copied === 'url'} onCopy={() => copy(connect.url, 'url')} />
          <CopyRow label="Token" value={connect.token} mono truncate copied={copied === 'token'} onCopy={() => copy(connect.token, 'token')} />
          <CopyRow label="Joining as" value={connect.identity} copied={copied === 'identity'} onCopy={() => copy(connect.identity, 'identity')} />
          <p className="text-[11px] text-slate-500">The token works for one hour.</p>
        </div>
      )}

      <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
        <div className="flex items-center justify-between mb-2 gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Shield className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-medium text-white">Bot scope</h2>
            {(m.scope_allow || []).length > 0 ? (
              <span data-testid="scope-badge" data-set="true" className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">topics set</span>
            ) : (
              <span data-testid="scope-badge" data-set="false" className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">no topics yet</span>
            )}
          </div>
          {!isLive && !isDone && (
            <button onClick={() => setEditingScope(v => !v)} data-testid="edit-scope" className="text-xs text-cyan-400 hover:underline">
              {editingScope ? 'Cancel' : 'Edit'}
            </button>
          )}
          {(isLive || isDone) && <span className="text-[10px] text-slate-500">{isLive ? 'Locked while the bot is live' : 'Locked after the meeting'}</span>}
        </div>
        <p className="text-[11px] text-slate-500 mb-3">
          The bot answers only on these topics, hands the second list and any commitment back to you, and politely declines
          everything else.
        </p>

        {!editingScope ? (
          <div className="grid md:grid-cols-3 gap-3 text-xs">
            <ScopeList label="Answers on" items={m.scope_allow} empty="Nothing yet. Add a topic to start the bot." tone="emerald" />
            <ScopeList label="Always hands back" items={m.scope_defer} empty="Only commitments, pricing and approvals" tone="amber" />
            <ScopeList label="Persona knowledge it may use" items={m.persona_scopes?.length ? m.persona_scopes : ['self']} empty="" tone="cyan" />
          </div>
        ) : (
          <div className="space-y-3">
            <ChipEditor label="Answers on" items={allowInput} setItems={setAllowInput} placeholder="e.g. project roadmap, sprint goals" newValue={newAllow} setNewValue={setNewAllow} color="emerald" testId="scope-allow" />
            <ChipEditor label="Always hands back" items={deferInput} setItems={setDeferInput} placeholder="e.g. pricing, contract value, deadlines" newValue={newDefer} setNewValue={setNewDefer} color="amber" testId="scope-defer" />
            <ChipEditor
              label="Persona knowledge it may use"
              items={personaInput}
              setItems={setPersonaInput}
              placeholder="self, client:acme, project:q2-launch"
              newValue={newPersona}
              setNewValue={setNewPersona}
              color="cyan"
              suggestions={knownScopes}
              hint="Pick one of your persona scopes or type a new one. Add notes to a scope under Persona."
              testId="scope-persona"
            />
            {withPending(allowInput, newAllow).length === 0 && (
              <p className="text-[11px] text-amber-300">With no topics the bot declines every question, and it cannot be started.</p>
            )}
            <button onClick={saveScope} disabled={savingScope} data-testid="save-scope" className="px-3 py-1.5 text-xs rounded bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50">
              {savingScope ? 'Saving…' : 'Save scope'}
            </button>
          </div>
        )}
      </div>

      {pending.length > 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 space-y-3" data-testid="pending-deferrals">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-medium text-amber-200">The bot is waiting on you</h2>
          </div>
          {pending.map(d => (
            <div key={d.id} className="rounded border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
              <p className="text-sm text-white break-words">{d.question}</p>
              {d.context && <p className="text-xs text-amber-200/70">{d.context}</p>}
              <div className="flex gap-2">
                <input
                  value={deferralAnswers[d.id] || ''}
                  onChange={e => setDeferralAnswers(prev => ({ ...prev, [d.id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && answerDeferral(d.id)}
                  aria-label="Your answer"
                  placeholder="Your answer. The bot says it to the room."
                  className="flex-1 min-w-0 px-3 py-1.5 bg-slate-900/70 border border-slate-700/50 rounded text-xs text-white focus:outline-none focus:border-amber-500/50"
                />
                <button
                  onClick={() => answerDeferral(d.id)}
                  disabled={!(deferralAnswers[d.id] || '').trim() || busy === `answer-${d.id}`}
                  title={!(deferralAnswers[d.id] || '').trim() ? 'Type an answer first' : undefined}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-amber-600/30 border border-amber-500/50 text-amber-100 hover:bg-amber-600/50 disabled:opacity-50"
                >
                  <Send className="w-3 h-3" /> Send
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {resolved.length > 0 && (
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-medium text-white">Questions handed back to you</h2>
            <span className="text-xs text-slate-500">{resolved.length}</span>
          </div>
          <div className="divide-y divide-slate-800/50">
            {resolved.map(d => (
              <div key={d.id} className="py-2 text-xs space-y-0.5" data-testid="resolved-deferral">
                <p className="text-slate-300 break-words"><span className="text-slate-500">Q:</span> {d.question}</p>
                {d.answer && <p className="text-slate-200 break-words"><span className="text-slate-500">A:</span> {d.answer}</p>}
                <p className="text-[10px] text-slate-500">
                  {d.status === 'timed_out' ? 'no answer in time, the bot said it would follow up' : d.status}
                  {d.answered_at && <> · {new Date(d.answered_at).toLocaleString()}</>}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {(isLive || isDone) && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 min-w-0">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-medium text-white">Transcript</h2>
              {isLive && <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />}
            </div>
            <div className="space-y-1.5 max-h-96 overflow-y-auto" data-testid="meeting-transcript">
              {(m.transcript || []).map((t, i) => (
                <div key={i} className="text-xs break-words" data-testid={t.bot ? 'transcript-bot-line' : 'transcript-line'}>
                  <span className={`font-mono ${t.bot ? 'text-cyan-300' : 'text-slate-500'}`}>{t.participant || 'unknown'}:</span>{' '}
                  <span className="text-slate-300">{t.text}</span>
                  {t.via === 'chat' && <span className="ml-1 text-[9px] px-1 rounded bg-slate-700/50 text-slate-300">chat</span>}
                  {t.addressed && !t.bot && <span className="ml-1 text-[9px] px-1 rounded bg-amber-500/10 text-amber-300">to the bot</span>}
                  {typeof t.latency_ms === 'number' && (
                    <span className="ml-1 text-[9px] px-1 rounded bg-cyan-500/10 text-cyan-300">replied in {(t.latency_ms / 1000).toFixed(1)} s</span>
                  )}
                </div>
              ))}
              {(m.transcript || []).length === 0 && (
                <p className="text-xs text-slate-500">{isLive ? 'Nothing heard yet. Speak or type in the room.' : 'Nothing was said while the bot was in the room.'}</p>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 min-w-0">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <CheckCircle2 className="w-4 h-4 text-purple-400" />
              <h2 className="text-sm font-medium text-white">What the bot did</h2>
              <label className="ml-auto flex items-center gap-1 text-[11px] text-slate-500">
                <input type="checkbox" checked={showSteps} onChange={e => setShowSteps(e.target.checked)} /> every step
              </label>
            </div>
            <div className="space-y-1.5 max-h-96 overflow-y-auto" data-testid="meeting-decisions">
              {decisions.map((d, i) => (
                <div key={i} className="text-xs break-words" data-testid="meeting-decision" data-kind={d.kind}>
                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded mr-2 ${KIND_STYLE[d.kind] || 'bg-slate-500/10 text-slate-400'}`}>{d.kind}</span>
                  <span className="text-slate-300">{d.summary}</span>
                  {d.kind === 'cite' && (d.detail?.citations || []).map((c: any, j: number) => (
                    <p key={j} className="pl-6 text-[11px] text-cyan-200/80">[{j + 1}] {c.title}</p>
                  ))}
                </div>
              ))}
              {decisions.length === 0 && <p className="text-xs text-slate-500">Nothing yet.</p>}
            </div>
          </div>
        </div>
      )}

      {sum && (
        <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-4" data-testid="meeting-summary" data-state={sum}>
          <h2 className="text-sm font-medium text-purple-200 mb-2">Meeting summary</h2>
          {sum === 'summary' && <p className="text-sm text-slate-200 whitespace-pre-wrap break-words">{m.summary}</p>}
          {sum === 'writing' && <p className="text-sm text-slate-300 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> The bot is leaving and writing its summary…</p>}
          {sum === 'none' && <p className="text-sm text-slate-400">The bot left without writing a summary. The transcript above is saved.</p>}
        </div>
      )}

      {m.provider === 'livekit' && !joinBlock && (
        <button onClick={openOtherClient} className="text-[11px] text-slate-500 hover:text-slate-300 underline" data-testid="connect-from-browser">
          Join from another LiveKit app instead
        </button>
      )}

      <ConfirmModal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        onConfirm={runConfirmed}
        loading={!!busy}
        variant={confirm === 'delete' || confirm === 'kick' ? 'danger' : 'warning'}
        icon={confirm === 'delete' ? Trash2 : confirm === 'kick' ? XCircle : Square}
        title={confirm === 'delete' ? 'Delete this meeting?' : confirm === 'kick' ? 'Remove the bot now?' : 'End the meeting?'}
        description={
          confirm === 'delete'
            ? 'The meeting, its transcript and the questions handed back to you are deleted. This cannot be undone.'
            : confirm === 'kick'
              ? 'The bot leaves at once without a summary. The transcript so far is kept.'
              : 'The bot says goodbye, writes a summary and leaves. The transcript and summary are saved here.'
        }
        confirmLabel={confirm === 'delete' ? 'Delete' : confirm === 'kick' ? 'Remove bot' : 'End meeting'}
        confirmTestId="confirm-action"
      />
    </div>
  );
}

function ScopeList({ label, items, empty, tone }: { label: string; items: string[]; empty: string; tone: 'emerald' | 'amber' | 'cyan' }) {
  const cls = { emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20', amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20', cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20' }[tone];
  return (
    <div className="min-w-0">
      <p className="text-slate-500 mb-1">{label}</p>
      <div className="flex flex-wrap gap-1">
        {(items || []).map(t => <span key={t} className={`px-1.5 py-0.5 rounded border break-all ${cls}`}>{t}</span>)}
        {(items || []).length === 0 && <span className="text-slate-600">{empty}</span>}
      </div>
    </div>
  );
}

function CopyRow({ label, value, mono, truncate, copied, onCopy }: { label: string; value: string; mono?: boolean; truncate?: boolean; copied?: boolean; onCopy: () => void }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-[11px] text-slate-500 w-20 shrink-0">{label}</span>
      <code className={`flex-1 min-w-0 px-2 py-1 rounded bg-slate-900/70 border border-slate-700/50 text-xs ${mono ? 'font-mono' : ''} ${truncate ? 'truncate' : 'break-all'} text-slate-200`}>{value}</code>
      <button onClick={onCopy} className="px-2 py-1 text-[11px] rounded border border-slate-700/50 text-slate-300 hover:bg-slate-800/70 shrink-0">{copied ? 'Copied' : 'Copy'}</button>
    </div>
  );
}

function ChipEditor({
  label, items, setItems, placeholder, newValue, setNewValue, color, suggestions, hint, testId,
}: {
  label: string;
  items: string[];
  setItems: (v: string[]) => void;
  placeholder: string;
  newValue: string;
  setNewValue: (v: string) => void;
  color: 'emerald' | 'amber' | 'cyan';
  suggestions?: string[];
  hint?: string;
  testId?: string;
}) {
  const ring = {
    emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
  }[color];
  const add = () => {
    const v = newValue.trim();
    if (!v) return;
    if (!items.includes(v)) setItems([...items, v]);
    setNewValue('');
  };
  const offered = (suggestions || []).filter(s => !items.includes(s));
  const listId = suggestions ? `chip-suggest-${label.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}` : undefined;
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-slate-400">{label}</p>
      <div className="flex flex-wrap gap-1">
        {items.map(t => (
          <span key={t} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs border break-all ${ring}`}>
            {t}
            <button onClick={() => setItems(items.filter(x => x !== t))} aria-label={`Remove ${t}`}><X className="w-3 h-3" /></button>
          </span>
        ))}
      </div>
      {offered.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[10px] text-slate-500">Your scopes:</span>
          {offered.map(s => (
            <button key={s} onClick={() => setItems([...items, s])} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] border border-dashed border-slate-700 text-slate-400 hover:text-white break-all">
              <Plus className="w-3 h-3 shrink-0" />{s}
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-1">
        <input
          value={newValue}
          onChange={e => setNewValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), add())}
          placeholder={placeholder}
          aria-label={label}
          data-testid={testId}
          list={listId}
          maxLength={120}
          className="flex-1 min-w-0 px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white placeholder-slate-500"
        />
        {listId && <datalist id={listId}>{offered.map(s => <option key={s} value={s} />)}</datalist>}
        <button onClick={add} disabled={!newValue.trim()} aria-label={`Add to ${label}`} title={!newValue.trim() ? 'Type a topic first' : undefined} className="px-2 py-1 text-xs rounded border border-slate-700/50 text-slate-300 hover:bg-slate-800/70 disabled:opacity-40">
          <Plus className="w-3 h-3" />
        </button>
      </div>
      {hint && <p className="text-[10px] text-slate-500">{hint}</p>}
    </div>
  );
}
