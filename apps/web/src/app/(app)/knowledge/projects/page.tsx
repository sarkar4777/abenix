'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Brain, ChevronRight, Database, FolderOpen, Loader2, Plus, Search,
  Shield, Trash2, Users, X,
} from 'lucide-react';

import ResponsiveModal from '@/components/ui/ResponsiveModal';
import EmptyState from '@/components/ui/EmptyState';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface KProject {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description: string;
  collection_count: number;
  created_at: string | null;
}

interface KCollection {
  id: string;
  name: string;
  description: string;
  status: string;
  doc_count: number;
  default_visibility: string;
  vector_backend: string;
  created_by: string | null;
  created_at: string | null;
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : {};
}

function statusColor(status: string): string {
  if (status === 'ready') return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
  if (status === 'processing') return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
  return 'text-red-400 bg-red-500/10 border-red-500/20';
}

function visibilityColor(v: string): string {
  if (v === 'tenant') return 'text-cyan-300 bg-cyan-500/10';
  if (v === 'project') return 'text-indigo-300 bg-indigo-500/10';
  return 'text-slate-300 bg-slate-700/40';
}

// ─── Create-Project Modal ───────────────────────────────────────────

function CreateProjectModal({
  open, onClose, onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (p: KProject) => void;
}) {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const reset = () => { setName(''); setSlug(''); setDescription(''); setErr(''); };

  const submit = async () => {
    if (!name.trim()) { setErr('Name is required'); return; }
    setSubmitting(true);
    setErr('');
    try {
      const res = await fetch(`${API_URL}/api/knowledge-projects`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          name: name.trim(),
          slug: slug.trim() || undefined,
          description: description.trim(),
        }),
      });
      const json = await res.json();
      if (json.error) { setErr(json.error.message || 'Failed'); return; }
      onCreated(json.data);
      toastSuccess('Project created');
      reset();
      onClose();
    } catch {
      setErr('Failed to create');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ResponsiveModal open={open} onClose={() => { reset(); onClose(); }} title="New Knowledge Project">
      <div className="space-y-4">
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">Name</label>
          <input
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Legal Knowledge"
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">
            Slug <span className="text-slate-500 normal-case">(optional — auto-generated from name)</span>
          </label>
          <input
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="legal-knowledge"
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">Description</label>
          <textarea
            className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500 resize-none"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What's this project for?"
          />
        </div>
        {err && <div className="text-xs text-red-400">{err}</div>}
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={() => { reset(); onClose(); }}
            className="px-3 py-2 text-sm text-slate-300 hover:text-white"
          >Cancel</button>
          <button
            onClick={submit}
            disabled={submitting}
            className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50 inline-flex items-center gap-2"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />} Create Project
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}

// ─── Grants Modal (per-collection) ──────────────────────────────────

interface AgentGrant { id: string; agent_id: string; permission: string; granted_at: string | null; }
interface UserGrant { id: string; user_id: string; permission: string; granted_at: string | null; expires_at: string | null; }

function GrantsModal({
  collectionId, collectionName, open, onClose,
}: {
  collectionId: string | null;
  collectionName: string;
  open: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'agents' | 'users'>('agents');
  const [agents, setAgents] = useState<AgentGrant[]>([]);
  const [users, setUsers] = useState<UserGrant[]>([]);
  const [loading, setLoading] = useState(false);
  const [newId, setNewId] = useState('');
  const [newPerm, setNewPerm] = useState('READ');
  const [submitting, setSubmitting] = useState(false);

  const refresh = async () => {
    if (!collectionId) return;
    setLoading(true);
    try {
      const [aRes, uRes] = await Promise.all([
        fetch(`${API_URL}/api/knowledge-collections/${collectionId}/agents`, { headers: authHeaders() }),
        fetch(`${API_URL}/api/knowledge-collections/${collectionId}/users`, { headers: authHeaders() }),
      ]);
      const aJson = await aRes.json();
      const uJson = await uRes.json();
      setAgents(aJson.data || []);
      setUsers(uJson.data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && collectionId) {
      void refresh();
      setNewId('');
      setNewPerm('READ');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, collectionId]);

  const grant = async () => {
    if (!collectionId || !newId.trim()) return;
    setSubmitting(true);
    try {
      const path = tab === 'agents'
        ? `${API_URL}/api/knowledge-collections/${collectionId}/agents`
        : `${API_URL}/api/knowledge-collections/${collectionId}/users`;
      const body = tab === 'agents'
        ? { agent_id: newId.trim(), permission: newPerm }
        : { user_id: newId.trim(), permission: newPerm };
      const res = await fetch(path, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify(body),
      });
      const json = await res.json();
      if (json.error) { toastError(json.error.message || 'Grant failed'); return; }
      toastSuccess('Grant saved');
      setNewId('');
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const revoke = async (subjectId: string) => {
    if (!collectionId) return;
    const path = tab === 'agents'
      ? `${API_URL}/api/knowledge-collections/${collectionId}/agents/${subjectId}`
      : `${API_URL}/api/knowledge-collections/${collectionId}/users/${subjectId}`;
    const res = await fetch(path, { method: 'DELETE', headers: authHeaders() });
    const json = await res.json();
    if (json.error) { toastError(json.error.message || 'Revoke failed'); return; }
    toastSuccess('Grant revoked');
    await refresh();
  };

  return (
    <ResponsiveModal open={open} onClose={onClose} title={`Manage Access — ${collectionName}`}>
      <div className="space-y-4">
        <div className="flex gap-2 border-b border-slate-800">
          {(['agents', 'users'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm capitalize ${tab === t ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}
            >
              {t === 'agents' ? <Shield className="w-4 h-4 inline -mt-px mr-1" /> : <Users className="w-4 h-4 inline -mt-px mr-1" />}
              {t}
            </button>
          ))}
        </div>

        {/* Existing grants list */}
        <div className="space-y-2 max-h-72 overflow-auto pr-1">
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
          ) : tab === 'agents' ? (
            agents.length === 0 ? (
              <div className="text-center text-xs text-slate-500 py-6">No agent grants yet.</div>
            ) : agents.map((g) => (
              <div key={g.id} className="flex items-center justify-between bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2">
                <div>
                  <div className="text-xs font-mono text-slate-300">{g.agent_id.slice(0, 8)}…</div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{g.permission}</div>
                </div>
                <button onClick={() => void revoke(g.agent_id)} className="text-slate-500 hover:text-red-400 p-1">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          ) : (
            users.length === 0 ? (
              <div className="text-center text-xs text-slate-500 py-6">No user grants yet.</div>
            ) : users.map((g) => (
              <div key={g.id} className="flex items-center justify-between bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2">
                <div>
                  <div className="text-xs font-mono text-slate-300">{g.user_id.slice(0, 8)}…</div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{g.permission}</div>
                </div>
                <button onClick={() => void revoke(g.user_id)} className="text-slate-500 hover:text-red-400 p-1">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
        </div>

        {/* Grant form */}
        <div className="border-t border-slate-800 pt-4">
          <div className="text-xs uppercase tracking-wider text-slate-400 mb-2">Add grant</div>
          <div className="flex gap-2">
            <input
              className="flex-1 bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500 font-mono"
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              placeholder={tab === 'agents' ? 'agent UUID' : 'user UUID'}
            />
            <select
              className="bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100"
              value={newPerm}
              onChange={(e) => setNewPerm(e.target.value)}
            >
              <option value="READ">READ</option>
              <option value="WRITE">WRITE</option>
              <option value="ADMIN">ADMIN</option>
            </select>
            <button
              onClick={grant}
              disabled={submitting || !newId.trim()}
              className="px-3 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50"
            >Grant</button>
          </div>
        </div>
      </div>
    </ResponsiveModal>
  );
}

// ─── Page ───────────────────────────────────────────────────────────

export default function KnowledgeProjectsPage() {
  usePageTitle('Knowledge Projects');
  const { data: projects, isLoading, mutate } = useApi<KProject[]>('/api/knowledge-projects?limit=100');
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [grantsFor, setGrantsFor] = useState<{ id: string; name: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<KProject | null>(null);
  const [collections, setCollections] = useState<Record<string, KCollection[]>>({});

  const filtered = useMemo(() => {
    if (!projects) return [] as KProject[];
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) =>
      p.name.toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q),
    );
  }, [projects, search]);

  const loadCollections = async (projectId: string) => {
    if (collections[projectId]) return;
    try {
      const res = await fetch(
        `${API_URL}/api/knowledge-projects/${projectId}/collections`,
        { headers: authHeaders() },
      );
      const json = await res.json();
      setCollections((m) => ({ ...m, [projectId]: json.data || [] }));
    } catch {
      // toastError handled by global; soft-fail UI
    }
  };

  const toggle = (projectId: string) => {
    if (expanded === projectId) {
      setExpanded(null);
    } else {
      setExpanded(projectId);
      void loadCollections(projectId);
    }
  };

  const removeProject = async (p: KProject) => {
    try {
      const res = await fetch(`${API_URL}/api/knowledge-projects/${p.id}`, {
        method: 'DELETE', headers: authHeaders(),
      });
      const json = await res.json();
      if (json.error) { toastError(json.error.message || 'Delete failed'); return; }
      toastSuccess('Project deleted');
      mutate();
    } finally {
      setConfirmDelete(null);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link href="/knowledge" className="text-xs text-slate-500 hover:text-slate-300 inline-flex items-center gap-1 mb-2">
            <ArrowLeft className="w-3 h-3" /> Back to all collections
          </Link>
          <h1 className="text-2xl font-semibold text-white">Knowledge Projects</h1>
          <p className="text-sm text-slate-400 mt-1">
            Group related collections, manage access per agent or per user, share an ontology across them.
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm"
        >
          <Plus className="w-4 h-4" /> New Project
        </button>
      </div>

      {/* Search */}
      <div className="relative mb-4 max-w-md">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          className="w-full pl-9 pr-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-100 outline-none focus:border-emerald-500"
          placeholder="Search projects…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* List */}
      {isLoading ? (
        <div className="text-sm text-slate-500 py-12 text-center">Loading…</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="No projects yet"
          description="Create your first project to group collections and manage access centrally."
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((p) => (
            <div key={p.id} className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden">
              <button
                onClick={() => toggle(p.id)}
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-800/30 transition-colors text-left"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
                    <FolderOpen className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium text-white truncate">{p.name}</div>
                    <div className="text-xs text-slate-500 truncate">
                      <span className="font-mono">{p.slug}</span> · {p.collection_count} collection{p.collection_count === 1 ? '' : 's'}
                      {p.description && <> · {p.description}</>}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Link
                    href={`/knowledge/projects/${p.id}/ontology`}
                    onClick={(e) => e.stopPropagation()}
                    className="hidden sm:inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
                    title="Open ontology editor"
                  >
                    <Brain className="w-3 h-3" /> Ontology
                  </Link>
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirmDelete(p); }}
                    className="text-slate-500 hover:text-red-400 p-1"
                    title="Delete project (must be empty)"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <ChevronRight className={`w-5 h-5 text-slate-500 transition-transform ${expanded === p.id ? 'rotate-90' : ''}`} />
                </div>
              </button>

              <AnimatePresence initial={false}>
                {expanded === p.id && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden border-t border-slate-800"
                  >
                    <div className="p-4 space-y-2">
                      {!collections[p.id] ? (
                        <div className="text-xs text-slate-500 py-3 text-center">Loading collections…</div>
                      ) : collections[p.id].length === 0 ? (
                        <div className="text-xs text-slate-500 py-3 text-center">
                          No collections yet. Create one from the{' '}
                          <Link href="/knowledge" className="text-emerald-400 hover:underline">Knowledge page</Link>.
                        </div>
                      ) : (
                        collections[p.id].map((c) => (
                          <div key={c.id} className="flex items-center justify-between bg-slate-800/40 border border-slate-700/40 rounded-lg px-4 py-3">
                            <div className="flex items-center gap-3 min-w-0">
                              <Database className="w-4 h-4 text-slate-400 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-sm text-white truncate">{c.name}</div>
                                <div className="text-xs text-slate-500 truncate">
                                  {c.doc_count} doc{c.doc_count === 1 ? '' : 's'} · backend: {c.vector_backend}
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider ${visibilityColor(c.default_visibility)}`}>
                                {c.default_visibility}
                              </span>
                              <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider border ${statusColor(c.status)}`}>
                                {c.status}
                              </span>
                              <button
                                onClick={() => setGrantsFor({ id: c.id, name: c.name })}
                                className="text-xs text-emerald-400 hover:text-emerald-300 inline-flex items-center gap-1"
                              >
                                <Shield className="w-3 h-3" /> Access
                              </button>
                              <Link
                                href={`/knowledge?id=${c.id}`}
                                className="text-xs text-slate-300 hover:text-white"
                              >Open →</Link>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      )}

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => mutate()}
      />

      <GrantsModal
        collectionId={grantsFor?.id ?? null}
        collectionName={grantsFor?.name ?? ''}
        open={grantsFor !== null}
        onClose={() => setGrantsFor(null)}
      />

      <ConfirmModal
        open={confirmDelete !== null}
        title="Delete project?"
        description={confirmDelete ? `This will delete "${confirmDelete.name}". The project must have no collections.` : ''}
        confirmLabel="Delete"
        variant="danger"
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && removeProject(confirmDelete)}
      />
    </div>
  );
}
