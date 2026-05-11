'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity, Inbox, Ship, Beaker, Network, Sparkles,
  LineChart, Crosshair, ShieldCheck,
} from 'lucide-react';

const NAV = [
  { href: '/workbench', label: 'Arbitrage Workbench', icon: Activity },
  { href: '/mispricing', label: 'Mispricing Lens', icon: Crosshair },
  { href: '/scenarios', label: 'Forward Scenarios', icon: LineChart },
  { href: '/inbox', label: 'Broker Inbox', icon: Inbox },
  { href: '/ops', label: 'Operations Watch', icon: Ship },
  { href: '/strategy', label: 'Strategy Lab', icon: Beaker },
  { href: '/graph', label: 'Knowledge Graph', icon: Network },
  { href: '/approvals', label: 'Approvals', icon: ShieldCheck },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-60 shrink-0 border-r border-slate-800 bg-[#0F172A] flex flex-col">
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-slate-900" />
          </div>
          <div>
            <div className="text-base font-bold text-white tracking-tight">Wingman</div>
            <div className="text-[10px] uppercase tracking-wider text-emerald-400">Trader Workbench</div>
          </div>
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
        <div className="text-slate-300">Demo Trader</div>
        <div className="text-slate-500 truncate">demo-trader@wingman.local</div>
        <div className="mt-2 text-[10px] text-slate-600">Powered by Abenix · v0.1</div>
      </div>
    </aside>
  );
}
