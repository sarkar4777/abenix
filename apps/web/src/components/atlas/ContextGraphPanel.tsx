'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Loader2, Network, Search } from 'lucide-react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api-client';

interface ConceptCount {
  id: string;
  label: string;
  entity_count: number;
}

interface ContextData {
  bound: boolean;
  kb_id: string | null;
  kb_name?: string;
  governs_extraction: boolean;
  ontology_mode: string;
  concepts: ConceptCount[];
  entity_count?: number;
  mapped_entities?: number;
  unmapped_entities?: number;
  relationship_count?: number;
  neo4j_available?: boolean;
  neo4j_entity_count?: number;
  last_cognified_at?: string | null;
  latest_job?: { status: string; off_ontology_dropped?: number; stop_reason?: string | null };
}

interface EntityRow {
  name: string;
  type: string;
  description?: string;
  mentions?: number;
  documents?: number;
}

interface Neighbour {
  name: string;
  type: string;
  relationship: string;
  outgoing: boolean;
}

export function ContextGraphSummary({
  graphId,
  canEdit,
  version,
  onChanged,
}: {
  graphId: string;
  canEdit: boolean;
  version?: number;
  onChanged?: () => void;
}) {
  const [data, setData] = useState<ContextData | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await apiFetch<ContextData>(`/api/atlas/graphs/${graphId}/context`, { throwOnError: false });
      if (live && r.data) setData(r.data);
    })();
    return () => { live = false; };
  }, [graphId, version]);

  if (!data) return null;
  if (!data.bound) {
    return (
      <div className="text-[11px] text-slate-500 border border-slate-800 rounded-lg p-3" data-testid="context-graph-unbound">
        <p className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5"><Network className="w-3 h-3" /> Context graph</p>
        Bind a knowledge collection and run Cognify. Your concepts then type what gets extracted, and the real entities show up here.
      </div>
    );
  }

  const toggle = async () => {
    setSaving(true);
    const next = !data.governs_extraction;
    const r = await apiFetch(`/api/atlas/graphs/${graphId}`, {
      method: 'PATCH', throwOnError: false,
      body: JSON.stringify({ settings: { governs_extraction: next } }),
    });
    setSaving(false);
    if (!r.error) {
      setData({ ...data, governs_extraction: next });
      onChanged?.();
    }
  };

  return (
    <div className="text-[11px] text-slate-400 border border-violet-500/30 rounded-lg p-3 space-y-2" data-testid="context-graph-summary">
      <p className="font-semibold text-slate-200 flex items-center gap-1.5"><Network className="w-3 h-3 text-violet-300" /> Context graph</p>
      <p>
        {(data.entity_count || 0).toLocaleString()} entities and {(data.relationship_count || 0).toLocaleString()} relationships from <span className="text-slate-200">{data.kb_name}</span>.
      </p>
      <p data-testid="context-graph-mapping">
        {(data.mapped_entities || 0).toLocaleString()} mapped to a concept, {(data.unmapped_entities || 0).toLocaleString()} not.
      </p>
      {data.neo4j_available === false && (
        <p className="text-amber-300">Neo4j is not answering. These counts come from Postgres and browsing is paused.</p>
      )}
      {!!data.latest_job?.off_ontology_dropped && (
        <p className="text-amber-300">The last Cognify run left out {data.latest_job.off_ontology_dropped.toLocaleString()} proposals that fit no concept here.</p>
      )}
      <div className="max-h-44 overflow-y-auto space-y-0.5">
        {data.concepts.map(c => (
          <p key={c.id} className="flex justify-between gap-2"><span className="truncate text-slate-300">{c.label}</span><span className="font-mono">{c.entity_count.toLocaleString()}</span></p>
        ))}
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={data.governs_extraction} disabled={!canEdit || saving} onChange={() => void toggle()} data-testid="context-graph-governs" />
        These concepts type what Cognify extracts
      </label>
      {data.kb_id && (
        <Link href={`/knowledge/${data.kb_id}/engine`} className="inline-flex items-center gap-1 text-violet-300 hover:text-violet-200">
          Run Cognify <ArrowRight className="w-3 h-3" />
        </Link>
      )}
    </div>
  );
}

export function ConceptEntities({ graphId, conceptId }: { graphId: string; conceptId: string }) {
  const [rows, setRows] = useState<EntityRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ name: string; neighbours: Neighbour[] } | null>(null);

  const load = useCallback(async (after: string, term: string) => {
    setLoading(true);
    const params = new URLSearchParams({ concept_id: conceptId, limit: '25' });
    if (after) params.set('after', after);
    if (term.trim()) params.set('q', term.trim());
    const r = await apiFetch<{ entities: EntityRow[]; next_cursor: string | null }>(
      `/api/atlas/graphs/${graphId}/entities?${params}`, { throwOnError: false },
    );
    setLoading(false);
    if (r.error || !r.data) {
      setError(typeof r.error === 'string' ? r.error : 'Neo4j did not answer. Try again in a moment.');
      return;
    }
    setError(null);
    const page = r.data;
    setRows(prev => (after ? [...prev, ...page.entities] : page.entities));
    setCursor(page.next_cursor);
  }, [graphId, conceptId]);

  useEffect(() => { setOpen(null); void load('', ''); }, [load]);

  const openEntity = async (name: string) => {
    const r = await apiFetch<{ neighbours: Neighbour[] }>(
      `/api/atlas/graphs/${graphId}/entities/neighbourhood?name=${encodeURIComponent(name)}`, { throwOnError: false },
    );
    if (r.data) setOpen({ name, neighbours: r.data.neighbours });
  };

  return (
    <div className="space-y-2 text-[11px]" data-testid="concept-entities">
      <form onSubmit={e => { e.preventDefault(); void load('', q); }} className="flex items-center gap-1.5">
        <Search className="w-3 h-3 text-slate-500" />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Find an entity by name"
          className="flex-1 bg-slate-900/60 border border-slate-800 rounded px-2 py-1 text-slate-200" data-testid="concept-entities-search" />
      </form>
      {error && <p className="text-amber-300" role="alert">{error}</p>}
      {!error && !loading && rows.length === 0 && (
        <p className="text-slate-500">No entities for this concept yet. Run Cognify on the bound collection.</p>
      )}
      <div className="space-y-1">
        {rows.map(e => (
          <button key={e.name} onClick={() => void openEntity(e.name)} className="w-full text-left rounded border border-slate-800 hover:border-violet-500/40 px-2 py-1">
            <span className="text-slate-200 block truncate">{e.name}</span>
            <span className="text-slate-500">{e.mentions ?? 0} mentions in {e.documents ?? 0} documents</span>
          </button>
        ))}
      </div>
      {loading && <Loader2 className="w-3 h-3 animate-spin text-slate-500" />}
      {cursor && !loading && (
        <button onClick={() => void load(cursor, q)} className="text-violet-300 hover:text-violet-200">Load more</button>
      )}
      {open && (
        <div className="rounded border border-violet-500/30 p-2" data-testid="concept-entity-neighbours">
          <p className="text-slate-200 font-semibold mb-1">{open.name}</p>
          {open.neighbours.length === 0 && <p className="text-slate-500">No relationships.</p>}
          {open.neighbours.map((n, i) => (
            <p key={`${n.name}-${i}`} className="text-slate-400">
              {n.outgoing ? '→' : '←'} <span className="font-mono text-[10px]">{n.relationship}</span> {n.name}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
