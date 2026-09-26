import type { Metadata } from 'next';
import Link from 'next/link';
import { FlaskConical, LayoutDashboard, TrendingUp } from 'lucide-react';

import ToastHost from '@/components/ToastHost';
import './globals.css';

export const metadata: Metadata = {
  title: 'PharmaVigil',
  description:
    'Adverse-event intake, MedDRA coding, causality and signal detection. Every assessment runs on Abenix.',
};

function NavItem({ href, label, icon }: { href: string; label: string; icon: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-slate-400 hover:text-teal-300 hover:bg-slate-800/50 transition-colors"
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-200 antialiased">
        <div className="flex min-h-screen">
          <aside className="w-56 shrink-0 border-r border-slate-800/80 bg-slate-900/40">
            <div className="p-4 border-b border-slate-800/80 flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-teal-500/15 ring-1 ring-teal-500/40 grid place-items-center">
                <FlaskConical className="w-4 h-4 text-teal-300" />
              </div>
              <div>
                <div className="text-sm font-bold text-white leading-tight">PharmaVigil</div>
                <div className="text-[10px] uppercase tracking-wider text-teal-500/70">
                  Drug safety
                </div>
              </div>
            </div>
            <nav className="p-3 space-y-1 text-sm">
              <NavItem href="/" label="Case queue" icon={<LayoutDashboard className="w-4 h-4" />} />
              <NavItem href="/signals" label="Signal board" icon={<TrendingUp className="w-4 h-4" />} />
            </nav>
            <div className="px-4 pb-4 mt-auto">
              <p className="text-[10px] text-slate-600 leading-relaxed">
                Every assessment runs on Abenix through the SDK. MedDRA coding and
                disproportionality are code assets; review priority is a trained model.
              </p>
            </div>
          </aside>
          <div className="flex-1 min-w-0">{children}</div>
        </div>
        <ToastHost />
      </body>
    </html>
  );
}
