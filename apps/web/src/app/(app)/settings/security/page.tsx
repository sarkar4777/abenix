'use client';

import { motion } from 'framer-motion';
import {
  Activity, Globe, Lock, Monitor, Smartphone, LogIn, Key, UserCog,
  Bot, Plug, Workflow, FileText, Zap, ShieldCheck, AlertTriangle,
  CircleDot,
} from 'lucide-react';
import { useState } from 'react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';
import TwoFactorPanel from '@/components/settings/TwoFactorPanel';

interface Session {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  method: string;
  created_at: string;
  last_seen_at: string | null;
  current: boolean;
}

const METHOD_LABEL: Record<string, string> = {
  password: 'password',
  'password+2fa': 'password and code',
  sso: 'single sign-on',
  invite: 'invite link',
};

interface ActivityItem {
  id: string;
  action: string;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

function parseUA(ua: string | null): { browser: string; os: string; icon: typeof Monitor } {
  if (!ua) return { browser: 'Unknown', os: 'Unknown', icon: Globe };
  const isMobile = /mobile|android|iphone/i.test(ua);
  let browser = 'Browser';
  if (ua.includes('Chrome')) browser = 'Chrome';
  else if (ua.includes('Firefox')) browser = 'Firefox';
  else if (ua.includes('Safari')) browser = 'Safari';
  else if (ua.includes('Edge')) browser = 'Edge';

  let os = 'Unknown OS';
  if (ua.includes('Mac')) os = 'macOS';
  else if (ua.includes('Windows')) os = 'Windows';
  else if (ua.includes('Linux')) os = 'Linux';
  else if (ua.includes('Android')) os = 'Android';
  else if (ua.includes('iPhone')) os = 'iOS';

  return { browser, os, icon: isMobile ? Smartphone : Monitor };
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Action → human label + icon. Adding rows here is the only thing
// needed when new audit events are introduced; everything else falls
// back to the verb at the end of the dotted name.
const ACTION_META: Record<string, { label: string; icon: any; tone: string }> = {
  'login':              { label: 'Signed in',                icon: LogIn,        tone: 'text-emerald-300' },
  'user.login':         { label: 'Signed in',                icon: LogIn,        tone: 'text-emerald-300' },
  'logout':             { label: 'Signed out',               icon: LogIn,        tone: 'text-slate-400' },
  'session.revoked':    { label: 'Signed out another device', icon: LogIn,       tone: 'text-rose-300' },
  'password.changed':   { label: 'Password changed',         icon: Key,          tone: 'text-amber-300' },
  'password.reset':     { label: 'Password reset by email',  icon: Key,          tone: 'text-amber-300' },
  'password.reset_requested': { label: 'Password reset link sent', icon: Key,    tone: 'text-slate-400' },
  '2fa.enabled':        { label: 'Two-step sign-in turned on', icon: ShieldCheck, tone: 'text-emerald-300' },
  '2fa.disabled':       { label: 'Two-step sign-in turned off', icon: AlertTriangle, tone: 'text-rose-300' },
  'user.2fa_failed':    { label: 'Wrong sign-in code',       icon: AlertTriangle, tone: 'text-rose-300' },
  'user.login_sso':     { label: 'Signed in with SSO',       icon: LogIn,        tone: 'text-emerald-300' },
  'sso.configured':     { label: 'Single sign-on saved',     icon: ShieldCheck,  tone: 'text-cyan-300' },
  'profile.updated':    { label: 'Profile updated',          icon: UserCog,      tone: 'text-cyan-300' },
  'api_key.created':    { label: 'API key created',          icon: Key,          tone: 'text-amber-300' },
  'api_key.revoked':    { label: 'API key revoked',          icon: Key,          tone: 'text-rose-300' },
  'team.invited':       { label: 'Team member invited',      icon: UserCog,      tone: 'text-cyan-300' },
  'team.removed':       { label: 'Team member removed',      icon: UserCog,      tone: 'text-rose-300' },
  'agent.created':      { label: 'Created agent',            icon: Bot,          tone: 'text-violet-300' },
  'agent.updated':      { label: 'Updated agent',            icon: Bot,          tone: 'text-cyan-300' },
  'agent.deleted':      { label: 'Deleted agent',            icon: Bot,          tone: 'text-rose-300' },
  'agent.executed':     { label: 'Ran agent',                icon: Zap,          tone: 'text-amber-300' },
  'pipeline.created':   { label: 'Created pipeline',         icon: Workflow,     tone: 'text-violet-300' },
  'pipeline.updated':   { label: 'Updated pipeline',         icon: Workflow,     tone: 'text-cyan-300' },
  'pipeline.deleted':   { label: 'Deleted pipeline',         icon: Workflow,     tone: 'text-rose-300' },
  'kb.created':         { label: 'Created knowledge base',   icon: FileText,     tone: 'text-emerald-300' },
  'kb.deleted':         { label: 'Deleted knowledge base',   icon: FileText,     tone: 'text-rose-300' },
  'document.uploaded':  { label: 'Uploaded document',        icon: FileText,     tone: 'text-cyan-300' },
  'mcp.created':        { label: 'Connected MCP server',     icon: Plug,         tone: 'text-violet-300' },
  'mcp.deleted':        { label: 'Removed MCP server',       icon: Plug,         tone: 'text-rose-300' },
  'moderation.blocked': { label: 'Moderation blocked input', icon: AlertTriangle,tone: 'text-rose-300' },
};

const SUMMARY_KEYS = ['name', 'slug', 'title', 'filename', 'email'];
const HIDE_KEYS = new Set([
  'integrity_hash', 'new_value', 'old_value',
  'resource_id', 'resource_type', 'tenant_id', 'user_id',
]);

function summarise(item: ActivityItem): string {
  const det = item.details || {};
  // Pull the most user-visible name first
  for (const k of SUMMARY_KEYS) {
    const v = (det as any)[k];
    if (v && typeof v === 'string' && v.length < 80) return v;
  }
  // Fall back to a small chip with kept fields only
  const kept = Object.entries(det).filter(([k, v]) =>
    !HIDE_KEYS.has(k) && v !== null && v !== undefined && v !== '',
  );
  if (kept.length === 0) return '';
  return kept.slice(0, 3).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' · ');
}

function formatIP(ip: string | null): string {
  if (!ip) return '';
  if (ip === '127.0.0.1' || ip === '::1' || ip.startsWith('10.') || ip.startsWith('172.16.') || ip.startsWith('192.168.')) {
    return 'internal';
  }
  return ip;
}

// Drop consecutive duplicates (e.g. 3 user.login events in a row); keep the most recent only.
function dedupeConsecutive(items: ActivityItem[]): Array<ActivityItem & { count?: number }> {
  const out: Array<ActivityItem & { count?: number }> = [];
  for (const it of items) {
    const last = out[out.length - 1];
    if (last && last.action === it.action && summarise(last) === summarise(it)) {
      last.count = (last.count || 1) + 1;
      continue;
    }
    out.push({ ...it });
  }
  return out;
}

export default function SecurityPage() {
  usePageTitle('Security');
  const { data: sessions, isLoading: loadingSessions, mutate: reloadSessions } =
    useApi<Session[]>('/api/settings/sessions');
  const [revoking, setRevoking] = useState<string | null>(null);

  const revoke = async (id: string) => {
    setRevoking(id);
    try {
      await apiFetch(id === 'others' ? '/api/settings/sessions/revoke-others' : `/api/settings/sessions/${id}`, {
        method: id === 'others' ? 'POST' : 'DELETE',
      });
      toastSuccess(id === 'others' ? 'Every other device is signed out' : 'That device is signed out');
      reloadSessions();
    } catch (e) {
      toastError(e instanceof Error ? e.message : 'Could not sign that device out');
    }
    setRevoking(null);
  };
  const { data: activity, isLoading: loadingActivity } =
    useApi<ActivityItem[]>('/api/settings/activity');

  const loading = loadingSessions || loadingActivity;

  const sessionsList = sessions ?? [];
  const activityRaw = activity ?? [];
  const activityList = dedupeConsecutive(activityRaw).slice(0, 25);

  if (loading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <div>
          <div className="h-7 w-24 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-64 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 space-y-4">
          <div className="h-4 w-32 bg-slate-700/50 animate-pulse rounded" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-slate-800 animate-pulse shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-32 bg-slate-800 animate-pulse rounded" />
                <div className="h-3 w-40 bg-slate-700/50 animate-pulse rounded" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-3xl"
    >
      <PageHeader
        title="Security"
        icon={Lock}
        purpose="Where you are signed in, two-step sign-in, and a log of changes made in this workspace. For everyone."
        primaryAction={{ label: 'Change password', icon: Key, href: '/settings/profile' }}
        steps={[
          'Check where you are signed in. The device marked This device is the one you are using.',
          'Sign out any device you do not recognise, then change your password.',
          'Turn on two-step sign-in so a stolen password is not enough.',
          'The activity list shows the last 25 changes, with repeats folded together.',
        ]}
        docSlug="01-architecture/07-governance"
        storageKey="settings-security"
      />

      {/* Signed-in devices */}
      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6" data-testid="sessions-panel" aria-labelledby="sessions-title">
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <Lock className="w-4 h-4 text-cyan-400" aria-hidden="true" />
          <h2 id="sessions-title" className="text-sm font-semibold text-white">Where you are signed in</h2>
          <span className="text-[11px] text-slate-500">{sessionsList.length} {sessionsList.length === 1 ? 'device' : 'devices'}</span>
          {sessionsList.length > 1 && (
            <button
              type="button"
              onClick={() => revoke('others')}
              disabled={revoking !== null}
              data-testid="sessions-revoke-others"
              className="ml-auto text-xs px-2.5 py-1 rounded-lg border border-slate-600 text-slate-200 hover:border-rose-500/60 disabled:opacity-50"
            >
              Sign out all other devices
            </button>
          )}
        </div>
        {sessionsList.length === 0 ? (
          <p className="text-xs text-slate-500">No sign-ins are recorded for this browser yet. Sign out and in again to see it here.</p>
        ) : (
          <ul className="space-y-3">
            {sessionsList.map((session) => {
              const ua = parseUA(session.user_agent);
              const Icon = ua.icon;
              const seen = session.last_seen_at || session.created_at;
              return (
                <li key={session.id} className="flex items-center gap-3" data-testid="session-row">
                  <div className="w-9 h-9 rounded-lg bg-slate-700/30 flex items-center justify-center shrink-0">
                    <Icon className="w-4 h-4 text-slate-400" aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-white truncate">{ua.browser} on {ua.os}</p>
                    <p className="text-[11px] text-slate-500 sm:truncate">
                      {formatIP(session.ip_address) || 'Unknown IP'}
                      {` · signed in with ${METHOD_LABEL[session.method] || session.method}`}
                      {session.created_at ? ` ${timeAgo(session.created_at)}` : ''}
                      {seen ? ` · last active ${timeAgo(seen)}` : ''}
                    </p>
                  </div>
                  {session.current ? (
                    <span className="text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-1.5 py-0.5 rounded shrink-0">This device</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => revoke(session.id)}
                      disabled={revoking !== null}
                      data-testid="session-revoke"
                      aria-label={`Sign out ${ua.browser} on ${ua.os}`}
                      className="text-[11px] px-2 py-1 rounded border border-slate-600 text-slate-300 hover:border-rose-500/60 hover:text-rose-200 disabled:opacity-50 shrink-0"
                    >
                      {revoking === session.id ? 'Signing out...' : 'Sign out'}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <TwoFactorPanel />

      {/* Activity Log */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-white">Activity</h2>
          <span className="ml-auto text-[11px] text-slate-500">last {activityList.length}</span>
        </div>
        {activityList.length > 0 ? (
          <div className="space-y-2">
            {activityList.map((item) => {
              const meta = ACTION_META[item.action];
              const Icon = meta?.icon || CircleDot;
              const label = meta?.label || item.action.replace(/[._]/g, ' ');
              const tone = meta?.tone || 'text-slate-400';
              const summary = summarise(item);
              return (
                <div key={item.id} className="flex items-start gap-3 py-1.5 border-b border-slate-800/40 last:border-b-0">
                  <div className="w-7 h-7 rounded-lg bg-slate-700/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Icon className={`w-3.5 h-3.5 ${tone}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[12.5px] text-slate-200">
                      <span className="font-medium">{label}</span>
                      {summary && <span className="text-slate-400"> — {summary}</span>}
                      {item.count && item.count > 1 && (
                        <span className="ml-1.5 text-[10px] text-slate-500 bg-slate-800/60 border border-slate-700/40 px-1.5 py-0.5 rounded">×{item.count}</span>
                      )}
                    </p>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      {formatIP(item.ip_address) ? `${formatIP(item.ip_address)} · ` : ''}
                      {item.created_at ? timeAgo(item.created_at) : ''}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No activity recorded yet.</p>
        )}
      </div>
    </motion.div>
  );
}
