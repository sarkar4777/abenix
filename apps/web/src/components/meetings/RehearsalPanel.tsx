'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle, BookOpen, Bot, CheckCircle2, Clock, FlaskConical, Hand, Loader2,
  Mic, MicOff, RotateCcw, Send, ShieldCheck, ShieldX, Square, User,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

export interface RehearsalMeeting {
  id: string;
  title: string;
  status: string;
  display_name: string;
  scope_allow: string[];
  scope_defer: string[];
  persona_scopes: string[];
}

interface Line {
  participant: string;
  text: string;
  ts_ms: number;
  via?: string;
  bot?: boolean;
  addressed?: boolean;
  latency_ms?: number | null;
}

interface Decision {
  kind: string;
  summary: string;
  ts_ms: number;
  detail?: Record<string, any>;
}

interface Deferral {
  id: string;
  question: string;
  context: string | null;
  answer: string | null;
  status: string;
  created_at_ms?: number;
}

interface Rehearsal {
  active: boolean;
  available?: boolean;
  rehearsal_id?: string;
  status?: 'starting' | 'live' | 'ending' | 'closed' | string;
  transcript?: Line[];
  decisions?: Decision[];
  deferrals?: Deferral[];
  queued_turns?: number;
}

type Item =
  | { type: 'line'; ts: number; line: Line }
  | { type: 'decision'; ts: number; d: Decision }
  | { type: 'deferral'; ts: number; f: Deferral };

const HOLD_SECONDS = 30;

function fmtMs(ms: number) {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

// the browser's own dictation, so speaking a turn costs nothing
function speechCtor(): any {
  if (typeof window === 'undefined') return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

export default function RehearsalPanel({ meeting }: { meeting: RehearsalMeeting }) {
  const [state, setState] = useState<Rehearsal | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [speaker, setSpeaker] = useState('Dana (client)');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [showSteps, setShowSteps] = useState(false);
  const [listening, setListening] = useState(false);
  const [now, setNow] = useState(Date.now());
  const recRef = useRef<any>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    const r = await apiFetch<Rehearsal>(`/api/meetings/${meeting.id}/rehearsal`, { silent: true });
    if (r.error) {
      setLoadErr(`Could not load the rehearsal. ${r.error}`);
      return;
    }
    setLoadErr(null);
    setState(r.data);
  }, [meeting.id]);

  useEffect(() => { load(); }, [load]);

  const running = !!state?.active && ['starting', 'live', 'ending'].includes(state.status || '');
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => { load(); setNow(Date.now()); }, 1200);
    return () => clearInterval(t);
  }, [running, load]);

  const items = useMemo<Item[]>(() => {
    if (!state?.active) return [];
    const out: Item[] = [];
    for (const line of state.transcript || []) out.push({ type: 'line', ts: line.ts_ms, line });
    for (const d of state.decisions || []) {
      if (d.kind === 'step' && !showSteps) continue;
      // the bot line and the hand-back card already show these
      if (/^Bot spoke:|^Chat message:|^Deferred to human:/.test(d.summary)) continue;
      out.push({ type: 'decision', ts: d.ts_ms, d });
    }
    for (const f of state.deferrals || []) out.push({ type: 'deferral', ts: f.created_at_ms || 0, f });
    return out.sort((a, b) => a.ts - b.ts);
  }, [state, showSteps]);

  // follow new lines inside the transcript box, never scroll the page itself
  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length]);

  const stats = useMemo(() => {
    const ds = state?.decisions || [];
    const lat = (state?.transcript || []).filter(l => l.bot && typeof l.latency_ms === 'number').map(l => l.latency_ms as number);
    return {
      turns: (state?.transcript || []).filter(l => !l.bot).length,
      answered: ds.filter(d => d.detail?.tool === 'scope_gate' && d.kind === 'answer').length,
      deferred: ds.filter(d => d.detail?.tool === 'scope_gate' && d.kind === 'defer').length,
      declined: ds.filter(d => d.detail?.tool === 'scope_gate' && d.kind === 'decline').length,
      avg: lat.length ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) : null,
    };
  }, [state]);

  const start = async (restart = false) => {
    setBusy(true);
    setActionErr(null);
    try {
      const r = await apiFetch<Rehearsal>(`/api/meetings/${meeting.id}/rehearsal`, {
        method: 'POST',
        body: JSON.stringify({ restart }),
      });
      setState(r.data);
    } catch (e: any) {
      setActionErr(`The rehearsal could not start. ${e?.message || ''}`.trim());
    }
    setBusy(false);
  };

  const end = async () => {
    setBusy(true);
    setActionErr(null);
    try {
      const r = await apiFetch<Rehearsal>(`/api/meetings/${meeting.id}/rehearsal/end`, { method: 'POST', body: '{}' });
      setState(r.data);
    } catch (e: any) {
      setActionErr(`Could not end the rehearsal. ${e?.message || ''}`.trim());
    }
    setBusy(false);
  };

  const send = async (override?: string) => {
    const t = (override ?? text).trim();
    if (!t) return;
    setSending(true);
    setActionErr(null);
    try {
      await apiFetch(`/api/meetings/${meeting.id}/rehearsal/turn`, {
        method: 'POST',
        body: JSON.stringify({ speaker: speaker.trim() || 'Participant', text: t }),
      });
      if (override === undefined) setText('');
      await load();
    } catch (e: any) {
      setActionErr(`That turn was not sent. ${e?.message || ''}`.trim());
    }
    setSending(false);
  };

  const answer = async (id: string) => {
    const a = (answers[id] || '').trim();
    if (!a) return;
    try {
      await apiFetch(`/api/meetings/${meeting.id}/rehearsal/deferrals/${id}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer: a }),
      });
      setAnswers(p => ({ ...p, [id]: '' }));
      await load();
    } catch (e: any) {
      setActionErr(`Your answer was not delivered. ${e?.message || ''}`.trim());
    }
  };

  const Speech = speechCtor();
  const toggleMic = () => {
    if (!Speech) return;
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new Speech();
    rec.lang = 'en-US';
    rec.interimResults = true;
    rec.onresult = (ev: any) => {
      let said = '';
      for (let i = 0; i < ev.results.length; i++) said += ev.results[i][0].transcript;
      setText(said);
    };
    rec.onerror = (ev: any) => setActionErr(`Dictation stopped: ${ev?.error || 'unknown error'}. You can type the turn instead.`);
    rec.onend = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const examples = [
    meeting.scope_allow[0] && { label: 'Inside scope', text: `Can you give us a quick update on ${meeting.scope_allow[0]}?` },
    meeting.scope_defer[0] && { label: 'Hand back', text: `What about ${meeting.scope_defer[0]}, can you confirm it today?` },
    { label: 'Outside scope', text: 'What did you think of the football match last night?' },
  ].filter(Boolean) as { label: string; text: string }[];

  const noTopics = meeting.scope_allow.length === 0;
  const isLive = meeting.status === 'live';
  const startBlocked = noTopics
    ? 'Add at least one topic the bot may answer first. Use Edit under Bot scope on the meeting page.'
    : isLive
      ? 'The bot is in the live meeting right now. Rehearse before or after it.'
      : state && state.available === false
        ? 'Rehearsal needs Redis, which this deployment does not have.'
        : null;

  return (
    <div className="space-y-4" data-testid="rehearsal-panel">
      <div className="rounded-lg border border-violet-500/40 bg-violet-500/10 p-3 flex items-start gap-2 text-sm text-violet-100" role="status" data-testid="rehearsal-banner">
        <FlaskConical className="w-4 h-4 mt-0.5 shrink-0 text-violet-300" />
        <p>
          <strong>This is a rehearsal.</strong> Nobody else hears it. You play the other people in the meeting, and the
          bot answers with the same agent, topics and persona knowledge it uses live. It joins no room and spends no voice
          credits. Its thinking still uses the model, the same as live.
        </p>
      </div>

      {loadErr && (
        <div role="alert" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex flex-wrap items-center gap-2">
          {loadErr}
          <button onClick={load} className="underline">Try again</button>
        </div>
      )}
      {actionErr && (
        <div role="alert" data-testid="rehearsal-error" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
          {actionErr}
        </div>
      )}

      {state === null && !loadErr && (
        <div className="flex items-center gap-2 text-sm text-slate-400 py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading the rehearsal…
        </div>
      )}

      {state && !state.active && (
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3" data-testid="rehearsal-intro">
          <h2 className="text-sm font-medium text-white">Try the bot before the real meeting</h2>
          <ul className="text-xs text-slate-400 space-y-1 list-disc pl-4">
            <li>Type what a participant says, or dictate it with the mic.</li>
            <li>See whether the bot answers, hands the question back to you, or declines it as outside its topics.</li>
            <li>See which of your persona notes it cited and how long each reply took.</li>
          </ul>
          <ScopeSummary meeting={meeting} />
          <button
            onClick={() => start(false)}
            disabled={busy || !!startBlocked}
            title={startBlocked || undefined}
            data-testid="rehearsal-start"
            className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FlaskConical className="w-4 h-4" />}
            {busy ? 'Starting…' : 'Start rehearsal'}
          </button>
          {startBlocked && <p className="text-xs text-amber-300" data-testid="rehearsal-blocked">{startBlocked}</p>}
        </div>
      )}

      {state?.active && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusPill status={state.status || 'starting'} />
            <span className="text-slate-400">{stats.turns} turns</span>
            <span className="text-emerald-300">{stats.answered} answered</span>
            <span className="text-amber-300">{stats.deferred} handed back</span>
            <span className="text-slate-300">{stats.declined} declined</span>
            {stats.avg !== null && <span className="text-cyan-300" data-testid="rehearsal-avg-latency">average reply {fmtMs(stats.avg)}</span>}
            <span className="flex-1" />
            <label className="flex items-center gap-1 text-slate-400">
              <input type="checkbox" checked={showSteps} onChange={e => setShowSteps(e.target.checked)} />
              Show every step
            </label>
            {running && state.status !== 'ending' ? (
              <button onClick={end} disabled={busy} data-testid="rehearsal-end" className="flex items-center gap-1 px-2.5 py-1 rounded border border-slate-700 text-slate-200 hover:bg-slate-800 disabled:opacity-50">
                <Square className="w-3 h-3" /> End rehearsal
              </button>
            ) : !running ? (
              <button
                onClick={() => start(true)}
                disabled={busy || !!startBlocked}
                title={startBlocked || undefined}
                data-testid="rehearsal-restart"
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-violet-600/30 border border-violet-500/40 text-violet-100 hover:bg-violet-600/50 disabled:opacity-50"
              >
                <RotateCcw className="w-3 h-3" /> Start a new rehearsal
              </button>
            ) : null}
          </div>

          <div ref={boxRef} className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-3 space-y-2 max-h-[60vh] overflow-y-auto" data-testid="rehearsal-transcript">
            {items.length === 0 && (
              <p className="text-xs text-slate-500 py-6 text-center">
                {state.status === 'starting' ? 'The bot is getting ready. You can type the first turn now.' : 'Nothing said yet. Type a turn below.'}
              </p>
            )}
            {items.map((it, i) => {
              if (it.type === 'line') return <TurnLine key={`l${i}`} line={it.line} />;
              if (it.type === 'deferral') {
                return (
                  <DeferralCard
                    key={`f${it.f.id}`}
                    f={it.f}
                    now={now}
                    value={answers[it.f.id] || ''}
                    onChange={v => setAnswers(p => ({ ...p, [it.f.id]: v }))}
                    onSend={() => answer(it.f.id)}
                  />
                );
              }
              return <DecisionRow key={`d${i}`} d={it.d} />;
            })}
            {(state.queued_turns || 0) > 0 && (
              <p className="text-[11px] text-slate-400 flex items-center gap-1" data-testid="rehearsal-queued">
                <Clock className="w-3 h-3" /> {state.queued_turns} turn{state.queued_turns === 1 ? '' : 's'} waiting for the bot to pick up
              </p>
            )}
          </div>

          {running && state.status !== 'ending' && (
            <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-3 space-y-2">
              <div className="flex flex-wrap gap-1">
                {examples.map(ex => (
                  <button
                    key={ex.label}
                    onClick={() => setText(ex.text)}
                    className="text-[11px] px-2 py-0.5 rounded border border-dashed border-slate-700 text-slate-300 hover:text-white"
                  >
                    {ex.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  value={speaker}
                  onChange={e => setSpeaker(e.target.value)}
                  aria-label="Who is speaking"
                  data-testid="rehearsal-speaker"
                  placeholder="Who is speaking"
                  className="sm:w-40 px-2 py-1.5 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
                />
                <input
                  value={text}
                  onChange={e => setText(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !sending && send()}
                  aria-label="What they say"
                  data-testid="rehearsal-input"
                  placeholder="What they say, for example: what is the status of the roadmap?"
                  maxLength={1000}
                  className="flex-1 min-w-0 px-2 py-1.5 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
                />
                <div className="flex gap-2">
                  <button
                    onClick={toggleMic}
                    disabled={!Speech}
                    title={Speech ? (listening ? 'Stop dictation' : 'Dictate the turn') : "This browser can't take dictation. Type the turn instead."}
                    aria-label={listening ? 'Stop dictation' : 'Dictate the turn'}
                    className={`px-2.5 py-1.5 rounded border text-xs disabled:opacity-40 ${listening ? 'border-red-500/50 text-red-200 bg-red-500/10' : 'border-slate-700 text-slate-300 hover:bg-slate-800'}`}
                  >
                    {listening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={() => send()}
                    disabled={sending || !text.trim()}
                    title={!text.trim() ? 'Type what the participant says first' : undefined}
                    data-testid="rehearsal-send"
                    className="flex-1 sm:flex-none flex items-center justify-center gap-1 px-3 py-1.5 text-xs rounded bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50"
                  >
                    {sending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />} Say it
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ScopeSummary({ meeting }: { meeting: RehearsalMeeting }) {
  return (
    <div className="grid sm:grid-cols-3 gap-2 text-[11px]">
      <div>
        <p className="text-slate-500">Answers on</p>
        <p className="text-emerald-300 break-words">{meeting.scope_allow.join(', ') || 'nothing yet'}</p>
      </div>
      <div>
        <p className="text-slate-500">Hands back to you</p>
        <p className="text-amber-300 break-words">{meeting.scope_defer.join(', ') || 'commitments, pricing and approvals'}</p>
      </div>
      <div>
        <p className="text-slate-500">Persona knowledge</p>
        <p className="text-cyan-300 break-words">{(meeting.persona_scopes.length ? meeting.persona_scopes : ['self']).join(', ')}</p>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    starting: ['Bot getting ready', 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30'],
    live: ['Bot listening', 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'],
    ending: ['Ending', 'bg-slate-500/10 text-slate-300 border-slate-500/30'],
    closed: ['Rehearsal ended', 'bg-slate-500/10 text-slate-300 border-slate-500/30'],
  };
  const [label, cls] = map[status] || [status, 'bg-slate-500/10 text-slate-300 border-slate-500/30'];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border ${cls}`} data-testid="rehearsal-status" data-status={status}>
      {(status === 'starting' || status === 'ending') && <Loader2 className="w-3 h-3 animate-spin" />}
      {label}
    </span>
  );
}

function TurnLine({ line }: { line: Line }) {
  if (line.bot) {
    return (
      <div className="flex justify-end" data-testid="rehearsal-bot-line">
        <div className="max-w-[85%] rounded-lg bg-cyan-500/10 border border-cyan-500/30 px-3 py-2">
          <p className="text-[10px] text-cyan-300 flex items-center gap-1">
            <Bot className="w-3 h-3" /> {line.participant}
            {line.via === 'chat' && <span className="text-cyan-300/60">in chat</span>}
            {typeof line.latency_ms === 'number' && (
              <span className="ml-1 px-1 rounded bg-cyan-500/20" data-testid="rehearsal-latency">replied in {fmtMs(line.latency_ms)}</span>
            )}
          </p>
          <p className="text-xs text-slate-100 mt-0.5 whitespace-pre-wrap break-words">{line.text}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex" data-testid="rehearsal-turn">
      <div className="max-w-[85%] rounded-lg bg-slate-800/60 border border-slate-700/50 px-3 py-2">
        <p className="text-[10px] text-slate-400 flex items-center gap-1">
          <User className="w-3 h-3" /> {line.participant.replace(/ \(chat\)$/, '')}
        </p>
        <p className="text-xs text-slate-100 mt-0.5 whitespace-pre-wrap break-words">{line.text}</p>
      </div>
    </div>
  );
}

function DecisionRow({ d }: { d: Decision }) {
  const tool = d.detail?.tool;
  if (tool === 'scope_gate') {
    const tone = d.kind === 'answer'
      ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5'
      : d.kind === 'defer'
        ? 'text-amber-300 border-amber-500/30 bg-amber-500/5'
        : 'text-slate-200 border-slate-500/40 bg-slate-500/10';
    const Icon = d.kind === 'decline' ? ShieldX : d.kind === 'defer' ? Hand : ShieldCheck;
    return (
      <div className={`text-[11px] px-2 py-1 rounded border inline-flex items-center gap-1 ${tone}`} data-testid="rehearsal-scope" data-decision={d.kind}>
        <Icon className="w-3 h-3" /> {d.summary}
      </div>
    );
  }
  if (d.kind === 'cite') {
    const cites: any[] = d.detail?.citations || [];
    return (
      <div className="text-[11px] rounded border border-cyan-500/20 bg-cyan-500/5 px-2 py-1.5 space-y-1" data-testid="rehearsal-citations">
        <p className="text-cyan-200 flex items-center gap-1"><BookOpen className="w-3 h-3" /> {d.summary}{d.detail?.scope ? ` in ${d.detail.scope}` : ''}</p>
        {cites.map((c, i) => (
          <div key={i} className="pl-4 text-slate-300">
            <span className="text-cyan-300">[{i + 1}] {c.title}</span>
            {typeof c.score === 'number' && <span className="text-slate-500"> · match {Math.round(c.score * 100)}%</span>}
            {c.snippet && <p className="text-slate-400 line-clamp-2 break-words">{c.snippet}</p>}
          </div>
        ))}
      </div>
    );
  }
  const tone: Record<string, string> = {
    error: 'text-red-300',
    notice: 'text-amber-200',
    decline: 'text-slate-200',
    defer: 'text-amber-300',
    join: 'text-slate-500',
    leave: 'text-slate-500',
    step: 'text-slate-500 font-mono',
  };
  return (
    <p className={`text-[11px] flex items-start gap-1 break-words ${tone[d.kind] || 'text-slate-400'}`} data-testid={`rehearsal-${d.kind}`}>
      {d.kind === 'error' || d.kind === 'notice' ? <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /> : <CheckCircle2 className="w-3 h-3 mt-0.5 shrink-0 opacity-50" />}
      <span className="min-w-0">{d.summary}</span>
    </p>
  );
}

function DeferralCard({
  f, now, value, onChange, onSend,
}: {
  f: Deferral; now: number; value: string; onChange: (v: string) => void; onSend: () => void;
}) {
  const left = f.created_at_ms ? Math.max(0, HOLD_SECONDS - Math.floor((now - f.created_at_ms) / 1000)) : null;
  if (f.status !== 'pending') {
    return (
      <div className="text-[11px] rounded border border-amber-500/20 bg-amber-500/5 px-2 py-1.5" data-testid="rehearsal-deferral-done">
        <p className="text-amber-200">Handed back to you: {f.question}</p>
        <p className="text-slate-300">
          {f.status === 'answered' ? 'You answered: ' : 'No answer in time, the bot said: '}
          {f.answer}
        </p>
      </div>
    );
  }
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 space-y-1.5" data-testid="rehearsal-deferral">
      <p className="text-xs text-amber-100 flex items-center gap-1"><Hand className="w-3 h-3" /> The bot is asking you: {f.question}</p>
      <p className="text-[10px] text-amber-200/70">
        {left !== null && left > 0
          ? `It waits ${left} more seconds, then tells the room it will follow up.`
          : 'Time is up. The bot is telling the room it will follow up.'}
      </p>
      <div className="flex gap-2">
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onSend()}
          aria-label="Your answer for the bot"
          data-testid="rehearsal-deferral-answer"
          placeholder="Your answer. The bot says it to the room."
          className="flex-1 min-w-0 px-2 py-1 bg-slate-900/70 border border-slate-700/50 rounded text-xs text-white"
        />
        <button
          onClick={onSend}
          disabled={!value.trim()}
          title={!value.trim() ? 'Type an answer first' : undefined}
          data-testid="rehearsal-deferral-send"
          className="px-2.5 py-1 text-xs rounded bg-amber-600/40 border border-amber-500/50 text-amber-50 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
