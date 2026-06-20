'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ScrollText, RefreshCw, AlertTriangle, Settings as SettingsIcon, UserCog, Mail } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { toastError } from '@/stores/toastStore';

interface AuditRow {
  actor: string;
  action: string;
  target: string;
  before: string | null;
  after: string | null;
  at: string | null;
  request_id: string | null;
  kind: 'setting' | 'role' | 'invite' | 'admin';
}

interface SettingRow {
  key: string;
  value: string;
  default: string;
  category: string;
  is_default: boolean;
  updated_at?: string | null;
}

interface SettingsResp {
  categories: Record<string, SettingRow[]>;
}

interface TeamMember {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface TeamInvite {
  id: string;
  email: string;
  role: string;
  status: string;
  created_at: string;
  expires_at: string;
}

interface TeamResp {
  members: TeamMember[];
  pending_invites: TeamInvite[];
}

interface NativeAuditResp {
  rows: AuditRow[];
}

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 0) return new Date(iso).toLocaleString();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function kindBadge(kind: AuditRow['kind']) {
  const map: Record<AuditRow['kind'], { cls: string; label: string; icon: React.ReactNode }> = {
    setting: { cls: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300', label: 'setting', icon: <SettingsIcon className="w-3 h-3" /> },
    role:    { cls: 'border-purple-500/40 bg-purple-500/10 text-purple-300', label: 'role', icon: <UserCog className="w-3 h-3" /> },
    invite:  { cls: 'border-amber-500/40 bg-amber-500/10 text-amber-300', label: 'invite', icon: <Mail className="w-3 h-3" /> },
    admin:   { cls: 'border-slate-700/60 bg-slate-900/40 text-slate-300', label: 'admin', icon: <ScrollText className="w-3 h-3" /> },
  };
  const m = map[kind];
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border ${m.cls} uppercase tracking-wider`}>
      {m.icon} {m.label}
    </span>
  );
}

export default function AuditLogPage() {
  const router = useRouter();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [fromNative, setFromNative] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);

    (async () => {
      // Try the native audit endpoint first; fall back to settings + team
      // when it doesn't exist on this build. The PM brief says the
      // endpoint may not be there yet — we degrade gracefully.
      const nativeEnabled = process.env.NEXT_PUBLIC_AUDIT_NATIVE === 'true';
      if (nativeEnabled) {
        const native = await apiFetch<NativeAuditResp>('/api/admin/audit-log', { silent: true });
        if (!cancelled && native.data?.rows?.length) {
          setRows(native.data.rows);
          setFromNative(true);
          setLoading(false);
          return;
        }
      }

      const [settingsRes, teamRes] = await Promise.all([
        apiFetch<SettingsResp>('/api/admin/settings', { silent: true }),
        apiFetch<TeamResp>('/api/team/members', { silent: true }),
      ]);
      if (cancelled) return;

      if (settingsRes.error && teamRes.error) {
        // Surface admin gate, but don't kick the user out — the layout
        // takes care of that. We just say what happened.
        if ((settingsRes.error || '').toLowerCase().includes('403')
            || (settingsRes.error || '').toLowerCase().includes('forbid')) {
          toastError('Admin role required', 'You do not have permission to view the audit log.');
          router.push('/dashboard');
          return;
        }
        setErr(settingsRes.error || teamRes.error || 'Could not load audit data');
        setLoading(false);
        return;
      }

      const stand: AuditRow[] = [];

      const settings = settingsRes.data;
      if (settings?.categories) {
        for (const [cat, items] of Object.entries(settings.categories)) {
          for (const s of items) {
            if (!s.updated_at || s.is_default) continue;
            stand.push({
              actor: 'admin',
              action: `setting changed`,
              target: `${cat}.${s.key}`,
              before: s.default,
              after: s.value,
              at: s.updated_at,
              request_id: null,
              kind: 'setting',
            });
          }
        }
      }

      const team = teamRes.data;
      if (team) {
        for (const m of team.members || []) {
          stand.push({
            actor: 'system',
            action: 'member joined',
            target: `${m.email} (${m.role})`,
            before: null,
            after: m.role,
            at: m.created_at,
            request_id: null,
            kind: 'role',
          });
        }
        for (const i of team.pending_invites || []) {
          stand.push({
            actor: 'admin',
            action: `invited as ${i.role}`,
            target: i.email,
            before: null,
            after: i.status,
            at: i.created_at,
            request_id: null,
            kind: 'invite',
          });
        }
      }

      stand.sort((a, b) => {
        const ta = a.at ? new Date(a.at).getTime() : 0;
        const tb = b.at ? new Date(b.at).getTime() : 0;
        return tb - ta;
      });
      setRows(stand);
      setFromNative(false);
      setLoading(false);
    })();

    return () => { cancelled = true; };
  }, [refreshKey, router]);

  const counts = useMemo(() => {
    const c = { setting: 0, role: 0, invite: 0, admin: 0 };
    for (const r of rows) c[r.kind] += 1;
    return c;
  }, [rows]);

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="admin-audit">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 ring-1 ring-cyan-500/40 flex items-center justify-center">
            <ScrollText className="w-5 h-5 text-cyan-300" />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Admin · platform</p>
            <h1 className="text-2xl font-bold text-white">Audit Log</h1>
            <p className="text-sm text-slate-400">
              {fromNative
                ? 'Recent admin actions across settings, roles, billing and tenant mutations.'
                : 'Stand-in view assembled from settings updates and team membership changes.'}
            </p>
          </div>
        </div>
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
          data-testid="audit-refresh"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load audit data</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Settings</div>
          <div className="text-2xl font-bold text-white">{counts.setting}</div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Role events</div>
          <div className="text-2xl font-bold text-white">{counts.role}</div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Invites</div>
          <div className="text-2xl font-bold text-white">{counts.invite}</div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Total rows</div>
          <div className="text-2xl font-bold text-white">{rows.length}</div>
        </div>
      </div>

      <section>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">When</th>
                <th className="text-left px-3 py-2 font-medium">Kind</th>
                <th className="text-left px-3 py-2 font-medium">Actor</th>
                <th className="text-left px-3 py-2 font-medium">Action</th>
                <th className="text-left px-3 py-2 font-medium">Target</th>
                <th className="text-left px-3 py-2 font-medium">Before</th>
                <th className="text-left px-3 py-2 font-medium">After</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={7}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && !err && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={7}>No audit events to show yet. Changes to LLM settings and team membership will appear here.</td></tr>
              )}
              {rows.map((r, idx) => (
                <tr key={`${r.target}-${idx}`} className="border-t border-slate-800/60 hover:bg-slate-800/30" data-testid={`audit-row-${idx}`}>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{relTime(r.at)}</td>
                  <td className="px-3 py-2">{kindBadge(r.kind)}</td>
                  <td className="px-3 py-2 text-slate-300 font-mono">{r.actor}</td>
                  <td className="px-3 py-2 text-slate-300">{r.action}</td>
                  <td className="px-3 py-2 text-slate-400 font-mono break-all">{r.target}</td>
                  <td className="px-3 py-2 text-slate-500 font-mono break-all">{r.before ?? '—'}</td>
                  <td className="px-3 py-2 text-slate-200 font-mono break-all">{r.after ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {!fromNative && (
        <p className="text-[11px] text-slate-500 mt-3">
          Backed by <code className="text-cyan-300">/api/admin/settings</code> + <code className="text-cyan-300">/api/team/members</code>.
          When <code className="text-cyan-300">/api/admin/audit-log</code> ships, this page picks it up automatically.
        </p>
      )}
    </div>
  );
}
