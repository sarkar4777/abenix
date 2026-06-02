'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, Activity, HelpCircle, Sparkles, Gauge, ShieldCheck, FileCheck2,
  GitBranch, LineChart as LineChartIcon, Calendar, BookOpen, AlertOctagon,
  Briefcase, Layers, Wind, RefreshCw, GitCompare, Wallet, FlaskConical,
  ChevronDown, Diamond, AlertTriangle, Truck, Globe, Radar, Compass,
  Database, Lock, Flame, Zap, Ship, Leaf, BrainCircuit, BellRing, Search,
} from 'lucide-react';
import { ContractIQExecutionsProvider, useContractIQExecutions } from './components/ContractIQExecutionsProvider';
import LiveActivityRail from './components/LiveActivityRail';
import DagDrawer from './components/DagDrawer';
import PageExplainer from './components/PageExplainer';
import { getPageDoc } from './components/page-docs';

function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }
function getUser() { if (typeof window === 'undefined') return null; try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; } }

type NavItem = { label: string; icon: any; href: string; children?: NavItem[]; badge?: string };
type NavSection = { title: string; description?: string; items: NavItem[] };

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Home',
    items: [
      { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
    ],
  },
  {
    title: 'Trading & Forecasting',
    description: 'Cross-commodity engines that feed every desk',
    items: [
      { label: 'Data Fabric', icon: Database, href: '/data-fabric' },
      { label: 'Offtake Forecaster', icon: TrendingUp, href: '/forecaster' },
      { label: 'Forward Price Engine', icon: LineChartIcon, href: '/price-engine' },
      { label: 'Analyst Workbench', icon: BrainCircuit, href: '/workbench' },
      { label: 'Performance & Backtest', icon: Activity, href: '/model-performance' },
      { label: 'Recommendations', icon: BellRing, href: '/recommendations' },
    ],
  },
  {
    title: 'Commodities',
    description: 'Per-commodity views into the engines above',
    items: [
      { label: 'Natural Gas', icon: Flame, href: '/commodities/gas' },
      { label: 'Power', icon: Zap, href: '/commodities/power' },
      { label: 'LNG', icon: Ship, href: '/commodities/lng' },
      { label: 'Environmental', icon: Leaf, href: '/commodities/environmental' },
      {
        label: 'Precious Metals', icon: Diamond, href: '/metals',
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
    title: 'Contracts',
    items: [
      { label: 'My Contracts', icon: FileText, href: '/contracts' },
      { label: 'Upload', icon: Upload, href: '/upload' },
      { label: 'Clause Library', icon: BookOpen, href: '/clauses' },
      { label: 'Deal Clusters', icon: GitBranch, href: '/deal-clusters' },
      { label: 'Event Timeline', icon: Calendar, href: '/timeline' },
      { label: 'Compare', icon: GitCompare, href: '/compare' },
    ],
  },
  {
    title: 'Risk & Analytics',
    items: [
      { label: 'Counterparty Risk', icon: ShieldCheck, href: '/credit-risk' },
      { label: 'KYC Checks', icon: FileCheck2, href: '/credit-risk/kyc' },
      { label: 'Market Risk (VaR/CVaR)', icon: Activity, href: '/risk' },
      { label: 'Valuation', icon: Wallet, href: '/valuation' },
      { label: 'Simulations', icon: Gauge, href: '/simulations' },
      { label: 'What-If (pick contract)', icon: FlaskConical, href: '/contracts' },
      { label: 'Market', icon: Activity, href: '/market' },
    ],
  },
  {
    title: 'Insights Hub',
    items: [
      {
        label: 'All Insights', icon: Sparkles, href: '/insights',
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
    ],
  },
  {
    title: 'Tools',
    items: [
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
  return (
    <ContractIQExecutionsProvider>
      <ContractIQLayoutInner>{children}</ContractIQLayoutInner>
    </ContractIQExecutionsProvider>
  );
}

function ContractIQLayoutInner({ children }: { children: React.ReactNode }) {
  const { drawerExecutionId, selectExecutionForDrawer } = useContractIQExecutions();
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (pathname === '/' || pathname === '/features') { setReady(true); return; }
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
    setReady(true);
  }, [pathname, router]);

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

  const filteredSections = useMemo(() => {
    if (!search.trim()) return NAV_SECTIONS;
    const q = search.trim().toLowerCase();
    return NAV_SECTIONS.map(section => ({
      ...section,
      items: section.items.flatMap(item => {
        const hit = item.label.toLowerCase().includes(q);
        const childHits = item.children?.filter(c => c.label.toLowerCase().includes(q)) ?? [];
        if (hit) return [item];
        if (childHits.length) return [{ ...item, children: childHits }];
        return [];
      }),
    })).filter(s => s.items.length > 0);
  }, [search]);

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
    if (href === '/credit-risk') return pathname === href || (pathname?.startsWith('/credit-risk/') && !pathname?.startsWith('/credit-risk/kyc'));
    if (href === '/insights') return pathname === href;
    if (href === '/metals') return pathname === href;
    return pathname === href || (pathname?.startsWith(href + '/') ?? false);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] flex">
      <aside className="w-72 border-r border-slate-800/50 flex flex-col shrink-0 bg-gradient-to-b from-[#0B0F19] to-[#0a0e17]">
        <div className="px-4 pt-4 pb-3 flex items-center gap-2.5 border-b border-slate-800/40">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500 via-cyan-500 to-blue-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <FileSearch className="w-[18px] h-[18px] text-white" />
          </div>
          <div className="leading-tight">
            <p className="text-[15px] font-bold text-white">E&amp;C-Copilot</p>
            <p className="text-[9.5px] text-slate-500 tracking-[0.15em] uppercase mt-0.5">Energy &amp; Commodities Suite</p>
          </div>
        </div>

        <div className="px-3 pt-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
            <input
              type="search"
              placeholder="Jump to…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-slate-900/60 border border-slate-800 rounded-md text-slate-200 placeholder-slate-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/30"
            />
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {filteredSections.length === 0 ? (
            <p className="text-xs text-slate-600 px-3 py-4">No matches for &quot;{search}&quot;.</p>
          ) : filteredSections.map(section => (
            <div key={section.title} className="mb-3.5 last:mb-0">
              <div className="px-3 mb-1">
                <p className="text-[10px] tracking-[0.16em] uppercase text-slate-500 font-bold">{section.title}</p>
                {section.description && <p className="text-[9.5px] text-slate-600 leading-snug mt-0.5">{section.description}</p>}
              </div>
              <div className="space-y-0.5">
                {section.items.map(item => {
                  const active = isItemActive(item.href);
                  const inGroup = !!item.children && (pathname === item.href || (pathname?.startsWith(item.href + '/') ?? false));
                  return (
                    <div key={item.href}>
                      <a
                        href={item.href}
                        className={`group flex items-center gap-2.5 px-3 py-1.5 rounded-md text-[13px] transition-all ${
                          active
                            ? 'bg-gradient-to-r from-emerald-500/15 to-emerald-500/0 text-emerald-50 border-l-2 border-emerald-400 pl-[10px]'
                            : 'text-slate-400 hover:text-white hover:bg-slate-800/40 border-l-2 border-transparent pl-[10px]'
                        }`}
                      >
                        <item.icon className={`w-4 h-4 shrink-0 transition-colors ${active ? 'text-emerald-400' : 'text-slate-500 group-hover:text-slate-300'}`} />
                        <span className="truncate flex-1">{item.label}</span>
                        {item.badge && <span className="text-[9px] uppercase tracking-wider bg-cyan-500/15 text-cyan-300 px-1.5 py-0.5 rounded">{item.badge}</span>}
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
                                className={`flex items-center gap-2 px-2 py-1.5 rounded text-[11.5px] transition-colors ${
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

        <div className="border-t border-slate-800/50 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-[10px] font-semibold text-emerald-300">
              {(user?.full_name || user?.email || '?').charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-slate-300 truncate font-medium">{user?.full_name || user?.email}</p>
              {user?.full_name && <p className="text-[10px] text-slate-600 truncate">{user?.email}</p>}
            </div>
            <button onClick={logout} title="Sign out" className="text-slate-500 hover:text-red-400 transition-colors shrink-0 p-1.5 rounded hover:bg-slate-800/50">
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto relative">
        {(() => {
          const doc = pathname ? getPageDoc(pathname) : undefined;
          return doc ? (
            <div className="absolute top-3 right-4 z-30">
              <PageExplainer doc={doc} />
            </div>
          ) : null;
        })()}
        {children}
      </main>
      <LiveActivityRail />
      <DagDrawer executionId={drawerExecutionId} onClose={() => selectExecutionForDrawer(null)} />
    </div>
  );
}
