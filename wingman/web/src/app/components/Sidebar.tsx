'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Activity, Inbox, Ship, Beaker, Network, Sparkles,
  LineChart, Crosshair, ShieldCheck, Home, Anchor,
} from 'lucide-react';
import NotificationBell from './NotificationBell';

const EM_DASH = '—';

type AuthUser = { full_name?: string; email?: string };

function readStoredUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem('wingman_user');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') return parsed as AuthUser;
  } catch {
    // bad json — ignore
  }
  return null;
}

const NAV = [
  { href: '/home', label: 'Home', icon: Home },
  { href: '/desk', label: 'Wingman Copilot', icon: Sparkles },
  { href: '/workbench', label: 'Arbitrage Workbench', icon: Activity },
  { href: '/mispricing', label: 'Price at Risk Lens', icon: Crosshair },
  { href: '/lab', label: 'Market & Freight Lab', icon: Anchor },
  { href: '/scenarios', label: 'Forward Scenarios', icon: LineChart },
  { href: '/inbox', label: 'Broker Inbox', icon: Inbox },
  { href: '/ops', label: 'Operations Watch', icon: Ship },
  { href: '/strategy', label: 'Strategy Lab', icon: Beaker },
  { href: '/graph', label: 'Knowledge Graph', icon: Network },
  { href: '/approvals', label: 'Approvals', icon: ShieldCheck },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    const stored = readStoredUser();
    if (stored) {
      setUser(stored);
      return;
    }
    let cancelled = false;
    fetch('/api/auth/me', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setUser({ full_name: data.full_name, email: data.email });
      })
      .catch(() => {
        // unauthenticated — leave em-dashes
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const version = process.env.NEXT_PUBLIC_APP_VERSION || EM_DASH;
  const fullName = user?.full_name || EM_DASH;
  const email = user?.email || EM_DASH;

  return (
    <aside className="w-60 shrink-0 border-r border-slate-800 bg-[#0F172A] flex flex-col">
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-slate-900" />
          </div>
          <div className="flex-1">
            <div className="text-base font-bold text-white tracking-tight">Wingman</div>
            <div className="text-[10px] uppercase tracking-wider text-emerald-400">Trader Workbench</div>
          </div>
          <NotificationBell />
        </div>
      </div>
      <nav className="px-2 py-4 flex-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 mb-1 rounded-lg text-sm transition-colors ${
                active
                  ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="px-4 py-3 border-t border-slate-800 text-[11px] text-slate-500">
        <div className="text-slate-300">{fullName}</div>
        <div className="text-slate-500 truncate">{email}</div>
        <div className="mt-2 text-[10px] text-slate-600">Powered by Abenix · {version}</div>
      </div>
    </aside>
  );
}
