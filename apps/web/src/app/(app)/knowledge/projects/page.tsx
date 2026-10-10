'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, ChevronRight, Database, FolderOpen, Loader2, Plus, Search,
  Shield, Trash2, Users,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import EmptyState from '@/components/ui/EmptyState';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import SubjectPicker, { useSubjectNames } from '@/components/share/SubjectPicker';
import { ShareExpiryBadge, ShareExpiryInput, expiryToIso } from '@/components/share/ShareExpiry';

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
interface UserGrant { id: string; user_id: string; permission: string; granted_at: string | null; expires_at: string | null; expired?: boolean; }

const COLLECTION_PERM_HELP: Record<string, string> = {
  READ: 'Can search and read the documents.',
  WRITE: 'Can also upload, replace and delete documents.',
  ADMIN: 'Can also change who has access.',
};

function GrantsModal({
  collectionId, collectionName, open, onClose,
}: {
  collectionId: string | null;
  collectionName: string;
  open: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'agents' | 'users'>('users');
  const [agents, setAgents] = useState<AgentGrant[]>([]);
  const [users, setUsers] = useState<UserGrant[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [newId, setNewId] = useState('');
  const [newPerm, setNewPerm] = useState('READ');
  const [expiry, setExpiry] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { names } = useSubjectNames();

  const refresh = async () => {
    if (!collectionId) return;
    setLoading(true);
    setLoadError('');
    try {
      const [aRes, uRes] = await Promise.all([
        apiFetch<AgentGrant[]>(`/api/knowledge-collections/${collectionId}/agents`, { silent: true, throwOnError: false }),
        apiFetch<UserGrant[]>(`/api/knowledge-collections/${collectionId}/users`, { silent: true, throwOnError: false }),
      ]);
      if (aRes.error || uRes.error) setLoadError(aRes.error || uRes.error || 'Could not load access');
      setAgents(aRes.data || []);
      setUsers(uRes.data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && collectionId) {
      void refresh();
      setNewId('');
      setNewPerm('READ');
      setExpiry('');
    }
  }, [open, collectionId]);

  const grant = async () => {
    if (!collectionId || !newId) return;
    setSubmitting(true);
    try {
      const path = tab === 'agents'
        ? `/api/knowledge-collections/${collectionId}/agents`
        : `/api/knowledge-collections/${collectionId}/users`;
      const body = tab === 'agents'
        ? { agent_id: newId, permission: newPerm }
        : { user_id: newId, permission: newPerm, expires_at: expiryToIso(expiry) };
      const res = await apiFetch(path, { method: 'POST', body: JSON.stringify(body), throwOnError: false });
      if (res.error) { toastError('Grant failed', res.error); return; }
      toastSuccess('Access granted', `${names[newId] || 'They'} can now use ${collectionName}`);
      setNewId('');
      setExpiry('');
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const revoke = async (subjectId: string) => {
    if (!collectionId) return;
    if (!window.confirm(`Remove access for ${names[subjectId] || 'this grantee'}?`)) return;
    const path = tab === 'agents'
      ? `/api/knowledge-collections/${collectionId}/agents/${subjectId}`
      : `/api/knowledge-collections/${collectionId}/users/${subjectId}`;
    const res = await apiFetch(path, { method: 'DELETE', throwOnError: false });
    if (res.error) { toastError('Revoke failed', res.error); return; }
    toastSuccess('Access removed');
    await refresh();
  };

  const rows: (AgentGrant | UserGrant)[] = tab === 'agents' ? agents : users;
  const subjectOf = (g: AgentGrant | UserGrant) => ('agent_id' in g ? g.agent_id : g.user_id);

  return (
    <ResponsiveModal open={open} onClose={onClose} title={`Who can use ${collectionName}`}>
      <div className="space-y-4" data-testid="collection-grants-modal">
        <div className="flex gap-2 border-b border-slate-800">
          {(['users', 'agents'] as const).map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); setNewId(''); }}
              data-testid={`grants-tab-${t}`}
              className={`px-3 py-2 text-sm ${tab === t ? 'text-emerald-400 border-b-2 border-emerald-400 -mb-px' : 'text-slate-400 hover:text-slate-200'}`}
            >
              {t === 'agents' ? <Shield className="w-4 h-4 inline -mt-px mr-1" /> : <Users className="w-4 h-4 inline -mt-px mr-1" />}
              {t === 'agents' ? 'Agents' : 'People'}
            </button>
          ))}
        </div>

        {loadError && <p role="alert" className="text-xs text-red-400">{loadError}</p>}

        <div className="space-y-2 max-h-72 overflow-auto pr-1">
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
          ) : rows.length === 0 ? (
            <div className="text-center text-xs text-slate-500 py-6">
              {tab === 'agents' ? 'No agent can search this collection yet.' : 'Nobody has been given access yet.'}
            </div>
          ) : rows.map((g) => {
            const sid = subjectOf(g);
            const expired = 'expired' in g && g.expired;
            return (
              <div key={g.id} data-testid="grant-row" data-subject={sid} className={`flex items-center justify-between gap-2 bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2 ${expired ? 'opacity-70' : ''}`}>
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate">{names[sid] || `${sid.slice(0, 8)}…`}</div>
                  <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                    <span className="text-[10px] uppercase tracking-wider text-slate-500">{g.permission}</span>
                    {'user_id' in g && <ShareExpiryBadge row={g} />}
                  </div>
                </div>
                <button onClick={() => void revoke(sid)} aria-label={`Remove access for ${names[sid] || sid}`} className="text-slate-500 hover:text-red-400 p-1 shrink-0">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            );
          })}
        </div>

        <div className="border-t border-slate-800 pt-4 space-y-2">
          <div className="text-xs uppercase tracking-wider text-slate-400">{tab === 'agents' ? 'Let an agent search it' : 'Give a person access'}</div>
          <div className="flex flex-wrap gap-2">
            <SubjectPicker
              kind={tab === 'agents' ? 'agent' : 'user'}
              value={newId}
              onChange={setNewId}
              exclude={rows.map(subjectOf)}
              testId="grant-subject"
            />
            <select
              className="bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100"
              value={newPerm}
              onChange={(e) => setNewPerm(e.target.value)}
              aria-label="Permission"
              data-testid="grant-permission"
            >
              <option value="READ">Read</option>
              <option value="WRITE">Write</option>
              <option value="ADMIN">Admin</option>
            </select>
            <button
              onClick={grant}
              disabled={submitting || !newId}
              data-testid="grant-submit"
              className="px-3 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50"
            >{submitting ? 'Saving…' : 'Grant'}</button>
          </div>
          <p className="text-[11px] text-slate-500">{COLLECTION_PERM_HELP[newPerm]}</p>
          {tab === 'users' && <ShareExpiryInput value={expiry} onChange={setExpiry} testId="grant-expiry" />}
        </div>
      </div>
    </ResponsiveModal>
  );
}

// ─── Members Modal (per-project) ────────────────────────────────────

interface ProjectMemberRow { id: string; user_id: string; role: string; granted_at: string | null }

const PROJECT_ROLE_HELP: Record<string, string> = {
  VIEW: 'Can read the knowledge bases in this project that are open to project members.',
  EDIT: 'Can also change those knowledge bases.',
  ADMIN: 'Can also add and remove members.',
};

function MembersModal({ project, onClose }: { project: KProject | null; onClose: () => void }) {
  const [rows, setRows] = useState<ProjectMemberRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [newId, setNewId] = useState('');
  const [role, setRole] = useState('VIEW');
  const [busy, setBusy] = useState(false);
  const { names } = useSubjectNames();

  const refresh = async () => {
    if (!project) return;
    setLoading(true);
    try {
      const r = await apiFetch<ProjectMemberRow[]>(`/api/knowledge-projects/${project.id}/members`, { silent: true, throwOnError: false });
      setRows(r.data || []);
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (project) { setNewId(''); setRole('VIEW'); void refresh(); }
  }, [project?.id]);

  const add = async () => {
    if (!project || !newId) return;
    setBusy(true);
    try {
      const r = await apiFetch(`/api/knowledge-projects/${project.id}/members`, {
        method: 'POST', body: JSON.stringify({ user_id: newId, role }), throwOnError: false,
      });
      if (r.error) { toastError('Could not add member', r.error); return; }
      toastSuccess('Member added', `${names[newId] || 'They'} joined ${project.name}`);
      setNewId('');
      await refresh();
    } finally { setBusy(false); }
  };

  const remove = async (userId: string) => {
    if (!project) return;
    if (!window.confirm(`Remove ${names[userId] || 'this member'} from ${project.name}?`)) return;
    const r = await apiFetch(`/api/knowledge-projects/${project.id}/members/${userId}`, { method: 'DELETE', throwOnError: false });
    if (r.error) { toastError('Could not remove member', r.error); return; }
    toastSuccess('Member removed');
    await refresh();
  };

  return (
    <ResponsiveModal open={project !== null} onClose={onClose} title={project ? `Members of ${project.name}` : 'Members'}>
      <div className="space-y-4" data-testid="project-members-modal">
        <p className="text-xs text-slate-400">Members can read the knowledge bases in this project that are open to project members. Private ones still need their own access.</p>
        <div className="space-y-2 max-h-72 overflow-auto pr-1">
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
          ) : rows.length === 0 ? (
            <div className="text-center text-xs text-slate-500 py-6">No members yet. Only the creator and tenant admins can see this project.</div>
          ) : rows.map((m) => (
            <div key={m.id} data-testid="member-row" data-subject={m.user_id} className="flex items-center justify-between gap-2 bg-slate-800/40 border border-slate-700/40 rounded-lg px-3 py-2">
              <div className="min-w-0">
                <div className="text-xs text-slate-200 truncate">{names[m.user_id] || `${m.user_id.slice(0, 8)}…`}</div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500">{m.role}</div>
              </div>
              <button onClick={() => void remove(m.user_id)} aria-label={`Remove ${names[m.user_id] || m.user_id}`} className="text-slate-500 hover:text-red-400 p-1 shrink-0">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
        <div className="border-t border-slate-800 pt-4 space-y-2">
          <div className="text-xs uppercase tracking-wider text-slate-400">Add a member</div>
          <div className="flex flex-wrap gap-2">
            <SubjectPicker kind="user" value={newId} onChange={setNewId} exclude={rows.map((m) => m.user_id)} testId="member-subject" />
            <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role" data-testid="member-role" className="bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100">
              <option value="VIEW">View</option>
              <option value="EDIT">Edit</option>
              <option value="ADMIN">Admin</option>
            </select>
            <button onClick={add} disabled={busy || !newId} data-testid="member-submit" className="px-3 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg text-sm disabled:opacity-50">
              {busy ? 'Adding…' : 'Add'}
            </button>
          </div>
          <p className="text-[11px] text-slate-500">{PROJECT_ROLE_HELP[role]}</p>
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
  const [membersFor, setMembersFor] = useState<KProject | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<KProject | null>(null);
  const [collections, setCollections] = useState<Record<string, KCollection[]>>({});
  const [created, setCreated] = useState<KProject | null>(null);

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
    <div className="p-4 md:p-8 max-w-7xl mx-auto">
      <PageHeader
        className="mb-6"
        back={{ href: '/knowledge', label: 'Back to all collections' }}
        title="Knowledge Projects"
        purpose="Group related knowledge bases, control which agents and people can read them, and share one map of terms across them. For admins and agent builders."
        icon={FolderOpen}
        iconClassName="text-emerald-400"
        storageKey="knowledge-projects"
        docSlug="02-runtime/15-v2-knowledge-enterprise"
        steps={[
          'Create a project for a topic or team, like Legal or Support.',
          'Open a project to see its knowledge bases and who can read each one.',
          'Use Access to give a specific agent or person read or write rights.',
          'Open Ontology to define the kinds of things and links the project talks about.',
        ]}
        primaryAction={{ label: 'New Project', icon: Plus, onClick: () => setCreateOpen(true) }}
      />

      {created && (
        <NextSteps
          className="mb-6"
          title={`${created.name} is ready. What next?`}
          testId="kp-next-steps"
          onDismiss={() => setCreated(null)}
          steps={[
            { id: 'ontology', label: 'Define its ontology', hint: 'Say which kinds of things and links matter here.', icon: Brain, href: `/knowledge/projects/${created.id}/ontology` },
            { id: 'kb', label: 'Add a knowledge base', hint: 'Create one in this project and upload the documents.', icon: Database, href: `/knowledge?new=1&project=${created.id}` },
          ]}
        />
      )}

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
                <div className="flex items-center gap-2 sm:gap-3 shrink-0">
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); setMembersFor(p); }}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setMembersFor(p); } }}
                    className="inline-flex items-center gap-1 text-xs text-slate-300 hover:text-white"
                    title="Who can see this project"
                    data-testid="kp-members"
                  >
                    <Users className="w-3 h-3" /> <span className="hidden sm:inline">Members</span>
                  </span>
                  <Link
                    href={`/knowledge/projects/${p.id}/ontology`}
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
                    title="Open ontology editor"
                    data-testid="kp-ontology"
                  >
                    <Brain className="w-3 h-3" /> <span className="hidden sm:inline">Ontology</span>
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
                          No collections yet.{' '}
                          <Link href={`/knowledge?new=1&project=${p.id}`} className="text-emerald-400 hover:underline" data-testid="kp-add-kb">Create a knowledge base in this project</Link>.
                        </div>
                      ) : (
                        collections[p.id].map((c) => (
                          <div key={c.id} data-testid="kp-collection" data-name={c.name} className="flex flex-wrap items-center justify-between gap-2 bg-slate-800/40 border border-slate-700/40 rounded-lg px-4 py-3">
                            <div className="flex items-center gap-3 min-w-0">
                              <Database className="w-4 h-4 text-slate-400 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-sm text-white truncate">{c.name}</div>
                                <div className="text-xs text-slate-500 truncate">
                                  {c.doc_count} doc{c.doc_count === 1 ? '' : 's'} · backend: {c.vector_backend}
                                </div>
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider ${visibilityColor(c.default_visibility)}`}>
                                {c.default_visibility}
                              </span>
                              <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider border ${statusColor(c.status)}`}>
                                {c.status}
                              </span>
                              <button
                                onClick={() => setGrantsFor({ id: c.id, name: c.name })}
                                data-testid="kp-access"
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
                        )).concat(
                          <Link key="add" href={`/knowledge?new=1&project=${p.id}`} className="block text-xs text-emerald-400 hover:underline pt-1" data-testid="kp-add-kb">
                            + Create another knowledge base in this project
                          </Link>,
                        )
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
        onCreated={(p) => { setCreated(p); mutate(); }}
      />

      <MembersModal project={membersFor} onClose={() => setMembersFor(null)} />

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
