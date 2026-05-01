'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft, Play, Shield, XCircle, Video, AlertCircle, CheckCircle2,
  MessageSquare, Clock, Send, Loader2, Radio, Plus, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  transcript?: Array<{ participant: string; text: string; ts_ms: number }>;
  decisions?: Array<{ kind: string; summary: string; ts_ms: number; detail?: any }>;
  deferrals?: Array<{ id: string; question: string; context: string | null; answer: string | null; status: string; created_at: string | null; answered_at?: string | null }>;
}

export default function MeetingDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id as string;
  usePageTitle('Meeting');
  const router = useRouter();
  const [m, setM] = useState<Meeting | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editingScope, setEditingScope] = useState(false);
  const [allowInput, setAllowInput] = useState<string[]>([]);
  const [deferInput, setDeferInput] = useState<string[]>([]);
  const [personaInput, setPersonaInput] = useState<string[]>(['self']);
  const [newAllow, setNewAllow] = useState('');
  const [newDefer, setNewDefer] = useState('');
  const [newPersona, setNewPersona] = useState('');
  const [starting, setStarting] = useState(false);
  const [deferralAnswers, setDeferralAnswers] = useState<Record<string, string>>({});
  const [injectSpeaker, setInjectSpeaker] = useState('test-participant');
  const [injectText, setInjectText] = useState('');
  const [connect, setConnect] = useState<{
    url: string; token: string; deep_link: string; identity: string;
  } | null>(null);
  const [connectErr, setConnectErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch<Meeting>(`/api/meetings/${id}`);
      if ((r as any)?.error) throw new Error(String((r as any).error?.message));
      setM(r.data || null);
      if (r.data) {
        setAllowInput(r.data.scope_allow || []);
        setDeferInput(r.data.scope_defer || []);
        setPersonaInput(r.data.persona_scopes?.length ? r.data.persona_scopes : ['self']);
      }
    } catch (e: any) {
      setErr(e?.message || 'load failed');
    }
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // SSE — subscribe to live events while meeting is LIVE
  useEffect(() => {
    if (!m || m.status !== 'live') return;
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    const es = new EventSource(`${API_URL}/api/meetings/${id}/stream?token=${token}`);
    es.addEventListener('transcript', () => load());
    es.addEventListener('decision', () => load());
    es.addEventListener('deferral', () => load());
    es.addEventListener('kill', () => load());
    es.onerror = () => { es.close(); };
    return () => { es.close(); };
  }, [m?.status, id, load, m]);

  const saveScope = async () => {
    try {
      await apiFetch(`/api/meetings/${id}/authorize`, {
        method: 'PUT',
        body: JSON.stringify({
          scope_allow: allowInput,
          scope_defer: deferInput,
          persona_scopes: personaInput.length ? personaInput : ['self'],
        }),
      });
      setEditingScope(false);
      await load();
    } catch (e: any) {
      setErr(e?.message || 'authorize failed');
    }
  };

  const startBot = async () => {
    setStarting(true);
    try {
      await apiFetch(`/api/meetings/${id}/start`, { method: 'POST', body: '{}' });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'start failed');
    }
    setStarting(false);
  };

  const killBot = async () => {
    if (!confirm('Kick the bot out of this meeting now?')) return;
    try {
      await apiFetch(`/api/meetings/${id}/kill`, { method: 'POST', body: '{}' });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'kill failed');
    }
  };

  const redispatchBot = async () => {
    setStarting(true);
    try {
      const r = await apiFetch(`/api/meetings/${id}/redispatch`, { method: 'POST', body: '{}' });
      if ((r as any)?.error) throw new Error(String((r as any).error?.message));
      await load();
    } catch (e: any) {
      setErr(e?.message || 'redispatch failed');
    }
    setStarting(false);
  };

  const openConnectPanel = async () => {
    setConnectErr(null);
    if (!m) return;
    try {
      const r = await apiFetch<any>(
        `/api/meetings/livekit-token?room=${encodeURIComponent(m.room)}`,
      );
      if ((r as any)?.error) throw new Error(String((r as any).error?.message));
      setConnect({
        url: r.data?.browser_url || r.data?.url || '',
        token: r.data?.token || '',
        deep_link: r.data?.deep_link || '',
        identity: r.data?.identity || '',
      });
    } catch (e: any) {
      setConnectErr(e?.message || 'Could not mint a join token');
    }
  };

  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 1200);
    } catch {
      setConnectErr('Clipboard write failed — copy manually');
    }
  };

  const injectTurn = async () => {
    if (!injectText.trim()) return;
    try {
      await apiFetch(`/api/meetings/${id}/inject-turn`, {
        method: 'POST',
        body: JSON.stringify({ speaker: injectSpeaker || 'test-participant', text: injectText }),
      });
      setInjectText('');
      await load();
    } catch (e: any) {
      setErr(e?.message || 'inject failed');
    }
  };

  const answerDeferral = async (deferralId: string) => {
    const answer = deferralAnswers[deferralId]?.trim();
    if (!answer) return;
    try {
      await apiFetch(`/api/meetings/${id}/deferrals/${deferralId}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer }),
      });
      setDeferralAnswers(prev => ({ ...prev, [deferralId]: '' }));
      await load();
    } catch (e: any) {
      setErr(e?.message || 'answer failed');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-500" />
      </div>
    );
  }

  if (!m) {
    return <div className="text-sm text-slate-500">Meeting not found.</div>;
  }

  const authorized = (m.scope_allow || []).length > 0 || m.status !== 'scheduled';
  const canStart = authorized && ['authorized', 'scheduled'].includes(m.status);
  const isLive = m.status === 'live';
  const isDone = ['done', 'killed', 'failed'].includes(m.status);

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <Link href="/meetings" className="text-xs text-slate-500 hover:text-cyan-400 flex items-center gap-1 mb-3">
          <ArrowLeft className="w-3 h-3" /> Back to meetings
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-white flex items-center gap-2">
              <Video className="w-5 h-5 text-cyan-400" />
              <span className="truncate">{m.title}</span>
            </h1>
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
              <span className="uppercase">{m.provider}</span>
              <span>·</span>
              <span className="font-mono">{m.room}</span>
              <span>·</span>
              <span className={`px-1.5 py-0.5 rounded ${
                m.status === 'live' ? 'bg-emerald-500/10 text-emerald-300' :
                m.status === 'done' ? 'bg-purple-500/10 text-purple-300' :
                m.status === 'killed' || m.status === 'failed' ? 'bg-red-500/10 text-red-300' :
                'bg-slate-500/10 text-slate-300'
              }`}>
                {m.status}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={openConnectPanel}
              className="px-3 py-1.5 text-xs rounded border border-slate-700/50 text-slate-300 hover:bg-slate-800/70"
              data-testid="connect-from-browser"
            >
              Connect from browser
            </button>
            {canStart && (
              <button
                onClick={startBot}
                disabled={starting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-emerald-600/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-600/30 disabled:opacity-50"
              >
                <Play className="w-3 h-3" />
                {starting ? 'Starting…' : 'Start bot'}
              </button>
            )}
            {/* Redispatch is allowed for any non-scheduled meeting — the
                whole point is to revive a killed/crashed bot without
                losing the transcript/decision history. */}
            {m.status !== 'scheduled' && (
              <button
                onClick={redispatchBot}
                disabled={starting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-amber-600/20 border border-amber-500/40 text-amber-200 hover:bg-amber-600/30 disabled:opacity-50"
                title="Re-spawn the bot agent. Works on killed / done / live meetings — preserves the existing transcript + decision log."
                data-testid="redispatch-bot"
              >
                <Play className="w-3 h-3" /> {starting ? 'Re-dispatching…' : 'Re-dispatch bot'}
              </button>
            )}
            {isLive && (
              <button
                onClick={killBot}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-red-600/20 border border-red-500/40 text-red-200 hover:bg-red-600/30"
              >
                <XCircle className="w-3 h-3" /> Kick bot
              </button>
            )}
          </div>
        </div>
      </div>

      {err && (
        <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
          {err}
        </div>
      )}

      {/* Connect-from-browser panel — opens on demand */}
      {connect && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-3" data-testid="connect-panel">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-white flex items-center gap-2">
              <Video className="w-4 h-4 text-cyan-400" />
              Connect to this meeting from your browser
            </h3>
            <button
              onClick={() => setConnect(null)}
              className="text-xs text-slate-500 hover:text-white"
            >Close</button>
          </div>
          <p className="text-xs text-slate-400">
            One-click via the LiveKit Meet hosted client (auto-fills both fields):
          </p>
          <a
            href={connect.deep_link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-cyan-600 text-white hover:bg-cyan-500"
          >
            <Video className="w-3 h-3" />
            Open LiveKit Meet (auto-fill)
          </a>
          <div className="text-xs text-slate-400 pt-2 border-t border-slate-800/50">
            Or paste these into any LiveKit client (e.g. <a href="https://meet.livekit.io" target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">meet.livekit.io</a> → Custom):
          </div>
          <div className="space-y-2">
            <CopyRow label="LiveKit Server URL" value={connect.url} copied={copied === 'url'} onCopy={() => copyToClipboard(connect.url, 'url')} />
            <CopyRow label="Token" value={connect.token} mono truncate copied={copied === 'token'} onCopy={() => copyToClipboard(connect.token, 'token')} />
            <CopyRow label="Joining as" value={connect.identity} copied={copied === 'identity'} onCopy={() => copyToClipboard(connect.identity, 'identity')} />
          </div>
          <p className="text-[11px] text-slate-500">
            Token is valid for 1 hour. If you see a "no permissions to access the room" error, request a fresh one.
          </p>
        </div>
      )}

      {connectErr && (
        <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
          {connectErr}
        </div>
      )}

      {/* Stale-meeting hint: live status but no meeting_join in the log */}
      {isLive && (m.decisions || []).length > 0 &&
        !(m.decisions || []).some((d: any) =>
          /meeting_join|bot joined/i.test(d.summary || '')
        ) && (
        <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between">
          <span>
            <strong>Looks like the bot never actually joined this meeting.</strong>{' '}
            The decision log has no <code className="text-amber-300">meeting_join</code> entry.
            Click <strong>Re-dispatch bot</strong> above to spawn it now.
          </span>
        </div>
      )}
      {isLive && (m.decisions || []).length === 0 && (
        <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs">
          <strong>No decisions logged yet.</strong> If the bot doesn't appear within ~10 seconds,
          click <strong>Re-dispatch bot</strong> above.
        </div>
      )}

      {/* Scope authorization */}
      <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-medium text-white">Bot scope</h2>
            {authorized ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                authorized
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">
                not authorized
              </span>
            )}
          </div>
          {!isLive && !isDone && (
            <button
              onClick={() => setEditingScope(v => !v)}
              className="text-xs text-cyan-400 hover:underline"
            >
              {editingScope ? 'Cancel' : 'Edit'}
            </button>
          )}
        </div>

        {!editingScope ? (
          <div className="grid md:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="text-slate-500 mb-1">Answer on</p>
              <div className="flex flex-wrap gap-1">
                {(m.scope_allow || []).map(t => (
                  <span key={t} className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                    {t}
                  </span>
                ))}
                {(m.scope_allow || []).length === 0 && <span className="text-slate-600">—</span>}
              </div>
            </div>
            <div>
              <p className="text-slate-500 mb-1">Always defer</p>
              <div className="flex flex-wrap gap-1">
                {(m.scope_defer || []).map(t => (
                  <span key={t} className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
                    {t}
                  </span>
                ))}
                {(m.scope_defer || []).length === 0 && <span className="text-slate-600">—</span>}
              </div>
            </div>
            <div>
              <p className="text-slate-500 mb-1">Persona scopes</p>
              <div className="flex flex-wrap gap-1">
                {(m.persona_scopes || []).map(t => (
                  <span key={t} className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                    {t}
                  </span>
                ))}
                {(m.persona_scopes || []).length === 0 && <span className="text-slate-600">self</span>}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <ChipEditor
              label="Answer on"
              items={allowInput}
              setItems={setAllowInput}
              placeholder="e.g. status update, sprint goals"
              newValue={newAllow}
              setNewValue={setNewAllow}
              color="emerald"
            />
            <ChipEditor
              label="Always defer"
              items={deferInput}
              setItems={setDeferInput}
              placeholder="e.g. pricing, contract value, deadlines"
              newValue={newDefer}
              setNewValue={setNewDefer}
              color="amber"
            />
            <ChipEditor
              label="Persona scopes (ring-fenced KB)"
              items={personaInput}
              setItems={setPersonaInput}
              placeholder="self, client:acme, project:q2-launch"
              newValue={newPersona}
              setNewValue={setNewPersona}
              color="cyan"
            />
            <button
              onClick={saveScope}
              className="px-3 py-1.5 text-xs rounded bg-cyan-600 text-white hover:bg-cyan-500"
            >
              Save authorization
            </button>
          </div>
        )}
      </div>

      {/* Pending deferrals — if any are pending, show urgent panel */}
      {(m.deferrals || []).filter(d => d.status === 'pending').length > 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-medium text-amber-200">Bot is waiting on you</h2>
          </div>
          {(m.deferrals || []).filter(d => d.status === 'pending').map(d => (
            <div key={d.id} className="rounded border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
              <p className="text-sm text-white">{d.question}</p>
              {d.context && <p className="text-xs text-amber-200/70">{d.context}</p>}
              <div className="flex gap-2">
                <input
                  value={deferralAnswers[d.id] || ''}
                  onChange={e => setDeferralAnswers(prev => ({ ...prev, [d.id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && answerDeferral(d.id)}
                  placeholder="Your answer (bot will speak this verbatim)…"
                  className="flex-1 px-3 py-1.5 bg-slate-900/70 border border-slate-700/50 rounded text-xs text-white focus:outline-none focus:border-amber-500/50"
                />
                <button
                  onClick={() => answerDeferral(d.id)}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-amber-600/30 border border-amber-500/50 text-amber-100 hover:bg-amber-600/50"
                >
                  <Send className="w-3 h-3" /> Send
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Inject a synthetic turn (demo + testing) */}
      {isLive && (
        <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <Send className="w-4 h-4 text-cyan-300" />
            <h3 className="text-sm font-medium text-white">Inject a test turn</h3>
            <span className="text-[10px] text-cyan-300/60">
              simulates a participant speaking — goes straight into the transcript + decision log
            </span>
          </div>
          <div className="flex gap-2">
            <input
              value={injectSpeaker}
              onChange={e => setInjectSpeaker(e.target.value)}
              className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white w-36"
              placeholder="speaker"
            />
            <input
              value={injectText}
              onChange={e => setInjectText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && injectTurn()}
              className="flex-1 px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
              placeholder='"What is our sprint progress?" or "Can you commit to Friday?"'
            />
            <button
              onClick={injectTurn}
              disabled={!injectText.trim()}
              className="px-3 py-1 text-xs rounded bg-cyan-600/30 border border-cyan-500/40 text-cyan-100 hover:bg-cyan-600/50 disabled:opacity-50"
            >
              Inject
            </button>
          </div>
        </div>
      )}

      {/* Resolved deferrals — history view, visible for live + done */}
      {(m.deferrals || []).filter(d => d.status !== 'pending').length > 0 && (
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-medium text-white">Resolved deferrals</h2>
            <span className="text-xs text-slate-500">
              {(m.deferrals || []).filter(d => d.status !== 'pending').length}
            </span>
          </div>
          <div className="divide-y divide-slate-800/50">
            {(m.deferrals || []).filter(d => d.status !== 'pending').map(d => (
              <div key={d.id} className="py-2 text-xs space-y-0.5" data-testid="resolved-deferral">
                <p className="text-slate-300"><span className="text-slate-500">Q:</span> {d.question}</p>
                {d.answer && <p className="text-slate-200"><span className="text-slate-500">A:</span> {d.answer}</p>}
                <p className="text-[10px] text-slate-500">
                  status: <span className="text-emerald-300">{d.status}</span>
                  {d.answered_at && <> · answered {new Date(d.answered_at).toLocaleString()}</>}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live view: transcript + decisions */}
      {(isLive || isDone) && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-medium text-white">Transcript</h2>
              {isLive && <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />}
            </div>
            <div className="space-y-1.5 max-h-96 overflow-y-auto">
              {(m.transcript || []).map((t: any, i) => (
                <div key={i} className="text-xs">
                  <span className="font-mono text-slate-500">{t.participant || 'unknown'}:</span>{' '}
                  <span className="text-slate-300">{t.text}</span>
                  {t.injected && (
                    <span className="ml-1 text-[9px] px-1 rounded bg-cyan-500/10 text-cyan-300">injected</span>
                  )}
                  {t.addressed && (
                    <span className="ml-1 text-[9px] px-1 rounded bg-amber-500/10 text-amber-300">@bot</span>
                  )}
                </div>
              ))}
              {(m.transcript || []).length === 0 && (
                <p className="text-xs text-slate-500">No transcript yet.</p>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle2 className="w-4 h-4 text-purple-400" />
              <h2 className="text-sm font-medium text-white">Decision log</h2>
            </div>
            <div className="space-y-1.5 max-h-96 overflow-y-auto">
              {(m.decisions || []).map((d, i) => (
                <div key={i} className="text-xs">
                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded mr-2 ${
                    d.kind === 'answer' ? 'bg-emerald-500/10 text-emerald-300' :
                    d.kind === 'defer' ? 'bg-amber-500/10 text-amber-300' :
                    d.kind === 'decline' ? 'bg-slate-500/10 text-slate-300' :
                    d.kind === 'leave' ? 'bg-purple-500/10 text-purple-300' :
                    'bg-cyan-500/10 text-cyan-300'
                  }`}>
                    {d.kind}
                  </span>
                  <span className="text-slate-300">{d.summary}</span>
                </div>
              ))}
              {(m.decisions || []).length === 0 && (
                <p className="text-xs text-slate-500">No decisions yet.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {isDone && m.summary && (
        <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-4">
          <h2 className="text-sm font-medium text-purple-200 mb-2">Meeting summary</h2>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{m.summary}</p>
        </div>
      )}
    </div>
  );
}

function CopyRow({
  label, value, mono, truncate, copied, onCopy,
}: {
  label: string; value: string; mono?: boolean; truncate?: boolean;
  copied?: boolean; onCopy: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-slate-500 w-32 shrink-0">{label}:</span>
      <code className={`flex-1 px-2 py-1 rounded bg-slate-900/70 border border-slate-700/50 text-xs ${mono ? 'font-mono' : ''} ${truncate ? 'truncate' : 'break-all'} text-slate-200`}>
        {value}
      </code>
      <button
        onClick={onCopy}
        className="px-2 py-1 text-[11px] rounded border border-slate-700/50 text-slate-300 hover:bg-slate-800/70 shrink-0"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
  );
}

function ChipEditor({
  label, items, setItems, placeholder, newValue, setNewValue, color,
}: {
  label: string;
  items: string[];
  setItems: (v: string[]) => void;
  placeholder: string;
  newValue: string;
  setNewValue: (v: string) => void;
  color: 'emerald' | 'amber' | 'cyan';
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
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-slate-400">{label}</p>
      <div className="flex flex-wrap gap-1">
        {items.map(t => (
          <span key={t} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs border ${ring}`}>
            {t}
            <button onClick={() => setItems(items.filter(x => x !== t))}>
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1">
        <input
          value={newValue}
          onChange={e => setNewValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), add())}
          placeholder={placeholder}
          className="flex-1 px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white placeholder-slate-500"
        />
        <button
          onClick={add}
          className="px-2 py-1 text-xs rounded border border-slate-700/50 text-slate-300 hover:bg-slate-800/70"
        >
          <Plus className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
