'use client';

import { useEffect, useMemo, useState } from 'react';
import { Shield, RefreshCw, AlertTriangle, UserCog, Check, X, Loader2, KeyRound } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { useAuth } from '@/contexts/AuthContext';
import { toastError, toastSuccess } from '@/stores/toastStore';

interface TeamMember {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

type Role = 'admin' | 'creator' | 'user';
const ROLES: Role[] = ['admin', 'creator', 'user'];

const ROLE_LABEL: Record<Role, string> = { admin: 'Admin', creator: 'Creator', user: 'Member' };

const ROLE_COLOR: Record<string, string> = {
  admin:   'border-purple-500/40 bg-purple-500/10 text-purple-300',
  creator: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  user:    'border-slate-700/60 bg-slate-900/40 text-slate-300',
};

const FEATURE_LABEL: Record<string, string> = {
  view_dashboard: 'See the dashboard',
  create_agents: 'Create agents',
  use_builder: 'Use the builder',
  create_pipelines: 'Create pipelines',
  use_chat: 'Chat with agents',
  use_kb: 'Use knowledge bases',
  use_persona: 'Use personas',
  use_ml_models: 'Use ML models',
  use_code_runner: 'Use Code Runner',
  use_meetings: 'Use meetings',
  use_triggers: 'Set up triggers',
  view_executions: 'See runs',
  view_analytics: 'See analytics',
  view_alerts: 'See alerts',
  use_marketplace: 'Browse the marketplace',
  use_sdk_playground: 'Use the SDK playground',
  use_load_playground: 'Use the load playground',
  review_queue: 'Review held content',
  manage_team: 'Manage the team',
  manage_settings: 'Change workspace settings',
  manage_api_keys: 'Manage their API keys',
  manage_mcp: 'Connect MCP servers',
  manage_ontology: 'Edit ontologies',
  publish_to_marketplace: 'Publish to the marketplace',
  see_other_users_resources: "See everyone's agents and data",
};

function label(f: string) {
  return FEATURE_LABEL[f] || f.replace(/_/g, ' ');
}

function RbacPage() {
  const { user: me } = useAuth();
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [matrix, setMatrix] = useState<Record<string, Record<string, boolean>>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [pending, setPending] = useState<{ m: TeamMember; role: Role } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(null);
    (async () => {
      const [mx, team] = await Promise.all([
        apiFetch<{ roles: Record<string, Record<string, boolean>> }>('/api/me/role-matrix', { silent: true }),
        apiFetch<{ members: TeamMember[] }>('/api/team/members', { silent: true }),
      ]);
      if (cancelled) return;
      if (mx.error || team.error) setErr(mx.error || team.error || 'Could not load roles');
      setMatrix(mx.data?.roles || {});
      setMembers(team.data?.members || []);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [refreshKey]);

  const byRole = useMemo(() => {
    const buckets: Record<string, TeamMember[]> = { admin: [], creator: [], user: [] };
    for (const m of members) (buckets[m.role] ||= []).push(m);
    return buckets;
  }, [members]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = q ? members.filter((m) => `${m.full_name || ''} ${m.email}`.toLowerCase().includes(q)) : members;
    return list.slice(0, 100);
  }, [members, filter]);

  const features = useMemo(() => Object.keys(matrix.user || matrix.admin || {}), [matrix]);
  const count = (r: string) => Object.values(matrix[r] || {}).filter(Boolean).length;

  const diff = (from: string, to: string) => {
    const gains = features.filter((f) => !matrix[from]?.[f] && matrix[to]?.[f]).map(label);
    const losses = features.filter((f) => matrix[from]?.[f] && !matrix[to]?.[f]).map(label);
    return { gains, losses };
  };

  const applyRole = async () => {
    if (!pending) return;
    const { m, role } = pending;
    setPending(null);
    setSaving(m.id);
    const r = await apiFetch<TeamMember>(`/api/team/members/${m.id}/role`, { method: 'PUT', body: JSON.stringify({ role }), throwOnError: false });
    setSaving(null);
    if (r.error) { toastError('Role not changed', r.error); return; }
    const { gains, losses } = diff(m.role, role);
    setNotice(`${m.full_name || m.email} is now ${ROLE_LABEL[role]}.${gains.length ? ` They can now: ${gains.join(', ')}.` : ''}${losses.length ? ` They can no longer: ${losses.join(', ')}.` : ''} It applies on their next page load.`);
    toastSuccess('Role changed', `${m.email} is now ${ROLE_LABEL[role]}`);
    setMembers((prev) => prev.map((x) => (x.id === m.id ? { ...x, role } : x)));
  };

  const pendingDiff = pending ? diff(pending.m.role, pending.role) : null;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-rbac">
      <PageHeader
        className="mb-6"
        title="Roles"
        purpose="Who has which role, what each role can do, and changing someone's role. For admins."
        icon={Shield}
        iconClassName="text-purple-300"
        storageKey="admin-rbac"
        docSlug="01-architecture/01-tenants-rbac"
        primaryAction={{ label: 'Refresh', icon: RefreshCw, busy: loading, onClick: () => setRefreshKey((k) => k + 1), testId: 'rbac-refresh' }}
        secondaryAction={{ label: 'Extra permissions', icon: KeyRound, href: '/admin/permissions', testId: 'rbac-permsets' }}
        steps={[
          'Every person has one role: Member, Creator or Admin.',
          'Pick a new role in the Members list. You see what they gain and lose before it is saved.',
          'Use Extra permissions to grant one ability without changing the whole role.',
        ]}
      />

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div><div className="font-semibold mb-1">Couldn&apos;t load roles</div><div className="text-xs opacity-80">{err}</div></div>
        </div>
      )}

      {notice && <p role="status" data-testid="rbac-notice" className="mb-4 text-xs rounded-lg border border-emerald-500/30 bg-emerald-500/5 text-emerald-300 px-3 py-2">{notice}</p>}

      <div className="grid grid-cols-3 gap-2 sm:gap-4 mb-6">
        {ROLES.map((r) => (
          <div key={r} className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3 sm:p-4">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{ROLE_LABEL[r]}s</div>
            <div className="text-2xl font-bold text-white">{byRole[r]?.length ?? 0}</div>
            <div className="text-xs text-slate-400 mt-1">{count(r)} of {features.length} abilities</div>
          </div>
        ))}
      </div>

      <section className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <UserCog className="w-4 h-4 text-purple-300" /> Members
          </h2>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find a person by name or email"
            aria-label="Find a person"
            data-testid="rbac-filter"
            className="w-full sm:w-72 px-3 py-1.5 bg-slate-800/60 border border-slate-700 rounded-lg text-xs text-white outline-none focus:border-purple-500"
          />
        </div>
        <div className="space-y-2">
          {loading && members.length === 0 && <div className="text-xs text-slate-500 py-6 text-center">Loading…</div>}
          {shown.length === 0 && !loading && <p className="text-xs text-slate-500 py-4 text-center">Nobody matches &ldquo;{filter}&rdquo;.</p>}
          {shown.map((m) => (
            <div key={m.id} data-testid={`rbac-row-${m.email}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-700/60 bg-slate-900/40 px-4 py-3">
              <div className="min-w-0">
                <div className="text-sm text-slate-200 truncate">{m.full_name || m.email}</div>
                <div className="text-[11px] text-slate-500 truncate">{m.email}{!m.is_active && <span className="ml-2 text-red-300">inactive</span>}</div>
              </div>
              <div className="flex items-center gap-2">
                {saving === m.id && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
                {m.id === me?.id ? (
                  <span className={`text-[10px] px-2 py-1 rounded border uppercase tracking-wider ${ROLE_COLOR[m.role] || ROLE_COLOR.user}`} title="You cannot change your own role">{ROLE_LABEL[m.role as Role] || m.role} · you</span>
                ) : (
                  <select
                    value={m.role}
                    onChange={(e) => setPending({ m, role: e.target.value as Role })}
                    aria-label={`Role for ${m.email}`}
                    data-testid={`rbac-role-${m.email}`}
                    className={`text-xs pl-2 pr-7 py-1.5 rounded-lg border bg-slate-900 ${ROLE_COLOR[m.role] || ROLE_COLOR.user}`}
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-200 mb-2">What each role can do</h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-x-auto">
          <table className="w-full min-w-[420px] text-xs" data-testid="rbac-matrix">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Ability</th>
                {ROLES.map((r) => <th key={r} className="px-3 py-2 font-medium text-center">{ROLE_LABEL[r]}</th>)}
              </tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 text-slate-300">{label(f)}</td>
                  {ROLES.map((r) => (
                    <td key={r} className="px-3 py-2 text-center">
                      {matrix[r]?.[f] ? <Check className="w-3.5 h-3.5 text-emerald-400 inline" aria-label="yes" /> : <X className="w-3.5 h-3.5 text-slate-700 inline" aria-label="no" />}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmModal
        open={pending !== null}
        onClose={() => setPending(null)}
        onConfirm={applyRole}
        title={pending ? `Make ${pending.m.full_name || pending.m.email} ${ROLE_LABEL[pending.role]}?` : ''}
        description={pendingDiff ? [
          pendingDiff.gains.length ? `They gain: ${pendingDiff.gains.join(', ')}.` : '',
          pendingDiff.losses.length ? `They lose: ${pendingDiff.losses.join(', ')}.` : '',
          !pendingDiff.gains.length && !pendingDiff.losses.length ? 'Nothing they can do changes.' : '',
        ].filter(Boolean).join(' ') : ''}
        confirmLabel="Change role"
        variant="warning"
        confirmTestId="rbac-role-confirm"
      />
    </div>
  );
}

export default function RbacPageGated() {
  return (
    <AccessGate
      title="Roles"
      purpose="Who has which role, what each role can do, and changing someone's role. For admins."
      icon={Shield}
      need={{ admin: true }}
    >
      <RbacPage />
    </AccessGate>
  );
}
