'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, Activity, HelpCircle, Sparkles, Gauge, ShieldCheck, FileCheck2,
  GitBranch, LineChart as LineChartIcon, Calendar, BookOpen, AlertOctagon,
  Briefcase, Layers, Wind, RefreshCw, GitCompare, Wallet, FlaskConical,
  ChevronDown, Diamond, AlertTriangle, Truck, Globe, Radar, Compass,
  Database, Lock, Users,
} from 'lucide-react';

function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }
function getUser() { if (typeof window === 'undefined') return null; try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; } }

type NavItem = { label: string; icon: any; href: string; children?: NavItem[] };
type NavSection = { title: string; items: NavItem[] };

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Workspace',
    items: [
      { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
      { label: 'My Contracts', icon: FileText, href: '/contracts' },
      { label: 'Upload Contract', icon: Upload, href: '/upload' },
    ],
  },
  {
    title: 'Intelligence',
    items: [
      {
        label: 'Insights Hub', icon: Sparkles, href: '/insights',
        children: [
          { label: 'Daily Briefing', icon: Sparkles, href: '/insights/briefing' },
          { label: 'Renewals', icon: RefreshCw, href: '/insights/renewals' },
          { label: 'Force Majeure', icon: AlertOctagon, href: '/insights/force-majeure' },
          { label: 'Reconciliation', icon: Wallet, href: '/insights/reconciliation' },
          { label: 'Contract Families', icon: Layers, href: '/insights/families' },
          { label: 'Anomalies', icon: AlertOctagon, href: '/insights/anomalies' },
          { label: 'Version Diff', icon: GitCompare, href: '/insights/version-diff' },
          { label: 'Stress Test', icon: FlaskConical, href: '/insights/stress-test' },
          { label: 'Hedge Ideas', icon: Wind, href: '/insights/hedge' },
          { label: 'Benchmarks', icon: Briefcase, href: '/insights/benchmark' },
        ],
      },
      { label: 'Clause Library', icon: BookOpen, href: '/clauses' },
      { label: 'Deal Clusters', icon: GitBranch, href: '/deal-clusters' },
      { label: 'Event Timeline', icon: Calendar, href: '/timeline' },
      { label: 'Valuation', icon: LineChartIcon, href: '/valuation' },
      { label: 'Market & Risk', icon: Activity, href: '/market' },
      { label: 'Simulations', icon: Gauge, href: '/simulations' },
    ],
  },
  {
    title: 'Compliance',
    items: [
      { label: 'Counterparty Risk', icon: ShieldCheck, href: '/credit-risk' },
      { label: 'KYC Standard Checks', icon: FileCheck2, href: '/credit-risk/kyc' },
    ],
  },
  {
    title: 'Precious Metals',
    items: [
      {
        label: 'Metals Hub', icon: Diamond, href: '/metals',
        children: [
          { label: 'Extraction', icon: Diamond, href: '/metals/extract' },
          { label: 'Compliance Audit', icon: ShieldCheck, href: '/metals/compliance' },
          { label: 'Dispute Risk', icon: AlertTriangle, href: '/metals/disputes' },
          { label: 'Loco + Delivery', icon: Truck, href: '/metals/loco' },
          { label: 'Responsible Sourcing', icon: Globe, href: '/metals/sourcing' },
          { label: 'Refiner Watch', icon: Radar, href: '/metals/refiners' },
        ],
      },
    ],
  },
  {
    title: 'Risk & What-If',
    items: [
      { label: 'Market Risk (VaR/CVaR)', icon: Activity, href: '/risk' },
    ],
  },
  {
    title: 'Tools',
    items: [
      { label: 'Compare', icon: TrendingUp, href: '/compare' },
      { label: 'Chat', icon: MessageSquare, href: '/chat' },
      { label: 'Features Tour', icon: Compass, href: '/features' },
      { label: 'Help', icon: HelpCircle, href: '/help' },
    ],
  },
  {
    title: 'Admin',
    items: [
      { label: 'Access Control', icon: Lock, href: '/admin/rbac' },
      { label: 'Market Data Sources', icon: Database, href: '/admin/market-sources' },
      { label: 'Audit Log', icon: FileCheck2, href: '/admin/audit' },
    ],
  },
];

export default function ContractIQLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (pathname === '/' || pathname === '/features') { setReady(true); return; }
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
    setReady(true);
  }, [pathname, router]);

  // Global 401 interceptor — bounce to login if any API call comes back
  // unauthenticated mid-session (JWT expired, secret rotated, etc.).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const orig = window.fetch.bind(window);
    let bouncing = false;
    window.fetch = async (input, init) => {
      const r = await orig(input, init);
      if (r.status === 401 && !bouncing) {
        const url = typeof input === 'string' ? input : (input as Request).url || '';
        if (!/\/auth\/(login|register|refresh)/.test(url)) {
          bouncing = true;
          localStorage.removeItem('contractiq_token');
          localStorage.removeItem('contractiq_refresh_token');
          localStorage.removeItem('contractiq_user');
          window.location.href = '/';
        }
      }
      return r;
    };
    return () => { window.fetch = orig; };
  }, []);

  if (pathname === '/') return <>{children}</>;

  if (!ready) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  const logout = () => {
    localStorage.removeItem('contractiq_token');
    localStorage.removeItem('contractiq_refresh_token');
    localStorage.removeItem('contractiq_user');
    router.replace('/');
  };

  const isItemActive = (href: string) => {
    if (href === '/dashboard') return pathname === href;
    // Special case: KYC detail routes include /credit-risk/kyc prefix — they should NOT also light up /credit-risk.
    if (href === '/credit-risk') return pathname === href || (pathname?.startsWith('/credit-risk/') && !pathname?.startsWith('/credit-risk/kyc'));
    return pathname === href || (pathname?.startsWith(href + '/') ?? false);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] flex">
      <aside className="w-64 border-r border-slate-800/50 p-4 flex flex-col shrink-0 bg-[#0B0F19]">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <FileSearch className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-base font-bold text-white leading-none">ContractIQ</p>
            <p className="text-[9px] text-slate-500 tracking-wider uppercase mt-0.5">Agent-Driven Contracts</p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto">
          {NAV_SECTIONS.map(section => (
            <div key={section.title} className="mb-4">
              <p className="text-[10px] tracking-[0.12em] uppercase text-slate-600 px-3 mb-1.5 font-semibold">{section.title}</p>
              <div className="space-y-0.5">
                {section.items.map(item => {
                  const active = isItemActive(item.href);
                  const inGroup = !!item.children && pathname?.startsWith(item.href);
                  return (
                    <div key={item.href}>
                      <a
                        href={item.href}
                        className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                          active
                            ? 'bg-emerald-500/10 text-emerald-100 border-l-2 border-emerald-400 pl-[10px]'
                            : 'text-slate-400 hover:text-white hover:bg-slate-800/40 border-l-2 border-transparent pl-[10px]'
                        }`}
                      >
                        <item.icon className={`w-4 h-4 shrink-0 ${active ? 'text-emerald-400' : 'text-slate-500'}`} />
                        <span className="truncate flex-1">{item.label}</span>
                        {item.children && (
                          <ChevronDown className={`w-3 h-3 text-slate-600 transition-transform ${inGroup ? 'rotate-0' : '-rotate-90'}`} />
                        )}
                      </a>
                      {item.children && inGroup && (
                        <div className="ml-7 mt-0.5 space-y-0.5 border-l border-slate-800/60 pl-2">
                          {item.children.map(child => {
                            const childActive = pathname === child.href;
                            return (
                              <a
                                key={child.href}
                                href={child.href}
                                className={`flex items-center gap-2 px-2 py-1.5 rounded text-[12px] transition-colors ${
                                  childActive
                                    ? 'text-emerald-200 bg-emerald-500/10'
                                    : 'text-slate-500 hover:text-white hover:bg-slate-800/30'
                                }`}
                              >
                                <child.icon className="w-3 h-3 shrink-0" />
                                <span className="truncate">{child.label}</span>
                              </a>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-slate-800/50 pt-3">
          <div className="flex items-center gap-2 px-1">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-[10px] font-semibold text-emerald-300">
              {(user?.full_name || user?.email || '?').charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-slate-300 truncate">{user?.full_name || user?.email}</p>
              {user?.full_name && <p className="text-[9px] text-slate-600 truncate">{user?.email}</p>}
            </div>
            <button onClick={logout} title="Sign out" className="text-slate-500 hover:text-red-400 transition-colors shrink-0">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
