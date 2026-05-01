'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft, Brain, Loader2, Network, Plus, Save, Sparkles, Trash2,
} from 'lucide-react';

import { useApi } from '@/hooks/useApi';
import { API_URL } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { usePageTitle } from '@/hooks/usePageTitle';

type Tab = 'schema' | 'correlations';

interface KProject {
  id: string;
  name: string;
  slug: string;
  ontology_schema_id: string | null;
}

interface EntityType { name: string; description: string; synonyms: string[]; }
interface RelType { name: string; description: string; source_types: string[]; target_types: string[]; }

interface OntologySchema {
  id: string;
  project_id: string;
  version: number;
  name: string;
  description: string;
  entity_types: EntityType[];
  relationship_types: RelType[];
  created_by: string | null;
  created_at: string | null;
}

interface Correlation { name: string; type: string; mentions: number; collections: number; }
interface RelatedItem { name: string; type: string; mentions: number; shared_documents: number; }
// /api/me/permissions returns { is_admin, features: { manage_ontology, … } }.
// The old shape (flat) is kept as a fallback for older API deployments.
interface Permissions {
  is_admin?: boolean;
  manage_ontology?: boolean;
  features?: { manage_ontology?: boolean };
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : {};
}

// ─── Schema editor ──────────────────────────────────────────────────

function SchemaEditor({
  projectId,
  active,
  canEdit,
  onSaved,
}: {
  projectId: string;
  active: OntologySchema | null;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [name, setName] = useState(active?.name || 'v1');
  const [description, setDescription] = useState(active?.description || '');
  const [entities, setEntities] = useState<EntityType[]>(active?.entity_types || []);
  const [relationships, setRelationships] = useState<RelType[]>(active?.relationship_types || []);
  const [saving, setSaving] = useState(false);

  // Reset local state when the active schema id changes (e.g. after activate).
  useEffect(() => {
    setName(active?.name || 'v1');
    setDescription(active?.description || '');
    setEntities(active?.entity_types || []);
    setRelationships(active?.relationship_types || []);
  }, [active?.id]);

  const addEntity = () => setEntities([...entities, { name: '', description: '', synonyms: [] }]);
  const removeEntity = (i: number) => setEntities(entities.filter((_, idx) => idx !== i));
  const updateEntity = (i: number, patch: Partial<EntityType>) =>
    setEntities(entities.map((e, idx) => idx === i ? { ...e, ...patch } : e));

  const addRel = () => setRelationships([...relationships, { name: '', description: '', source_types: [], target_types: [] }]);
  const removeRel = (i: number) => setRelationships(relationships.filter((_, idx) => idx !== i));
  const updateRel = (i: number, patch: Partial<RelType>) =>
    setRelationships(relationships.map((r, idx) => idx === i ? { ...r, ...patch } : r));

  const save = async () => {
    if (!name.trim()) { toastError('Schema name is required'); return; }
    const cleanEntities = entities.filter((e) => e.name.trim()).map((e) => ({
      name: e.name.trim(), description: e.description, synonyms: e.synonyms,
    }));
    const cleanRels = relationships.filter((r) => r.name.trim()).map((r) => ({
      name: r.name.trim().toUpperCase().replace(/\s+/g, '_'),
      description: r.description,
      source_types: r.source_types,
      target_types: r.target_types,
    }));
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/api/knowledge-projects/${projectId}/ontology-schemas`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          name: name.trim(),
          description,
          entity_types: cleanEntities,
          relationship_types: cleanRels,
        }),
      });
      const json = await res.json();
      if (json.error) { toastError(json.error.message || 'Save failed'); return; }
      toastSuccess(`Saved as version ${json.data.version}`);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  if (!canEdit) {
    return (
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6">
        <div className="text-sm text-slate-300 mb-3">You can view the current ontology but not edit it.</div>
        <div className="text-xs text-slate-500">Editing requires the <code className="px-1 py-0.5 rounded bg-slate-800 text-emerald-300">manage_ontology</code> permission, project ownership, or tenant admin.</div>
        {active && (
          <div className="mt-6">
            <SchemaReadView active={active} />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Metadata */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-3">
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">Schema name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
            placeholder="e.g. Legal Domain v1"
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">Description</label>
          <textarea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500 resize-none"
            placeholder="What domain does this ontology cover?"
          />
        </div>
        {active && (
          <div className="text-xs text-slate-500">
            Currently active: <span className="font-mono text-slate-300">{active.name} v{active.version}</span>. Saving creates a new version.
          </div>
        )}
      </div>

      {/* Entity types */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-semibold text-white">Entity types</div>
            <div className="text-xs text-slate-500">What kinds of things live in your documents.</div>
          </div>
          <button
            onClick={addEntity}
            className="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-medium rounded-md border border-emerald-500/30"
          >
            <Plus className="w-3 h-3" /> Add type
          </button>
        </div>
        <div className="space-y-2">
          {entities.length === 0 && (
            <div className="text-xs text-slate-500 py-3 text-center">
              No entity types yet. Add one — e.g. <span className="font-mono">Contract</span>, <span className="font-mono">Party</span>, <span className="font-mono">Obligation</span>.
            </div>
          )}
          {entities.map((e, i) => (
            <div key={i} className="bg-slate-800/40 border border-slate-700/40 rounded-lg p-3 grid grid-cols-12 gap-3">
              <input
                value={e.name}
                onChange={(ev) => updateEntity(i, { name: ev.target.value })}
                placeholder="Type name"
                className="col-span-3 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 font-mono outline-none focus:border-emerald-500"
              />
              <input
                value={e.description}
                onChange={(ev) => updateEntity(i, { description: ev.target.value })}
                placeholder="One-sentence description"
                className="col-span-7 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-emerald-500"
              />
              <input
                value={(e.synonyms || []).join(', ')}
                onChange={(ev) => updateEntity(i, { synonyms: ev.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                placeholder="synonyms (comma-sep)"
                className="col-span-1 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 outline-none focus:border-emerald-500"
              />
              <button
                onClick={() => removeEntity(i)}
                className="col-span-1 text-slate-500 hover:text-red-400"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Relationship types */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-semibold text-white">Relationship types</div>
            <div className="text-xs text-slate-500">How entities connect. UPPER_SNAKE_CASE recommended.</div>
          </div>
          <button
            onClick={addRel}
            className="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-medium rounded-md border border-emerald-500/30"
          >
            <Plus className="w-3 h-3" /> Add relationship
          </button>
        </div>
        <div className="space-y-2">
          {relationships.length === 0 && (
            <div className="text-xs text-slate-500 py-3 text-center">
              No relationship types yet. e.g. <span className="font-mono">GOVERNS</span>, <span className="font-mono">EXPIRES_ON</span>, <span className="font-mono">PARTY_TO</span>.
            </div>
          )}
          {relationships.map((r, i) => (
            <div key={i} className="bg-slate-800/40 border border-slate-700/40 rounded-lg p-3 grid grid-cols-12 gap-3">
              <input
                value={r.name}
                onChange={(ev) => updateRel(i, { name: ev.target.value })}
                placeholder="REL_NAME"
                className="col-span-2 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 font-mono outline-none focus:border-emerald-500 uppercase"
              />
              <input
                value={r.description}
                onChange={(ev) => updateRel(i, { description: ev.target.value })}
                placeholder="What does this relationship mean?"
                className="col-span-5 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-emerald-500"
              />
              <input
                value={(r.source_types || []).join(', ')}
                onChange={(ev) => updateRel(i, { source_types: ev.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                placeholder="from types"
                className="col-span-2 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 outline-none focus:border-emerald-500"
              />
              <input
                value={(r.target_types || []).join(', ')}
                onChange={(ev) => updateRel(i, { target_types: ev.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                placeholder="to types"
                className="col-span-2 bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 outline-none focus:border-emerald-500"
              />
              <button
                onClick={() => removeRel(i)}
                className="col-span-1 text-slate-500 hover:text-red-400"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Save */}
      <div className="flex justify-end">
        <button
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save as new version
        </button>
      </div>
    </div>
  );
}

function SchemaReadView({ active }: { active: OntologySchema }) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-400 mb-1">Entity types</div>
        <div className="grid grid-cols-2 gap-2">
          {active.entity_types.map((e, i) => (
            <div key={i} className="bg-slate-800/40 border border-slate-700/40 rounded p-2">
              <div className="font-mono text-emerald-300 text-xs">{e.name}</div>
              <div className="text-slate-400 text-xs mt-0.5">{e.description}</div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-400 mb-1">Relationship types</div>
        <div className="grid grid-cols-2 gap-2">
          {active.relationship_types.map((r, i) => (
            <div key={i} className="bg-slate-800/40 border border-slate-700/40 rounded p-2">
              <div className="font-mono text-cyan-300 text-xs">{r.name}</div>
              <div className="text-slate-400 text-xs mt-0.5">{r.description}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Correlations view ──────────────────────────────────────────────

function CorrelationsView({ projectId }: { projectId: string }) {
  const { data: top, isLoading } = useApi<Correlation[]>(`/api/knowledge-projects/${projectId}/correlations`);
  const [selected, setSelected] = useState<Correlation | null>(null);
  const [related, setRelated] = useState<RelatedItem[]>([]);
  const [loadingRelated, setLoadingRelated] = useState(false);

  const loadRelated = async (entity: Correlation) => {
    setSelected(entity);
    setLoadingRelated(true);
    setRelated([]);
    try {
      const res = await fetch(
        `${API_URL}/api/knowledge-projects/${projectId}/correlations/${encodeURIComponent(entity.name)}`,
        { headers: authHeaders() },
      );
      const json = await res.json();
      if (json.error) { toastError(json.error.message); return; }
      setRelated(json.data?.related || []);
    } finally {
      setLoadingRelated(false);
    }
  };

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-5 bg-slate-900/40 border border-slate-800 rounded-xl p-4">
        <div className="text-sm font-semibold text-white mb-3">Top entities</div>
        {isLoading ? (
          <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
        ) : !top || top.length === 0 ? (
          <div className="text-xs text-slate-500 py-6 text-center">
            No entities yet. Run Cognify on a collection first.
          </div>
        ) : (
          <div className="space-y-1 max-h-[60vh] overflow-auto">
            {top.map((e) => (
              <button
                key={`${e.type}:${e.name}`}
                onClick={() => loadRelated(e)}
                className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                  selected?.name === e.name
                    ? 'bg-emerald-500/10 border-emerald-500/40'
                    : 'bg-slate-800/30 border-slate-700/30 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="text-sm text-white truncate">{e.name}</div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-400">{e.type}</span>
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {e.mentions} mention{e.mentions === 1 ? '' : 's'} · {e.collections} collection{e.collections === 1 ? '' : 's'}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="col-span-7 bg-slate-900/40 border border-slate-800 rounded-xl p-4">
        <div className="text-sm font-semibold text-white mb-3">
          {selected ? <>Related to <span className="text-emerald-300 font-mono">{selected.name}</span></> : 'Pick an entity to see correlations'}
        </div>
        {!selected ? (
          <div className="text-xs text-slate-500 py-12 text-center">
            <Network className="w-8 h-8 text-slate-700 mx-auto mb-2" />
            Click an entity on the left.
          </div>
        ) : loadingRelated ? (
          <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
        ) : related.length === 0 ? (
          <div className="text-xs text-slate-500 py-6 text-center">No related entities found.</div>
        ) : (
          <div className="space-y-2 max-h-[60vh] overflow-auto">
            {related.map((r, i) => (
              <div key={`${r.type}:${r.name}:${i}`} className="bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2 flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">{r.name}</div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{r.type}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-emerald-300">{r.shared_documents} shared doc{r.shared_documents === 1 ? '' : 's'}</div>
                  <div className="text-[10px] text-slate-500">{r.mentions} mention{r.mentions === 1 ? '' : 's'}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────

export default function OntologyPage({ params }: { params: { projectId: string } }) {
  const { projectId } = params;
  usePageTitle('Ontology');
  const [tab, setTab] = useState<Tab>('schema');

  const { data: project } = useApi<KProject>(`/api/knowledge-projects/${projectId}`);
  const { data: active, mutate: mutateActive } = useApi<OntologySchema | null>(
    `/api/knowledge-projects/${projectId}/ontology-schemas/active`,
  );
  const { data: perms } = useApi<Permissions>('/api/me/permissions');

  const canEdit = useMemo(
    () => Boolean(perms?.is_admin || perms?.features?.manage_ontology || perms?.manage_ontology),
    [perms],
  );

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <Link
            href="/knowledge/projects"
            className="text-xs text-slate-500 hover:text-slate-300 inline-flex items-center gap-1 mb-3"
          >
            <ArrowLeft className="w-3 h-3" /> Back to projects
          </Link>
          <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
            <Brain className="w-6 h-6 text-emerald-400 shrink-0" />
            <span>Ontology</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1 truncate">
            {project ? <>For project <span className="font-mono text-slate-300">{project.slug}</span> · {project.name}</> : 'Loading…'}
          </p>
        </div>
        {active && (
          <div className="shrink-0 text-xs text-slate-400 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5">
            Active: <span className="text-emerald-300 font-mono">{active.name} v{active.version}</span>
          </div>
        )}
      </div>

      <div className="flex gap-2 border-b border-slate-800 mb-6">
        <button
          onClick={() => setTab('schema')}
          className={`px-4 py-2 text-sm inline-flex items-center gap-1 ${tab === 'schema' ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}
        >
          <Sparkles className="w-4 h-4" /> Schema
        </button>
        <button
          onClick={() => setTab('correlations')}
          className={`px-4 py-2 text-sm inline-flex items-center gap-1 ${tab === 'correlations' ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}
        >
          <Network className="w-4 h-4" /> Correlations
        </button>
      </div>

      {tab === 'schema' ? (
        <SchemaEditor
          projectId={projectId}
          active={active ?? null}
          canEdit={canEdit}
          onSaved={() => mutateActive()}
        />
      ) : (
        <CorrelationsView projectId={projectId} />
      )}
    </div>
  );
}
