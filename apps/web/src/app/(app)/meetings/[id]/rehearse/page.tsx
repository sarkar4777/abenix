'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, FlaskConical, Loader2, Shield } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import PageHeader from '@/components/layout/PageHeader';
import RehearsalPanel, { type RehearsalMeeting } from '@/components/meetings/RehearsalPanel';

export default function RehearsePage() {
  const { id } = useParams<{ id: string }>();
  usePageTitle('Rehearse meeting');
  const [m, setM] = useState<RehearsalMeeting | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await apiFetch<RehearsalMeeting>(`/api/meetings/${id}`, { silent: true });
    if (r.error) setErr(r.errorDetail?.code === 404 ? 'This meeting does not exist or is not yours.' : `Could not load the meeting. ${r.error}`);
    setM(r.data);
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4 max-w-4xl">
      {!m && (
        <Link href={`/meetings/${id}`} className="text-xs text-slate-500 hover:text-cyan-400 inline-flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" /> Back to the meeting
        </Link>
      )}
      {loading ? (
        <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-violet-400" /></div>
      ) : !m ? (
        <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-200 space-y-2">
          <p>{err || 'Meeting not found.'}</p>
          <div className="flex gap-3 text-xs">
            <button onClick={load} className="underline">Try again</button>
            <Link href="/meetings" className="underline">All meetings</Link>
          </div>
        </div>
      ) : (
        <>
          <PageHeader
            title={`Rehearse: ${m.title}`}
            titleTestId="rehearse-title"
            purpose="Type questions at the meeting bot to see how it answers before the real call. Nothing is said in a real room. For the meeting owner."
            icon={FlaskConical}
            iconClassName="text-violet-300"
            storageKey="meeting-rehearse"
            docSlug="08-howto/15-meetings"
            back={{ href: `/meetings/${id}`, label: 'Back to the meeting' }}
            primaryAction={{ label: 'Edit the scope', icon: Shield, href: `/meetings/${id}` }}
            steps={[
              'Start a rehearsal. The bot uses the same scope and persona notes as the real meeting.',
              'Type what a person in the call might ask. Each line shows if it was inside the scope.',
              'Questions it hands back show up for you to answer, just like in a live call.',
              'Not happy with an answer? Change the scope on the meeting page and try again.',
            ]}
          />
          <RehearsalPanel meeting={{ ...m, scope_allow: m.scope_allow || [], scope_defer: m.scope_defer || [], persona_scopes: m.persona_scopes || [] }} />
        </>
      )}
    </div>
  );
}
