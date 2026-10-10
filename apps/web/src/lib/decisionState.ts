// where a decision stands, in the words its list card uses
import { STATE_STYLE, type VersionSummary } from '@/lib/decisions';

export interface StateRow {
  published: VersionSummary[];
  drafts: VersionSummary[];
  proposed: VersionSummary[];
  latest_version: number;
  state?: 'in_force' | 'retired' | 'draft_only' | 'never_published';
  in_force_version?: number | null;
  waiting?: { version: number; state: 'proposed' | 'approved' }[];
  rejected?: VersionSummary[];
}

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '';
}

// what a card says about where a decision stands, from what the API reports
export function stateChips(m: StateRow): { text: string; cls: string; testId: string }[] {
  const out: { text: string; cls: string; testId: string }[] = [];
  const live = m.published[m.published.length - 1];
  const state = m.state ?? (live ? 'in_force' : m.latest_version && !m.drafts.length && !m.proposed.length ? 'retired' : 'never_published');
  const inForce = m.in_force_version ?? live?.version;
  if (state === 'in_force' && inForce) out.push({ text: `v${inForce} in force${live?.valid_from ? ` from ${when(live.valid_from)}` : ''}`, cls: STATE_STYLE.published, testId: 'chip-in-force' });
  else if (state === 'retired') out.push({ text: 'Retired, nothing in force', cls: STATE_STYLE.retired, testId: 'chip-retired' });
  else out.push({ text: 'Not published yet', cls: 'border-slate-700 text-slate-400', testId: 'chip-unpublished' });
  const waiting = m.waiting ?? m.proposed.map((v) => ({ version: v.version, state: v.state as 'proposed' | 'approved' }));
  for (const w of waiting) {
    out.push(w.state === 'approved'
      ? { text: `v${w.version} approved, ready to publish`, cls: STATE_STYLE.approved, testId: `chip-approved-${w.version}` }
      : { text: `v${w.version} waiting for sign-off`, cls: STATE_STYLE.proposed, testId: `chip-waiting-${w.version}` });
  }
  // a denied latest version is in none of the lists the card gets, so it is named here
  const known = new Set([...m.published, ...m.drafts, ...m.proposed, ...waiting].map((v) => v.version));
  const denied = m.rejected?.map((v) => v.version) ?? (m.latest_version && !known.has(m.latest_version) && state !== 'retired' && !(state === 'in_force' && inForce === m.latest_version) ? [m.latest_version] : []);
  for (const n of denied) out.push({ text: `v${n} denied`, cls: STATE_STYLE.rejected, testId: `chip-denied-${n}` });
  if (m.drafts.length) out.push({ text: `${m.drafts.length} draft${m.drafts.length > 1 ? 's' : ''}`, cls: STATE_STYLE.draft, testId: 'chip-drafts' });
  return out;
}
