'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  AlertTriangle, ArrowLeft, Check, CheckCircle2, ChevronDown, Download, FilePlus2, FileUp, GitBranch, History,
  ListChecks, Loader2, Rocket, Scale, Send, ShieldCheck, Table2, TestTube2, Undo2, Users, Workflow, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import {
  STATE_LABEL, STATE_STYLE, mergeDocs, type MergeResult, type Problem, type RuleDoc, type Tier,
  type Validation, type VersionFull, type VersionSummary,
} from '@/lib/decisions';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import ConfirmModal from '@/components/ui/ConfirmModal';
import RuleBuilder from '@/components/decisions/RuleBuilder';
import DecisionTable from '@/components/decisions/DecisionTable';
import FactsOutcomes from '@/components/decisions/FactsOutcomes';
import TryPanel from '@/components/decisions/TryPanel';
import TestsTab from '@/components/decisions/TestsTab';
import HistoryTab from '@/components/decisions/HistoryTab';
import FlowView from '@/components/decisions/FlowView';
import MergeDialog from '@/components/decisions/MergeDialog';

interface Model {
  id: string; key: string; name: string; description: string; risk_tier: Tier; tags: string[]; log_mode: string;
  versions: VersionSummary[]; test_count: number;
  policy: { publish_approvals: { min_approvers: number; exclude_author: boolean; capability: string } };
}
type Tab = 'rules' | 'table' | 'flow' | 'facts' | 'tests' | 'history';
type SaveState = 'saved' | 'unsaved' | 'saving' | 'error' | 'conflict';

const TABS: { id: Tab; label: string; icon: typeof Scale; needsBuilder?: boolean }[] = [
  { id: 'rules', label: 'Rules', icon: Scale, needsBuilder: true },
  { id: 'table', label: 'Table', icon: Table2, needsBuilder: true },
  { id: 'flow', label: 'Flow', icon: Workflow },
  { id: 'facts', label: 'Facts and outcomes', icon: ListChecks, needsBuilder: true },
  { id: 'tests', label: 'Golden tests', icon: TestTube2 },
  { id: 'history', label: 'History', icon: History },
];

function pickDefault(vs: VersionSummary[]): number {
  const drafts = vs.filter((v) => v.state === 'draft');
  if (drafts.length) return Math.max(...drafts.map((v) => v.version));
  const live = vs.filter((v) => v.state === 'published');
  if (live.length) return Math.max(...live.map((v) => v.version));
  return Math.max(0, ...vs.map((v) => v.version));
}

export default function DecisionWorkspace() {
  const { key } = useParams<{ key: string }>();
  const decisionKey = decodeURIComponent(key);
  const router = useRouter();
  const search = useSearchParams();
  const { perms } = useMyPermissions();
  const caps = perms?.capabilities;
  const canAuthor = holds(caps, 'decisions.author');
  const canPublish = holds(caps, 'decisions.publish');
  const { data: model, mutate: refreshModel, error: modelErr } = useApi<Model>(`/api/decisions/${encodeURIComponent(decisionKey)}`);
  const { data: refSets } = useApi<{ key: string; name: string; count: number }[]>('/api/decision-reference-sets');
  const [versionNo, setVersionNo] = useState<number | null>(null);
  const [version, setVersion] = useState<VersionFull | null>(null);
  const [doc, setDoc] = useState<RuleDoc | null>(null);
  const baseDoc = useRef<RuleDoc | null>(null);
  const etag = useRef<string>('');
  const [save, setSave] = useState<SaveState>('saved');
  const [problems, setProblems] = useState<Problem[]>([]);
  const [overlaps, setOverlaps] = useState<any[]>([]);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [tab, setTab] = useState<Tab>('rules');
  const [selectedRule, setSelectedRule] = useState<string | null>(null);
  const [merge, setMerge] = useState<{ who: string; result: MergeResult; theirs: VersionFull } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmPublish, setConfirmPublish] = useState<any | null>(null);
  const [showTry, setShowTry] = useState(true);
  const [importOpen, setImportOpen] = useState(false);
  const [versionMenu, setVersionMenu] = useState(false);
  const [editingNow, setEditingNow] = useState<{ email: string }[]>([]);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingContent = useRef<any>(null);

  const readOnly = !version || version.state !== 'draft' || !canAuthor;

  useEffect(() => {
    if (!model || versionNo !== null) return;
    const q = Number(search.get('version'));
    setVersionNo(q && model.versions.some((v) => v.version === q) ? q : pickDefault(model.versions));
  }, [model, versionNo, search]);

  const load = useCallback(async (n: number) => {
    const r = await apiFetch<VersionFull>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${n}`, { throwOnError: false });
    if (!r.data) return;
    setVersion(r.data);
    etag.current = r.data.etag;
    const d = r.data.authoring ? structuredClone(r.data.authoring) : null;
    setDoc(d);
    baseDoc.current = d ? structuredClone(d) : null;
    setSave('saved');
    setValidation(r.data.validation);
    setEditingNow(r.data.editing_now || []);
    if (!r.data.authoring) setTab((t) => (TABS.find((x) => x.id === t)?.needsBuilder ? 'flow' : t));
  }, [decisionKey]);

  useEffect(() => {
    if (versionNo) {
      load(versionNo);
      const url = new URL(window.location.href);
      url.searchParams.set('version', String(versionNo));
      window.history.replaceState(null, '', url.toString());
    }
  }, [versionNo, load]);

  // validation as the author types
  useEffect(() => {
    if (!doc) return;
    const t = setTimeout(async () => {
      const r = await apiFetch<{ problems: Problem[]; overlaps?: any[] }>(`/api/decisions/${encodeURIComponent(decisionKey)}/check`, {
        method: 'POST', body: JSON.stringify({ authoring: doc }), throwOnError: false, silent: true,
      });
      if (r.data) { setProblems(r.data.problems); setOverlaps(r.data.overlaps ?? []); }
    }, 300);
    return () => clearTimeout(t);
  }, [doc, decisionKey]);

  // presence, so two authors know about each other before they collide
  useEffect(() => {
    if (!version || version.state !== 'draft') return;
    const beat = async () => {
      const r = await apiFetch<{ editing_now: { email: string }[]; etag: string }>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${version.version}/presence`, { method: 'POST', throwOnError: false, silent: true });
      if (r.data) setEditingNow(r.data.editing_now);
    };
    beat();
    const i = setInterval(beat, 20000);
    return () => clearInterval(i);
  }, [version, decisionKey]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (save === 'unsaved' || save === 'saving') { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [save]);

  const persist = useCallback(async (body: Record<string, any>) => {
    if (!version) return;
    setSave('saving');
    const r = await apiFetch<VersionFull & { problems: Problem[] }>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${version.version}`, {
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
  }, [version, decisionKey]);

  const onDoc = useCallback((d: RuleDoc) => {
    setDoc(d);
    setSave('unsaved');
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

  async function act(name: string, path: string, body: any = {}, method = 'POST') {
    if (!version) return null;
    setBusy(name);
    setNotice(null);
    if (save === 'unsaved' && doc) { if (saveTimer.current) clearTimeout(saveTimer.current); await persist({ authoring: doc }); }
    const r = await apiFetch<any>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${version.version}/${path}`, { method, body: JSON.stringify(body), throwOnError: false });
    setBusy(null);
    return r;
  }

  async function check() {
    const r = await act('check', 'validate');
    if (r?.data) { setValidation(r.data); setNotice({ ok: r.data.ok, text: r.data.summary }); }
    else if (r?.error) setNotice({ ok: false, text: r.error });
  }
  async function propose() {
    const r = await act('propose', 'propose', {});
    if (r?.data) {
      setNotice({ ok: true, text: r.data.approvals_needed ? `Sent for sign-off. ${r.data.approvals_needed} approval${r.data.approvals_needed > 1 ? 's are' : ' is'} needed on the Approvals page.` : 'Approved. You can publish it now.' });
      await load(version!.version); refreshModel();
    } else if (r?.error) {
      if (r.errorDetail?.details) setValidation(r.errorDetail.details as any);
      setNotice({ ok: false, text: r.error });
      if (r.errorDetail?.error_code === 'VALIDATION_FAILED') setTab('tests');
    }
  }
  async function withdraw() {
    const r = await act('withdraw', 'withdraw');
    if (r?.data) { setNotice({ ok: true, text: 'Withdrawn. It is a draft again.' }); await load(version!.version); refreshModel(); }
    else if (r?.error) setNotice({ ok: false, text: r.error });
  }
  async function previewPublish() {
    const r = await apiFetch<any>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${version!.version}/publish-plan`, { throwOnError: false });
    if (r.data) setConfirmPublish(r.data);
  }
  async function publish() {
    const r = await act('publish', 'publish', { expected_current: confirmPublish?.current ?? 0 });
    setConfirmPublish(null);
    if (r?.data) { setNotice({ ok: true, text: `Version ${version!.version} is now in force. Agents and apps use it within seconds.` }); await load(version!.version); refreshModel(); }
    else if (r?.error) setNotice({ ok: false, text: r.error });
  }
  async function newDraft(from?: number) {
    setBusy('draft');
    const r = await apiFetch<VersionFull>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions`, { method: 'POST', body: JSON.stringify(from ? { from_version: from } : {}), throwOnError: false });
    setBusy(null);
    if (r.data) { await refreshModel(); setVersionNo(r.data.version); setNotice({ ok: true, text: `Draft version ${r.data.version} created from version ${from ?? 'in force'}.` }); }
    else setNotice({ ok: false, text: r.error || 'Could not create a draft' });
  }
  async function setTier(tier: Tier) {
    setBusy('tier');
    const r = await apiFetch<any>(`/api/decisions/${encodeURIComponent(decisionKey)}`, { method: 'PATCH', body: JSON.stringify({ risk_tier: tier }), throwOnError: false });
    setBusy(null);
    if (r.data) { await refreshModel(); setNotice({ ok: true, text: `Risk tier is now ${TIER_STYLE[tier].label.toLowerCase()}. It applies to the next version you propose.` }); }
    else setNotice({ ok: false, text: r.error || 'Could not change the risk tier' });
  }
  async function exportJson() {
    const r = await apiFetch<any>(`/api/decisions/${encodeURIComponent(decisionKey)}/export?version=${version!.version}`, { throwOnError: false });
    if (!r.data) return;
    const payload = r.data.format === 'rules' ? r.data.rules : r.data.content;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${decisionKey}-v${version!.version}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const selectRule = useCallback((ref: string) => {
    if (!doc) return;
    const r = doc.rules.find((x) => x.key === ref || x.id === ref);
    if (r) { setSelectedRule(r.id); setTab('rules'); }
  }, [doc]);

  const errorCount = useMemo(() => problems.filter((p) => p.severity === 'error').length, [problems]);

  if (modelErr) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <Scale className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <p className="text-slate-300">{modelErr}</p>
        <Link href="/decisions" className="text-cyan-300 text-sm hover:underline">Back to decisions</Link>
      </div>
    );
  }
  if (!model || !version) {
    return <div className="max-w-7xl mx-auto px-6 py-8"><div className="h-12 w-64 rounded bg-slate-800/40 animate-pulse mb-4" /><div className="h-96 rounded-xl bg-slate-800/40 animate-pulse" /></div>;
  }

  const live = model.versions.filter((v) => v.state === 'published');
  const tabs = TABS.filter((t) => !t.needsBuilder || doc);
  const saveText = { saved: 'All changes saved', unsaved: 'Unsaved changes', saving: 'Saving…', error: 'Not saved', conflict: 'Someone else saved first' }[save];

  return (
    <div className="max-w-[1400px] mx-auto px-4 md:px-6 py-6">
      <div className="mb-4">
        <Link href="/decisions" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"><ArrowLeft className="w-3.5 h-3.5" /> Decisions</Link>
        <div className="flex flex-wrap items-center gap-3 mt-1">
          <h1 className="text-2xl font-semibold text-white">{model.name}</h1>
          {canPublish ? (
            <select
              value={model.risk_tier}
              onChange={(e) => setTier(e.target.value as Tier)}
              disabled={busy === 'tier'}
              className={`text-[11px] px-1.5 py-0.5 rounded border bg-transparent cursor-pointer ${TIER_STYLE[model.risk_tier].chip}`}
              aria-label="Risk tier"
              title="Higher tiers need more sign-off before a new version goes live"
              data-testid="decision-tier"
            >
              {(Object.keys(TIER_STYLE) as Tier[]).map((t) => <option key={t} value={t} className="bg-slate-900 text-white">{TIER_STYLE[t].label} risk</option>)}
            </select>
          ) : (
            <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[model.risk_tier].chip}`}>{TIER_STYLE[model.risk_tier].label} risk</span>
          )}
          <span className="text-xs font-mono text-slate-500">{model.key}</span>
          <div className="relative">
            <button type="button" onClick={() => setVersionMenu((o) => !o)} className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded border ${STATE_STYLE[version.state]}`} data-testid="version-picker" aria-haspopup="listbox">
              <GitBranch className="w-3.5 h-3.5" /> Version {version.version} · {STATE_LABEL[version.state]} <ChevronDown className="w-3 h-3" />
            </button>
            {versionMenu && (
              <ul className="absolute z-40 mt-1 w-72 rounded-lg border border-slate-700 bg-slate-900 shadow-xl py-1" role="listbox">
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
        </div>
      </div>

      <LifecycleBar
        version={version} model={model} live={live} canAuthor={canAuthor} canPublish={canPublish} busy={busy} saveText={saveText} save={save} errorCount={errorCount}
        validation={validation} onCheck={check} onPropose={propose} onWithdraw={withdraw} onPublish={previewPublish} onNewDraft={newDraft}
        onExport={exportJson} onImport={() => setImportOpen(true)}
      />

      {notice && (
        <div className={`mb-3 flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${notice.ok ? 'bg-emerald-500/10 text-emerald-200' : 'bg-rose-500/10 text-rose-200'}`} role="status" data-testid="workspace-notice">
          {notice.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5" /> : <AlertTriangle className="w-4 h-4 mt-0.5" />}
          <span className="flex-1">{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X className="w-4 h-4" /></button>
        </div>
      )}

      {version.state === 'draft' && (
        <VersionPeriod version={version} readOnly={readOnly} onSave={setVersionField} />
      )}

      <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 mb-4" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px ${tab === t.id ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`} data-testid={`tab-${t.id}`}>
            <t.icon className="w-4 h-4" /> {t.label}
            {t.id === 'rules' && errorCount > 0 && <span className="text-[10px] px-1 rounded bg-rose-500/20 text-rose-300">{errorCount}</span>}
            {t.id === 'tests' && model.test_count > 0 && <span className="text-[10px] text-slate-500">{model.test_count}</span>}
          </button>
        ))}
        <button type="button" onClick={() => setShowTry((s) => !s)} className="ml-auto text-xs text-slate-400 hover:text-white px-2" aria-pressed={showTry} data-testid="toggle-try">{showTry ? 'Hide' : 'Show'} Try it</button>
      </div>

      {!doc && version.state === 'draft' && (
        <p className="mb-3 text-xs text-slate-400">This draft is authored as a flow, so the rule builder and table do not apply. Start a new draft from a builder version to use them.</p>
      )}
      {readOnly && version.state !== 'draft' && (
        <p className="mb-3 text-xs text-slate-400" data-testid="readonly-note">
          Version {version.version} is {STATE_LABEL[version.state].toLowerCase()} and cannot change. {canAuthor && <button type="button" onClick={() => newDraft(version.version)} className="text-cyan-300 hover:underline">Start a new draft from it</button>}
        </p>
      )}

      <div className={`grid gap-4 ${showTry && ['rules', 'table', 'facts', 'flow'].includes(tab) ? '2xl:grid-cols-[minmax(0,1fr)_340px]' : ''}`}>
        <div className="min-w-0">
          {tab === 'rules' && doc && (
            <RuleBuilder doc={doc} onChange={onDoc} problems={problems} overlaps={overlaps} referenceSets={refSets || []} readOnly={readOnly} selectedId={selectedRule} onSelect={setSelectedRule} />
          )}
          {tab === 'table' && doc && <DecisionTable doc={doc} onChange={onDoc} problems={problems} readOnly={readOnly} onOpenRule={(id) => { setSelectedRule(id); setTab('rules'); }} />}
          {tab === 'facts' && doc && <FactsOutcomes doc={doc} onChange={onDoc} problems={problems} readOnly={readOnly} />}
          {tab === 'flow' && <FlowView content={version.content} hasBuilder={!!doc} editable={!readOnly} onChangeContent={(j) => { setDoc(null); onFlowContent(j); }} />}
          {tab === 'tests' && <TestsTab decisionKey={decisionKey} version={version.version} validation={validation} onRun={check} canEdit={canAuthor} />}
          {tab === 'history' && <HistoryTab decisionKey={decisionKey} versions={model.versions} current={version.version} onOpen={(n) => setVersionNo(n)} />}
        </div>
        {showTry && ['rules', 'table', 'facts', 'flow'].includes(tab) && (
          <TryPanel decisionKey={decisionKey} version={version.version} doc={doc} live={version.state === 'draft' && !!doc} onSelectRule={selectRule} onSavedTest={refreshModel} canSaveTest={canAuthor} />
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
      <ConfirmModal
        open={!!confirmPublish}
        onClose={() => setConfirmPublish(null)}
        onConfirm={publish}
        loading={busy === 'publish'}
        variant="warning"
        icon={Rocket}
        title={confirmPublish?.blocked ? 'This version cannot be published as it is' : `Publish version ${version.version}?`}
        description={
          confirmPublish?.blocked
            ? confirmPublish.blocked
            : [
                `It applies ${confirmPublish?.valid_from ? `from ${confirmPublish.valid_from.slice(0, 10)}` : 'from the start'}${confirmPublish?.valid_to ? ` until ${confirmPublish.valid_to.slice(0, 10)}` : ' with no end date'}.`,
                confirmPublish?.supersede?.length ? ` It replaces version ${confirmPublish.supersede.join(', ')}.` : '',
                confirmPublish?.close?.length ? ` Version ${confirmPublish.close.map((c: any) => `${c.version} will end on ${c.valid_to.slice(0, 10)}`).join(', ')}.` : '',
                ' Past evaluations keep the version they used. This is recorded in the audit log.',
              ].join('')
        }
        confirmLabel={confirmPublish?.blocked ? 'Close' : 'Publish'}
      />
    </div>
  );
}

function VersionPeriod({ version, readOnly, onSave }: { version: VersionFull; readOnly: boolean; onSave: (b: Record<string, any>) => void }) {
  const [note, setNote] = useState(version.change_note);
  useEffect(() => setNote(version.change_note), [version.change_note]);
  return (
    <div className="mb-4 flex flex-wrap items-end gap-4 rounded-xl border border-slate-800 bg-slate-900/30 px-4 py-3" data-testid="version-period">
      <div>
        <div className="text-xs text-slate-400 mb-1">This version applies</div>
        <div className="flex items-center gap-2">
          <input type="date" disabled={readOnly} value={version.valid_from?.slice(0, 10) || ''} onChange={(e) => onSave(e.target.value ? { valid_from: e.target.value } : { clear_valid_from: true })} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white [color-scheme:dark]" aria-label="Version applies from" data-testid="version-valid-from" />
          <span className="text-xs text-slate-500">until</span>
          <input type="date" disabled={readOnly} value={version.valid_to?.slice(0, 10) || ''} onChange={(e) => onSave(e.target.value ? { valid_to: e.target.value } : { clear_valid_to: true })} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white [color-scheme:dark]" aria-label="Version applies until" data-testid="version-valid-to" />
        </div>
        <p className="text-[11px] text-slate-500 mt-0.5">Leave the end open unless the rules stop on a known date.</p>
      </div>
      <div className="flex-1 min-w-[260px]">
        <label className="block text-xs text-slate-400 mb-1" htmlFor="change-note">What changed and why</label>
        <input id="change-note" disabled={readOnly} value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== version.change_note && onSave({ change_note: note })} placeholder="Threshold raised to 100 t under the 2027 implementing act" className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white" data-testid="change-note" />
      </div>
    </div>
  );
}

function LifecycleBar(props: {
  version: VersionFull; model: Model; live: VersionSummary[]; canAuthor: boolean; canPublish: boolean; busy: string | null;
  saveText: string; save: SaveState; errorCount: number; validation: Validation | null;
  onCheck: () => void; onPropose: () => void; onWithdraw: () => void; onPublish: () => void; onNewDraft: (from?: number) => void;
  onExport: () => void; onImport: () => void;
}) {
  const { version: v, model, canAuthor, canPublish, busy } = props;
  const need = model.policy?.publish_approvals?.min_approvers ?? 0;
  const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm disabled:opacity-40';
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2" data-testid="lifecycle-bar">
      {v.state === 'draft' && (
        <>
          <span className={`text-xs inline-flex items-center gap-1 ${props.save === 'saved' ? 'text-slate-400' : props.save === 'error' || props.save === 'conflict' ? 'text-rose-300' : 'text-amber-300'}`} data-testid="save-state">
            {props.save === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : props.save === 'saved' ? <Check className="w-3.5 h-3.5" /> : null} {props.saveText}
          </span>
          {props.errorCount > 0 && <span className="text-xs text-rose-300">{props.errorCount} to fix before proposing</span>}
          <span className="flex-1" />
          {canAuthor && (
            <>
              <button type="button" onClick={props.onImport} className={`${btn} text-slate-300 hover:bg-slate-800`} data-testid="import-open"><FileUp className="w-4 h-4" /> Import</button>
              <button type="button" onClick={props.onCheck} disabled={!!busy} className={`${btn} border border-slate-700 text-slate-200 hover:bg-slate-800`} data-testid="check">
                {busy === 'check' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />} Check
              </button>
              <button type="button" onClick={props.onPropose} disabled={!!busy || props.errorCount > 0} title={props.errorCount ? 'Fix the marked problems first' : ''} className={`${btn} bg-cyan-500 text-white hover:bg-cyan-400`} data-testid="propose">
                {busy === 'propose' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} {need ? `Propose for sign-off (${need})` : 'Propose'}
              </button>
            </>
          )}
        </>
      )}
      {v.state === 'proposed' && (
        <>
          <span className="text-sm text-amber-200">Waiting for sign-off. Approvers see it on the Approvals page.</span>
          <Link href="/approvals" className="text-sm text-cyan-300 hover:underline">Open Approvals</Link>
          <span className="flex-1" />
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
            <span className="text-xs text-slate-500">Publishing needs the decisions.publish capability.</span>
          )}
        </>
      )}
      {v.state === 'rejected' && (
        <>
          <span className="text-sm text-rose-200">This version was rejected.</span>
          <span className="flex-1" />
          {canAuthor && <button type="button" onClick={() => props.onNewDraft(v.version)} className={`${btn} border border-slate-700 text-slate-200`}><FilePlus2 className="w-4 h-4" /> New draft from it</button>}
        </>
      )}
      {['published', 'superseded', 'retired'].includes(v.state) && (
        <>
          <span className="text-sm text-slate-300">{v.state === 'published' ? `In force${v.valid_from ? ` from ${v.valid_from.slice(0, 10)}` : ''}${v.valid_to ? ` until ${v.valid_to.slice(0, 10)}` : ''}.` : STATE_LABEL[v.state] + '.'}</span>
          <span className="flex-1" />
          {canAuthor && <button type="button" onClick={() => props.onNewDraft(v.version)} disabled={!!busy} className={`${btn} bg-cyan-500 text-white hover:bg-cyan-400`} data-testid="new-draft"><FilePlus2 className="w-4 h-4" /> New draft</button>}
        </>
      )}
      <button type="button" onClick={props.onExport} className={`${btn} text-slate-300 hover:bg-slate-800`} data-testid="export"><Download className="w-4 h-4" /> Export</button>
      {props.validation && v.state === 'draft' && (
        <span className={`basis-full text-xs ${props.validation.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="validation-summary">{props.validation.summary}</span>
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
          <p className="text-sm text-slate-400">Paste typed JSON rules (ruleKey, requiresFacts, when, then, provenance) or a decision model exported from the flow view.</p>
          <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-950 text-xs">
            <button type="button" onClick={() => setMode('merge')} className={`px-2 py-1 rounded ${mode === 'merge' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'merge'}>Add and update by ruleKey</button>
            <button type="button" onClick={() => setMode('replace')} className={`px-2 py-1 rounded ${mode === 'replace' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'replace'}>Replace everything</button>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono" aria-label="Rules JSON" data-testid="import-json" />
          {(parseErr || err) && <p className="text-xs text-rose-300">{parseErr ? `Not valid JSON: ${parseErr}` : err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-300">Cancel</button>
          <button type="button" onClick={go} disabled={!parsed || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white disabled:opacity-40" data-testid="import-go">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Import
          </button>
        </div>
      </div>
    </div>
  );
}


