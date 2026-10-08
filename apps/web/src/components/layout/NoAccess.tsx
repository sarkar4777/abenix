'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { ArrowRight, Lock, Users, type LucideIcon } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { holds, useMyPermissions, type MyPermissions } from '@/lib/capabilities';
import { roleLabel } from '@/lib/monitor-format';

// admin role, a ROLE_FEATURES flag (admin by default), or a named capability
export type AccessNeed =
  | { admin: true }
  | { feature: string }
  | { capability: string; label: string };

export interface Onward {
  text: ReactNode;
  href: string;
  label: string;
}

export interface NoAccessProps {
  title: string;
  purpose: ReactNode;
  icon?: LucideIcon;
  need: AccessNeed;
  role?: string | null;
  instead?: Onward;
  testId?: string;
}

export function canAccess(perms: MyPermissions | null | undefined, need: AccessNeed): boolean {
  if (!perms) return false;
  const admin = !!perms.is_admin || perms.role === 'admin';
  if ('admin' in need) return admin;
  if ('feature' in need) return admin || !!perms.features?.[need.feature];
  return holds(perms.capabilities, need.capability);
}

export function whoCanUse(title: string, need: AccessNeed): ReactNode {
  if ('capability' in need) {
    return (
      <>
        {title} needs the {need.label} permission (<code className="rounded bg-slate-800 px-1 text-xs text-slate-300">{need.capability}</code>).
        An admin can grant it to you under Admin, Permissions.
      </>
    );
  }
  return <>Only admins can use {title}. An admin can change your role on the Team page.</>;
}

const DASHBOARD: Onward = {
  text: 'Your dashboard has your agents, recent runs and anything waiting on you.',
  href: '/dashboard',
  label: 'Go to the dashboard',
};

// Shown in place of a page the person cannot open, never a blank screen or a redirect.
export default function NoAccess({ title, purpose, icon, need, role, instead = DASHBOARD, testId = 'no-access' }: NoAccessProps) {
  return (
    <div className="mx-auto max-w-3xl" data-testid={testId}>
      <PageHeader
        className="mb-6"
        title={title}
        purpose={purpose}
        icon={icon}
        primaryAction={{ label: 'Ask an admin', icon: Users, href: '/settings/team', testId: 'no-access-ask' }}
      />
      <section className="rounded-xl border border-slate-700/60 bg-slate-800/30 p-5" aria-labelledby={`${testId}-title`}>
        <div className="flex items-start gap-3">
          <Lock className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden />
          <div className="min-w-0 space-y-2 text-sm leading-relaxed text-slate-300">
            <h2 id={`${testId}-title`} className="text-base font-semibold text-white">
              You don&apos;t have access to this page
            </h2>
            <p data-testid="no-access-who">
              {whoCanUse(title, need)}
              {role ? <> You are signed in as a {roleLabel(role)}.</> : null}
            </p>
            <p>
              Ask an admin if you need it. The Team page lists who the admins are.
            </p>
            <p className="text-slate-400">{instead.text}</p>
            <Link
              href={instead.href}
              className="inline-flex items-center gap-1.5 text-cyan-300 hover:underline"
              data-testid="no-access-instead"
            >
              {instead.label} <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

// Renders the page only for people who can use it, NoAccess for everyone else.
export function AccessGate({ children, ...props }: Omit<NoAccessProps, 'role'> & { children: ReactNode }) {
  const { perms, loading } = useMyPermissions();
  if (loading && !perms) {
    return (
      <div className="mx-auto max-w-3xl" aria-busy="true">
        <div className="h-24 animate-pulse rounded-xl bg-slate-800/40" />
      </div>
    );
  }
  // permissions did not load, let the page and the API decide
  if (!perms) return <>{children}</>;
  if (!canAccess(perms, props.need)) return <NoAccess {...props} role={perms.role} />;
  return <>{children}</>;
}
