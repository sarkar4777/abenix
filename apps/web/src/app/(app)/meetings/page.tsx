'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Plus, Video, Calendar, CheckCircle2, XCircle, Loader2, Radio } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import PageHeader from '@/components/layout/PageHeader';
import MeetingReadiness from '@/components/meetings/MeetingReadiness';

interface Meeting {
  id: string;
  title: string;
  provider: string;
  room: string;
  join_url: string | null;
  status: string;
  scheduled_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  scope_allow: string[];
  scope_defer: string[];
  persona_scopes: string[];
  transcript_count: number;
  decision_count: number;
  deferral_count: number;
  display_name: string;
  summary: string | null;
}

const STATUS_STYLE: Record<string, string> = {
  scheduled: 'bg-slate-500/10 text-slate-300 border-slate-500/20',
  authorized: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
  live: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  done: 'bg-purple-500/10 text-purple-300 border-purple-500/20',
  killed: 'bg-red-500/10 text-red-300 border-red-500/20',
  failed: 'bg-red-500/10 text-red-300 border-red-500/20',
};

export default function MeetingsPage() {
  usePageTitle('Meetings');
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<'upcoming' | 'live' | 'history'>('upcoming');

  const load = async () => {
    setLoading(true);
    setErr(null);
    const r = await apiFetch<Meeting[]>('/api/meetings', { silent: true });
    if (r.error) setErr(`Could not load meetings. ${r.error}`);
    setMeetings(r.data || []);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const createMeeting = async () => {
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const r = await apiFetch<Meeting>('/api/meetings', {
        method: 'POST',
        body: JSON.stringify({ title: newTitle.trim(), provider: 'livekit' }),
      });
      setNewTitle('');
      setShowCreate(false);
      // straight to the new meeting so its scope can be set
      if (r.data?.id) {
        try { sessionStorage.setItem('meeting-created', r.data.id); } catch { /* storage blocked, no next steps then */ }
        router.push(`/meetings/${r.data.id}`);
        return;
      }
      await load();
    } catch (e: any) {
      setErr(`Could not create the meeting. ${e?.message || ''}`.trim());
    }
    setCreating(false);
  };

  const filtered = meetings.filter(m => {
    if (tab === 'upcoming') return ['scheduled', 'authorized'].includes(m.status);
    if (tab === 'live') return m.status === 'live';
    return ['done', 'killed', 'failed'].includes(m.status);
  });

  return (
    <div className="space-y-6 max-w-6xl">
      <PageHeader
        title="Meeting sessions"
        purpose="An agent can sit in a call for you and answer only on the topics you choose. For anyone who wants a stand-in at meetings."
        icon={Video}
        storageKey="meetings"
        docSlug="08-howto/15-meetings"
        primaryAction={{ label: 'New meeting', icon: Plus, onClick: () => setShowCreate(true), testId: 'new-meeting-btn' }}
        steps={[
          { title: 'Create a meeting', body: 'Give it a title. It gets its own room.' },
          { title: 'Set the scope', body: 'List the topics the bot may answer and the ones it must hand back to you.' },
          { title: 'Rehearse it', body: 'Type questions at the bot before the real call. No room or voice needed.' },
          { title: 'Start the bot', body: 'It joins the room, answers within scope and writes a summary at the end.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            The built-in{' '}
            <Link href="/agents?tab=prebuilt" className="text-cyan-400 hover:underline">
              Meeting Representative
            </Link>{' '}
            does this out of the box, and any agent with the meeting tools can too.
          </p>
        }
      />

      <MeetingReadiness />

      {err && (
        <div role="alert" data-testid="meetings-error" className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex flex-wrap gap-2">
          {err}
          <button onClick={load} className="underline">Try again</button>
        </div>
      )}

      {showCreate && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-3">
          <h3 className="text-sm font-medium text-white">New LiveKit meeting</h3>
          <input
            autoFocus
            aria-label="Meeting title"
            data-testid="new-meeting-title"
            type="text"
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') createMeeting();
              if (e.key === 'Escape') { setShowCreate(false); setNewTitle(''); }
            }}
            maxLength={300}
            placeholder="e.g. Weekly standup with client ACME"
            className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
          <p className="text-[11px] text-slate-500">Next you pick the topics the bot may answer. You can rehearse it before the real meeting.</p>
          <div className="flex gap-2">
            <button
              onClick={createMeeting}
              data-testid="new-meeting-create"
              disabled={creating || !newTitle.trim()}
              title={!newTitle.trim() ? 'Give the meeting a title first' : undefined}
              className="px-3 py-1.5 text-xs rounded bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'Create'}
            </button>
            <button
              onClick={() => { setShowCreate(false); setNewTitle(''); }}
              className="px-3 py-1.5 text-xs rounded border border-slate-700/50 text-slate-400 hover:text-white"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-1 border-b border-slate-800/50">
        {(['upcoming', 'live', 'history'] as const).map(k => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm capitalize border-b-2 transition-colors ${
              tab === k
                ? 'border-cyan-500 text-white'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {k}
            {k === 'live' && meetings.some(m => m.status === 'live') && (
              <span className="ml-1.5 inline-flex items-center gap-1 text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              </span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-cyan-500" />
        </div>
      ) : err && meetings.length === 0 ? null : filtered.length === 0 ? (
        <div className="text-center py-16 text-sm text-slate-500" data-testid="meetings-empty">
          {tab === 'upcoming'
            ? 'No upcoming meetings. Click New meeting to create one.'
            : tab === 'live'
              ? 'No meeting is live right now. Start the bot from a meeting to see it here.'
              : 'No finished meetings yet. Ended and stopped meetings show here with their summary.'}
        </div>
      ) : (
        <div className="grid gap-3">
          {filtered.map(m => (
            <Link
              key={m.id}
              href={`/meetings/${m.id}`}
              className="block rounded-lg border border-slate-800/50 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/60 p-4 transition-colors"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-slate-800/70 flex items-center justify-center shrink-0">
                  {m.status === 'live' ? (
                    <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
                  ) : m.status === 'done' ? (
                    <CheckCircle2 className="w-4 h-4 text-purple-300" />
                  ) : m.status === 'killed' || m.status === 'failed' ? (
                    <XCircle className="w-4 h-4 text-red-400" />
                  ) : (
                    <Calendar className="w-4 h-4 text-cyan-300" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-medium text-white truncate max-w-full">{m.title}</h3>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${STATUS_STYLE[m.status] || ''}`}>
                      {m.status}
                    </span>
                    <span className="text-[10px] text-slate-500 uppercase">{m.provider}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(m.scope_allow || []).slice(0, 6).map(t => (
                      <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300/70 border border-emerald-500/20">
                        {t}
                      </span>
                    ))}
                    {(m.scope_allow || []).length === 0 && m.status !== 'scheduled' && (
                      <span className="text-[10px] text-amber-300/70">no scope declared</span>
                    )}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span>{m.transcript_count} lines</span>
                    <span>{m.decision_count} decisions</span>
                    <span className={m.deferral_count > 0 ? 'text-amber-300/70' : ''}>
                      {m.deferral_count} deferrals
                    </span>
                    <span className="ml-auto font-mono text-slate-600 break-all">{m.room}</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
