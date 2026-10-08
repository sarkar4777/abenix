'use client';

import Link from 'next/link';
import { KeyRound, Volume2 } from 'lucide-react';
import { useApi } from '@/hooks/useApi';

export interface Readiness {
  livekit_ready: boolean;
  missing: string[];
  message: string | null;
  configure_url: string | null;
  stt_ready?: boolean;
  stt_message?: string | null;
  tts_ready?: boolean;
  tts_message?: string | null;
  voice_configure_url?: string | null;
  rehearsal_ready?: boolean;
  works_without_keys: string[];
}

export function useMeetingReadiness() {
  return useApi<Readiness>('/api/meetings/readiness');
}

// Says up front what live audio needs, and what works without it.
export default function MeetingReadiness() {
  const { data } = useMeetingReadiness();
  if (!data) return null;
  const voice = [data.stt_message, data.tts_message].filter(Boolean) as string[];
  if (data.livekit_ready && voice.length === 0) return null;
  return (
    <div className="space-y-2">
      {!data.livekit_ready && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-100" role="status" data-testid="meetings-readiness">
          <div className="flex items-start gap-2">
            <KeyRound className="w-4 h-4 mt-0.5 text-amber-300 shrink-0" />
            <div className="min-w-0 space-y-1.5">
              <p>{data.message}</p>
              <p className="text-xs text-amber-200/80 break-words">
                Not set yet: {data.missing.map((k) => <code key={k} className="mx-0.5 text-amber-200">{k}</code>)}
              </p>
              {data.works_without_keys.length > 0 && (
                <p className="text-xs text-amber-200/80">Without them you can still {data.works_without_keys.join(', ')}.</p>
              )}
              {data.configure_url ? (
                <Link href={data.configure_url} className="inline-block text-xs text-cyan-300 hover:underline" data-testid="meetings-configure">
                  Set the LiveKit keys
                </Link>
              ) : (
                <p className="text-xs text-amber-200/80">Ask an admin to set them.</p>
              )}
            </div>
          </div>
        </div>
      )}
      {data.livekit_ready && voice.length > 0 && (
        <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-xs text-sky-100" role="status" data-testid="meetings-voice-readiness">
          <div className="flex items-start gap-2">
            <Volume2 className="w-4 h-4 text-sky-300 shrink-0" />
            <div className="min-w-0 space-y-1">
              {voice.map(v => <p key={v}>{v}</p>)}
              <p className="text-sky-200/70">Rehearsals do not need these keys.</p>
              {data.voice_configure_url ? (
                <Link href={data.voice_configure_url} className="inline-block text-cyan-300 hover:underline">Set the voice keys</Link>
              ) : (
                <p className="text-sky-200/70">Ask an admin to set them.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
