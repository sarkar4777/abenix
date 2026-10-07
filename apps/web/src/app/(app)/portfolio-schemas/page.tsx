'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Database, Trash2, Edit3, Save, FileJson, Layers, Package,
  Sparkles, AlertTriangle, RefreshCw, Loader2, Upload, FlaskConical, Bot, PenLine, CheckCircle2, MessageSquare,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch, ApiError } from '@/lib/api-client';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { toastError, toastSuccess } from '@/stores/toastStore';
import SpreadsheetImport from '@/components/portfolio-schemas/SpreadsheetImport';
import MyRows from '@/components/portfolio-schemas/MyRows';
import DeleteSchemaModal from '@/components/portfolio-schemas/DeleteSchemaModal';
import {
  type PortfolioSchema, type ImportCapabilities, type ImportResult,
  DEFAULT_CAPS, agentHref, exampleQuestions,
} from '@/components/portfolio-schemas/shared';

interface Template {
  id: string;
  label: string;
  description: string;
  requires_own_tables?: boolean;
  schema_json: any;
}

interface Draft {
  creating: boolean;
  selectedId: string | null;
  templateLabel: string | null;
  domain: string;
  label: string;
  description: string;
  recordNoun: string;
  recordNounPlural: string;
  isActive: boolean;
  json: string;
}

const DRAFT_KEY = 'portfolio-schemas:draft';
const DOMAIN_RE = /^[a-z][a-z0-9_]*$/;

const BLANK_SCHEMA = {
  domain: { label: '', record_noun: 'record', record_noun_plural: 'records' },
  main_table: {
    name: '',
    user_scope_column: 'user_id',
    title_column: 'title',
    list_columns: ['id', 'title'],
    columns: { id: { type: 'uuid', label: 'ID' }, title: { type: 'string', label: 'Title' } },
    summary_aggregations: { total: { sql: 'count(*)', label: 'Total records' } },
  },
  related_tables: [],
};

function readDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

function writeDraft(d: Draft | null) {
  try {
    if (d) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(d));
    else sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // storage blocked, the draft just won't survive a reload
  }
}

const inputCls =
  'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none';
const labelCls = 'text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 block';

export default function PortfolioSchemasPage() {
  const { data: schemas, error: listError, isLoading, mutate } = useApi<PortfolioSchema[]>('/api/portfolio-schemas');
  const { data: templates, error: templatesError } = useApi<Template[]>('/api/portfolio-schemas/templates/list');
  const { data: capsData } = useApi<ImportCapabilities>('/api/portfolio-schemas/import/capabilities');
  const caps = capsData || DEFAULT_CAPS;
  const [allAgents, setAllAgents] = useState<any[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);
  const [agentLoadProgress, setAgentLoadProgress] = useState<{ loaded: number; total: number } | null>(null);
  const agentLoadStartedAt = useRef<number>(0);

  useEffect(() => {
    let cancelled = false;
    agentLoadStartedAt.current = Date.now();
    (async () => {
      try {
        const { agents } = await fetchAllAgents({
          onProgress: (loaded, total) => {
            if (cancelled) return;
            if (Date.now() - agentLoadStartedAt.current > 2000) {
              setAgentLoadProgress({ loaded, total });
            }
          },
        });
        if (cancelled) return;
        setAllAgents(Array.isArray(agents) ? agents : []);
      } catch {
        // usage badges are a hint, the page still works without them
      }
      if (!cancelled) {
        setAgentLoadProgress(null);
        setAgentsLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // tool_name -> agents listing it, drives the usage badges, banner and delete warning
  const agentsByTool = useMemo(() => {
    const m = new Map<string, { slug: string; name: string }[]>();
    for (const a of allAgents) {
      const tools = a?.model_config?.tools;
      if (!Array.isArray(tools)) continue;
      for (const t of tools) {
        if (typeof t !== 'string') continue;
        const arr = m.get(t) || [];
        arr.push({ slug: a.slug, name: a.name });
        m.set(t, arr);
      }
    }
    return m;
  }, [allAgents]);

  const [selected, setSelected] = useState<PortfolioSchema | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [templateLabel, setTemplateLabel] = useState<string | null>(null);
  const [draftJson, setDraftJson] = useState('');
  const [draftLabel, setDraftLabel] = useState('');
  const [draftDomainName, setDraftDomainName] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [draftRecordNoun, setDraftRecordNoun] = useState('record');
  const [draftRecordNounPlural, setDraftRecordNounPlural] = useState('records');
  const [draftActive, setDraftActive] = useState(true);
  const [showTemplates, setShowTemplates] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [problems, setProblems] = useState<string[]>([]);
  const [jsonError, setJsonError] = useState('');
  const [pendingDelete, setPendingDelete] = useState<{ schema: PortfolioSchema; blockedBy: string | null } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importTarget, setImportTarget] = useState<PortfolioSchema | null>(null);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleError, setSampleError] = useState('');
  const [nextStep, setNextStep] = useState<ImportResult | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const problemsRef = useRef<HTMLDivElement>(null);
  const restored = useRef(false);

  const clearFeedback = () => { setError(''); setProblems([]); setJsonError(''); };

  const loadForm = (d: Draft) => {
    setCreating(d.creating);
    setTemplateLabel(d.templateLabel);
    setDraftDomainName(d.domain);
    setDraftLabel(d.label);
    setDraftDescription(d.description);
    setDraftRecordNoun(d.recordNoun);
    setDraftRecordNounPlural(d.recordNounPlural);
    setDraftActive(d.isActive);
    setDraftJson(d.json);
    setEditing(true);
    clearFeedback();
  };

  // bring back an unsaved draft after a reload
  useEffect(() => {
    if (restored.current || !schemas) return;
    restored.current = true;
    const d = readDraft();
    if (!d) return;
    if (d.creating) {
      setSelected(null);
      loadForm(d);
      return;
    }
    const s = schemas.find(x => x.id === d.selectedId);
    if (!s) { writeDraft(null); return; }
    setSelected(s);
    loadForm(d);
  }, [schemas]);

  useEffect(() => {
    if (!editing) return;
    writeDraft({
      creating,
      selectedId: selected?.id ?? null,
      templateLabel,
      domain: draftDomainName,
      label: draftLabel,
      description: draftDescription,
      recordNoun: draftRecordNoun,
      recordNounPlural: draftRecordNounPlural,
      isActive: draftActive,
      json: draftJson,
    });
  }, [editing, creating, selected, templateLabel, draftDomainName, draftLabel, draftDescription,
    draftRecordNoun, draftRecordNounPlural, draftActive, draftJson]);

  const closeEditor = () => {
    setEditing(false);
    setCreating(false);
    setTemplateLabel(null);
    clearFeedback();
    writeDraft(null);
  };

  const startEdit = (s: PortfolioSchema) => {
    setSelected(s);
    setShowTemplates(false);
    setImporting(false);
    setNextStep(null);
    loadForm({
      creating: false,
      selectedId: s.id,
      templateLabel: null,
      domain: s.domain_name,
      label: s.label,
      description: s.description || '',
      recordNoun: s.record_noun,
      recordNounPlural: s.record_noun_plural,
      isActive: s.is_active,
      json: JSON.stringify(s.schema_json, null, 2),
    });
  };

  const startCreate = (template?: Template) => {
    const schema = template?.schema_json || BLANK_SCHEMA;
    const dom = schema.domain || {};
    setSelected(null);
    setShowTemplates(false);
    setImporting(false);
    setNextStep(null);
    loadForm({
      creating: true,
      selectedId: null,
      templateLabel: template?.label ?? null,
      domain: template ? (dom.name || template.id || '') : '',
      label: template?.label || '',
      description: dom.description || '',
      recordNoun: dom.record_noun || 'record',
      recordNounPlural: dom.record_noun_plural || 'records',
      isActive: true,
      json: JSON.stringify(schema, null, 2),
    });
  };

  const startImport = (target?: PortfolioSchema) => {
    if (editing) closeEditor();
    setShowTemplates(false);
    setNextStep(null);
    setImportTarget(target || null);
    if (!target) setSelected(null);
    setImporting(true);
  };

  const viewSchema = (s: PortfolioSchema) => {
    setImporting(false);
    setImportTarget(null);
    if (editing) closeEditor();
    setSelected(s);
  };

  const onImported = (r: ImportResult) => {
    mutate();
    setSelected(r.schema);
    toastSuccess(r.mode === 'create' ? 'Schema created' : 'Rows imported', `${r.rows_imported} rows in ${r.schema.tool_name}`);
  };

  const trySample = async () => {
    setSampleBusy(true);
    setSampleError('');
    try {
      const res = await apiFetch<ImportResult>('/api/portfolio-schemas/import/sample', { method: 'POST', silent: true });
      const r = res.data!;
      if (editing) closeEditor();
      setImporting(false);
      setShowTemplates(false);
      setSelected(r.schema);
      setNextStep(r);
      mutate();
    } catch (e: any) {
      setSampleError(e?.message || 'The sample could not be created.');
    }
    setSampleBusy(false);
  };

  const trimmedLabel = draftLabel.trim();
  const domainOk = !creating || DOMAIN_RE.test(draftDomainName);
  const canSave = !saving && !!trimmedLabel && domainOk && !!draftRecordNoun.trim() && !!draftRecordNounPlural.trim();

  const showError = (msg: string) => {
    setError(msg);
    requestAnimationFrame(() => errorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  };

  const save = async () => {
    clearFeedback();
    let schemaObj: any;
    try {
      schemaObj = JSON.parse(draftJson);
    } catch (e: any) {
      setJsonError(`Schema JSON does not parse: ${e?.message || 'invalid JSON'}`);
      requestAnimationFrame(() => problemsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
      return;
    }
    if (!schemaObj || typeof schemaObj !== 'object' || Array.isArray(schemaObj)) {
      setJsonError('Schema JSON must be an object');
      return;
    }
    setSaving(true);
    const common = {
      label: trimmedLabel,
      description: draftDescription.trim() || null,
      record_noun: draftRecordNoun.trim(),
      record_noun_plural: draftRecordNounPlural.trim(),
      schema_json: schemaObj,
    };
    try {
      if (creating) {
        await apiFetch<PortfolioSchema>('/api/portfolio-schemas', {
          method: 'POST',
          body: JSON.stringify({ domain_name: draftDomainName, ...common }),
        });
        toastSuccess('Schema created', `Tool portfolio_${draftDomainName} is ready to add to an agent.`);
      } else if (selected) {
        const res = await apiFetch<PortfolioSchema>(`/api/portfolio-schemas/${selected.id}`, {
          method: 'PUT',
          body: JSON.stringify({ ...common, is_active: draftActive }),
        });
        if (res.data) setSelected(res.data);
        toastSuccess('Schema saved', selected.tool_name);
      }
      mutate();
      setEditing(false);
      setCreating(false);
      setTemplateLabel(null);
      writeDraft(null);
      if (creating) setSelected(null);
    } catch (e: any) {
      const list = e instanceof ApiError ? (e.details?.problems as string[] | undefined) : undefined;
      if (Array.isArray(list) && list.length) {
        setProblems(list);
        requestAnimationFrame(() => problemsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
      } else {
        showError(e?.message || 'Failed to save');
      }
    }
    setSaving(false);
  };

  const askDelete = (s: PortfolioSchema) => setPendingDelete({ schema: s, blockedBy: null });

  const doDelete = async ({ force, dropTable }: { force: boolean; dropTable: boolean }) => {
    if (!pendingDelete) return;
    const { schema: s } = pendingDelete;
    setDeleting(true);
    const q = new URLSearchParams();
    if (force) q.set('force', 'true');
    if (dropTable) q.set('drop_table', 'true');
    try {
      const res = await apiFetch<{ dropped_table: string | null }>(`/api/portfolio-schemas/${s.id}${q.toString() ? `?${q}` : ''}`, { method: 'DELETE', silent: true });
      toastSuccess('Schema deleted', res.data?.dropped_table ? `${s.tool_name} and table ${res.data.dropped_table}` : s.tool_name);
      setPendingDelete(null);
      if (selected?.id === s.id) { setSelected(null); setNextStep(null); closeEditor(); }
      if (importTarget?.id === s.id) { setImporting(false); setImportTarget(null); }
      mutate();
    } catch (e: any) {
      if (e instanceof ApiError && e.errorCode === 'PORTFOLIO_SCHEMA_IN_USE') {
        setPendingDelete({ schema: s, blockedBy: e.message });
      } else if (e instanceof ApiError && e.status < 500 && e.status !== 404) {
        // e.g. the table is shared, leave the dialog open so the box can be unticked
        toastError('Could not delete schema', e.message);
      } else {
        toastError('Could not delete schema', e?.message || 'Unknown error');
        setPendingDelete(null);
      }
    }
    setDeleting(false);
  };

  const current = selected ? (schemas || []).find(x => x.id === selected.id) || selected : null;

  const wired = (schemas || [])
    .map(s => ({ s, used: agentsByTool.get(s.tool_name) || [] }))
    .filter(x => x.used.length > 0);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-4 sm:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center shrink-0">
              <Database className="w-5 h-5 text-purple-400" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                Portfolio Schemas
                <Sparkles className="w-4 h-4 text-purple-400" />
              </h1>
              <p className="text-sm text-slate-400">
                Give your agents a table of records they can list, search and total. Bring a spreadsheet, or describe an existing table.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 shrink-0">
            <button
              onClick={trySample}
              disabled={sampleBusy}
              data-testid="ps-try-sample"
              className="px-3 py-2 text-xs rounded-lg border border-purple-500/40 text-purple-200 hover:bg-purple-500/10 transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              {sampleBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />} Try with a sample
            </button>
            <button
              onClick={() => startImport()}
              data-testid="ps-create-from-sheet"
              className="px-3 py-2 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium hover:shadow-lg hover:shadow-purple-500/20 transition-all flex items-center gap-1.5"
            >
              <Upload className="w-3.5 h-3.5" /> Create from a spreadsheet
            </button>
          </div>
        </div>

        {sampleError && (
          <div role="alert" className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-300 break-words flex items-start justify-between gap-3">
            <span>Could not create the sample: {sampleError}</span>
            <button onClick={() => setSampleError('')} className="text-red-200 underline shrink-0">Dismiss</button>
          </div>
        )}

        <div className="bg-gradient-to-br from-purple-500/5 via-slate-800/30 to-pink-500/5 border border-purple-500/20 rounded-xl p-4 sm:p-5">
          <div className="flex items-start gap-3 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-500/20 border border-purple-500/40 flex items-center justify-center shrink-0 mt-0.5">
              <Sparkles className="w-4 h-4 text-purple-300" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white">How this works</h2>
              <p className="text-[12px] text-slate-300 mt-1 leading-relaxed">
                A <strong className="text-white">portfolio schema</strong> describes one table of records, like trades, contracts or properties: its columns,
                which column names each record, and which totals make sense. Each schema becomes a tool called
                <code className="text-purple-300 mx-1">portfolio_<em>name</em></code> that any agent can use.
                <strong className="text-white"> Each person sees only their own rows</strong>, and so do agents acting for them.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">1 · Bring your data</p>
              <p className="text-[11px] text-slate-300">Upload a CSV{caps.formats.includes('xlsx') ? ' or Excel file' : ''}. The first row holds column names, every other row becomes a record. You check the column types before anything is saved.</p>
            </div>
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">2 · Use it in an agent</p>
              <p className="text-[11px] text-slate-300">Press <strong className="text-white">Use in an agent</strong>. The builder opens with the tool added and a starter prompt. Save and publish.</p>
            </div>
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">3 · Ask questions</p>
              <p className="text-[11px] text-slate-300">The agent calls <code>list_records</code> to read rows, <code>search</code> to find them by text and <code>get_summary</code> for counts, totals and averages, then answers from those numbers.</p>
            </div>
          </div>
          {agentsLoaded && wired.length > 0 && (
            <div className="flex items-start gap-2 mt-3 text-[11px] text-slate-400 bg-slate-900/40 border border-slate-700/40 rounded-lg p-2.5">
              <Database className="w-3.5 h-3.5 text-cyan-400 mt-0.5 shrink-0" />
              <div className="min-w-0 space-y-0.5">
                <p><strong className="text-white">In use:</strong></p>
                {wired.slice(0, 4).map(({ s, used }) => (
                  <p key={s.id} className="break-words">
                    <code className="text-cyan-300">{s.tool_name}</code> by {used.slice(0, 3).map(a => a.name).join(', ')}
                    {used.length > 3 ? ` +${used.length - 3}` : ''}
                  </p>
                ))}
                {wired.length > 4 && <p>and {wired.length - 4} more schema{wired.length - 4 !== 1 ? 's' : ''}</p>}
              </div>
            </div>
          )}
        </div>

        {agentLoadProgress && (
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-3 text-xs text-slate-300">
            Loading {agentLoadProgress.loaded} of {agentLoadProgress.total} agents…
          </div>
        )}

        {showTemplates && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
            <p className="text-xs font-semibold text-white uppercase tracking-wider mb-1">Starter Templates</p>
            <p className="text-[11px] text-amber-300/80 mb-3">
              Templates are examples. Their tables are not in your database, so change the table and column names to your own
              tables before saving or the save will list what is missing.
            </p>
            {templatesError ? (
              <p className="text-xs text-red-400">Could not load templates: {templatesError}</p>
            ) : !templates ? (
              <p className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading templates…</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {templates.map(t => (
                  <button
                    key={t.id}
                    onClick={() => startCreate(t)}
                    className="text-left p-3 rounded-lg border border-slate-700 hover:border-purple-500/50 hover:bg-slate-800/50 transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <Package className="w-4 h-4 text-purple-400 shrink-0" />
                      <span className="text-xs font-semibold text-white">{t.label}</span>
                    </div>
                    <p className="text-[10px] text-slate-400">{t.description}</p>
                  </button>
                ))}
              </div>
            )}
          </motion.div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-4 space-y-2 min-w-0">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1">
              Your Schemas ({schemas?.length || 0})
            </p>
            {isLoading && !schemas ? (
              <div className="space-y-2" aria-busy="true">
                {[0, 1, 2].map(i => (
                  <div key={i} className="h-16 rounded-lg bg-slate-800/40 border border-slate-700/40 animate-pulse" />
                ))}
              </div>
            ) : listError && !schemas ? (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-xs text-red-300">
                <p className="font-medium mb-1">Could not load schemas</p>
                <p className="text-red-300/80 mb-3 break-words">{listError}</p>
                <button
                  onClick={() => mutate()}
                  className="px-3 py-1.5 rounded-lg border border-red-500/40 text-red-200 hover:bg-red-500/10 inline-flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3 h-3" /> Retry
                </button>
              </div>
            ) : !schemas || schemas.length === 0 ? (
              <div className="bg-slate-800/20 border border-slate-700/30 rounded-lg p-6 text-center">
                <FileJson className="w-8 h-8 text-slate-600 mx-auto mb-2" />
                <p className="text-xs text-slate-400">No schemas yet</p>
                <p className="text-[11px] text-slate-500 mt-1">Start with the sample or your own spreadsheet.</p>
              </div>
            ) : (
              schemas.map(s => {
                const used = agentsByTool.get(s.tool_name) || [];
                return (
                  <div
                    key={s.id}
                    role="button"
                    tabIndex={0}
                    data-testid={`ps-card-${s.domain_name}`}
                    onClick={() => viewSchema(s)}
                    onKeyDown={e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); viewSchema(s); } }}
                    className={`bg-slate-800/30 border rounded-lg p-3 cursor-pointer transition-colors ${
                      selected?.id === s.id ? 'border-purple-500/50 bg-purple-500/5' : 'border-slate-700/50 hover:border-slate-600'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileJson className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                        <span className="text-sm font-medium text-white truncate">{s.label}</span>
                        {!s.is_active && (
                          <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-400 shrink-0">Off</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={(e) => { e.stopPropagation(); startEdit(s); }}
                          aria-label={`Edit ${s.label}`}
                          title="Edit the schema JSON"
                          className="p-1.5 text-slate-500 hover:text-white"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); askDelete(s); }}
                          aria-label={`Delete ${s.label}`}
                          className="p-1.5 text-slate-500 hover:text-red-400"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono break-all">{s.tool_name}</div>
                    <p className="text-[10px] text-slate-400 mt-1">
                      {s.source === 'spreadsheet'
                        ? (typeof s.my_rows === 'number' ? `From a spreadsheet · ${s.my_rows.toLocaleString()} of your ${s.record_noun_plural}` : 'From a spreadsheet')
                        : `Reads table ${s.table_name || '?'}`}
                    </p>
                    {agentsLoaded && used.length > 0 && (
                      <p className="text-[10px] text-emerald-300 mt-1 truncate" title={used.map(a => a.name).join(', ')}>
                        Used by {used.length} agent{used.length !== 1 ? 's' : ''}: <span className="text-slate-300">{used.slice(0, 3).map(a => a.name).join(', ')}</span>{used.length > 3 ? ` +${used.length - 3}` : ''}
                      </p>
                    )}
                    <Link
                      href={agentHref(s)}
                      onClick={e => e.stopPropagation()}
                      className="mt-2 inline-flex items-center gap-1 text-[11px] text-purple-300 hover:text-purple-200"
                    >
                      <Bot className="w-3 h-3" /> {agentsLoaded && used.length === 0 ? 'Not in an agent yet · Use in an agent' : 'Use in an agent'}
                    </Link>
                  </div>
                );
              })
            )}
            <div className="pt-3 mt-1 border-t border-slate-800 space-y-1.5">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1">Advanced</p>
              <button
                onClick={() => startCreate()}
                className="w-full text-left px-3 py-2 text-xs rounded-lg border border-slate-700/60 text-slate-300 hover:text-white hover:border-slate-600 flex items-center gap-2"
              >
                <PenLine className="w-3.5 h-3.5 shrink-0" /> Write a schema by hand
              </button>
              <button
                onClick={() => setShowTemplates(!showTemplates)}
                aria-expanded={showTemplates}
                className="w-full text-left px-3 py-2 text-xs rounded-lg border border-slate-700/60 text-slate-300 hover:text-white hover:border-slate-600 flex items-center gap-2"
              >
                <Layers className="w-3.5 h-3.5 shrink-0" /> {showTemplates ? 'Hide templates' : 'Start from a template'}
              </button>
              <p className="text-[10px] text-slate-500 px-1">For tables that already exist in the platform database, like ones another app created.</p>
            </div>
          </div>

          <div className="lg:col-span-8 min-w-0">
            {editing ? (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <div className="px-4 sm:px-5 py-4 border-b border-slate-700/50 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-white min-w-0 break-words">
                    {creating ? 'New Schema' : `Edit: ${selected?.label}`}
                  </h3>
                  <div className="flex gap-2">
                    <button
                      onClick={closeEditor}
                      className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-400 hover:text-white"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={save}
                      disabled={!canSave}
                      title={!trimmedLabel ? 'Enter a display label' : !domainOk ? 'Enter a valid domain name' : undefined}
                      className="px-3 py-1.5 text-xs rounded-lg bg-purple-500 text-white hover:bg-purple-400 disabled:opacity-30 flex items-center gap-1"
                    >
                      {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} {saving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                </div>
                {error && (
                  <div ref={errorRef} role="alert" className="mx-4 sm:mx-5 mt-4 bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-400 break-words">
                    {error}
                  </div>
                )}
                <div className="p-4 sm:p-5 space-y-4">
                  {templateLabel && (
                    <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-[11px] text-amber-200">
                      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <p>
                        Started from the <strong>{templateLabel}</strong> example. Change <code>main_table.name</code>, the column names and any
                        <code className="mx-1">related_tables</code> to tables that exist in your database before saving.
                      </p>
                    </div>
                  )}
                  <div>
                    <label htmlFor="ps-domain" className={labelCls}>Domain Name (snake_case)</label>
                    {creating ? (
                      <>
                        <input
                          id="ps-domain"
                          type="text"
                          value={draftDomainName}
                          onChange={e => setDraftDomainName(e.target.value.trim())}
                          placeholder="e.g., real_estate"
                          aria-invalid={!!draftDomainName && !domainOk}
                          className={`${inputCls} font-mono`}
                        />
                        {draftDomainName && !domainOk ? (
                          <p className="text-[10px] text-red-400 mt-1">Use lowercase letters, digits and underscores, starting with a letter.</p>
                        ) : (
                          <p className="text-[10px] text-slate-500 mt-1">
                            The tool will be named <span className="font-mono text-purple-400">portfolio_{draftDomainName || 'your_domain'}</span>
                          </p>
                        )}
                      </>
                    ) : (
                      <>
                        <div id="ps-domain" className={`${inputCls} font-mono text-slate-400 bg-slate-900/30 cursor-not-allowed`}>
                          {draftDomainName}
                        </div>
                        <p className="text-[10px] text-slate-500 mt-1">
                          The domain can&apos;t change because agents call this schema by its tool name{' '}
                          <span className="font-mono text-purple-400">portfolio_{draftDomainName}</span>. Create a new schema to use a different name.
                        </p>
                      </>
                    )}
                  </div>
                  <div>
                    <label htmlFor="ps-label" className={labelCls}>Display Label</label>
                    <input
                      id="ps-label"
                      type="text"
                      value={draftLabel}
                      onChange={e => setDraftLabel(e.target.value)}
                      placeholder="e.g., Real Estate Portfolio"
                      maxLength={255}
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label htmlFor="ps-desc" className={labelCls}>Description (optional)</label>
                    <input
                      id="ps-desc"
                      type="text"
                      value={draftDescription}
                      onChange={e => setDraftDescription(e.target.value)}
                      placeholder="What these records are, shown in the schema list"
                      className={inputCls}
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label htmlFor="ps-noun" className={labelCls}>Record noun</label>
                      <input id="ps-noun" type="text" value={draftRecordNoun} onChange={e => setDraftRecordNoun(e.target.value)} placeholder="e.g., property" className={inputCls} />
                    </div>
                    <div>
                      <label htmlFor="ps-nouns" className={labelCls}>Record noun (plural)</label>
                      <input id="ps-nouns" type="text" value={draftRecordNounPlural} onChange={e => setDraftRecordNounPlural(e.target.value)} placeholder="e.g., properties" className={inputCls} />
                    </div>
                  </div>
                  {!creating && (
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs text-white">Active</p>
                        <p className="text-[10px] text-slate-500">When off, agents that list {`portfolio_${draftDomainName}`} can&apos;t load this schema.</p>
                      </div>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={draftActive}
                        aria-label="Active"
                        onClick={() => setDraftActive(!draftActive)}
                        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${draftActive ? 'bg-purple-500' : 'bg-slate-600'}`}
                      >
                        <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${draftActive ? 'translate-x-4' : 'translate-x-0.5'}`} />
                      </button>
                    </div>
                  )}
                  <div>
                    <label htmlFor="ps-json" className={labelCls}>Schema JSON</label>
                    <textarea
                      id="ps-json"
                      value={draftJson}
                      onChange={e => { setDraftJson(e.target.value); if (jsonError) setJsonError(''); }}
                      rows={24}
                      spellCheck={false}
                      aria-invalid={!!jsonError || problems.length > 0}
                      aria-describedby="ps-json-help"
                      className={`w-full bg-slate-900/50 border rounded-lg px-3 py-2 text-[11px] text-emerald-300 placeholder-slate-500 focus:outline-none font-mono resize-y ${
                        jsonError || problems.length ? 'border-red-500/50 focus:border-red-400' : 'border-slate-700 focus:border-purple-500'
                      }`}
                    />
                    <p id="ps-json-help" className="text-[10px] text-slate-500 mt-1">
                      <code>domain.name</code> is set to the domain name for you. Label and record nouns fall back to the fields above when left out.
                    </p>
                    <div ref={problemsRef}>
                      {jsonError && (
                        <div role="alert" className="mt-2 bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-400 break-words">
                          {jsonError}
                        </div>
                      )}
                      {problems.length > 0 && (
                        <div role="alert" className="mt-2 bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-300">
                          <p className="font-medium text-red-400 mb-1.5">
                            {problems.length} problem{problems.length !== 1 ? 's' : ''} to fix before this schema can be saved
                          </p>
                          <ul className="list-disc pl-4 space-y-1 break-words">
                            {problems.map((p, i) => <li key={i}>{p}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : importing ? (
              <SpreadsheetImport
                key={importTarget?.id || 'new'}
                caps={caps}
                existingDomains={(schemas || []).map(x => x.domain_name)}
                target={importTarget}
                onCancel={() => { setImporting(false); setImportTarget(null); }}
                onDone={onImported}
                onView={viewSchema}
              />
            ) : current ? (
              <div className="space-y-4">
                {nextStep && nextStep.schema.id === current.id && (
                  <div data-testid="ps-next-step" className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-3">
                    <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white font-medium">
                        {nextStep.sample ? `Sample ready: ${nextStep.rows_imported} ${current.record_noun_plural} you own` : `${nextStep.rows_imported} rows imported`}
                      </p>
                      <p className="text-[11px] text-slate-300">Next, make an agent that answers questions about them. The tool and a starter prompt are filled in for you.</p>
                    </div>
                    <Link
                      href={agentHref(current)}
                      data-testid="ps-use-in-agent"
                      className="px-3 py-2 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium inline-flex items-center gap-1.5 shrink-0 justify-center"
                    >
                      <Bot className="w-3.5 h-3.5" /> Use in an agent
                    </Link>
                  </div>
                )}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                  <div className="px-4 sm:px-5 py-4 border-b border-slate-700/50 flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-white break-words">
                        {current.label}
                        {!current.is_active && <span className="ml-2 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-400 align-middle">Off</span>}
                      </h3>
                      <p className="text-[10px] text-slate-500 font-mono break-all">{current.tool_name}</p>
                      {current.description && <p className="text-[11px] text-slate-400 mt-1">{current.description}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {!(nextStep && nextStep.schema.id === current.id) && (
                        <Link
                          href={agentHref(current)}
                          data-testid="ps-use-in-agent"
                          className="px-3 py-1.5 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium inline-flex items-center gap-1"
                        >
                          <Bot className="w-3 h-3" /> Use in an agent
                        </Link>
                      )}
                      {current.source === 'spreadsheet' && (
                        <button
                          onClick={() => startImport(current)}
                          className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-300 hover:text-white inline-flex items-center gap-1"
                        >
                          <Upload className="w-3 h-3" /> Add rows
                        </button>
                      )}
                      <button
                        onClick={() => startEdit(current)}
                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-300 hover:text-white inline-flex items-center gap-1"
                      >
                        <Edit3 className="w-3 h-3" /> Edit
                      </button>
                      <button
                        onClick={() => askDelete(current)}
                        aria-label={`Delete ${current.label}`}
                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-400 hover:text-red-300 hover:border-red-500/40 inline-flex items-center gap-1"
                      >
                        <Trash2 className="w-3 h-3" /> Delete
                      </button>
                    </div>
                  </div>
                  <div className="p-4 sm:p-5 space-y-5">
                    {current.source === 'spreadsheet' ? (
                      <div>
                        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Your rows</p>
                        <MyRows key={`${current.id}-${current.updated_at}-${current.my_rows ?? ''}`} schemaId={current.id} noun={current.record_noun_plural} />
                      </div>
                    ) : (
                      <p className="text-[11px] text-slate-400">
                        Reads the existing table <code className="text-slate-300">{current.table_name}</code>. Rows are matched to people by
                        <code className="text-slate-300 mx-1">{current.schema_json?.main_table?.user_scope_column}</code>.
                      </p>
                    )}
                    <div>
                      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <MessageSquare className="w-3 h-3" /> Questions an agent with this tool can answer
                      </p>
                      <ul className="text-[11px] text-slate-300 space-y-1">
                        {exampleQuestions(current).map(q => <li key={q} className="bg-slate-900/40 border border-slate-700/40 rounded px-2 py-1">{q}</li>)}
                      </ul>
                    </div>
                    <details>
                      <summary className="text-[11px] text-slate-400 cursor-pointer hover:text-slate-200">Schema JSON (advanced)</summary>
                      <pre className="mt-2 text-[10px] text-slate-400 font-mono overflow-x-auto max-h-[600px] overflow-y-auto bg-slate-900/50 rounded-lg p-3">
                        {JSON.stringify(current.schema_json, null, 2)}
                      </pre>
                    </details>
                  </div>
                </div>
              </div>
            ) : !isLoading && schemas && schemas.length === 0 ? (
              <div data-testid="ps-empty" className="bg-slate-800/20 border border-slate-700/30 rounded-xl p-6 sm:p-10 text-center">
                <Database className="w-10 h-10 text-purple-400/70 mx-auto mb-3" />
                <h2 className="text-base font-semibold text-white">Give your agents some data to work with</h2>
                <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                  Try the sample energy trading book to see it working in a minute, or upload your own spreadsheet. Nothing to install and no SQL.
                </p>
                <div className="flex flex-col sm:flex-row gap-2 justify-center mt-5">
                  <button
                    onClick={trySample}
                    disabled={sampleBusy}
                    className="px-4 py-2.5 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium inline-flex items-center justify-center gap-1.5 disabled:opacity-50"
                  >
                    {sampleBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />} Try with a sample
                  </button>
                  <button
                    onClick={() => startImport()}
                    className="px-4 py-2.5 text-xs rounded-lg bg-purple-500/15 border border-purple-500/40 text-purple-100 hover:bg-purple-500/25 font-medium inline-flex items-center justify-center gap-1.5"
                  >
                    <Upload className="w-3.5 h-3.5" /> Create from a spreadsheet
                  </button>
                </div>
                <button onClick={() => startCreate()} className="mt-4 text-[11px] text-slate-400 hover:text-slate-200 underline">
                  Write a schema by hand (advanced)
                </button>
              </div>
            ) : (
              <div className="bg-slate-800/20 border border-slate-700/30 rounded-xl p-8 sm:p-12 text-center">
                <Database className="w-10 h-10 text-slate-600 mx-auto mb-3" />
                <p className="text-sm text-slate-400 mb-1">Pick a schema on the left to see your rows and use it in an agent</p>
                <p className="text-[11px] text-slate-500">
                  Or bring more data with <button onClick={() => startImport()} className="underline hover:text-slate-300">Create from a spreadsheet</button>.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <DeleteSchemaModal
        schema={pendingDelete?.schema || null}
        usedBy={pendingDelete ? agentsByTool.get(pendingDelete.schema.tool_name) || [] : []}
        blockedBy={pendingDelete?.blockedBy || null}
        loading={deleting}
        onClose={() => { if (!deleting) setPendingDelete(null); }}
        onConfirm={doDelete}
      />
    </div>
  );
}
