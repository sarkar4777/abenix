'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, Bot, Loader2, LogOut, Mic, MicOff, Send, User, Users, Video } from 'lucide-react';
import type { Room as LkRoom } from 'livekit-client';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import PageHeader from '@/components/layout/PageHeader';

interface MeetingLite {
  id: string;
  title: string;
  room: string;
  provider: string;
  status: string;
  display_name: string;
}

interface Person { identity: string; name: string; speaking: boolean; isLocal: boolean }
interface ChatLine { from: string; text: string; ts: number; mine: boolean }

type Phase = 'idle' | 'connecting' | 'connected' | 'error';

export default function JoinMeetingPage() {
  const { id } = useParams<{ id: string }>();
  usePageTitle('Join meeting');
  const [m, setM] = useState<MeetingLite | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [err, setErr] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [micOn, setMicOn] = useState(false);
  const [micBusy, setMicBusy] = useState(false);
  const [chat, setChat] = useState<ChatLine[]>([]);
  const [msg, setMsg] = useState('');
  const roomRef = useRef<LkRoom | null>(null);
  const audioRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    apiFetch<MeetingLite>(`/api/meetings/${id}`, { silent: true }).then(r => {
      if (r.error) setLoadErr(r.errorDetail?.code === 404 ? 'This meeting does not exist or is not yours.' : `Could not load the meeting. ${r.error}`);
      setM(r.data);
    });
  }, [id]);

  const refreshPeople = useCallback(() => {
    const room = roomRef.current;
    if (!room) return;
    const list: Person[] = [{
      identity: room.localParticipant.identity,
      name: 'You',
      speaking: room.localParticipant.isSpeaking,
      isLocal: true,
    }];
    room.remoteParticipants.forEach(p => list.push({
      identity: p.identity,
      name: p.name || p.identity,
      speaking: p.isSpeaking,
      isLocal: false,
    }));
    setPeople(list);
  }, []);

  useEffect(() => () => { roomRef.current?.disconnect(); }, []);

  const join = async () => {
    if (!m) return;
    setPhase('connecting');
    setErr(null);
    const tok = await apiFetch<{ token: string; browser_url: string; url: string }>(
      `/api/meetings/livekit-token?room=${encodeURIComponent(m.room)}`, { silent: true },
    );
    if (tok.error || !tok.data) {
      setErr(tok.error || 'Could not get a join token.');
      setPhase('error');
      return;
    }
    const url = tok.data.browser_url || tok.data.url;
    try {
      const { Room, RoomEvent, Track } = await import('livekit-client');
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;
      const dec = new TextDecoder();
      room
        .on(RoomEvent.ParticipantConnected, refreshPeople)
        .on(RoomEvent.ParticipantDisconnected, refreshPeople)
        .on(RoomEvent.ActiveSpeakersChanged, refreshPeople)
        .on(RoomEvent.TrackSubscribed, (track) => {
          if (track.kind === Track.Kind.Audio && audioRef.current) {
            audioRef.current.appendChild(track.attach());
          }
        })
        .on(RoomEvent.TrackUnsubscribed, (track) => { track.detach().forEach(el => el.remove()); })
        .on(RoomEvent.DataReceived, (payload, participant) => {
          const text = dec.decode(payload);
          if (!text.trim()) return;
          setChat(c => [...c, { from: participant?.name || participant?.identity || 'someone', text, ts: Date.now(), mine: false }]);
        })
        .on(RoomEvent.Disconnected, () => { setPhase('idle'); setPeople([]); setMicOn(false); });
      await room.connect(url, tok.data.token);
      await room.startAudio().catch(() => {});
      setPhase('connected');
      refreshPeople();
    } catch (e: any) {
      roomRef.current = null;
      setErr(
        `Your browser could not reach the LiveKit server at ${url}. ${e?.message || ''} ` +
        'If LiveKit runs inside the cluster, its port has to be reachable from this machine.',
      );
      setPhase('error');
    }
  };

  const leave = async () => {
    await roomRef.current?.disconnect();
    roomRef.current = null;
  };

  const toggleMic = async () => {
    const room = roomRef.current;
    if (!room) return;
    setMicBusy(true);
    try {
      await room.localParticipant.setMicrophoneEnabled(!micOn);
      setMicOn(!micOn);
    } catch (e: any) {
      setErr(`The microphone could not start: ${e?.message || 'permission denied'}. Allow microphone access for this site and try again.`);
    }
    setMicBusy(false);
  };

  const sendChat = async () => {
    const room = roomRef.current;
    const t = msg.trim();
    if (!room || !t) return;
    try {
      await room.localParticipant.publishData(new TextEncoder().encode(t), { reliable: true });
      setChat(c => [...c, { from: 'You', text: t, ts: Date.now(), mine: true }]);
      setMsg('');
    } catch (e: any) {
      setErr(`Your message was not sent: ${e?.message || 'unknown error'}`);
    }
  };

  const bots = people.filter(p => p.identity.startsWith('bot-'));

  return (
    <div className="space-y-4 max-w-4xl">
      {!m && (
        <Link href={`/meetings/${id}`} className="text-xs text-slate-500 hover:text-cyan-400 inline-flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" /> Back to the meeting
        </Link>
      )}

      {!m && !loadErr && (
        <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-cyan-500" /></div>
      )}
      {loadErr && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-200">{loadErr}</div>}

      {m && (
        <>
          <PageHeader
            title={`Join: ${m.title}`}
            titleTestId="join-title"
            purpose="Join the meeting room yourself from this browser to talk to the bot or watch it work. For the meeting owner."
            icon={Video}
            storageKey="meeting-join"
            docSlug="08-howto/15-meetings"
            back={{ href: `/meetings/${id}`, label: 'Back to the meeting' }}
            primaryAction={
              m.provider !== 'livekit'
                ? undefined
                : phase === 'connected'
                  ? { label: 'Leave', icon: LogOut, onClick: leave, testId: 'join-leave' }
                  : {
                      label: phase === 'connecting' ? 'Joining…' : phase === 'error' ? 'Try again' : 'Join the room',
                      icon: phase === 'connecting' ? Loader2 : Video,
                      busy: phase === 'connecting',
                      onClick: join,
                      testId: 'join-connect',
                    }
            }
            steps={[
              'Join the room. Your microphone stays off until you turn it on.',
              'Start the bot from the meeting page. It shows up in the room list within a few seconds.',
              'Speak, or type in the room chat. The bot replies when it is asked something in its scope.',
            ]}
          />
          {m.provider !== 'livekit' ? (
            <p className="text-sm text-slate-400">This meeting runs on {m.provider}. Join it from {m.provider} itself.</p>
          ) : (
            <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3" data-testid="join-panel" data-phase={phase}>
              <p className="text-xs text-slate-400">
                You join as yourself. Your microphone stays off until you turn it on. The bot, once started from the meeting page,
                shows up in the list below.
              </p>
              {err && <div role="alert" data-testid="join-error" className="px-3 py-2 rounded bg-red-500/10 border border-red-500/30 text-red-300 text-xs break-words">{err}</div>}
              {phase === 'connected' && (
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={toggleMic}
                    disabled={micBusy}
                    data-testid="join-mic"
                    data-on={micOn ? 'true' : 'false'}
                    className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border disabled:opacity-50 ${micOn ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200' : 'border-slate-700 text-slate-200 hover:bg-slate-800'}`}
                  >
                    {micOn ? <Mic className="w-4 h-4" /> : <MicOff className="w-4 h-4" />}
                    {micOn ? 'Mic on, tap to mute' : 'Turn on mic'}
                  </button>
                </div>
              )}

              {phase === 'connected' && (
                <div className="grid md:grid-cols-2 gap-3">
                  <div className="rounded border border-slate-800 p-3" data-testid="join-participants">
                    <p className="text-xs text-slate-400 mb-2 flex items-center gap-1"><Users className="w-3.5 h-3.5" /> In the room ({people.length})</p>
                    <ul className="space-y-1">
                      {people.map(p => (
                        <li key={p.identity} className="text-xs flex items-center gap-1.5" data-testid="join-participant" data-bot={p.identity.startsWith('bot-') ? 'true' : 'false'}>
                          {p.identity.startsWith('bot-') ? <Bot className="w-3.5 h-3.5 text-cyan-300" /> : <User className="w-3.5 h-3.5 text-slate-400" />}
                          <span className="text-slate-200 truncate">{p.name}</span>
                          {p.speaking && <span className="text-[10px] text-emerald-300">speaking</span>}
                        </li>
                      ))}
                    </ul>
                    {bots.length === 0 && (
                      <p className="text-[11px] text-slate-500 mt-2">The bot is not here yet. Start it from the meeting page and it joins within a few seconds.</p>
                    )}
                  </div>
                  <div className="rounded border border-slate-800 p-3 flex flex-col min-h-[12rem]">
                    <p className="text-xs text-slate-400 mb-2">Room chat</p>
                    <div className="flex-1 space-y-1 max-h-64 overflow-y-auto" data-testid="join-chat">
                      {chat.length === 0 && <p className="text-[11px] text-slate-500">No messages yet. The bot posts here when it joins and when it replies.</p>}
                      {chat.map((c, i) => (
                        <p key={i} className="text-xs break-words" data-testid="join-chat-line">
                          <span className={c.mine ? 'text-slate-400' : 'text-cyan-300'}>{c.from}:</span>{' '}
                          <span className="text-slate-200">{c.text}</span>
                        </p>
                      ))}
                    </div>
                    <div className="flex gap-2 mt-2">
                      <input
                        value={msg}
                        onChange={e => setMsg(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && sendChat()}
                        aria-label="Message the room"
                        data-testid="join-chat-input"
                        placeholder="Message the room"
                        className="flex-1 min-w-0 px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
                      />
                      <button onClick={sendChat} disabled={!msg.trim()} data-testid="join-chat-send" className="px-2.5 py-1 text-xs rounded bg-cyan-600 text-white disabled:opacity-50" aria-label="Send message">
                        <Send className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                </div>
              )}
              <div ref={audioRef} className="hidden" aria-hidden />
            </div>
          )}
        </>
      )}
    </div>
  );
}
