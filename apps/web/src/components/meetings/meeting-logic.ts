// Why a meeting button is disabled, in plain words. Null means go.

export interface MeetingLike {
  status: string;
  provider: string;
  scope_allow: string[];
  summary?: string | null;
  bot_status?: string | null;
  finalized?: boolean;
  ended_at?: string | null;
}

export interface ReadinessLike {
  livekit_ready: boolean;
}

export const ENDED = ['done', 'killed', 'failed'];

export function startBlockReason(m: MeetingLike, r: ReadinessLike | null): string | null {
  if (!(m.scope_allow || []).length) return 'Add at least one topic the bot may answer first. Use Edit under Bot scope.';
  if (m.provider === 'livekit' && r && !r.livekit_ready) return 'Live meetings need the LiveKit keys. Rehearse instead, or ask an admin to set them.';
  return null;
}

export function joinBlockReason(m: MeetingLike, r: ReadinessLike | null): string | null {
  if (m.provider !== 'livekit') return `Join this meeting from ${m.provider} itself.`;
  if (r && !r.livekit_ready) return 'Joining needs the LiveKit keys. Ask an admin to set them.';
  if (ENDED.includes(m.status)) return 'This meeting has ended.';
  return null;
}

export function rehearseBlockReason(m: MeetingLike): string | null {
  if (m.status === 'live') return 'The bot is in the live meeting right now. Rehearse before or after it.';
  return null;
}

const SUMMARY_WAIT_MS = 2 * 60_000;

// what the summary card says once the meeting is over
export function summaryState(m: MeetingLike, now = Date.now()): 'summary' | 'writing' | 'none' | null {
  if (!ENDED.includes(m.status)) return null;
  if (m.summary) return 'summary';
  if (m.finalized) return 'none';
  // a bot that never reports back, say after a restart, is not waited on forever
  const ended = m.ended_at ? Date.parse(m.ended_at) : 0;
  if (!ended || now - ended > SUMMARY_WAIT_MS) return 'none';
  return 'writing';
}
