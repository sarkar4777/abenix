'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Archive, ArchiveRestore, CheckCircle2, FileJson, Layers, Loader2, Plus, Scale, Search, Sparkles, Upload, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { CLIENT_SAMPLE, KEY_RE, STATE_STYLE, type Tier, type VersionSummary } from '@/lib/decisions';
import { stateChips } from '@/lib/decisionState';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import GuardedActionDialog from '@/components/decisions/GuardedActionDialog';
import { SoleOperatorDialog } from '@/components/decisions/SignOff';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { decisionErrorText } from '@/lib/decisionValues';
import ImportDecisionDialog from '@/components/decisions/ImportDecisionDialog';

interface ModelRow {
  id: string;
  key: string;
  name: string;
  description: string;
  risk_tier: Tier;
  tags: string[];
  updated_at: string | null;
  published: VersionSummary[];
  drafts: VersionSummary[];
  proposed: VersionSummary[];
  latest_version: number;
  state?: 'in_force' | 'retired' | 'draft_only' | 'never_published';
  in_force_version?: number | null;
  waiting?: { version: number; state: 'proposed' | 'approved' }[];
  archived_at?: string | null;
  pending_action?: { kind: string; approval_id?: string; requested_by_name?: string | null } | null;
}

// restoring or archiving something that was live needs sign-off at High and Critical
function restoreNeedsSignoff(m: Pick<ModelRow, 'risk_tier' | 'state'>): boolean {
  const high = m.risk_tier === 'high' || m.risk_tier === 'critical';
  return high && m.state !== 'never_published' && m.state !== 'draft_only';
}


function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '';
}

export default function DecisionsPage() {
  const { perms } = useMyPermissions();
  const canAuthor = holds(perms?.capabilities, 'decisions.author');
  const canView = holds(perms?.capabilities, 'decisions.view');
  const canPublish = holds(perms?.capabilities, 'decisions.publish');
  const [q, setQ] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const { data, isLoading, error, mutate } = useApi<ModelRow[]>(canView ? '/api/decisions' : null);
  // archived ones are fetched to show them, and to say when a search only matches archived decisions
  const { data: archived, isLoading: archLoading, mutate: refreshArchived } = useApi<ModelRow[]>(canView && (showArchived || q.trim() || (data && data.length === 0)) ? '/api/decisions?archived=1' : null, { dedupingInterval: 0 });
  const [creating, setCreating] = useState<null | 'blank' | 'import' | 'example'>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [restoring, setRestoring] = useState<ModelRow | null>(null);
  const [soleRestore, setSoleRestore] = useState<{ id: string; key: string; reason: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string; undo?: string; undoAsks?: boolean; open?: string; approval?: string } | null>(null);

  // arriving from Archive on a decision page
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('show') === 'archived') setShowArchived(true);
    const k = params.get('archived');
    if (!k) return;
    const never = params.get('never') === '1';
    setNotice({
      ok: true,
      text: never ? `Archived ${k}. Nothing was ever published, so no sign-off was needed.` : `Archived ${k}. Agents and apps can no longer call it.`,
      undo: k,
      undoAsks: params.get('signoff') === '1',
    });
    mutate();
    const url = new URL(window.location.href);
    url.searchParams.delete('archived');
    url.searchParams.delete('never');
    url.searchParams.delete('signoff');
    window.history.replaceState(null, '', url.toString());
  }, [mutate]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data || []).filter(
      (m) => !needle || m.name.toLowerCase().includes(needle) || m.key.includes(needle) || m.tags.some((t) => t.toLowerCase().includes(needle)),
    );
  }, [data, q]);
  const archivedRows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (archived || []).filter((m) => !needle || m.name.toLowerCase().includes(needle) || m.key.includes(needle));
  }, [archived, q]);
  const archivedMatches = q.trim() ? archivedRows.length : 0;

  async function restore(key: string, reason: string): Promise<string | null> {
    setBusy(true);
    const r = await apiFetch<any>(`/api/decisions/${encodeURIComponent(key)}/restore`, { method: 'POST', body: JSON.stringify(reason ? { reason } : {}), throwOnError: false });
    setBusy(false);
    if (r.errorDetail?.error_code === 'REASON_REQUIRED') return decisionErrorText('REASON_REQUIRED', r.error);
    setRestoring(null);
    if (r.error) { setNotice({ ok: false, text: decisionErrorText(r.errorDetail?.error_code, r.error) }); return null; }
    if (r.data?.pending) {
      const id = r.data.pending.approval_id;
      const a = id ? await apiFetch<{ sign_alone?: boolean }>(`/api/approvals/${encodeURIComponent(id)}`, { throwOnError: false, silent: true }) : null;
      setNotice({
        ok: true,
        text: a?.data?.sign_alone
          ? `Step 1 of 2 done: restoring ${key} is asked for. You are the only person here who can approve, so step 2 is to sign it yourself, here or on Approvals. Until then it stays archived.`
          : `Sent for sign-off. ${key} comes back once someone who can approve signs it on Approvals. Until then it stays archived.`,
        approval: id,
      });
      if (a?.data?.sign_alone && id) setSoleRestore({ id, key, reason });
      refreshArchived();
      return null;
    }
    // say what is true now, a decision whose only version was retired answers nothing
    const st = r.data?.state;
    const v = r.data?.in_force_version;
    const text = st === 'in_force' || v
      ? `Restored ${key}. Version ${v ?? ''} is in force and answers agents and apps again.`.replace('Version  is', 'Its version in force is')
      : st === 'retired'
        ? `Restored ${key}. It is back on the list, but nothing is in force because its last version was retired. Publish a version to make it answer again.`
        : `Restored ${key}. It is back on the list. Nothing is published yet.`;
    setNotice({ ok: true, text, open: key });
    mutate();
    refreshArchived();
    return null;
  }
  async function undoArchive(key: string) {
    const r = await apiFetch<ModelRow[]>('/api/decisions?archived=1', { throwOnError: false, silent: true });
    const row = (r.data || []).find((x) => x.key === key);
    if (row) setRestoring(row);
  }

  if (perms && !canView) {
    return (
      <NoAccess
        testId="decisions-no-access"
        title="Decisions"
        purpose="Business rules that give the same answer every time, with a trace of why. For the people who own those rules and the agents that apply them."
        icon={Scale}
        need={{ capability: 'decisions.view', label: 'View decisions' }}
        role={perms.role}
      />
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      <PageHeader
        className="mb-6"
        title="Decisions"
        purpose="Business rules that give the same answer every time, with a trace of why. For the people who own those rules and the agents that apply them."
        icon={Scale}
        storageKey="decisions"
        docSlug="08-howto/09-decisions"
        primaryAction={canAuthor
          ? { label: 'New decision', onClick: () => setCreating('blank'), icon: Plus, testId: 'decision-new' }
          : { label: 'Reference sets', href: '/decisions/reference-sets', icon: Layers }}
        secondaryAction={canAuthor ? { label: 'Import a decision file', onClick: () => setImportOpen(true), icon: FileJson, testId: 'decision-import' } : undefined}
        steps={[
          'Write rules in plain terms: the facts that come in and the outcome that goes out. Or paste them from Excel.',
          'Test them against golden cases until every answer is right.',
          'Get a new version signed off and publish it. Old versions stay for replay.',
          'Agents, pipelines and apps ask for an answer by the decision key.',
        ]}
      />

      {perms && !canAuthor && (
        <ViewOnlyBanner testId="decisions-view-only">
          You can open any decision, read its rules and run Try it. People with Author decisions create and change them. Ask an admin for the right under Admin, Permissions.
        </ViewOnlyBanner>
      )}

      {notice && (
        <div className={`mb-4 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-sm ${notice.ok ? 'bg-emerald-500/10 text-emerald-200' : 'bg-rose-500/10 text-rose-200'}`} role="status" data-testid="decisions-notice">
          {notice.ok && <CheckCircle2 className="w-4 h-4" />}
          <span className="flex-1">{notice.text}</span>
          {notice.undo && canPublish && <button type="button" onClick={() => undoArchive(notice.undo!)} disabled={busy} className="text-xs underline hover:text-white" data-testid="decisions-undo-archive">{notice.undoAsks ? 'Undo, ask to restore it' : 'Undo, restore it'}</button>}
          {notice.open && <Link href={`/decisions/${encodeURIComponent(notice.open)}`} className="text-xs underline hover:text-white">Open it</Link>}
          {notice.approval && <Link href={`/approvals#${notice.approval}`} className="text-xs underline hover:text-white" data-testid="decisions-notice-approval">Open Approvals</Link>}
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X className="w-4 h-4" /></button>
        </div>
      )}

      {((data || []).length > 0 || showArchived) && (
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 w-full sm:w-auto sm:flex-1 sm:min-w-[200px] max-w-md">
            <Search className="w-4 h-4 text-slate-500" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, key or tag" className="flex-1 min-w-0 w-full border-0 bg-transparent py-2 text-sm text-white outline-none placeholder:text-slate-500" aria-label="Search decisions" />
          </div>
          <label className="inline-flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="accent-cyan-500" data-testid="decisions-show-archived" />
            Show archived
          </label>
        </div>
      )}
      {!showArchived && q.trim() && archivedMatches > 0 && (
        <p className="mb-3 text-sm text-slate-400" data-testid="archived-matches">
          {archivedMatches === 1 ? '1 archived decision matches' : `${archivedMatches} archived decisions match`} “{q.trim()}”.{' '}
          <button type="button" onClick={() => setShowArchived(true)} className="text-cyan-300 hover:underline" data-testid="archived-matches-show">Show {archivedMatches === 1 ? 'it' : 'them'}</button>
        </p>
      )}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div>
      ) : isLoading && !data ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
      ) : (data || []).length === 0 && !showArchived ? (
        <EmptyState canAuthor={canAuthor} onStart={setCreating} onImport={() => setImportOpen(true)} onArchived={() => setShowArchived(true)} archivedCount={(archived || []).length} />
      ) : rows.length === 0 && !showArchived ? (
        archivedMatches ? null : <p className="text-sm text-slate-500">No decision matches “{q}”.</p>
      ) : (
        <div className="grid gap-3" data-testid="decision-list">
          {rows.map((m) => {
            return (
              <Link key={m.id} href={`/decisions/${encodeURIComponent(m.key)}`} className="block rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-600 transition" data-testid={`decision-row-${m.key}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-semibold text-white">{m.name}</span>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[m.risk_tier]?.chip}`}>{TIER_STYLE[m.risk_tier]?.label} risk</span>
                    </div>
                    <div className="text-xs font-mono text-slate-500 mt-0.5 break-all">{m.key}</div>
                    {m.description && <p className="text-sm text-slate-400 mt-1 line-clamp-2">{m.description}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    {stateChips(m).map((c) => <span key={c.testId} className={`px-2 py-0.5 rounded border ${c.cls}`} data-testid={c.testId}>{c.text}</span>)}
                    {m.pending_action && <span className={`px-2 py-0.5 rounded border ${STATE_STYLE.proposed}`}>{m.pending_action.kind.charAt(0).toUpperCase()}{m.pending_action.kind.slice(1)} waiting for sign-off</span>}
                  </div>
                </div>
              </Link>
            );
          })}
          {showArchived && rows.length === 0 && (data || []).length > 0 && q && <p className="text-sm text-slate-500">No decision in use matches “{q}”.</p>}
          {showArchived && (
            <section className="mt-4" data-testid="decision-archived">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-300 mb-2"><Archive className="w-4 h-4" /> Archived</h2>
              {archLoading && !archived ? (
                <div className="h-16 rounded-xl bg-slate-800/40 animate-pulse" />
              ) : archivedRows.length === 0 ? (
                <p className="text-sm text-slate-500">{q ? `No archived decision matches “${q}”.` : 'Nothing is archived.'}</p>
              ) : (
                <div className="grid gap-2">
                  {archivedRows.map((m) => (
                    <div key={m.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-slate-700 bg-slate-900/30 p-3" data-testid={`decision-archived-${m.key}`}>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-slate-300">{m.name}</span>
                          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[m.risk_tier]?.chip}`}>{TIER_STYLE[m.risk_tier]?.label} risk</span>
                        </div>
                        <div className="text-xs font-mono text-slate-500 break-all">{m.key}</div>
                      </div>
                      {m.pending_action?.kind === 'restore' ? (
                        <span className={`text-[11px] px-2 py-0.5 rounded border ${STATE_STYLE.proposed}`} data-testid={`decision-restore-waiting-${m.key}`}>
                          Restore waiting for sign-off{m.pending_action.requested_by_name ? `, asked by ${m.pending_action.requested_by_name}` : ''}
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Archived. Agents and apps can&apos;t call it.</span>
                      )}
                      {m.pending_action?.kind === 'restore' ? (
                        m.pending_action.approval_id
                          ? <Link href={`/approvals#${m.pending_action.approval_id}`} className="text-xs text-cyan-300 hover:underline">See the request</Link>
                          : null
                      ) : canPublish ? (
                        <button type="button" onClick={() => setRestoring(m)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-700 text-sm text-cyan-300 hover:bg-slate-800" data-testid={`decision-restore-${m.key}`}>
                          <ArchiveRestore className="w-4 h-4" /> Restore
                        </button>
                      ) : (
                        <span className="text-[11px] text-slate-500">Only people who can publish decisions can restore one. Ask an admin.</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {creating && <CreateDialog start={creating} onClose={() => setCreating(null)} />}
      {importOpen && <ImportDecisionDialog onClose={() => setImportOpen(false)} />}
      {soleRestore && (
        <SoleOperatorDialog
          approvalId={soleRestore.id}
          title={`Step 2 of 2: restore ${soleRestore.key}`}
          initialReason={soleRestore.reason}
          onClose={() => setSoleRestore(null)}
          onDone={() => { const k = soleRestore.key; setSoleRestore(null); setNotice({ ok: true, text: `Restored ${k}. It is recorded as self-approved with your reason.`, open: k }); mutate(); refreshArchived(); }}
        />
      )}
      {restoring && (
        <GuardedActionDialog
          kind="restore"
          title={`Restore ${restoring.name}?`}
          tier={restoring.risk_tier}
          needsSignoff={restoreNeedsSignoff(restoring)}
          neverLive={restoring.state === 'never_published' || restoring.state === 'draft_only'}
          busy={busy}
          onClose={() => setRestoring(null)}
          onConfirm={(reason) => restore(restoring.key, reason)}
          effect={`It comes back to the list. ${restoring.published.length ? `Version ${restoring.published[restoring.published.length - 1].version} answers agents and apps again.` : 'Nothing is in force, so it answers nothing until a version is published.'}`}
        />
      )}
    </div>
  );
}

function EmptyState({ canAuthor, onStart, onImport, onArchived, archivedCount = 0 }: { canAuthor: boolean; onStart: (s: 'blank' | 'import' | 'example') => void; onImport: () => void; onArchived: () => void; archivedCount?: number }) {
  const cards = [
    { id: 'example' as const, icon: Sparkles, title: 'Start from an example', text: 'A surcharge rule, ready to test and change.', onClick: () => onStart('example') },
    { id: 'blank' as const, icon: Plus, title: 'Start blank', text: 'Name it, then paste rules from Excel or build them row by row.', onClick: () => onStart('blank') },
    { id: 'file' as const, icon: FileJson, title: 'Import a decision file', text: 'A whole decision exported from here or from Groundwork, with its rules, tests and risk tier.', onClick: onImport },
    { id: 'import' as const, icon: Upload, title: 'Start from JSON rules', text: 'Only the rules, pasted as JSON with ruleKey, when and then, into a new decision.', onClick: () => onStart('import') },
  ];
  return (
    <div className="rounded-2xl border border-dashed border-slate-700 p-6 sm:p-8" data-testid="decision-empty">
      <h2 className="text-lg font-semibold text-white">{archivedCount ? 'No decisions in use' : 'No decisions yet'}</h2>
      {archivedCount > 0 && (
        <p className="text-sm text-amber-200 mt-1" data-testid="decision-empty-archived">
          {archivedCount === 1 ? 'One decision is archived.' : `${archivedCount} decisions are archived.`}{' '}
          <button type="button" onClick={onArchived} className="text-cyan-300 underline hover:text-cyan-200">Show archived</button>
        </p>
      )}
      <p className="text-sm text-slate-400 mt-1 max-w-2xl">
        A decision takes facts, such as a distance and a speed, and returns an outcome, such as stop or carry on, using rules you can read.
        Every answer can be replayed later with the rules that applied then.
      </p>
      {canAuthor ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mt-5">
          {cards.map((c) => (
            <button key={c.id} type="button" onClick={c.onClick} className="text-left rounded-xl border border-slate-700 bg-slate-900/50 p-4 hover:border-cyan-500/50 transition" data-testid={`decision-start-${c.id}`}>
              <c.icon className="w-5 h-5 text-cyan-400 mb-2" />
              <div className="text-sm font-medium text-white">{c.title}</div>
              <div className="text-xs text-slate-400 mt-1">{c.text}</div>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500 mt-4">Creating decisions needs Author decisions. Ask an admin for it.</p>
      )}
      <button type="button" onClick={onArchived} className="mt-4 text-xs text-slate-400 hover:text-white underline">Show archived decisions</button>
    </div>
  );
}

function slugify(s: string) {
  return s.toLowerCase().trim().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 120);
}

interface KeyCheck { available: boolean; valid?: boolean; suggestion: string | null; message?: string; archived?: boolean }

// tells people as they type whether the key is free, with a free one to use if not
function useKeyCheck(key: string) {
  const [state, setState] = useState<{ key: string; res: KeyCheck | null; checking: boolean }>({ key: '', res: null, checking: false });
  useEffect(() => {
    if (!key || !KEY_RE.test(key)) { setState({ key, res: null, checking: false }); return; }
    let off = false;
    setState((s) => ({ ...s, key, checking: true }));
    const t = setTimeout(async () => {
      const r = await apiFetch<KeyCheck>(`/api/decisions/check-key?key=${encodeURIComponent(key)}`, { throwOnError: false, silent: true });
      if (!off) setState({ key, res: r.data ?? null, checking: false });
    }, 300);
    return () => { off = true; clearTimeout(t); };
  }, [key]);
  return state.key === key ? state : { key, res: null, checking: !!key && KEY_RE.test(key) };
}

function CreateDialog({ start, onClose }: { start: 'blank' | 'import' | 'example'; onClose: () => void }) {
  const router = useRouter();
  const [mode, setMode] = useState(start);
  const [name, setName] = useState(start === 'example' ? 'Remote area surcharge' : '');
  const [key, setKey] = useState(start === 'example' ? 'freight.remote.surcharge' : '');
  const [keyTouched, setKeyTouched] = useState(start === 'example');
  const [tier, setTier] = useState<Tier>(start === 'example' ? 'high' : 'low');
  const [description, setDescription] = useState(start === 'example' ? 'Whether a shipment to a remote postcode carries a surcharge.' : '');
  const [json, setJson] = useState(start === 'example' ? JSON.stringify(CLIENT_SAMPLE, null, 2) : '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const effectiveKey = keyTouched ? key : slugify(name);
  const keyOk = KEY_RE.test(effectiveKey);
  const check = useKeyCheck(effectiveKey);
  const taken = !!check.res && check.res.available === false;
  let parsed: any = null;
  let parseErr: string | null = null;
  if (mode !== 'blank' && json.trim()) {
    try {
      parsed = JSON.parse(json);
    } catch (e: any) {
      parseErr = `This is not valid JSON: ${e.message}`;
    }
  }
  const ruleCount = parsed ? (Array.isArray(parsed) ? parsed.length : Array.isArray(parsed?.rules) ? parsed.rules.length : parsed?.ruleKey ? 1 : 0) : 0;
  const why = !name.trim()
    ? 'Give it a name to continue.'
    : !effectiveKey ? 'Give it a key to continue.'
    : !keyOk ? 'Fix the key to continue.'
    : taken ? 'Pick a key that is free.'
    : check.checking ? 'Checking the key…'
    : mode !== 'blank' && !json.trim() ? 'Paste the rules to continue.'
    : mode !== 'blank' && (parseErr || ruleCount === 0) ? 'Fix the rules JSON to continue.'
    : '';
  const ready = !why;

  async function onFile(f: File) {
    setJson(await f.text());
  }

  async function create() {
    setBusy(true);
    setErr(null);
    const r = await apiFetch<{ key: string }>('/api/decisions', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), key: effectiveKey, description, risk_tier: tier, rules: mode === 'blank' ? null : parsed }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(r.error);
    else router.push(`/decisions/${encodeURIComponent(r.data!.key)}?created=1`);
  }

  const keyMsg = !effectiveKey
    ? { cls: 'text-slate-500', text: 'Made from the name. Agents and apps call the decision by this key.' }
    : !keyOk
      ? { cls: 'text-rose-300', text: 'Use lowercase letters, digits, dots, dashes or underscores.' }
      : check.checking
        ? { cls: 'text-slate-500', text: 'Checking whether it is free…' }
        : taken
          ? { cls: 'text-rose-300', text: check.res!.message || `${effectiveKey} is already used.` }
          : check.res?.available
            ? { cls: 'text-emerald-300', text: 'Free to use. Agents and apps call the decision by this key.' }
            : { cls: 'text-slate-500', text: 'Agents and apps call the decision by this key.' };
  const field = 'w-full bg-slate-950 border rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 placeholder:italic';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="new-decision-title">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="new-decision-title" className="text-lg font-semibold text-white">New decision</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div className="inline-flex flex-wrap rounded-lg border border-slate-700 p-0.5 bg-slate-950" role="radiogroup" aria-label="How to start">
            {([['blank', 'Blank'], ['import', 'Import JSON rules'], ['example', 'Surcharge example']] as const).map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={mode === id} onClick={() => { setMode(id); if (id === 'example') { setJson(JSON.stringify(CLIENT_SAMPLE, null, 2)); if (!name) setName('Remote area surcharge'); } }} className={`px-3 py-1.5 text-xs rounded-md ${mode === id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="dn-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
              <input id="dn-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="what people call these rules" className={`${field} border-slate-700`} data-testid="decision-name" autoFocus />
            </div>
            <div>
              <label htmlFor="dn-key" className="block text-sm font-medium text-slate-200 mb-1.5">Key</label>
              <input id="dn-key" value={effectiveKey} onChange={(e) => { setKeyTouched(true); setKey(e.target.value); }} placeholder="made from the name" className={`${field} font-mono placeholder:font-sans ${(!keyOk && effectiveKey) || taken ? 'border-rose-500/60' : 'border-slate-700'}`} aria-invalid={(!keyOk && !!effectiveKey) || taken} aria-describedby="dn-key-help" data-testid="decision-key" />
              <p id="dn-key-help" className={`mt-1 text-xs ${keyMsg.cls}`} data-testid="decision-key-help">
                {keyMsg.text}
                {taken && check.res?.suggestion && (
                  <> <button type="button" onClick={() => { setKeyTouched(true); setKey(check.res!.suggestion!); }} className="text-cyan-300 underline hover:text-cyan-200" data-testid="decision-key-suggestion">Use {check.res.suggestion}</button></>
                )}
              </p>
            </div>
          </div>
          <div>
            <label htmlFor="dn-desc" className="block text-sm font-medium text-slate-200 mb-1.5">What it decides <span className="text-slate-500 font-normal">(optional)</span></label>
            <input id="dn-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="one sentence on the question it answers" className={`${field} border-slate-700`} />
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1.5">Risk tier</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 p-0.5 rounded-lg border border-slate-700 bg-slate-950" role="radiogroup" aria-label="Risk tier">
              {(['low', 'medium', 'high', 'critical'] as Tier[]).map((t) => (
                <button key={t} type="button" role="radio" aria-checked={tier === t} tabIndex={tier === t ? 0 : -1} onKeyDown={(e) => { const order: Tier[] = ['low', 'medium', 'high', 'critical']; const i = order.indexOf(tier); if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); setTier(order[Math.min(3, i + 1)]); } if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); setTier(order[Math.max(0, i - 1)]); } }} onClick={() => setTier(t)} className={`py-1.5 rounded-md text-xs flex items-center justify-center gap-1.5 ${tier === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid={`decision-tier-${t}`}>
                  {tier === t ? <CheckCircle2 className="w-3 h-3" aria-hidden /> : <span className={`w-1.5 h-1.5 rounded-full ${TIER_STYLE[t].dot}`} />} {TIER_STYLE[t].label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-500">Higher tiers need more sign-off before a new version goes live. Raising it later is instant, lowering it needs sign-off.</p>
          </div>
          {mode !== 'blank' && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="dn-json" className="text-sm font-medium text-slate-200">Rules as JSON</label>
                <label className="inline-flex items-center gap-1.5 text-xs text-cyan-300 cursor-pointer hover:underline">
                  <Upload className="w-3.5 h-3.5" /> Upload a file
                  <input type="file" accept=".json,application/json" className="hidden" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
                </label>
              </div>
              <textarea id="dn-json" value={json} onChange={(e) => setJson(e.target.value)} rows={12} spellCheck={false} placeholder="one rule, a list of rules, or an object with a rules list" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono placeholder:text-slate-600 placeholder:italic placeholder:font-sans" data-testid="decision-json" />
              <p className={`mt-1 text-xs ${parseErr ? 'text-rose-300' : 'text-slate-500'}`}>
                {parseErr || (parsed ? `${ruleCount} rule${ruleCount === 1 ? '' : 's'} found. Facts and outcomes are added for you, and anything else the rules carry is kept.` : 'For a whole decision file with tests, use Import a decision on the list instead.')}
              </p>
            </div>
          )}
          {mode === 'blank' && <p className="text-xs text-slate-500">Next you can paste the rules from Excel, header row first, or build them one at a time.</p>}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          {why && <span className="mr-auto text-xs text-slate-400" data-testid="decision-create-why">{why}</span>}
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={create} disabled={!ready || busy} title={why} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="decision-create">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create and open
          </button>
        </div>
      </div>
    </div>
  );
}
