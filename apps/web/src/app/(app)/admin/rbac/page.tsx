'use client';

import { useEffect, useMemo, useState } from 'react';
import { Shield, RefreshCw, AlertTriangle, ExternalLink, UserCog, Check, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';

interface MePermissions {
  role: string;
  is_admin: boolean;
  features: Record<string, boolean>;
}

interface TeamMember {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface TeamResp {
  members: TeamMember[];
}

// Static role → feature map. Mirrors the back-end RBAC defaults so the
// UI can show "what permissions does this role have" without a per-user
// permissions endpoint (none exists today). When /api/users/{id}/permissions
// ships we'll swap this out.
const ROLE_FEATURES: Record<string, string[]> = {
  admin: [
    'agents', 'pipelines', 'workflows', 'knowledge', 'ml_models', 'code_assets',
    'analytics', 'team', 'billing', 'settings', 'connectors',
    'admin.cluster', 'admin.scaling', 'admin.llm_pricing', 'admin.audit', 'admin.rbac',
  ],
  creator: ['agents', 'pipelines', 'workflows', 'knowledge', 'ml_models', 'code_assets', 'analytics'],
  user:    ['agents', 'pipelines', 'analytics'],
};

const ROLE_COLOR: Record<string, string> = {
  admin:   'border-purple-500/40 bg-purple-500/10 text-purple-300',
  creator: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  user:    'border-slate-700/60 bg-slate-900/40 text-slate-300',
};

function RbacPage() {
  const [me, setMe] = useState<MePermissions | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(null);

    (async () => {
      const [meRes, teamRes] = await Promise.all([
        apiFetch<MePermissions>('/api/me/permissions', { silent: true }),
        apiFetch<TeamResp>('/api/team/members', { silent: true }),
      ]);
      if (cancelled) return;


      if (meRes.error && teamRes.error) {
        const lower = (meRes.error || teamRes.error || '').toLowerCase();
        if (lower.includes('403') || lower.includes('forbid')) {
          setErr('Only admins can see roles. Ask an admin if you need this.');
          setLoading(false);
          return;
        }
        setErr(meRes.error || teamRes.error || 'Could not load RBAC data');
        setLoading(false);
        return;
      }

      if (meRes.data) setMe(meRes.data);
      if (teamRes.data) setMembers(teamRes.data.members || []);
      setLoading(false);
    })();

    return () => { cancelled = true; };
  }, [refreshKey]);

  const byRole = useMemo(() => {
    const buckets: Record<string, TeamMember[]> = { admin: [], creator: [], user: [] };
    for (const m of members) {
      (buckets[m.role] ||= []).push(m);
    }
    return buckets;
  }, [members]);

  const featureUniverse = useMemo(() => {
    const all = new Set<string>();
    for (const list of Object.values(ROLE_FEATURES)) list.forEach((f) => all.add(f));
    if (me?.features) Object.keys(me.features).forEach((f) => all.add(f));
    return Array.from(all).sort();
  }, [me]);

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="admin-rbac">
      <PageHeader
        className="mb-6"
        title="Roles & Permissions"
        purpose="See who in the workspace has which role and what each role can open. For admins."
        icon={Shield}
        iconClassName="text-purple-300"
        storageKey="admin-rbac"
        docSlug="01-architecture/01-tenants-rbac"
        primaryAction={{ label: 'Edit roles', icon: UserCog, href: '/settings/team', testId: 'rbac-edit-link' }}
        secondaryAction={{
          label: 'Refresh',
          icon: RefreshCw,
          busy: loading,
          onClick: () => setRefreshKey((k) => k + 1),
          testId: 'rbac-refresh',
        }}
        steps={[
          'Every person has one role: user, creator or admin.',
          'The table shows which parts of the platform each role can use.',
          'Change someone’s role on the Team settings page. Use Permissions to grant extra abilities without changing the role.',
        ]}
      />

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load RBAC</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4 mb-6">
        {(['admin', 'creator', 'user'] as const).map((r) => (
          <div key={r} className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{r}s</div>
            <div className="text-2xl font-bold text-white">{byRole[r]?.length ?? 0}</div>
            <div className="text-xs text-slate-400 mt-1">{ROLE_FEATURES[r]?.length ?? 0} permissions</div>
          </div>
        ))}
      </div>

      <section className="mb-6">
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <UserCog className="w-4 h-4 text-purple-300" /> Members
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">User</th>
                <th className="text-left px-3 py-2 font-medium">Role</th>
                <th className="text-left px-3 py-2 font-medium">Permissions</th>
                <th className="text-right px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={4}>Loading…</td></tr>
              )}
              {!loading && members.length === 0 && !err && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={4}>No members in this workspace.</td></tr>
              )}
              {members.map((m) => {
                const perms = ROLE_FEATURES[m.role] || [];
                return (
                  <tr key={m.id} className="border-t border-slate-800/60 hover:bg-slate-800/30" data-testid={`rbac-row-${m.email}`}>
                    <td className="px-3 py-2 align-top">
                      <div className="text-slate-200 font-medium">{m.full_name || m.email}</div>
                      <div className="text-[10px] text-slate-500 font-mono">{m.email}</div>
                    </td>
                    <td className="px-3 py-2 align-top">
                      <span className={`inline-flex items-center text-[10px] px-2 py-0.5 rounded border ${ROLE_COLOR[m.role] || ROLE_COLOR.user} uppercase tracking-wider`}>
                        {m.role}
                      </span>
                      {!m.is_active && (
                        <span className="ml-2 inline-flex items-center text-[10px] px-2 py-0.5 rounded border border-red-500/40 bg-red-500/10 text-red-300 uppercase tracking-wider">
                          inactive
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top">
                      <div className="flex flex-wrap gap-1 max-w-md">
                        {perms.length === 0 ? (
                          <span className="text-slate-500 italic">no permissions</span>
                        ) : perms.slice(0, 8).map((p) => (
                          <span key={p} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border border-slate-700/60 bg-slate-900/60 text-slate-300 font-mono">
                            {p}
                          </span>
                        ))}
                        {perms.length > 8 && (
                          <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border border-slate-700/60 bg-slate-900/60 text-slate-400 font-mono">
                            +{perms.length - 8} more
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right align-top">
                      <a
                        href="/settings/team"
                        className="inline-flex items-center gap-1 px-2 py-1 rounded border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60 text-[10px]"
                        data-testid={`rbac-edit-${m.email}`}
                      >
                        Edit role <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-200 mb-2">Role → permission matrix</h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Permission</th>
                <th className="px-3 py-2 font-medium text-center">Admin</th>
                <th className="px-3 py-2 font-medium text-center">Creator</th>
                <th className="px-3 py-2 font-medium text-center">User</th>
              </tr>
            </thead>
            <tbody>
              {featureUniverse.map((f) => (
                <tr key={f} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 text-slate-300 font-mono">{f}</td>
                  {(['admin', 'creator', 'user'] as const).map((r) => {
                    const has = (ROLE_FEATURES[r] || []).includes(f);
                    return (
                      <td key={r} className="px-3 py-2 text-center">
                        {has
                          ? <Check className="w-3.5 h-3.5 text-emerald-400 inline" />
                          : <X className="w-3.5 h-3.5 text-slate-700 inline" />}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-[11px] text-slate-500 mt-3">
        Members come from <code className="text-cyan-300">/api/team/members</code>; viewer permissions from <code className="text-cyan-300">/api/me/permissions</code>.
        Per-user permission overrides land in a future <code className="text-cyan-300">/api/users/{`{id}`}/permissions</code> endpoint.
      </p>
    </div>
  );
}

export default function RbacPageGated() {
  return (
    <AccessGate
      title="Roles & Permissions"
      purpose="See who in the workspace has which role and what each role can open. For admins."
      icon={Shield}
      need={{ admin: true }}
    >
      <RbacPage />
    </AccessGate>
  );
}
