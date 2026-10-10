'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Activity,
  Bell,
  Box,
  Coins,
  CreditCard,
  Eye,
  Building2,
  Key,
  Lock,
  Plug,
  Shield,
  User,
  Users,
  Webhook,
} from 'lucide-react';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';
import { useAuth } from '@/contexts/AuthContext';

const NAV_ITEMS: { label: string; icon: typeof User; href: string; capability?: string; monetization?: boolean; adminOnly?: boolean }[] = [
  { label: 'Profile', icon: User, href: '/settings/profile' },
  { label: 'API Keys', icon: Key, href: '/settings/api-keys' },
  { label: 'Billing', icon: CreditCard, href: '/settings/billing', monetization: true },
  { label: 'Team', icon: Users, href: '/settings/team' },
  { label: 'Integrations', icon: Plug, href: '/settings/integrations' },
  { label: 'Notifications', icon: Bell, href: '/settings/notifications' },
  { label: 'Observability', icon: Activity, href: '/settings/observability' },
  { label: 'Security', icon: Lock, href: '/settings/security' },
  { label: 'Single sign-on', icon: Building2, href: '/settings/sso', adminOnly: true },
  { label: 'Data & DLP', icon: Shield, href: '/settings/data' },
  { label: 'Privacy & GDPR', icon: Eye, href: '/settings/privacy' },
  { label: 'Events', icon: Webhook, href: '/settings/webhooks', capability: 'events.manage' },
  { label: 'Token Quotas', icon: Coins, href: '/settings/quotas' },
  { label: 'Sandbox', icon: Box, href: '/settings/sandbox' },
];

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { perms } = useMyPermissions();
  const { monetization } = usePlatformFeatures();
  const { user } = useAuth();
  const items = NAV_ITEMS.filter(
    (item) =>
      (!item.capability || holds(perms?.capabilities, item.capability)) &&
      (!item.monetization || monetization) &&
      (!item.adminOnly || user?.role === 'admin'),
  );
  const current =
    items.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))?.href ??
    (pathname === '/settings' ? '/settings/profile' : '');

  return (
    <div className="flex flex-col md:flex-row gap-4 md:gap-6 max-w-[1400px]">
      {/* phones get a picker so the forms keep the full width */}
      <div className="md:hidden">
        <label htmlFor="settings-section" className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
          Settings section
        </label>
        <select
          id="settings-section"
          data-testid="settings-section-select"
          value={current}
          onChange={(e) => router.push(e.target.value)}
          className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          {current === '' && <option value="">Choose a section</option>}
          {items.map((item) => (
            <option key={item.href} value={item.href}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <aside className="hidden md:block w-[220px] shrink-0">
        <div className="sticky top-6">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-3">
            Settings
          </h2>
          <nav className="space-y-0.5">
            {items.map((item) => {
              const active = item.href === current;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-sm ${
                    active
                      ? 'bg-cyan-500/10 text-cyan-400'
                      : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                  }`}
                >
                  <item.icon className="w-[18px] h-[18px]" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </aside>
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
