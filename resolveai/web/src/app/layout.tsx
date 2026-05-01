import type { Metadata } from 'next';
import Link from 'next/link';
import { LayoutDashboard, Inbox, Headphones, Settings, AlertTriangle, Star, TrendingUp, HelpCircle } from 'lucide-react';
import './globals.css';

export const metadata: Metadata = {
  title: 'ResolveAI',
  description: 'Customer service agents that resolve tickets, cite policies, and catch tomorrow\'s problem tonight.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0B0F19] text-slate-100 min-h-screen antialiased">
        <div className="flex min-h-screen">
          <aside className="w-56 border-r border-slate-800/60 bg-[#0F172A]/70 shrink-0">
            <div className="p-5 border-b border-slate-800/60">
              <div className="text-lg font-semibold text-white flex items-center gap-2">
                <span className="w-6 h-6 rounded bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center">
                  <span className="text-[10px] font-bold text-slate-950">R</span>
                </span>
                ResolveAI
              </div>
              <p className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider">Resolution-first CS</p>
            </div>
            <nav className="p-3 space-y-1 text-sm">
              <NavItem href="/" label="Dashboard"   icon={<LayoutDashboard className="w-4 h-4" />} />
              <NavItem href="/cases" label="Cases"  icon={<Inbox className="w-4 h-4" />} />
              <NavItem href="/sla" label="SLA Board" icon={<AlertTriangle className="w-4 h-4" />} />
              <NavItem href="/qa" label="QA & CSAT" icon={<Star className="w-4 h-4" />} />
              <NavItem href="/trends" label="Trends / VoC" icon={<TrendingUp className="w-4 h-4" />} />
              <NavItem href="/live-console" label="Live Console" icon={<Headphones className="w-4 h-4" />} />
              <NavItem href="/admin" label="Admin"  icon={<Settings className="w-4 h-4" />} />
              <div className="pt-2 mt-2 border-t border-slate-800/60">
                <NavItem href="/help" label="Walkthrough" icon={<HelpCircle className="w-4 h-4" />} />
              </div>
            </nav>
          </aside>
          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </body>
    </html>
  );
}

function NavItem({ href, label, icon }: { href: string; label: string; icon: React.ReactNode }) {
  return (
    <Link href={href} className="flex items-center gap-2 px-3 py-2 rounded-md text-slate-300 hover:bg-slate-800/50 hover:text-white transition-colors">
      {icon}
      {label}
    </Link>
  );
}
