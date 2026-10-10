'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  Activity, AlertTriangle, Archive, Bot, Check, CheckCircle2, ChevronDown, Download, FilePlus2, FileUp, GitBranch, History,
  HelpCircle, ListChecks, Loader2, Lock, Trash2, PowerOff, Rocket, Scale, Send, ShieldAlert, ShieldCheck, Table2, TestTube2, Undo2, Users, Workflow, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import {
  STATE_LABEL, STATE_STYLE, errorsOf, mergeDocs, pickDefault, normProblems, problemPlace, readTryPreload, type MergeResult, type Problem, type RuleDoc, type Tier,
  type Validation, type VersionFull, type VersionSummary,
} from '@/lib/decisions';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import RuleBuilder from '@/components/decisions/RuleBuilder';
import DecisionTable from '@/components/decisions/DecisionTable';
import FactsOutcomes from '@/components/decisions/FactsOutcomes';
import TryPanel from '@/components/decisions/TryPanel';
import TestsTab from '@/components/decisions/TestsTab';
import HistoryTab from '@/components/decisions/HistoryTab';
import FlowView from '@/components/decisions/FlowView';
import MergeDialog from '@/components/decisions/MergeDialog';
import EvaluationsTab from '@/components/decisions/EvaluationsTab';
import { decisionErrorText, tidySummary } from '@/lib/decisionValues';
import DecisionGuide, { docSection, nextStep } from '@/components/decisions/DecisionGuide';
import { SignOffSummary, SoleApproveButton, SoleOperatorDialog, type SignOffInfo } from '@/components/decisions/SignOff';
import GuardedActionDialog from '@/components/decisions/GuardedActionDialog';
import { scrollInMain } from '@/lib/scrollInMain';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';

interface PendingTier { approval_id: string; from_tier: Tier; to_tier: Tier; requested_by_name?: string | null; reason?: string | null; required_signoffs?: number; requested_at?: string | null }
interface Reattest { approval_id: string; version: number; from_tier: Tier; to_tier: Tier; status: string }
interface PendingAction { approval_id: string; kind: 'retire' | 'archive' | 'restore' | string; version?: number | null; reason?: string | null; requested_by_name?: string | null }
interface Waiting { version: number; state: 'proposed' | 'approved'; approval_id?: string | null; proposed_by_name?: string | null; proposed_at?: string | null }
interface Model {
  id: string; key: string; name: string; description: string; risk_tier: Tier; tags: string[]; log_mode: string;
  versions: VersionSummary[]; test_count: number;
  policy: { publish_approvals: { min_approvers: number; exclude_author: boolean; capability: string } };
  pending_tier_change?: PendingTier | null;
  reattest?: Reattest | null;
  pending_action?: PendingAction | null;
  state?: 'in_force' | 'retired' | 'draft_only' | 'never_published';
  in_force_version?: number | null;
  waiting?: Waiting[];
  drafts?: VersionSummary[];
  last_denial?: { approval_id: string; kind: string; version?: number | null; reason?: string | null; by_name?: string | null; at?: string | null } | null;
}
type Tab = 'rules' | 'table' | 'flow' | 'facts' | 'tests' | 'history' | 'evaluations';
type SaveState = 'saved' | 'unsaved' | 'saving' | 'error' | 'conflict';

const DENIED_WHAT: Record<string, string> = {
  decision_publish: 'Publishing', decision_tier_change: 'Lowering the risk tier', decision_reattest: 'The review after the tier was raised',
  decision_retire: 'Retiring', decision_archive: 'Archiving', decision_restore: 'Restoring',
};

const TAB_HELP: Partial<Record<Tab, string>> = {
  rules: 'One rule at a time: when it applies and what it answers',
  table: 'Every rule as a row, the quickest way to type or paste many',
  flow: 'The same rules drawn as a flow chart. Some decisions are built as a flow instead of rules',
  facts: 'Facts are what callers send in, outcomes are the answers it gives back',
  tests: 'Golden tests are cases with the answer they must always give, run before every proposal',
  history: 'Every version and the dates it applies',
  evaluations: 'Answers this decision gave, kept for replay',
};

const TABS: { id: Tab; label: string; icon: typeof Scale; needsBuilder?: boolean }[] = [
  { id: 'rules', label: 'Rules', icon: Scale, needsBuilder: true },
  { id: 'table', label: 'Table', icon: Table2, needsBuilder: true },
  { id: 'flow', label: 'Flow', icon: Workflow },
  { id: 'facts', label: 'Facts and outcomes', icon: ListChecks, needsBuilder: true },
  { id: 'tests', label: 'Golden tests', icon: TestTube2 },
  { id: 'history', label: 'History', icon: History },
  { id: 'evaluations', label: 'Evaluations', icon: Activity },
];

const TIER_ORDER: Tier[] = ['low', 'medium', 'high', 'critical'];
const tierLabel = (t: Tier) => TIER_STYLE[t]?.label ?? t;

export default function DecisionWorkspace() {
  const { key } = useParams<{ key: string }>();
  const decisionKey = decodeURIComponent(key);
  const enc = encodeURIComponent(decisionKey);
  const router = useRouter();
  const search = useSearchParams();
  const { perms } = useMyPermissions();
  const caps = perms?.capabilities;
  const canAuthor = holds(caps, 'decisions.author');
  const canPublish = holds(caps, 'decisions.publish');
  const isAdmin = !!perms?.is_admin;
  // while someone else's sign-off is awaited, look again now and then so the page never goes stale
  const { data: model, mutate: refreshModel, error: modelErr } = useApi<Model>(`/api/decisions/${enc}`, {
    refreshInterval: (r: any) => (r?.data?.pending_action || r?.data?.pending_tier_change ? 15000 : 0),
  });
  const { data: archivedNow } = useApi<{ key: string; name: string }[]>(modelErr ? '/api/decisions?archived=1' : null);
  const wasArchived = (archivedNow || []).find((m) => m.key === decisionKey);
  const { data: refSets } = useApi<{ key: string; name: string; count: number }[]>('/api/decision-reference-sets');
  const [versionNo, setVersionNo] = useState<number | null>(null);
  const [version, setVersion] = useState<VersionFull | null>(null);
  const { data: signoff, mutate: refreshSignoff } = useApi<SignOffInfo>(version ? `/api/decisions/${enc}/versions/${version.version}/sign-off` : null, { dedupingInterval: 0 });
  const [doc, setDoc] = useState<RuleDoc | null>(null);
  const baseDoc = useRef<RuleDoc | null>(null);
  const etag = useRef<string>('');
  const [save, setSave] = useState<SaveState>('saved');
  const [problems, setProblems] = useState<Problem[]>([]);
  const [overlaps, setOverlaps] = useState<any[]>([]);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [tab, setTab] = useState<Tab>(() => {
    const t = search.get('tab');
    return TABS.some((x) => x.id === t) ? (t as Tab) : 'rules';
  });
  const [tryPreload] = useState(() => readTryPreload(decisionKey, search.get('try')));
  const [initialEvaluation] = useState(() => search.get('evaluation'));
  const [justCreated, setJustCreated] = useState(() => search.get('created') === '1');
  const [selectedRule, setSelectedRule] = useState<string | null>(null);
  const [merge, setMerge] = useState<{ who: string; result: MergeResult; theirs: VersionFull } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string; link?: { href: string; label: string }; check?: boolean } | null>(null);
  const [confirmPublish, setConfirmPublish] = useState<any | null>(null);
  const [showTry, setShowTry] = useState(true);
  const [importOpen, setImportOpen] = useState(false);
  const [versionMenu, setVersionMenu] = useState(false);
  const [editingNow, setEditingNow] = useState<{ email: string }[]>([]);
  const [tierAsk, setTierAsk] = useState<Tier | null>(null);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [denialSeen, setDenialSeen] = useState(false);
  // bumped to bring the paste box into view and focus it
  const [pasteFocus, setPasteFocus] = useState(0);
  const [soleOpen, setSoleOpen] = useState<null | { id: string; title: string }>(null);
  const [retireOpen, setRetireOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingContent = useRef<any>(null);

  const readOnly = !version || version.state !== 'draft' || !canAuthor;

  useEffect(() => {
    if (!model || versionNo !== null) return;
    const q = Number(search.get('version'));
    setVersionNo(q && model.versions.some((v) => v.version === q) ? q : pickDefault(model.versions));
  }, [model, versionNo, search]);

  const load = useCallback(async (n: number) => {
    const r = await apiFetch<VersionFull>(`/api/decisions/${enc}/versions/${n}`, { throwOnError: false });
    if (!r.data) return;
    setVersion(r.data);
    etag.current = r.data.etag;
    const d = r.data.authoring ? structuredClone(r.data.authoring) : null;
    setDoc(d);
    baseDoc.current = d ? structuredClone(d) : null;
    setSave('saved');
    setValidation(r.data.validation ? { ...r.data.validation, problems: normProblems(r.data.validation.problems) } : null);
    setEditingNow(r.data.editing_now || []);
    if (!r.data.authoring) setTab((t) => (TABS.find((x) => x.id === t)?.needsBuilder ? 'flow' : t));
  }, [enc]);

  useEffect(() => {
    if (versionNo) {
      load(versionNo);
      const url = new URL(window.location.href);
      url.searchParams.set('version', String(versionNo));
      url.searchParams.delete('try');
      url.searchParams.delete('created');
      window.history.replaceState(null, '', url.toString());
    }
  }, [versionNo, load]);

  // validation as the author types
  useEffect(() => {
    if (!doc) { setProblems([]); return; }
    const t = setTimeout(async () => {
      const r = await apiFetch<{ problems: Problem[]; overlaps?: any[] }>(`/api/decisions/${enc}/check`, {
        method: 'POST', body: JSON.stringify({ authoring: doc }), throwOnError: false, silent: true,
      });
      if (r.data) { setProblems(normProblems(r.data.problems)); setOverlaps(r.data.overlaps ?? []); }
    }, 300);
    return () => clearTimeout(t);
  }, [doc, enc]);

  // presence, so two authors know about each other before they collide
  useEffect(() => {
    if (!version || version.state !== 'draft') return;
    const beat = async () => {
      const r = await apiFetch<{ editing_now: { email: string }[]; etag: string }>(`/api/decisions/${enc}/versions/${version.version}/presence`, { method: 'POST', throwOnError: false, silent: true });
      if (r.data) setEditingNow(r.data.editing_now);
      else refreshModel();
    };
    beat();
    const i = setInterval(beat, 20000);
    return () => clearInterval(i);
  }, [version, enc]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (save === 'unsaved' || save === 'saving') { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [save]);

  const persist = useCallback(async (body: Record<string, any>) => {
    if (!version) return;
    setSave('saving');
    const r = await apiFetch<VersionFull & { problems: Problem[] }>(`/api/decisions/${enc}/versions/${version.version}`, {
      method: 'PUT', body: JSON.stringify(body), headers: { 'If-Match': etag.current }, throwOnError: false, silent: true,
    });
    if (r.data) {
      etag.current = r.data.etag;
      baseDoc.current = r.data.authoring ? structuredClone(r.data.authoring) : null;
      setVersion((v) => (v ? { ...v, ...r.data!, authoring: v.authoring && body.authoring ? body.authoring : r.data!.authoring } : r.data!));
      setValidation(null);
      setSave('saved');
      return;
    }
    if (r.errorDetail?.error_code === 'STALE_DRAFT') {
      const theirs = (r.errorDetail.details as any)?.current as VersionFull;
      const who = theirs?.editing_now?.[0]?.email || 'Someone';
      if (theirs?.authoring && baseDoc.current && body.authoring) {
        setMerge({ who, theirs, result: mergeDocs(baseDoc.current, body.authoring, theirs.authoring) });
      } else {
        setNotice({ ok: false, text: `${who} saved this draft first. Reload to see their version.` });
      }
      setSave('conflict');
      return;
    }
    setSave('error');
    setNotice({ ok: false, text: r.error || 'Could not save' });
  }, [version, enc]);

  const onDoc = useCallback((d: RuleDoc) => {
    setDoc(d);
    setSave('unsaved');
    setNotice((n) => (n?.check ? null : n));
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => persist({ authoring: d }), 1200);
  }, [persist]);

  function onFlowContent(jdm: any) {
    pendingContent.current = jdm;
    setSave('unsaved');
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => persist({ content: pendingContent.current }), 1500);
  }

  async function setVersionField(body: Record<string, any>) {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    await persist({ ...(doc ? { authoring: doc } : {}), ...body });
  }

  // a refusal in plain words, with what to do about it
  const fail = (r: any, fallback?: string) => setNotice({ ok: false, text: decisionErrorText(r?.errorDetail?.error_code, r?.error || fallback, r?.errorDetail?.details) });

  async function act(name: string, path: string, body: any = {}, method = 'POST') {
    if (!version) return null;
    setBusy(name);
    setNotice(null);
    if (save === 'unsaved' && doc) { if (saveTimer.current) clearTimeout(saveTimer.current); await persist({ authoring: doc }); }
    const r = await apiFetch<any>(`/api/decisions/${enc}/versions/${version.version}/${path}`, { method, body: JSON.stringify(body), throwOnError: false });
    setBusy(null);
    return r;
  }

  // the result shows once: in the notice, and the bar's own line stays hidden while it is up
  async function check() {
    const r = await act('check', 'validate');
    if (r?.data) { setValidation({ ...r.data, problems: normProblems(r.data.problems) }); setNotice({ ok: r.data.ok, text: tidySummary(r.data.summary), check: true }); }
    else if (r?.error) fail(r);
  }
  async function propose() {
    const r = await act('propose', 'propose', {});
    if (r?.data) {
      const need = r.data.approvals_needed;
      setNotice(need
        ? { ok: true, text: `Sent for sign-off. ${need} approval${need > 1 ? 's are' : ' is'} needed.`, link: { href: '/approvals', label: 'Open Approvals' } }
        : { ok: true, text: 'Approved. You can publish it now.' });
      await load(version!.version); refreshModel(); refreshSignoff();
    } else if (r?.error) {
      if (r.errorDetail?.details) setValidation(r.errorDetail.details as any);
      fail(r);
      if (r.errorDetail?.error_code === 'VALIDATION_FAILED') setTab('tests');
    }
  }
  async function withdraw() {
    const r = await act('withdraw', 'withdraw');
    if (r?.data) { setNotice({ ok: true, text: 'Withdrawn. It is a draft again.' }); await load(version!.version); refreshModel(); refreshSignoff(); }
    else if (r?.error) fail(r);
  }
  async function previewPublish() {
    const r = await apiFetch<any>(`/api/decisions/${enc}/versions/${version!.version}/publish-plan`, { throwOnError: false });
    if (r.data) setConfirmPublish(r.data);
    else if (r.error) fail(r);
  }
  async function publish() {
    const r = await act('publish', 'publish', { expected_current: confirmPublish?.current ?? 0 });
    setConfirmPublish(null);
    if (r?.data) { setNotice({ ok: true, text: `Version ${version!.version} is now in force. Agents and apps use it within seconds.` }); await load(version!.version); refreshModel(); refreshSignoff(); }
    else if (r?.error) fail(r);
  }
  // the list's undo says whether bringing it back waits for sign-off
  const archivedHref = () => {
    const ever = !!model && model.versions.some((v) => !!v.published_at);
    const high = model?.risk_tier === 'high' || model?.risk_tier === 'critical';
    return `/decisions?archived=${enc}${ever ? '' : '&never=1'}${ever && high ? '&signoff=1' : ''}`;
  };
  const waitNote = (what: string) => `Sent for sign-off. ${what} once someone who can approve signs it on Approvals. Until then nothing changes.`;
  // the only approver signs the request in the same step, with the reason they gave
  async function signAloneNow(approvalId: string, reason: string): Promise<boolean> {
    const r = await apiFetch(`/api/approvals/${encodeURIComponent(approvalId)}/signoff`, {
      method: 'POST', body: JSON.stringify({ decision: 'approve', reason, sole_operator: true }), throwOnError: false,
    });
    return !r.error;
  }
  async function retire(reason: string): Promise<string | null> {
    const r = await act('retire', 'retire', reason ? { reason } : {});
    const n = version!.version;
    if (r?.errorDetail?.error_code === 'REASON_REQUIRED') return decisionErrorText('REASON_REQUIRED', r.error);
    setRetireOpen(false);
    if (r?.data?.pending) {
      if (signAlone && await signAloneNow(r.data.pending.approval_id, reason)) {
        setNotice({ ok: true, text: `Version ${n} is retired and no longer in force. It is recorded as self-approved with your reason.` });
        await load(n); refreshModel(); refreshSignoff();
        return null;
      }
      setNotice({ ok: true, text: waitNote(`Version ${n} is retired`), link: { href: `/approvals#${r.data.pending.approval_id}`, label: 'Open Approvals' } }); refreshModel(); return null;
    }
    // the answer can be lost after the change is made, so trust what the version says now
    const now = r?.data ? null : await apiFetch<VersionFull>(`/api/decisions/${enc}/versions/${n}`, { throwOnError: false, silent: true });
    if (r?.data || now?.data?.state === 'retired') { setNotice({ ok: true, text: `Version ${n} is retired and no longer in force.` }); await load(n); refreshModel(); }
    else if (r?.error) fail(r);
    return null;
  }
  async function archive(reason: string): Promise<string | null> {
    setBusy('archive');
    const r = await apiFetch<any>(`/api/decisions/${enc}`, { method: 'DELETE', body: JSON.stringify(reason ? { reason } : {}), throwOnError: false });
    setBusy(null);
    if (r.errorDetail?.error_code === 'REASON_REQUIRED') return decisionErrorText('REASON_REQUIRED', r.error);
    setArchiveOpen(false);
    if (r.error) fail(r);
    else if (r.data?.pending && !(signAlone && await signAloneNow(r.data.pending.approval_id, reason))) {
      setNotice({ ok: true, text: waitNote(`${model!.name} is archived`), link: { href: `/approvals#${r.data.pending.approval_id}`, label: 'Open Approvals' } }); refreshModel();
    } else router.push(archivedHref());
    return null;
  }
  async function discardDraft() {
    const n = version!.version;
    setBusy('discard');
    const r = await apiFetch<any>(`/api/decisions/${enc}/versions/${n}`, { method: 'DELETE', throwOnError: false });
    setBusy(null);
    setDiscardOpen(false);
    if (r.error) { fail(r); return; }
    const m = await apiFetch<Model>(`/api/decisions/${enc}`, { throwOnError: false, silent: true });
    refreshModel();
    const left = (m.data?.versions || model!.versions).filter((v) => v.version !== n);
    setVersionNo(left.length ? pickDefault(left) : null);
    setNotice({ ok: true, text: `Draft version ${n} is discarded. Nothing else changed.` });
  }
  async function newDraft(from?: number) {
    setBusy('draft');
    const r = await apiFetch<VersionFull>(`/api/decisions/${enc}/versions`, { method: 'POST', body: JSON.stringify(from ? { from_version: from } : {}), throwOnError: false });
    setBusy(null);
    if (r.data) { await refreshModel(); setVersionNo(r.data.version); setNotice({ ok: true, text: `Draft version ${r.data.version} created from version ${from ?? 'in force'}.` }); }
    else fail(r, 'The draft could not be made. Reload the page and try again.');
  }
  async function setTier(tier: Tier, reason: string): Promise<string | null> {
    setBusy('tier');
    const r = await apiFetch<any>(`/api/decisions/${enc}`, { method: 'PATCH', body: JSON.stringify({ risk_tier: tier, ...(reason ? { reason } : {}) }), throwOnError: false });
    setBusy(null);
    if (r.error) {
      if (r.errorDetail?.error_code === 'REASON_REQUIRED') return decisionErrorText('REASON_REQUIRED', r.error);
      setTierAsk(null);
      fail(r);
      return null;
    }
    setTierAsk(null);
    await refreshModel();
    refreshSignoff();
    if (r.data?.pending_tier_change) {
      const p = r.data.pending_tier_change;
      setNotice({ ok: true, text: `Sent for sign-off. The tier stays ${tierLabel(p.from_tier || model!.risk_tier)} until ${p.required_signoffs || 'the needed'} ${p.required_signoffs === 1 ? 'approver agrees' : 'approvers agree'}.`, link: { href: '/approvals', label: 'Open Approvals' } });
    } else {
      const fresh = await apiFetch<Model>(`/api/decisions/${enc}`, { throwOnError: false, silent: true });
      const re = fresh.data?.reattest;
      setNotice({ ok: true, text: re && re.status === 'pending'
        ? `Risk tier is now ${tierLabel(tier)}. Version ${re.version} stays in force and needs a ${tierLabel(tier)}-risk review, shown above. New versions need the ${tierLabel(tier)} tier's sign-off.`
        : `Risk tier is now ${tierLabel(tier)}. It applies to the next version you propose.` });
    }
    return null;
  }
  async function withdrawTierChange() {
    setBusy('tier');
    const r = await apiFetch<any>(`/api/decisions/${enc}/tier-change`, { method: 'DELETE', throwOnError: false });
    setBusy(null);
    if (r.error) fail(r);
    else { setNotice({ ok: true, text: 'The tier change was withdrawn. Nothing changed.' }); refreshModel(); }
  }
  async function exportJson(full: boolean) {
    const r = await apiFetch<any>(`/api/decisions/${enc}/export?version=${version!.version}${full ? '&full=1' : ''}`, { throwOnError: false });
    if (!r.data) { setNotice({ ok: false, text: r.error || 'Could not export' }); return; }
    const payload = full ? r.data : r.data.format === 'rules' ? r.data.rules : r.data.content;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = full ? `${decisionKey}.json` : `${decisionKey}-v${version!.version}-rules.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const selectRule = useCallback((ref: string) => {
    if (!doc) return;
    const r = doc.rules.find((x) => x.key === ref || x.id === ref);
    if (r) { setSelectedRule(r.id); setTab('rules'); }
  }, [doc]);

  const errors = useMemo(() => (version?.state === 'draft' ? errorsOf(problems) : []), [problems, version?.state]);
  const counts = useMemo(() => {
    const c = { rules: 0, facts: 0 };
    for (const p of errors) c[problemPlace(doc, p).tab]++;
    return c;
  }, [errors, doc]);

  function goToProblem(p: Problem) {
    const place = problemPlace(doc, p);
    if (place.tab === 'facts') setTab('facts');
    else { setTab('rules'); if (place.ruleId) setSelectedRule(place.ruleId); }
  }

  if (modelErr) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <Scale className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        {wasArchived ? (
          <div data-testid="decision-was-archived">
            <p className="text-slate-200 font-medium">{wasArchived.name} was archived.</p>
            <p className="text-sm text-slate-400 mt-1">It no longer answers agents and apps. Its versions and golden tests are kept, and it can be restored.</p>
            <Link href="/decisions?show=archived" className="mt-3 inline-block text-cyan-300 text-sm hover:underline">See it under Show archived</Link>
          </div>
        ) : (
          <>
            <p className="text-slate-300">{modelErr}</p>
            <p className="text-xs text-slate-500 mt-1">If it was archived, turn on Show archived on the list to restore it.</p>
            <Link href="/decisions" className="text-cyan-300 text-sm hover:underline">Back to decisions</Link>
          </>
        )}
      </div>
    );
  }
  if (!model || !version) {
    return <div className="max-w-7xl mx-auto px-6 py-8"><div className="h-12 w-64 rounded bg-slate-800/40 animate-pulse mb-4" /><div className="h-96 rounded-xl bg-slate-800/40 animate-pulse" /></div>;
  }

  const live = model.versions.filter((v) => v.state === 'published');
  const drafts = model.versions.filter((v) => v.state === 'draft').sort((a, b) => b.version - a.version);
  const authorNames: Record<string, string> = Object.fromEntries((model.drafts || []).filter((d) => d.author_id && d.author_name).map((d) => [d.author_id!, d.author_name!]));
  const proposed = model.versions.find((v) => v.state === 'proposed');
  const tierLock = proposed ? `Version ${proposed.version} is waiting for sign-off. Withdraw it or let it finish before changing the risk tier.` : null;
  const tabs = TABS.filter((t) => !t.needsBuilder || doc);
  const agentHref = `/builder?tool=decision_evaluate&name=${encodeURIComponent(`${model.name} agent`)}&prompt=${encodeURIComponent(`When a question needs the ${model.name} rules, call decision_evaluate with decision '${model.key}' and the facts from the request. Answer from its result and say which rule applied.`)}`;
  const saveText = { saved: 'All changes saved', unsaved: 'Unsaved changes', saving: 'Saving…', error: 'Not saved', conflict: 'Someone else saved first' }[save];
  const pending = model.pending_tier_change;
  const reattest = model.reattest;
  const pendingAction = model.pending_action;
  const waiting: Waiting[] = model.waiting ?? model.versions.filter((v) => v.state === 'proposed' || v.state === 'approved').sort((a, b) => a.version - b.version).map((v) => ({ version: v.version, state: v.state as 'proposed' | 'approved', approval_id: v.approval_id }));
  const everPublished = model.versions.some((v) => !!v.published_at);
  const needsSignoff = (model.policy?.publish_approvals?.min_approvers ?? 0) > 0;
  // archiving something never live needs nobody else
  const archiveNeedsSignoff = needsSignoff && everPublished;
  const signAlone = !!signoff && !signoff.eligible_approvers.some((e) => String(e.id) !== String(perms?.user_id ?? ''));
  const otherLive = live.filter((v) => v.version !== version.version);
  const guide = nextStep(
    {
      version, doc, errors, testCount: model.test_count, validation, signoff: signoff ?? null, canAuthor, canPublish, isAdmin,
      liveVersion: live.length ? Math.max(...live.map((v) => v.version)) : null, agentHref, meId: perms?.user_id ?? null, decisionKey: model.key, reattest: reattest && reattest.status === 'pending' ? reattest : null,
    },
    {
      openTable: () => { setTab('table'); setPasteFocus((x) => x + 1); },
      openTry: () => {
        setShowTry(true);
        if (!['rules', 'table', 'facts', 'flow'].includes(tab)) setTab('rules');
        setTimeout(() => scrollInMain(document.querySelector('[data-testid="try-panel"]')), 100);
      },
      openTests: () => setTab('tests'),
      showProblem: () => errors[0] && goToProblem(errors[0]),
      check,
      propose,
      publish: previewPublish,
      sole: () => signoff?.approval_id && setSoleOpen({ id: signoff.approval_id, title: `Publish ${model.name} version ${version.version}` }),
      newDraft: () => newDraft(version.version),
      openVersion: (n) => setVersionNo(n),
    },
  );

  return (
    <div className="max-w-[1400px] mx-auto px-4 md:px-6 py-6">
      <PageHeader
        className="mb-4"
        title={model.name}
        purpose="Write, test and sign off one set of business rules, then publish it for agents and apps to call. For the rule owners."
        icon={Scale}
        storageKey="decision-workspace"
        docSlug="08-howto/09-decisions"
        back={{ href: '/decisions', label: 'Decisions' }}
        // until something is in force the rules come first, wiring an agent is a quiet option
        primaryAction={live.length ? { label: 'Use in an agent', href: agentHref, icon: Bot, title: 'Open the builder with a tool that evaluates this decision' } : undefined}
        secondaryAction={live.length ? undefined : { label: 'Use in an agent', href: agentHref, icon: Bot, title: 'It answers agents once a version is published. You can set the agent up now.' }}
        steps={canAuthor ? [
          'Edit the draft under Rules or Table. Changes save as you type and are checked for gaps and overlaps.',
          'Use Try it to run facts through the rules and see which rule fired.',
          'Add golden tests, then propose the version for sign off and publish it.',
          'Agents and apps call it by its key. Answers given inside runs, and any you choose to record, are kept for replay.',
        ] : [
          'Read the rules under Rules, Table or Flow. Each one says when it applies and what it answers.',
          'Use Try it to run facts through the rules and see which rule fired.',
          'Golden tests and History show what each version must answer and who changed it.',
          'Agents and apps call it by its key. Changing the rules needs Author decisions, which an admin can give you.',
        ]}
        meta={
          <>
            {canAuthor ? (
              <span className="inline-flex items-center gap-1" title={tierLock || 'Higher tiers need more sign-off before a new version goes live'} data-testid="decision-tier-wrap">
                <select
                  value={model.risk_tier}
                  onChange={(e) => setTierAsk(e.target.value as Tier)}
                  disabled={busy === 'tier' || !!tierLock}
                  className={`text-[11px] px-1.5 py-0.5 rounded border bg-transparent cursor-pointer disabled:cursor-not-allowed disabled:opacity-70 ${TIER_STYLE[model.risk_tier].chip}`}
                  aria-label="Risk tier"
                  aria-describedby={tierLock ? 'tier-lock' : undefined}
                  data-testid="decision-tier"
                >
                  {TIER_ORDER.map((t) => <option key={t} value={t} className="bg-slate-900 text-white">{TIER_STYLE[t].label} risk</option>)}
                </select>
                {tierLock && <Lock className="w-3 h-3 text-slate-500" aria-hidden="true" />}
                <Link href={docSection('changing-the-risk-tier')} className="text-slate-500 hover:text-cyan-300" title="What the risk tier does and how to change it" aria-label="Help on the risk tier" data-testid="tier-help"><HelpCircle className="w-3.5 h-3.5" /></Link>
                {tierLock && <span id="tier-lock" className="sr-only">{tierLock}</span>}
              </span>
            ) : (
              <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[model.risk_tier].chip}`}>{TIER_STYLE[model.risk_tier].label} risk</span>
            )}
            <span className="text-xs font-mono text-slate-500 break-all">{model.key}</span>
            <div className="relative">
              <button type="button" onClick={() => setVersionMenu((o) => !o)} className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded border ${STATE_STYLE[version.state]}`} data-testid="version-picker" aria-haspopup="listbox">
                <GitBranch className="w-3.5 h-3.5" /> Version {version.version} · {STATE_LABEL[version.state]} <ChevronDown className="w-3 h-3" />
              </button>
              {versionMenu && (
                <ul className="absolute z-40 mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-700 bg-slate-900 shadow-xl py-1" role="listbox">
                  {[...model.versions].sort((a, b) => b.version - a.version).map((v) => (
                    <li key={v.id}>
                      <button type="button" onClick={() => { setVersionMenu(false); setVersionNo(v.version); }} className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-slate-800 ${v.version === version.version ? 'text-white' : 'text-slate-300'}`}>
                        <span className="w-8">v{v.version}</span>
                        <span className={`text-[10px] px-1.5 rounded border ${STATE_STYLE[v.state]}`}>{STATE_LABEL[v.state]}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {editingNow.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs text-amber-300" data-testid="also-editing"><Users className="w-3.5 h-3.5" /> {editingNow.map((e) => e.email).join(', ')} also editing</span>
            )}
          </>
        }
      />

      {!canAuthor && (
        <ViewOnlyBanner testId="decision-view-only">
          You can read these rules, run Try it and export them. People with Author decisions change them, and people with Publish decisions put a version in force. Ask an admin for the right under Admin, Permissions.
        </ViewOnlyBanner>
      )}

      {tierLock && canAuthor && (
        <p className="mb-3 -mt-2 text-[11px] text-slate-500 flex items-center gap-1" data-testid="tier-lock-note"><Lock className="w-3 h-3" /> The risk tier can&apos;t change while version {proposed!.version} waits for sign-off.</p>
      )}

      {pending && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100" role="status" data-testid="pending-tier-change">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span className="flex-1 min-w-[220px]">
            Lowering the risk tier from {tierLabel(pending.from_tier)} to {tierLabel(pending.to_tier)} is waiting for sign-off{pending.requested_by_name ? `, asked by ${pending.requested_by_name}` : ''}. Until it is approved the tier stays {tierLabel(pending.from_tier)}.
            {pending.reason && <span className="block text-xs text-amber-200/80">Reason: “{pending.reason}”</span>}
          </span>
          <SoleApproveButton approvalId={pending.approval_id} title={`Lower ${model.name} from ${tierLabel(pending.from_tier)} to ${tierLabel(pending.to_tier)} risk`} onDone={() => { setNotice({ ok: true, text: 'Approved and recorded as self-approved. The tier has changed.' }); refreshModel(); refreshSignoff(); }} testId="tier-change-sole" />
          <Link href={`/approvals#${pending.approval_id}`} className="text-cyan-300 hover:underline text-xs">Open Approvals</Link>
          {canAuthor && <button type="button" onClick={withdrawTierChange} disabled={busy === 'tier'} className="text-xs text-slate-300 hover:text-white underline" data-testid="tier-change-withdraw">Withdraw the change</button>}
        </div>
      )}

      {reattest && reattest.status === 'pending' && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100" role="status" data-testid="reattest-notice">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span className="flex-1 min-w-[220px]">
            Version {reattest.version} is in force but was approved under {tierLabel(reattest.from_tier)} risk. It needs a {tierLabel(reattest.to_tier)}-risk review. It keeps answering while the review waits.
          </span>
          <SoleApproveButton approvalId={reattest.approval_id} title={`Review ${model.name} version ${reattest.version} at ${tierLabel(reattest.to_tier)} risk`} onDone={() => { setNotice({ ok: true, text: `Version ${reattest.version} is reviewed at ${tierLabel(reattest.to_tier)} risk and recorded as self-approved.` }); refreshModel(); refreshSignoff(); }} testId="reattest-sole" />
          <Link href={`/approvals#${reattest.approval_id}`} className="text-cyan-300 hover:underline text-xs" data-testid="reattest-open">Open the review</Link>
        </div>
      )}

      {justCreated && !live.length && (
        <NextSteps
          className="mb-4"
          title="Decision created. Where it can be used"
          onDismiss={() => setJustCreated(false)}
          testId="decision-next-steps"
          steps={[
            { id: 'paste', label: 'Paste rules from Excel', hint: 'Opens the paste box in the Table tab. Copy the rows with their header row.', icon: Table2, onClick: () => { setTab('table'); setPasteFocus((x) => x + 1); } },
            { id: 'tests', label: 'Add golden tests', hint: 'Pin the answers it must always give before you publish.', icon: TestTube2, onClick: () => setTab('tests') },
            { id: 'agent', label: 'Use in an agent', hint: 'Open the builder with a tool that evaluates this decision.', icon: Bot, href: agentHref },
          ]}
        />
      )}

      {pendingAction && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100" role="status" data-testid="pending-action">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span className="flex-1 min-w-[220px]">
            {pendingAction.kind === 'retire' ? `Retiring version ${pendingAction.version ?? ''}` : pendingAction.kind === 'archive' ? 'Archiving this decision' : 'Restoring this decision'} is waiting for sign-off{pendingAction.requested_by_name ? `, asked by ${pendingAction.requested_by_name}` : ''}. Nothing changes until it is approved.
            {pendingAction.reason && <span className="block text-xs text-amber-200/80">Reason: “{pendingAction.reason}”</span>}
          </span>
          <SoleApproveButton approvalId={pendingAction.approval_id} title={`${pendingAction.kind === 'retire' ? 'Retire' : pendingAction.kind === 'archive' ? 'Archive' : 'Restore'} ${model.name}`} onDone={async () => { setNotice({ ok: true, text: 'Approved and recorded as self-approved. It is done.' }); if (pendingAction.kind === 'archive') router.push(archivedHref()); else { await load(version.version); refreshModel(); } }} testId="pending-action-sole" />
          <Link href={`/approvals#${pendingAction.approval_id}`} className="text-cyan-300 hover:underline text-xs">Open Approvals</Link>
        </div>
      )}

      {model.last_denial && (model.last_denial.version == null || model.last_denial.version === version.version) && !denialSeen && (
        <div className="mb-3 flex flex-wrap items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="status" data-testid="last-denial">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="flex-1 min-w-[220px]">
            {DENIED_WHAT[model.last_denial.kind] || 'A request'}{model.last_denial.version ? ` for version ${model.last_denial.version}` : ''} was denied{model.last_denial.by_name ? ` by ${model.last_denial.by_name}` : ''}{model.last_denial.at ? ` on ${model.last_denial.at.slice(0, 10)}` : ''}.
            {model.last_denial.reason ? <span className="block text-xs text-rose-200/90">Their reason: “{model.last_denial.reason}”</span> : null}
          </span>
          <button type="button" onClick={() => setDenialSeen(true)} className="text-xs text-rose-200 hover:text-white">Dismiss</button>
        </div>
      )}

      {waiting.length > 0 && !(waiting.length === 1 && waiting[0].version === version.version) && (
        <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-slate-200" role="status" data-testid="waiting-banner">
          <p className="flex items-center gap-2 text-amber-100"><ShieldAlert className="w-4 h-4 shrink-0" /> {waiting.length === 1 ? 'One version is' : `${waiting.length} versions are`} on the way to being published.</p>
          <ul className="mt-1 ml-6 space-y-1">
            {waiting.map((w) => (
              <li key={w.version} className="flex flex-wrap items-center gap-2 text-xs" data-testid={`waiting-${w.version}`}>
                <span>Version {w.version} {w.state === 'approved' ? 'is approved and ready to publish' : 'is waiting for sign-off'}{w.proposed_by_name ? `, proposed by ${w.proposed_by_name}` : ''}{w.proposed_at ? ` on ${w.proposed_at.slice(0, 10)}` : ''}.</span>
                {w.version !== version.version && <button type="button" onClick={() => setVersionNo(w.version)} className="text-cyan-300 hover:underline">Open version {w.version}</button>}
              </li>
            ))}
          </ul>
          {waiting.length > 1 && <p className="mt-1 ml-6 text-[11px] text-slate-400">Only one version is in force at a time, and publishing one replaces the version in force. Open the ones you no longer want and withdraw them.</p>}
        </div>
      )}

      {version.state !== 'draft' && drafts.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-300" data-testid="draft-pointer">
          <FilePlus2 className="w-4 h-4 text-cyan-400" />
          <span className="flex-1">
            {drafts.length === 1 ? `Version ${drafts[0].version} is a draft` : `There are ${drafts.length} drafts, the newest is version ${drafts[0].version}`}, with changes that are not in force yet.
          </span>
          <button type="button" onClick={() => setVersionNo(drafts[0].version)} className="text-cyan-300 hover:underline text-sm" data-testid="open-draft">Open version {drafts[0].version}</button>
        </div>
      )}

      <DecisionGuide guide={guide} />

      <LifecycleBar
        version={version} model={model} live={live} canAuthor={canAuthor} canPublish={canPublish} isAdmin={isAdmin} busy={busy} saveText={saveText} save={save}
        errors={errors} doc={doc} onProblem={goToProblem} signoff={signoff ?? null} checkShown={!!notice?.check}
        validation={validation} onCheck={check} onPropose={propose} onWithdraw={withdraw} onPublish={previewPublish} onNewDraft={newDraft}
        onExport={exportJson} onImport={() => setImportOpen(true)} onRetire={() => setRetireOpen(true)} onArchive={() => setArchiveOpen(true)} onDiscard={() => setDiscardOpen(true)} onSignoffChanged={() => refreshSignoff()}
        onSole={() => signoff?.approval_id && setSoleOpen({ id: signoff.approval_id, title: `Publish ${model.name} version ${version.version}` })}
        pendingAction={pendingAction}
      />

      {notice && (
        <div className={`mb-3 flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${notice.ok ? 'bg-emerald-500/10 text-emerald-200' : 'bg-rose-500/10 text-rose-200'}`} role="status" data-testid="workspace-notice">
          {notice.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />}
          <span className="flex-1">{notice.text}{notice.link && <> <Link href={notice.link.href} className="underline hover:text-white">{notice.link.label}</Link></>}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X className="w-4 h-4" /></button>
        </div>
      )}

      {version.state === 'draft' && (
        <VersionPeriod version={version} readOnly={readOnly} onSave={setVersionField} />
      )}

      <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 mb-4" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px ${tab === t.id ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`} data-testid={`tab-${t.id}`} title={TAB_HELP[t.id]}>
            <t.icon className="w-4 h-4" /> {t.label}
            {t.id === 'rules' && counts.rules > 0 && <span className="text-[10px] px-1 rounded bg-rose-500/20 text-rose-300" data-testid="tab-rules-count" title={`${counts.rules} to fix in the rules`}>{counts.rules}</span>}
            {t.id === 'facts' && counts.facts > 0 && <span className="text-[10px] px-1 rounded bg-rose-500/20 text-rose-300" data-testid="tab-facts-count" title={`${counts.facts} to fix in facts and outcomes`}>{counts.facts}</span>}
            {t.id === 'tests' && model.test_count > 0 && <span className="text-[10px] text-slate-500">{model.test_count}</span>}
          </button>
        ))}
        <button type="button" onClick={() => setShowTry((s) => !s)} className="ml-auto text-xs text-slate-400 hover:text-white px-2" aria-pressed={showTry} data-testid="toggle-try">{showTry ? 'Hide' : 'Show'} Try it</button>
      </div>

      {!doc && version.state === 'draft' && (
        <p className="mb-3 text-xs text-slate-400">This draft is authored as a flow, so the rule builder and table do not apply. Start a new draft from a builder version to use them.</p>
      )}
      {readOnly && version.state !== 'draft' && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-400" data-testid="readonly-note">
          <Lock className="w-3.5 h-3.5" />
          <span>Version {version.version} is {STATE_LABEL[version.state].toLowerCase()} and can&apos;t change. {canAuthor ? 'To change the rules, start a new draft from it.' : 'Changing the rules needs Author decisions.'}</span>
          {canAuthor && (
            <button type="button" onClick={() => newDraft(version.version)} disabled={!!busy} className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/10" data-testid="readonly-new-draft">
              <FilePlus2 className="w-3.5 h-3.5" /> New draft from this version
            </button>
          )}
        </div>
      )}

      <div className={`grid gap-4 ${showTry && ['rules', 'table', 'facts', 'flow'].includes(tab) ? '2xl:grid-cols-[minmax(0,1fr)_340px]' : ''}`}>
        <div className="min-w-0">
          {tab === 'rules' && doc && (
            <RuleBuilder doc={doc} onChange={onDoc} problems={problems} overlaps={overlaps} referenceSets={refSets || []} readOnly={readOnly} selectedId={selectedRule} onSelect={setSelectedRule} onPaste={() => { setTab('table'); setPasteFocus((x) => x + 1); }} />
          )}
          {tab === 'table' && doc && <DecisionTable key={`${version.version}-${version.state}`} doc={doc} onChange={onDoc} problems={problems} readOnly={readOnly} focusPaste={pasteFocus} onOpenRule={(id) => { setSelectedRule(id); setTab('rules'); }} />}
          {tab === 'facts' && doc && <FactsOutcomes doc={doc} onChange={onDoc} problems={problems} readOnly={readOnly} />}
          {tab === 'flow' && <FlowView content={version.content} hasBuilder={!!doc} editable={!readOnly} onChangeContent={(j) => { setDoc(null); onFlowContent(j); }} />}
          {tab === 'tests' && <TestsTab decisionKey={decisionKey} version={version.version} validation={validation} onRun={check} canEdit={canAuthor} doc={doc} onOpenTry={() => { setShowTry(true); setTab('rules'); setTimeout(() => scrollInMain(document.querySelector('[data-testid="try-panel"]')), 100); }} />}
          {tab === 'history' && <HistoryTab decisionKey={decisionKey} versions={model.versions} current={version.version} onOpen={(n) => setVersionNo(n)} authors={authorNames} />}
          {tab === 'evaluations' && <EvaluationsTab decisionKey={decisionKey} versions={model.versions} initialEvaluation={initialEvaluation} onOpenVersion={(n) => { setVersionNo(n); setTab('rules'); }} />}
        </div>
        {showTry && ['rules', 'table', 'facts', 'flow'].includes(tab) && (
          <TryPanel decisionKey={decisionKey} version={version.version} doc={doc} live={version.state === 'draft' && !!doc} onSelectRule={selectRule} onSavedTest={refreshModel} canSaveTest={canAuthor} preload={tryPreload} problemCount={version.state === 'draft' ? errors.length : 0} />
        )}
      </div>

      {merge && (
        <MergeDialog
          who={merge.who}
          result={merge.result}
          onTakeTheirs={() => { setMerge(null); load(version.version); }}
          onApply={(d) => { etag.current = merge.theirs.etag; baseDoc.current = structuredClone(merge.theirs.authoring); setMerge(null); setDoc(d); persist({ authoring: d }); }}
        />
      )}
      {importOpen && doc && (
        <ImportDialog decisionKey={decisionKey} version={version.version} etag={etag.current} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); load(version.version); }} />
      )}
      {tierAsk && tierAsk !== model.risk_tier && (
        <TierDialog
          from={model.risk_tier}
          to={tierAsk}
          needNow={model.policy?.publish_approvals?.min_approvers ?? 0}
          liveVersion={live.length ? Math.max(...live.map((v) => v.version)) : null}
          liveSignedAt={(() => { const lv = live.length ? live.reduce((a, b) => (a.version > b.version ? a : b)) : null; return lv ? (lv.attested_under || lv.risk_tier_at_proposal || null) : null; })()}
          busy={busy === 'tier'}
          onClose={() => setTierAsk(null)}
          onConfirm={setTier}
        />
      )}
      {soleOpen && (
        <SoleOperatorDialog approvalId={soleOpen.id} title={soleOpen.title} onClose={() => setSoleOpen(null)} onDone={async () => { setSoleOpen(null); setNotice({ ok: true, text: 'Approved and recorded as self-approved. You can publish it now.' }); await load(version.version); refreshModel(); refreshSignoff(); }} />
      )}
      <ConfirmModal
        open={!!confirmPublish}
        onClose={() => setConfirmPublish(null)}
        onConfirm={confirmPublish?.blocked ? () => setConfirmPublish(null) : publish}
        loading={busy === 'publish'}
        variant="warning"
        icon={Rocket}
        title={confirmPublish?.blocked ? 'This version cannot be published as it is' : `Publish version ${version.version}?`}
        description={
          confirmPublish?.blocked
            ? confirmPublish.blocked
            : [
                `It applies to activity ${confirmPublish?.valid_from ? `from ${confirmPublish.valid_from.slice(0, 10)}` : 'on any date, since it has no start date'}${confirmPublish?.valid_to ? ` until ${confirmPublish.valid_to.slice(0, 10)}` : confirmPublish?.valid_from ? ' with no end date' : ''}.`,
                confirmPublish?.supersede?.length ? ` It replaces version ${confirmPublish.supersede.join(', ')}.` : '',
                confirmPublish?.close?.length ? ` Version ${confirmPublish.close.map((c: any) => `${c.version} will end on ${c.valid_to.slice(0, 10)}`).join(', ')}.` : '',
                ' Past evaluations keep the version they used. This is recorded in the audit log.',
              ].join('')
        }
        confirmLabel={confirmPublish?.blocked ? 'Close' : 'Publish'}
      />
      {retireOpen && (
        <GuardedActionDialog
          kind="retire"
          title={`Retire version ${version.version}?`}
          tier={model.risk_tier}
          needsSignoff={needsSignoff}
          signAlone={signAlone}
          busy={busy === 'retire'}
          onClose={() => setRetireOpen(false)}
          onConfirm={retire}
          effect={
            (otherLive.length
              ? `After this, version ${otherLive.map((v) => v.version).join(' and ')} stays in force for ${otherLive.length === 1 ? 'its' : 'their'} dates.`
              : 'After this, no version is in force. Agents and apps that ask this decision get an answer saying nothing is in force, until you publish another version.') +
            ' Past evaluations keep the version they used, and it stays in History.'
          }
        />
      )}
      {archiveOpen && (
        <GuardedActionDialog
          kind="archive"
          title={`Archive ${model.name}?`}
          tier={model.risk_tier}
          needsSignoff={archiveNeedsSignoff}
          signAlone={signAlone}
          busy={busy === 'archive'}
          onClose={() => setArchiveOpen(false)}
          onConfirm={archive}
          neverLive={!everPublished}
          effect={(everPublished
            ? `It leaves the list and agents and apps can no longer call ${model.key}${live.length ? `, so version ${live.map((v) => v.version).join(', ')} stops answering` : ''}. Its versions, golden tests and past answers are kept, and it can be restored from the list with Show archived.`
            : 'Nothing was ever published, so no agent or app has used it. It leaves the list, and its drafts and golden tests are kept so it can be restored with Show archived.') +
            (waiting.length ? ` ${waiting.length === 1 ? `Version ${waiting[0].version} is` : `Versions ${waiting.map((w) => w.version).join(' and ')} are`} waiting for sign-off. Archiving withdraws ${waiting.length === 1 ? 'that request' : 'those requests'}.` : '')}
        />
      )}
      <ConfirmModal
        open={discardOpen}
        onClose={() => setDiscardOpen(false)}
        onConfirm={discardDraft}
        loading={busy === 'discard'}
        variant="danger"
        icon={Trash2}
        title={`Discard draft version ${version.version}?`}
        description={`Its unpublished changes are deleted. The version in force${live.length ? `, version ${live.map((v) => v.version).join(', ')},` : ''} and every other version stay as they are. This is recorded in the audit log.`}
        confirmLabel="Discard draft"
        confirmTestId="discard-confirm"
      />
    </div>
  );
}

function TierDialog({ from, to, needNow, busy, onClose, onConfirm, liveVersion, liveSignedAt }: {
  from: Tier; to: Tier; needNow: number; busy: boolean; onClose: () => void; onConfirm: (t: Tier, reason: string) => Promise<string | null>; liveVersion?: number | null; liveSignedAt?: Tier | null;
}) {
  const coveredAlready = !!liveSignedAt && TIER_ORDER.indexOf(liveSignedAt) >= TIER_ORDER.indexOf(to);
  const lowering = TIER_ORDER.indexOf(to) < TIER_ORDER.indexOf(from);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const ok = !lowering || reason.trim().length >= 3;
  const desc = lowering
    ? needNow
      ? `Lowering it makes later versions easier to publish, so it needs the sign-off the ${tierLabel(from)} tier asks for: ${needNow} approver${needNow > 1 ? 's' : ''}, not you. Until then the tier stays ${tierLabel(from)}. Approvers see the request in Needs you.`
      : `The ${tierLabel(from)} tier needs no sign-off, so this applies straight away. It is recorded in the audit log with your reason.`
    : `It applies straight away. Versions proposed from now on need the sign-off the ${tierLabel(to)} tier asks for. This is recorded in the audit log.`;
  return (
    <ConfirmModal
      open
      onClose={onClose}
      onConfirm={async () => { if (!ok) return; const e = await onConfirm(to, reason.trim()); if (e) setErr(e); }}
      loading={busy}
      variant="warning"
      icon={lowering ? ShieldAlert : ShieldCheck}
      title={`${lowering ? 'Lower' : 'Raise'} the risk tier from ${tierLabel(from)} to ${tierLabel(to)}?`}
      description={desc}
      confirmLabel={lowering ? (needNow ? 'Ask for sign-off' : 'Lower it') : 'Raise it'}
      confirmDisabled={!ok}
      confirmTestId="tier-confirm"
    >
      {!lowering && liveVersion && (
        <div className="mt-3 rounded-lg border border-slate-700 bg-slate-950/50 p-3 text-xs text-slate-300" data-testid="tier-raise-review">
          <p className="font-medium text-slate-200">Version {liveVersion} is in force</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            {coveredAlready ? (
              <li>It was signed off at {tierLabel(liveSignedAt!)} risk, which already covers {tierLabel(to)}, so no review is needed.</li>
            ) : (
              <>
                <li>{liveSignedAt ? `It was signed off at ${tierLabel(liveSignedAt)} risk, so a review goes to Approvals` : 'A review goes to Approvals'} so someone checks it still fits at {tierLabel(to)} risk.</li>
                <li>It keeps answering while the review waits.</li>
                <li>Approve: it is recorded as reviewed at {tierLabel(to)} risk.</li>
                <li>Deny: what it answers does not change. This page keeps asking for the review until a version signed at {tierLabel(to)} risk replaces it, or it is retired.</li>
              </>
            )}
          </ul>
        </div>
      )}
      {lowering && (
        <div className="mt-3">
          <label htmlFor="tier-reason" className="block text-xs text-slate-400 mb-1">Why it should be lower (required)</label>
          <textarea id="tier-reason" value={reason} onChange={(e) => { setReason(e.target.value); setErr(null); }} rows={3} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic" placeholder="what changed about the risk" data-testid="tier-reason" />
          {!ok && <p className="text-[11px] text-slate-500">Write a reason to continue. It goes on the record.</p>}
          {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
        </div>
      )}
    </ConfirmModal>
  );
}

function VersionPeriod({ version, readOnly, onSave }: { version: VersionFull; readOnly: boolean; onSave: (b: Record<string, any>) => void }) {
  const [note, setNote] = useState(version.change_note);
  useEffect(() => setNote(version.change_note), [version.change_note]);
  return (
    <div className="mb-4 flex flex-wrap items-end gap-4 rounded-xl border border-slate-800 bg-slate-900/30 px-4 py-3" data-testid="version-period">
      <div>
        <div className="text-xs text-slate-400 mb-1">This version applies</div>
        <div className="flex flex-wrap items-center gap-2">
          <input type="date" disabled={readOnly} value={version.valid_from?.slice(0, 10) || ''} onChange={(e) => onSave(e.target.value ? { valid_from: e.target.value } : { clear_valid_from: true })} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white [color-scheme:dark]" aria-label="Version applies from" data-testid="version-valid-from" />
          <span className="text-xs text-slate-500">until</span>
          <input type="date" disabled={readOnly} value={version.valid_to?.slice(0, 10) || ''} onChange={(e) => onSave(e.target.value ? { valid_to: e.target.value } : { clear_valid_to: true })} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white [color-scheme:dark]" aria-label="Version applies until" data-testid="version-valid-to" />
        </div>
        <p className="text-[11px] text-slate-500 mt-0.5">Leave the end open unless the rules stop on a known date.</p>
      </div>
      <div className="flex-1 min-w-[220px]">
        <label className="block text-xs text-slate-400 mb-1" htmlFor="change-note">What changed and why</label>
        <input id="change-note" disabled={readOnly} value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== version.change_note && onSave({ change_note: note })} placeholder="a line for the people who sign it off" className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic" data-testid="change-note" />
      </div>
    </div>
  );
}

function ProblemList({ errors, doc, onProblem }: { errors: Problem[]; doc: RuleDoc | null; onProblem: (p: Problem) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="basis-full" data-testid="problem-list">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-xs text-rose-300 hover:text-rose-200" data-testid="problem-toggle">
        <AlertTriangle className="w-3.5 h-3.5" /> {errors.length} to fix before proposing <ChevronDown className={`w-3 h-3 transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {errors.map((p, i) => (
            <li key={`${p.path}-${i}`}>
              <button type="button" onClick={() => onProblem(p)} className="w-full text-left flex flex-wrap gap-x-2 rounded-md px-2 py-1 text-xs hover:bg-slate-800" data-testid={`problem-${i}`}>
                <span className="text-slate-400 shrink-0">{problemPlace(doc, p).where}</span>
                <span className="text-rose-200">{p.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExportMenu({ onExport }: { onExport: (full: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm';
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu" className={`${btn} text-slate-300 hover:bg-slate-800`} data-testid="export"><Download className="w-4 h-4" /> Export <ChevronDown className="w-3 h-3" /></button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-700 bg-slate-900 shadow-xl py-1">
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onExport(true); }} className="w-full text-left px-3 py-2 hover:bg-slate-800" data-testid="export-full">
            <div className="text-sm text-white">Full decision (rules, tests, tier)</div>
            <div className="text-[11px] text-slate-400">A file you can import here or into another workspace.</div>
          </button>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onExport(false); }} className="w-full text-left px-3 py-2 hover:bg-slate-800" data-testid="export-rules">
            <div className="text-sm text-white">Rules only</div>
            <div className="text-[11px] text-slate-400">The rules of this version as typed JSON.</div>
          </button>
        </div>
      )}
    </div>
  );
}

function LifecycleBar(props: {
  version: VersionFull; model: Model; live: VersionSummary[]; canAuthor: boolean; canPublish: boolean; isAdmin: boolean; busy: string | null;
  saveText: string; save: SaveState; checkShown: boolean; errors: Problem[]; doc: RuleDoc | null; onProblem: (p: Problem) => void; validation: Validation | null; signoff: SignOffInfo | null;
  onCheck: () => void; onPropose: () => void; onWithdraw: () => void; onPublish: () => void; onNewDraft: (from?: number) => void;
  onExport: (full: boolean) => void; onImport: () => void; onRetire: () => void; onArchive: () => void; onSole: () => void; onDiscard: () => void; onSignoffChanged: () => void;
  pendingAction?: PendingAction | null;
}) {
  const { version: v, model, canAuthor, canPublish, busy, signoff } = props;
  const need = signoff?.required ?? model.policy?.publish_approvals?.min_approvers ?? 0;
  const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm disabled:opacity-40';
  const errorCount = props.errors.length;
  const nobody = !!signoff && need > 0 && !signoff.eligible_approvers.length && !signoff.sole_operator_available;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2" data-testid="lifecycle-bar">
      {v.state === 'draft' && (
        <>
          <span className={`text-xs inline-flex items-center gap-1 ${props.save === 'saved' ? 'text-slate-400' : props.save === 'error' || props.save === 'conflict' ? 'text-rose-300' : 'text-amber-300'}`} data-testid="save-state">
            {props.save === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : props.save === 'saved' ? <Check className="w-3.5 h-3.5" /> : null} {props.saveText}
          </span>
          <span className="flex-1" />
          {canAuthor && (
            <>
              <button type="button" onClick={props.onImport} className={`${btn} text-slate-300 hover:bg-slate-800`} data-testid="import-open"><FileUp className="w-4 h-4" /> Import</button>
              <button type="button" onClick={props.onDiscard} disabled={!!busy} className={`${btn} text-slate-400 hover:bg-slate-800 hover:text-rose-200`} title="Delete this draft. Nothing in force changes." data-testid="discard-draft"><Trash2 className="w-4 h-4" /> Discard</button>
              <button type="button" onClick={props.onCheck} disabled={!!busy} className={`${btn} border border-slate-700 text-slate-200 hover:bg-slate-800`} data-testid="check" title="Run the golden tests and look for gaps and overlaps">
                {busy === 'check' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />} Check
              </button>
              <button type="button" onClick={props.onPropose} disabled={!!busy || errorCount > 0} title={errorCount ? 'Fix the problems listed first' : signoff?.policy_text || ''} className={`${btn} bg-cyan-500 text-white hover:bg-cyan-400`} data-testid="propose">
                {busy === 'propose' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} {need ? `Propose for sign-off, ${need} approver${need > 1 ? 's' : ''} needed` : 'Propose, no sign-off needed'}
              </button>
            </>
          )}
        </>
      )}
      {v.state === 'proposed' && (
        <>
          <span className="text-sm text-amber-200">Waiting for sign-off.{signoff?.required ? ` ${signoff.signoffs.filter((s) => (s.decision ?? 'approve') === 'approve').length} of ${signoff.required} so far.` : ''}</span>
          <Link href="/approvals" className="text-sm text-cyan-300 hover:underline">Open Approvals</Link>
          <span className="flex-1" />
          {canAuthor && signoff?.sole_operator_available && signoff.approval_id && (
            <button type="button" onClick={props.onSole} disabled={!!busy} className={`${btn} border border-amber-500/50 text-amber-200 hover:bg-amber-500/10`} data-testid="sole-open">
              <ShieldAlert className="w-4 h-4" /> Approve as the only approver
            </button>
          )}
          {canAuthor && <button type="button" onClick={props.onWithdraw} disabled={!!busy} className={`${btn} text-slate-300 hover:bg-slate-800`} data-testid="withdraw"><Undo2 className="w-4 h-4" /> Withdraw</button>}
        </>
      )}
      {v.state === 'approved' && (
        <>
          <span className="text-sm text-cyan-200">Approved. Publishing makes it the version in force.</span>
          <span className="flex-1" />
          {canAuthor && <button type="button" onClick={props.onWithdraw} disabled={!!busy} className={`${btn} text-slate-300 hover:bg-slate-800`}><Undo2 className="w-4 h-4" /> Withdraw</button>}
          {canPublish ? (
            <button type="button" onClick={props.onPublish} disabled={!!busy} className={`${btn} bg-emerald-600 text-white hover:bg-emerald-500`} data-testid="publish"><Rocket className="w-4 h-4" /> Publish</button>
          ) : (
            <span className="text-xs text-slate-500">Publishing needs Publish decisions, which an admin can give you.</span>
          )}
        </>
      )}
      {v.state === 'rejected' && (
        <>
          <span className="text-sm text-rose-200">This version was denied.</span>
          <span className="flex-1" />
          {canAuthor && <button type="button" onClick={() => props.onNewDraft(v.version)} className={`${btn} border border-slate-700 text-slate-200`}><FilePlus2 className="w-4 h-4" /> New draft from it</button>}
        </>
      )}
      {['published', 'superseded', 'retired'].includes(v.state) && (
        <>
          <span className="text-sm text-slate-300">{v.state === 'published' ? `In force${v.valid_from ? ` from ${v.valid_from.slice(0, 10)}` : ''}${v.valid_to ? ` until ${v.valid_to.slice(0, 10)}` : ''}.` : STATE_LABEL[v.state] + '.'}</span>
          <span className="flex-1" />
          {v.state === 'published' && canPublish && (
            <button type="button" onClick={props.onRetire} disabled={!!busy || props.pendingAction?.kind === 'retire'} className={`${btn} text-slate-300 hover:bg-slate-800 hover:text-rose-200 disabled:opacity-50`} data-testid="retire" title={props.pendingAction?.kind === 'retire' ? 'Retiring is already waiting for sign-off, see the banner above' : 'Stop this version answering'}>
              <PowerOff className="w-4 h-4" /> Retire
            </button>
          )}
          {canAuthor && <button type="button" onClick={() => props.onNewDraft(v.version)} disabled={!!busy} className={`${btn} bg-cyan-500 text-white hover:bg-cyan-400`} data-testid="new-draft"><FilePlus2 className="w-4 h-4" /> New draft</button>}
        </>
      )}
      <ExportMenu onExport={props.onExport} />
      {canPublish && (
        <button type="button" onClick={props.onArchive} disabled={!!busy || props.pendingAction?.kind === 'archive'} className={`${btn} text-slate-400 hover:bg-slate-800 hover:text-rose-200 disabled:opacity-50`} data-testid="archive" title={props.pendingAction?.kind === 'archive' ? 'Archiving is already waiting for sign-off, see the banner above' : 'Take this decision out of use. It can be restored.'}>
          <Archive className="w-4 h-4" /> Archive
        </button>
      )}
      {v.state === 'draft' && errorCount > 0 && <ProblemList errors={props.errors} doc={props.doc} onProblem={props.onProblem} />}
      {signoff && (v.state === 'draft' || v.state === 'proposed') && <div className="basis-full border-t border-slate-800 pt-2"><SignOffSummary info={signoff} isAdmin={props.isAdmin} decisionKey={model.key} onChanged={props.onSignoffChanged} /></div>}
      {signoff && (v.state === 'approved' || ['published', 'superseded', 'retired'].includes(v.state)) && (
        <div className="basis-full border-t border-slate-800 pt-2"><SignOffSummary info={signoff} isAdmin={props.isAdmin} compact /></div>
      )}
      {v.state === 'proposed' && nobody && <p className="basis-full text-[11px] text-slate-500">An admin can let the only approver sign with a reason under Risk and Controls, Tier policies.</p>}
      {props.validation?.returned && v.state === 'draft' && (
        <div className="basis-full rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200" role="status" data-testid="returned-note">
          <span className="font-semibold">Returned for changes.</span> {props.validation.returned.note || 'The reviewer left no reason.'} Make the changes, run Check, then propose it again.
        </div>
      )}
      {props.validation && v.state === 'draft' && props.validation.summary && !props.checkShown && (
        <span className={`basis-full text-xs ${props.validation.ok ? 'text-emerald-300' : 'text-rose-300'}`} role="status" data-testid="validation-summary">{tidySummary(props.validation.summary)}</span>
      )}
    </div>
  );
}

function ImportDialog({ decisionKey, version, etag, onClose, onDone }: { decisionKey: string; version: number; etag: string; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<'merge' | 'replace'>('merge');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  let parsed: any = null;
  let parseErr: string | null = null;
  if (text.trim()) { try { parsed = JSON.parse(text); } catch (e: any) { parseErr = e.message; } }
  async function go() {
    setBusy(true);
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/import`, { method: 'POST', body: JSON.stringify({ payload: parsed, mode, version }), headers: { 'If-Match': etag }, throwOnError: false });
    setBusy(false);
    if (r.error) setErr(r.error);
    else onDone();
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="import-title" className="text-lg font-semibold text-white">Import rules into version {version}</h2>
          <button type="button" onClick={onClose} aria-label="Close"><X className="w-5 h-5 text-slate-400" /></button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <p className="text-sm text-slate-400">Paste typed JSON rules (ruleKey, requiresFacts, when, then, provenance) or a decision model exported from the flow view. To bring in a whole decision with its tests, use Import a decision on the Decisions list.</p>
          <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-950 text-xs">
            <button type="button" onClick={() => setMode('merge')} className={`px-2 py-1 rounded ${mode === 'merge' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'merge'}>Add and update by ruleKey</button>
            <button type="button" onClick={() => setMode('replace')} className={`px-2 py-1 rounded ${mode === 'replace' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'replace'}>Replace everything</button>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono" aria-label="Rules JSON" data-testid="import-json" />
          {(parseErr || err) && <p className="text-xs text-rose-300">{parseErr ? `Not valid JSON: ${parseErr}` : err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-300">Cancel</button>
          <button type="button" onClick={go} disabled={!parsed || busy} title={!parsed ? 'Paste the rules first' : ''} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white disabled:opacity-40" data-testid="import-go">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Import
          </button>
        </div>
      </div>
    </div>
  );
}
