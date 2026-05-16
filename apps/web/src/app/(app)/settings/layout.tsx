'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  Bell,
  Box,
  Coins,
  CreditCard,
  Eye,
  Key,
  Lock,
  Plug,
  Shield,
  User,
  Users,
  Webhook,
} from 'lucide-react';

const MONETIZATION_ENABLED = process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false';

const NAV_ITEMS = [
  { label: 'Profile', icon: User, href: '/settings/profile' },
  { label: 'API Keys', icon: Key, href: '/settings/api-keys' },
  ...(MONETIZATION_ENABLED ? [{ label: 'Billing', icon: CreditCard, href: '/settings/billing' }] : []),
  { label: 'Team', icon: Users, href: '/settings/team' },
  { label: 'Integrations', icon: Plug, href: '/settings/integrations' },
  { label: 'Notifications', icon: Bell, href: '/settings/notifications' },
  { label: 'Observability', icon: Activity, href: '/settings/observability' },
  { label: 'Security', icon: Lock, href: '/settings/security' },
  { label: 'Data & DLP', icon: Shield, href: '/settings/data' },
  { label: 'Privacy & GDPR', icon: Eye, href: '/settings/privacy' },
  { label: 'Webhooks', icon: Webhook, href: '/settings/webhooks' },
  { label: 'Token Quotas', icon: Coins, href: '/settings/quotas' },
  { label: 'Sandbox', icon: Box, href: '/settings/sandbox' },
];

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex gap-6 max-w-[1400px]">
      <aside className="w-[220px] shrink-0">
        <div className="sticky top-6">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-3">
            Settings
          </h2>
          <nav className="space-y-0.5">
            {NAV_ITEMS.map((item) => {
              const active =
                pathname === item.href ||
                (item.href === '/settings/profile' && pathname === '/settings');
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
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
