'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Database, Plus, Trash2, Edit3, Copy, Save, X, FileJson,
  Layers, Package, ChevronRight, Sparkles, Check,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

interface PortfolioSchema {
  id: string;
  domain_name: string;
  label: string;
  description: string | null;
  record_noun: string;
  record_noun_plural: string;
  schema_json: any;
  is_active: boolean;
  tool_name: string;
  created_at: string;
  updated_at: string;
}

interface Template {
  id: string;
  label: string;
  description: string;
  schema_json: any;
}

export default function PortfolioSchemasPage() {
  const { data: schemas, mutate } = useApi<PortfolioSchema[]>('/api/portfolio-schemas');
  const { data: templates } = useApi<Template[]>('/api/portfolio-schemas/templates/list');
  const { data: allAgents } = useApi<any[]>('/api/agents?limit=500');

  // Map tool_name -> [{slug, name}] for the "used by these agents" badge
  const agentsByTool = (() => {
    const m = new Map<string, { slug: string; name: string }[]>();
    for (const a of (allAgents || [])) {
      const tools = a?.model_config?.tools as string[] | undefined;
      if (!tools) continue;
      for (const t of tools) {
        const arr = m.get(t) || [];
        arr.push({ slug: a.slug, name: a.name });
        m.set(t, arr);
      }
    }
    return m;
  })();
  const [selected, setSelected] = useState<PortfolioSchema | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draftJson, setDraftJson] = useState('');
  const [draftLabel, setDraftLabel] = useState('');
  const [draftDomainName, setDraftDomainName] = useState('');
  const [showTemplates, setShowTemplates] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const startEdit = (s: PortfolioSchema) => {
    setSelected(s);
    setDraftLabel(s.label);
    setDraftDomainName(s.domain_name);
    setDraftJson(JSON.stringify(s.schema_json, null, 2));
    setEditing(true);
    setCreating(false);
    setError('');
  };

  const startCreate = (template?: Template) => {
    setSelected(null);
    setDraftLabel(template?.label || '');
    setDraftDomainName('');
    setDraftJson(JSON.stringify(template?.schema_json || {
      domain: { name: '', label: '', record_noun: 'record', record_noun_plural: 'records' },
      main_table: {
        name: '',
        user_scope_column: 'user_id',
        title_column: 'title',
        list_columns: [],
        columns: {},
        summary_aggregations: {},
      },
      related_tables: [],
    }, null, 2));
    setCreating(true);
    setEditing(true);
    setShowTemplates(false);
    setError('');
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const schemaObj = JSON.parse(draftJson);
      if (creating) {
        if (!draftDomainName.match(/^[a-z][a-z0-9_]*$/)) {
          throw new Error('domain_name must be lowercase letters, numbers, underscores (start with letter)');
        }
        const res = await apiFetch<any>('/api/portfolio-schemas', {
          method: 'POST',
          body: JSON.stringify({
            domain_name: draftDomainName,
            label: draftLabel,
            description: schemaObj.domain?.description || null,
            record_noun: schemaObj.domain?.record_noun || 'record',
            record_noun_plural: schemaObj.domain?.record_noun_plural || 'records',
            schema_json: schemaObj,
          }),
        });
        if (res.error) throw new Error(res.error);
      } else if (selected) {
        const res = await apiFetch<any>(`/api/portfolio-schemas/${selected.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            label: draftLabel,
            schema_json: schemaObj,
          }),
        });
        if (res.error) throw new Error(res.error);
      }
      mutate();
      setEditing(false);
      setCreating(false);
      setSelected(null);
    } catch (e: any) {
      setError(e.message || 'Failed to save');
    }
    setSaving(false);
  };

  const remove = async (s: PortfolioSchema) => {
    if (!confirm(`Delete schema "${s.label}"?`)) return;
    await apiFetch(`/api/portfolio-schemas/${s.id}`, { method: 'DELETE' });
    mutate();
    if (selected?.id === s.id) setSelected(null);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center">
              <Database className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                Portfolio Schemas
                <Sparkles className="w-4 h-4 text-purple-400" />
              </h1>
              <p className="text-sm text-slate-400">
                Define domain schemas for the SchemaPortfolioTool — agents query your data without code changes.
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className="px-3 py-2 text-xs rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 transition-colors flex items-center gap-1.5"
            >
              <Layers className="w-3.5 h-3.5" /> Templates
            </button>
            <button
              onClick={() => startCreate()}
              className="px-3 py-2 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium hover:shadow-lg hover:shadow-purple-500/20 transition-all flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" /> New Schema
            </button>
          </div>
        </div>

        {/* What this is — onboarding explainer */}
        <div className="bg-gradient-to-br from-purple-500/5 via-slate-800/30 to-pink-500/5 border border-purple-500/20 rounded-xl p-5">
          <div className="flex items-start gap-3 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-500/20 border border-purple-500/40 flex items-center justify-center shrink-0 mt-0.5">
              <Sparkles className="w-4 h-4 text-purple-300" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">What is a Portfolio Schema?</h2>
              <p className="text-[12px] text-slate-300 mt-1 leading-relaxed">
                A <strong className="text-white">Portfolio Schema</strong> is a declarative description of your domain's tables, columns, and relationships
                (e.g. <code className="text-purple-300">contracts → clauses → events</code>). Once registered, the platform's
                <code className="text-purple-300 mx-1">SchemaPortfolioTool</code> automatically lets <strong className="text-white">any agent</strong> query
                that data — list rows, fetch a record by id, search free-text, follow relationships — without you writing a custom tool per table.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">1 · Define</p>
              <p className="text-[11px] text-slate-300">Pick a starter template or write your own JSON: tables, columns, primary keys, relationships, free-text search fields.</p>
            </div>
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">2 · Wire to agents</p>
              <p className="text-[11px] text-slate-300">Add tool <code className="text-purple-300">portfolio_<em>your_domain</em></code> to any agent. The tool exposes <code>list_records</code>, <code>get_record</code>, <code>search</code>, <code>get_summary</code>, <code>get_related</code>, <code>discover_fields</code>.</p>
            </div>
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">3 · Chat / query</p>
              <p className="text-[11px] text-slate-300">Users ask cross-portfolio questions in natural language. The agent picks the right schema operation, RBAC is enforced via <code>ActingSubject</code>, and answers cite specific rows.</p>
            </div>
          </div>
          <div className="flex items-start gap-2 mt-3 text-[11px] text-slate-400 bg-slate-900/40 border border-slate-700/40 rounded-lg p-2.5">
            <Database className="w-3.5 h-3.5 text-cyan-400 mt-0.5 shrink-0" />
            <p>
              <strong className="text-white">Already used by:</strong> the example app&apos;s chat agent uses the <code className="text-cyan-300">portfolio_energy_contracts</code> tool
              (built from the Energy Contracts starter schema) to answer cross-contract questions like &quot;total MW expiring before 2030&quot;.
              The same pattern can be reused by any standalone app — just register your schema, point your agent&apos;s
              <code className="text-cyan-300 mx-1">tools:</code> array at it.
            </p>
          </div>
        </div>

        {/* Templates dropdown */}
        {showTemplates && templates && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
            <p className="text-xs font-semibold text-white uppercase tracking-wider mb-3">Starter Templates</p>
            <div className="grid grid-cols-3 gap-3">
              {templates.map(t => (
                <button
                  key={t.id}
                  onClick={() => startCreate(t)}
                  className="text-left p-3 rounded-lg border border-slate-700 hover:border-purple-500/50 hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Package className="w-4 h-4 text-purple-400" />
                    <span className="text-xs font-semibold text-white">{t.label}</span>
                  </div>
                  <p className="text-[10px] text-slate-400">{t.description}</p>
                </button>
              ))}
            </div>
          </motion.div>
        )}

        <div className="grid grid-cols-12 gap-6">
          {/* Schema list */}
          <div className="col-span-4 space-y-2">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1">
              Your Schemas ({schemas?.length || 0})
            </p>
            {(schemas || []).map(s => (
              <div
                key={s.id}
                onClick={() => setSelected(s)}
                className={`bg-slate-800/30 border rounded-lg p-3 cursor-pointer transition-colors ${
                  selected?.id === s.id ? 'border-purple-500/50 bg-purple-500/5' : 'border-slate-700/50 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <FileJson className="w-3.5 h-3.5 text-purple-400" />
                    <span className="text-sm font-medium text-white">{s.label}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); startEdit(s); }}
                      className="p-1 text-slate-500 hover:text-white"
                    >
                      <Edit3 className="w-3 h-3" />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); remove(s); }}
                      className="p-1 text-slate-500 hover:text-red-400"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                <div className="text-[10px] text-slate-500 font-mono">{s.tool_name}</div>
                {s.description && <p className="text-[10px] text-slate-400 mt-1 line-clamp-2">{s.description}</p>}
                {(() => {
                  const used = agentsByTool.get(s.tool_name) || [];
                  if (used.length === 0) {
                    return (
                      <p className="text-[10px] text-amber-300/70 mt-1.5 inline-flex items-center gap-1">
                        ⚠ Not wired to any agent yet — add <code className="text-amber-200">{s.tool_name}</code> to an agent&apos;s tools.
                      </p>
                    );
                  }
                  return (
                    <p className="text-[10px] text-emerald-300 mt-1.5 truncate" title={used.map(a => a.name).join(', ')}>
                      ✓ Used by {used.length} agent{used.length !== 1 ? 's' : ''}: <span className="text-slate-300">{used.slice(0, 3).map(a => a.name).join(', ')}</span>{used.length > 3 ? ` +${used.length - 3}` : ''}
                    </p>
                  );
                })()}
              </div>
            ))}
            {(!schemas || schemas.length === 0) && (
              <div className="bg-slate-800/20 border border-slate-700/30 rounded-lg p-8 text-center">
                <FileJson className="w-8 h-8 text-slate-600 mx-auto mb-2" />
                <p className="text-xs text-slate-500">No schemas yet</p>
                <button
                  onClick={() => startCreate()}
                  className="mt-3 text-xs text-purple-400 hover:text-purple-300"
                >
                  Create your first schema →
                </button>
              </div>
            )}
          </div>

          {/* Detail / Editor */}
          <div className="col-span-8">
            {editing ? (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    {creating ? 'New Schema' : `Edit: ${selected?.label}`}
                  </h3>
                  <div className="flex gap-2">
                    <button
                      onClick={() => { setEditing(false); setCreating(false); }}
                      className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-400 hover:text-white"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={save}
                      disabled={saving || !draftLabel}
                      className="px-3 py-1.5 text-xs rounded-lg bg-purple-500 text-white hover:bg-purple-400 disabled:opacity-30 flex items-center gap-1"
                    >
                      <Save className="w-3 h-3" /> {saving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                </div>
                <div className="p-5 space-y-4">
                  {creating && (
                    <div>
                      <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 block">
                        Domain Name (snake_case)
                      </label>
                      <input
                        type="text"
                        value={draftDomainName}
                        onChange={e => setDraftDomainName(e.target.value)}
                        placeholder="e.g., real_estate"
                        className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none font-mono"
                      />
                      <p className="text-[10px] text-slate-500 mt-1">
                        The tool will be named <span className="font-mono text-purple-400">portfolio_{draftDomainName || 'your_domain'}</span>
                      </p>
                    </div>
                  )}
                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 block">
                      Display Label
                    </label>
                    <input
                      type="text"
                      value={draftLabel}
                      onChange={e => setDraftLabel(e.target.value)}
                      placeholder="e.g., Real Estate Portfolio"
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 block">
                      Schema JSON
                    </label>
                    <textarea
                      value={draftJson}
                      onChange={e => setDraftJson(e.target.value)}
                      rows={24}
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-[10px] text-emerald-300 placeholder-slate-500 focus:border-purple-500 focus:outline-none font-mono resize-none"
                    />
                  </div>
                  {error && (
                    <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-400">
                      {error}
                    </div>
                  )}
                </div>
              </div>
            ) : selected ? (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-white">{selected.label}</h3>
                    <p className="text-[10px] text-slate-500 font-mono">{selected.tool_name}</p>
                  </div>
                  <button
                    onClick={() => startEdit(selected)}
                    className="px-3 py-1.5 text-xs rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-400 hover:bg-purple-500/20 flex items-center gap-1"
                  >
                    <Edit3 className="w-3 h-3" /> Edit
                  </button>
                </div>
                <div className="p-5">
                  <pre className="text-[10px] text-slate-400 font-mono overflow-x-auto max-h-[600px] overflow-y-auto bg-slate-900/50 rounded-lg p-3">
                    {JSON.stringify(selected.schema_json, null, 2)}
                  </pre>
                </div>
              </div>
            ) : (
              <div className="bg-slate-800/20 border border-slate-700/30 rounded-xl p-12 text-center">
                <Database className="w-10 h-10 text-slate-600 mx-auto mb-3" />
                <p className="text-sm text-slate-400 mb-1">Select a schema to view, or create a new one</p>
                <p className="text-[10px] text-slate-500">
                  Schemas define how the SchemaPortfolioTool queries your domain data.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
