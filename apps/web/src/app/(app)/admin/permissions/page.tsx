'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, KeyRound, Loader2, Mail, Pencil, Plus, Search, ShieldCheck, Trash2, UserCog, UserPlus, Users, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import NextSteps, { type NextStep } from '@/components/shared/NextSteps';

interface Cap {
  key: string;
  label: string;
  group: string;
  description: string;
}
interface Catalog {
  catalog: Cap[];
  role_defaults: Record<string, string[]>;
  mine: string[];
}
interface Member {
  user_id: string;
  email: string;
  name: string | null;
}
interface PermSet {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
  members: Member[];
}
interface TeamMember {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
}

const ROLE_LABEL: Record<string, string> = { user: 'Member', creator: 'Creator', admin: 'Admin' };

function labelFor(catalog: Cap[], cap: string): string {
  const [base, qual] = cap.split(':');
  if (base.endsWith('.*')) return `Everything in ${base.slice(0, -2)}`;
  const c = catalog.find((x) => x.key === base);
  return `${c?.label || base}${qual ? ` (${qual} only)` : ''}`;
}

export default function PermissionsPage() {
  const { perms, loading } = useMyPermissions();
  const allowed = holds(perms?.capabilities, 'permissions.manage');
  const { data: cat } = useApi<Catalog>(allowed ? '/api/governance/capabilities' : null);
  const { data: sets, isLoading, error, mutate } = useApi<PermSet[]>(allowed ? '/api/governance/permission-sets' : null);
  // always fresh, someone who just accepted an invite must be pickable
  const { data: team, mutate: refreshTeam } = useApi<{ members: TeamMember[] }>(allowed ? '/api/team/members' : null, { revalidateOnMount: true, dedupingInterval: 0 });
  // a list the Team page fetched seconds ago is reused on mount, ask again so new joiners show
  useEffect(() => {
    if (allowed) refreshTeam();
  }, [allowed]);
  const [editing, setEditing] = useState<PermSet | 'new' | null>(null);
  const [firstSet, setFirstSet] = useState<{ name: string; capabilities: string[] } | null>(null);

  if (loading && !perms) {
    return <div className="max-w-6xl mx-auto px-6 py-8"><div className="h-40 rounded-xl bg-slate-800/40 animate-pulse" /></div>;
  }
  if (!allowed) {
    return (
      <NoAccess
        testId="permissions-no-access"
        title="Permissions"
        purpose="Give specific people extra abilities, like reviewing decisions or signing legal approvals, without making them admins. For admins."
        icon={UserCog}
        need={{ capability: 'permissions.manage', label: 'Manage permissions' }}
        role={perms?.role}
      />
    );
  }

  const catalog = cat?.catalog || [];

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        className="mb-6"
        title="Permissions"
        purpose="Give specific people extra abilities, like reviewing decisions or signing legal approvals, without making them admins. For admins."
        icon={UserCog}
        storageKey="admin-permissions"
        docSlug="01-architecture/01-tenants-rbac"
        primaryAction={{ label: 'New permission set', icon: Plus, onClick: () => setEditing('new'), testId: 'permset-new' }}
        steps={[
          'Every person starts with what their role allows. The role cards show exactly what that is.',
          'A permission set is a named bundle of extra abilities. Create one and tick what it grants.',
          'Add people to the set. Changes apply within ten seconds and are recorded in the audit log.',
        ]}
      />

      {firstSet && (
        <NextSteps
          className="mb-6"
          title={`${firstSet.name} is ready. What next?`}
          testId="permissions-next-steps"
          onDismiss={() => setFirstSet(null)}
          steps={firstSetSteps(firstSet, () => setFirstSet(null))}
        />
      )}

      {cat && (
        <section className="mb-8" aria-labelledby="role-baseline">
          <h2 id="role-baseline" className="text-sm font-semibold text-white mb-3">What each role already has</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {(['user', 'creator', 'admin'] as const).map((r) => (
              <div key={r} className="rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid={`role-baseline-${r}`}>
                <div className="text-sm font-medium text-white mb-2">{ROLE_LABEL[r]}</div>
                {(cat.role_defaults[r] || []).includes('*') ? (
                  <p className="text-xs text-slate-400">Every capability.</p>
                ) : (
                  <ul className="space-y-1">
                    {(cat.role_defaults[r] || []).map((c) => (
                      <li key={c} className="text-xs text-slate-300 flex items-center gap-1.5">
                        <Check className="w-3 h-3 text-emerald-400" /> {labelFor(catalog, c)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="permsets">
        <h2 id="permsets" className="text-sm font-semibold text-white mb-3">Permission sets</h2>
        {error ? (
          <p className="text-sm text-rose-300">{error}</p>
        ) : isLoading && !sets ? (
          <div className="h-32 rounded-xl bg-slate-800/40 animate-pulse" />
        ) : (sets || []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center" data-testid="permset-empty">
            <KeyRound className="w-8 h-8 text-slate-600 mx-auto mb-2" />
            <p className="text-slate-300">No permission sets yet.</p>
            <p className="text-sm text-slate-500 mt-1">
              Create one, for example &ldquo;Decision reviewers&rdquo; with Review decisions, then add the people who need it.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {(sets || []).map((s) => (
              <SetCard key={s.id} set={s} catalog={catalog} team={team?.members || []} onMissing={refreshTeam} onEdit={() => setEditing(s)} onChanged={mutate} />
            ))}
          </div>
        )}
      </section>

      {editing && (
        <SetEditor
          initial={editing === 'new' ? null : editing}
          catalog={catalog}
          existingNames={(sets || []).filter((s) => editing === 'new' || s.id !== editing.id).map((s) => s.name.toLowerCase())}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            if (editing === 'new' && (sets || []).length === 0) setFirstSet(saved);
            setEditing(null);
            mutate();
          }}
        />
      )}
    </div>
  );
}

function firstSetSteps(set: { name: string; capabilities: string[] }, hide: () => void): NextStep[] {
  const steps: NextStep[] = [
    {
      id: 'add-people',
      label: 'Add people to it',
      hint: 'Pick who should get these abilities.',
      icon: UserPlus,
      onClick: () => {
        const input = Array.from(document.querySelectorAll<HTMLInputElement>('input[data-testid^="permset-add-"]'))
          .find((el) => el.dataset.testid === `permset-add-${set.name}`);
        input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        input?.focus();
        hide();
      },
    },
    { id: 'invite', label: 'Invite a teammate', hint: 'People must join the workspace before you can add them.', icon: Mail, href: '/team' },
  ];
  if (set.capabilities.some((c) => c === 'approvals.sign' || c.startsWith('approvals.sign:'))) {
    steps.push({ id: 'approvals', label: 'Open approvals', hint: 'Where members of this set sign gates.', icon: ShieldCheck, href: '/approvals' });
  }
  return steps;
}

function SetCard({
  set,
  catalog,
  team,
  onMissing,
  onEdit,
  onChanged,
}: {
  set: PermSet;
  catalog: Cap[];
  team: TeamMember[];
  onMissing: () => void;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const memberIds = new Set(set.members.map((m) => m.user_id));
  const candidates = useMemo(() => {
    const q = adding.trim().toLowerCase();
    return team
      .filter((t) => t.is_active && !memberIds.has(t.id))
      .filter((t) => !q || t.email.toLowerCase().includes(q) || (t.full_name || '').toLowerCase().includes(q))
      .slice(0, 6);
  }, [team, adding, set.members]);
  // nobody matches, they may have joined since the list loaded, look again at most every few seconds
  const lastRefresh = useRef(0);
  useEffect(() => {
    if (!adding.trim() || candidates.length > 0) return;
    if (Date.now() - lastRefresh.current < 3000) return;
    lastRefresh.current = Date.now();
    onMissing();
  }, [adding, candidates.length, onMissing]);

  async function add(email: string) {
    setBusy(true);
    setErr(null);
    const r = await apiFetch(`/api/governance/permission-sets/${set.id}/members`, {
      method: 'POST',
      body: JSON.stringify({ email }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(r.error);
    else {
      setAdding('');
      onChanged();
    }
  }
  async function remove(m: Member) {
    setBusy(true);
    const r = await apiFetch(`/api/governance/permission-sets/${set.id}/members/${m.user_id}`, { method: 'DELETE', throwOnError: false });
    setBusy(false);
    if (r.error) setErr(r.error);
    else onChanged();
  }
  async function del() {
    setBusy(true);
    const r = await apiFetch(`/api/governance/permission-sets/${set.id}`, { method: 'DELETE', throwOnError: false });
    setBusy(false);
    setConfirmDelete(false);
    if (r.error) setErr(r.error);
    else onChanged();
  }

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/50 p-5" data-testid={`permset-${set.name}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-white">{set.name}</h3>
          {set.description && <p className="text-sm text-slate-400 mt-0.5">{set.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onEdit} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-300 border border-slate-700 hover:bg-slate-800" data-testid={`permset-edit-${set.name}`}>
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
          <button type="button" onClick={() => setConfirmDelete(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-rose-300 border border-rose-500/30 hover:bg-rose-500/10" aria-label={`Delete ${set.name}`}>
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 mt-3">
        {set.capabilities.length === 0 && <span className="text-xs text-slate-500">No capabilities yet. Edit to add some.</span>}
        {set.capabilities.map((c) => (
          <span key={c} title={c} className="text-xs px-2 py-0.5 rounded border border-cyan-500/30 bg-cyan-500/10 text-cyan-200">
            {labelFor(catalog, c)}
          </span>
        ))}
      </div>

      <div className="mt-4">
        <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-2">
          <Users className="w-3.5 h-3.5" /> {set.members.length === 0 ? 'Nobody has this set yet.' : `${set.members.length} ${set.members.length === 1 ? 'person' : 'people'}`}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {set.members.map((m) => (
            <span key={m.user_id} className="inline-flex items-center gap-1.5 text-xs pl-2 pr-1 py-1 rounded-full bg-slate-800 text-slate-200">
              {m.name || m.email}
              <button type="button" onClick={() => remove(m)} disabled={busy} aria-label={`Remove ${m.email}`} className="p-0.5 rounded-full text-slate-400 hover:text-white hover:bg-slate-700">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="relative mt-3 max-w-md">
          <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3">
            <UserPlus className="w-4 h-4 text-slate-500" />
            <input
              value={adding}
              onChange={(e) => setAdding(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && candidates[0]) add(candidates[0].email);
              }}
              placeholder="Add a person by name or email…"
              className="flex-1 bg-transparent py-2 text-sm text-white outline-none"
              data-testid={`permset-add-${set.name}`}
            />
            {busy && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
          </div>
          {adding.trim() && (
            <ul className="absolute z-10 mt-1 w-full rounded-md border border-slate-700 bg-slate-900 shadow-xl py-1" role="listbox">
              {candidates.length === 0 ? (
                <li className="px-3 py-2 text-sm text-slate-500">No one in this tenant matches. Invite them under Team first.</li>
              ) : (
                candidates.map((t) => (
                  <li key={t.id}>
                    <button type="button" role="option" aria-selected={false} onClick={() => add(t.email)} className="w-full text-left px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800">
                      {t.full_name || t.email} <span className="text-slate-500 text-xs">{t.email} · {ROLE_LABEL[t.role] || t.role}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
        {err && <p className="text-xs text-rose-300 mt-2">{err}</p>}
      </div>

      <ConfirmModal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={del}
        loading={busy}
        title={`Delete ${set.name}?`}
        description={`${set.members.length} ${set.members.length === 1 ? 'person loses' : 'people lose'} these capabilities within ten seconds, unless their role or another set grants them.`}
      />
    </article>
  );
}

function SetEditor({
  initial,
  catalog,
  existingNames,
  onClose,
  onSaved,
}: {
  initial: PermSet | null;
  catalog: Cap[];
  existingNames: string[];
  onClose: () => void;
  onSaved: (saved: { name: string; capabilities: string[] }) => void;
}) {
  const [name, setName] = useState(initial?.name || '');
  const [description, setDescription] = useState(initial?.description || '');
  const [caps, setCaps] = useState<string[]>(initial?.capabilities || []);
  const [q, setQ] = useState('');
  const [group, setGroup] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = new Map<string, Cap[]>();
    catalog
      .filter((c) => !needle || c.label.toLowerCase().includes(needle) || c.description.toLowerCase().includes(needle) || c.key.includes(needle))
      .forEach((c) => out.set(c.group, [...(out.get(c.group) || []), c]));
    return Array.from(out.entries());
  }, [catalog, q]);

  const nameProblem = !name.trim()
    ? 'Give the set a name.'
    : existingNames.includes(name.trim().toLowerCase())
      ? 'Another set already has this name.'
      : null;
  const groupOk = /^[a-z0-9_-]*$/.test(group);

  function toggle(key: string) {
    setCaps((cs) => (cs.includes(key) ? cs.filter((c) => c !== key && !c.startsWith(`${key}:`)) : [...cs, key]));
  }
  function addSignGroup() {
    const g = group.trim();
    if (!g || !groupOk) return;
    const k = `approvals.sign:${g}`;
    setCaps((cs) => (cs.includes(k) ? cs : [...cs.filter((c) => c !== 'approvals.sign'), k]));
    setGroup('');
  }

  async function save() {
    setBusy(true);
    setErr(null);
    const body = JSON.stringify({ name: name.trim(), description: description.trim(), capabilities: caps });
    const r = initial
      ? await apiFetch(`/api/governance/permission-sets/${initial.id}`, { method: 'PATCH', body, throwOnError: false })
      : await apiFetch(`/api/governance/permission-sets`, { method: 'POST', body, throwOnError: false });
    setBusy(false);
    if (r.error) setErr(r.error);
    else onSaved({ name: name.trim(), capabilities: caps });
  }

  const signGroups = caps.filter((c) => c.startsWith('approvals.sign:')).map((c) => c.split(':')[1]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="permset-editor-title">
      <div className="w-full max-w-3xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="permset-editor-title" className="text-lg font-semibold text-white">
            {initial ? `Edit ${initial.name}` : 'New permission set'}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="ps-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
              <input
                id="ps-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Decision reviewers"
                className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white"
                aria-invalid={!!nameProblem && name.length > 0}
                data-testid="permset-name"
                autoFocus
              />
              {nameProblem && name.length > 0 && <p className="mt-1 text-xs text-rose-300">{nameProblem}</p>}
            </div>
            <div>
              <label htmlFor="ps-desc" className="block text-sm font-medium text-slate-200 mb-1.5">What it is for</label>
              <input
                id="ps-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="People who approve rule changes before they go live"
                className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-200">Capabilities <span className="text-slate-500 font-normal">({caps.length} chosen)</span></span>
              <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-2 w-56">
                <Search className="w-3.5 h-3.5 text-slate-500" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="flex-1 bg-transparent py-1.5 text-xs text-white outline-none" aria-label="Filter capabilities" />
              </div>
            </div>
            <div className="space-y-4">
              {groups.map(([g, items]) => (
                <fieldset key={g}>
                  <legend className="text-xs uppercase tracking-wide text-slate-500 mb-1.5">{g}</legend>
                  <div className="grid gap-1.5 md:grid-cols-2">
                    {items.map((c) => {
                      const on = caps.includes(c.key) || (c.key === 'approvals.sign' && signGroups.length > 0);
                      return (
                        <label
                          key={c.key}
                          className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 cursor-pointer transition ${
                            on ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-800 hover:border-slate-600'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => {
                              if (c.key === 'approvals.sign' && signGroups.length) {
                                setCaps((cs) => cs.filter((x) => !x.startsWith('approvals.sign')));
                              } else toggle(c.key);
                            }}
                            className="mt-0.5 accent-cyan-500"
                            data-testid={`permset-cap-${c.key}`}
                          />
                          <span>
                            <span className="block text-sm text-white">{c.label}</span>
                            <span className="block text-xs text-slate-400">{c.description}</span>
                            {c.key === 'approvals.sign' && on && (
                              <span className="mt-2 block" onClick={(e) => e.preventDefault()}>
                                <span className="block text-xs text-slate-400 mb-1">
                                  {signGroups.length ? `Only gates for: ${signGroups.join(', ')}` : 'Any approval gate. Limit to a group:'}
                                </span>
                                <span className="flex items-center gap-1.5">
                                  <input
                                    value={group}
                                    onChange={(e) => setGroup(e.target.value.toLowerCase())}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') {
                                        e.preventDefault();
                                        addSignGroup();
                                      }
                                    }}
                                    placeholder="legal"
                                    className="w-28 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                                    aria-label="Approval group"
                                  />
                                  <button type="button" onClick={addSignGroup} disabled={!group.trim() || !groupOk} className="text-xs px-2 py-1 rounded border border-slate-700 text-slate-300 disabled:opacity-40">
                                    Add group
                                  </button>
                                </span>
                                {!groupOk && <span className="block text-xs text-rose-300 mt-1">Use lowercase letters, numbers, - or _.</span>}
                              </span>
                            )}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
            </div>
          </div>
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button
            type="button"
            onClick={save}
            disabled={!!nameProblem || busy}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40"
            data-testid="permset-save"
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} {initial ? 'Save changes' : 'Create set'}
          </button>
        </div>
      </div>
    </div>
  );
}
