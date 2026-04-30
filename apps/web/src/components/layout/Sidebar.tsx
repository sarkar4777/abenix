'use client';

import { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApi } from '@/hooks/useApi';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  ChevronLeft,
  ChevronRight,
  Database,
  DollarSign,
  Key,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Plug,
  Radio,
  Settings,
  ShieldCheck,
  Sparkles,
  Store,
  Users,
  HelpCircle,
  Wand2,
  Code2,
  Gauge,
  Cpu,
  FileJson,
  Brain,
  Webhook,
  Wrench,
  X,
  Zap,
  UserCircle2,
  BookOpen,
  ExternalLink,
  Workflow,
  Network,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/stores/sidebar';
import { useIsMobile } from '@/hooks/useMediaQuery';

// Feature flag: hide marketplace/billing for enterprise self-hosted deployments
// Set NEXT_PUBLIC_ENABLE_MONETIZATION=false to hide Marketplace, Creator Hub, Billing
const MONETIZATION_ENABLED = process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false';


interface NavItem {
  label: string;
  icon: any;
  href: string;
  feature?: string;          // permissions.features key — must be true
  adminOnly?: boolean;       // hard role gate (admin only)
  badge?: string;            // tiny badge (e.g. "new", count)
  external?: boolean;        // open in new tab (e.g. /docs)
}

interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
  defaultOpen?: boolean;
}

const NAV_GROUPS: NavGroup[] = [
  {
    id: 'pinned',
    label: 'PINNED',
    defaultOpen: true,
    items: [
      { label: 'Dashboard',     icon: LayoutDashboard, href: '/dashboard',  feature: 'view_dashboard' },
      { label: 'My Agents',     icon: Bot,             href: '/agents',     feature: 'create_agents' },
      { label: 'AI Chat',       icon: MessageSquare,   href: '/chat',       feature: 'use_chat' },
      { label: 'Alerts',        icon: AlertTriangle,   href: '/alerts',     feature: 'view_alerts' },
    ],
  },
  {
    id: 'build',
    label: 'BUILD',
    defaultOpen: false,
    items: [
      { label: 'Agent Builder',     icon: Wand2,    href: '/builder',           feature: 'use_builder' },
      { label: 'Code Runner',       icon: Code2,    href: '/code-runner',       feature: 'use_code_runner' },
      { label: 'ML Models',         icon: Brain,    href: '/ml-models',         feature: 'use_ml_models' },
      { label: 'Knowledge Bases',   icon: Database, href: '/knowledge',         feature: 'use_kb' },
      { label: 'Persona KB',        icon: UserCircle2, href: '/persona',        feature: 'use_persona' },
      { label: 'Portfolio Schemas', icon: FileJson, href: '/portfolio-schemas', feature: 'create_pipelines' },
      { label: 'BPM Analyzer',      icon: Workflow, href: '/bpm-analyzer',      feature: 'use_builder' },
      { label: 'Atlas',             icon: Network,  href: '/atlas',             feature: 'use_kb' },
    ],
  },
  {
    id: 'run',
    label: 'RUN & TEST',
    defaultOpen: false,
    items: [
      { label: 'SDK Playground',  icon: Code2, href: '/sdk-playground',  feature: 'use_sdk_playground' },
      { label: 'Load Playground', icon: Gauge, href: '/load-playground', feature: 'use_load_playground' },
      { label: 'Triggers',        icon: Zap,   href: '/triggers',        feature: 'use_triggers' },
    ],
  },
  {
    id: 'monitor',
    label: 'MONITOR',
    defaultOpen: false,
    items: [
      { label: 'Executions',  icon: Activity,  href: '/executions',      feature: 'view_executions' },
      { label: 'Live Debug',  icon: Radio,     href: '/executions/live', feature: 'view_executions' },
      { label: 'Analytics',   icon: BarChart3, href: '/analytics',       feature: 'view_analytics' },
      { label: 'Moderation',  icon: ShieldCheck, href: '/moderation',    feature: 'view_alerts' },
    ],
  },
  ...(MONETIZATION_ENABLED ? [{
    id: 'monetize',
    label: 'MONETIZE',
    defaultOpen: false,
    items: [
      { label: 'Marketplace', icon: Store,      href: '/marketplace', feature: 'use_marketplace' },
      { label: 'Creator Hub', icon: DollarSign, href: '/creator',     feature: 'publish_to_marketplace' },
    ],
  }] : []),
  {
    id: 'admin',
    label: 'ADMIN',
    defaultOpen: false,
    items: [
      // Platform operations
      { label: 'Scaling',         icon: Gauge,       href: '/admin/scaling',      adminOnly: true },
      { label: 'Model Selection', icon: Cpu,         href: '/admin/llm-settings', adminOnly: true },
      { label: 'LLM Pricing',     icon: DollarSign,  href: '/admin/llm-pricing',  adminOnly: true },
      // Safety / governance — Moderation + Alerts already render under MONITOR
      // for every user with view_alerts; the ADMIN entries here would just be
      // duplicates. Review Queue is admin-only so it stays.
      { label: 'Review Queue',    icon: ShieldCheck, href: '/review-queue',       adminOnly: true },
      // People + access
      { label: 'Team',            icon: Users,       href: '/settings/team',      feature: 'manage_team' },
    ],
  },
  {
    id: 'workspace',
    label: 'WORKSPACE',
    defaultOpen: false,
    items: [
      { label: 'MCP Servers',    icon: Plug, href: '/mcp',                feature: 'manage_mcp' },
      { label: 'API Keys',       icon: Key,  href: '/settings/api-keys',  feature: 'manage_api_keys' },
      { label: 'Settings',       icon: Settings,   href: '/settings' },
      { label: 'Help',           icon: HelpCircle, href: '/help' },
      { label: 'Docs',           icon: BookOpen, href: '/docs', external: true, badge: 'new' },
    ],
  },
];

function useMiniStats() {
  const { data: stats } = useApi<{
    total_agents: number;
    active_executions: number;
    today_executions: number;
    today_failed: number;
  }>('/api/analytics/live-stats');
  return [
    { label: 'Total Agents', value: String(stats?.total_agents ?? 0), color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
    { label: 'Active', value: String(stats?.active_executions ?? 0), color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
    { label: 'Executions', value: String(stats?.today_executions ?? 0), color: 'text-amber-400', bg: 'bg-amber-500/10' },
    { label: 'Failed', value: String(stats?.today_failed ?? 0), color: 'text-red-400', bg: 'bg-red-500/10' },
  ];
}

function useMyPermissions() {
  const { data } = useApi<{
    role: string;
    is_admin: boolean;
    features: Record<string, boolean>;
  }>('/api/me/permissions');
  return data;
}

function SidebarNav({
  collapsed,
  pathname,
  onLinkClick,
  userRole,
}: {
  collapsed: boolean;
  pathname: string;
  onLinkClick?: () => void;
  userRole?: string;
}) {
  const perms = useMyPermissions();
  const features = perms?.features || {};
  const isAdmin = perms?.is_admin || userRole === 'admin';

  // Track which groups are open. Persist to localStorage so a user's
  // sidebar preferences survive reloads — they don't have to re-collapse
  // groups every time they hit refresh.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    if (typeof window === 'undefined') {
      return Object.fromEntries(NAV_GROUPS.map(g => [g.id, !!g.defaultOpen]));
    }
    try {
      const raw = window.localStorage.getItem('abenix.sidebar.groups');
      if (raw) return JSON.parse(raw);
    } catch {}
    return Object.fromEntries(NAV_GROUPS.map(g => [g.id, !!g.defaultOpen]));
  });

  const toggleGroup = (id: string) => {
    setOpenGroups(prev => {
      const next = { ...prev, [id]: !prev[id] };
      try { window.localStorage.setItem('abenix.sidebar.groups', JSON.stringify(next)); } catch {}
      return next;
    });
  };

  // Filter items by feature flag + adminOnly + return only groups
  // that have at least one visible item (no empty group headers).
  const visibleGroups = NAV_GROUPS
    .map(group => {
      const items = group.items.filter(item => {
        if (item.adminOnly && !isAdmin) return false;
        if (item.feature && features[item.feature] === false) return false;
        return true;
      });
      return { ...group, items };
    })
    .filter(g => g.items.length > 0);

  return (
    <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-1">
      {visibleGroups.map(group => {
        const open = openGroups[group.id] ?? !!group.defaultOpen;
        const isPinned = group.id === 'pinned';
        return (
          <div key={group.id}>
            {!collapsed && !isPinned && (
              <button
                onClick={() => toggleGroup(group.id)}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300 transition-colors"
              >
                <ChevronRight
                  className={`w-3 h-3 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
                />
                <span>{group.label}</span>
                <span className="ml-auto text-slate-700">{group.items.length}</span>
              </button>
            )}
            {!collapsed && isPinned && (
              <p className="text-[10px] uppercase tracking-wider text-cyan-400/70 px-3 py-1.5 flex items-center gap-1.5">
                <Sparkles className="w-3 h-3" />
                {group.label}
              </p>
            )}
            {(open || collapsed || isPinned) && (
              <div className="space-y-0.5 mb-2">
                {group.items.map(item => {
                  const active =
                    pathname === item.href ||
                    (item.href === '/settings' && pathname.startsWith('/settings/') && !pathname.startsWith('/settings/team') && !pathname.startsWith('/settings/api-keys'));
                  const linkCls = `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors relative group ${
                    active
                      ? 'bg-cyan-500/10 text-cyan-400'
                      : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                  } ${collapsed ? 'justify-center px-0' : ''}`;
                  const inner = (
                    <>
                      {active && (
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-cyan-400 rounded-r" />
                      )}
                      <item.icon className="w-[18px] h-[18px] shrink-0" />
                      {!collapsed && (
                        <>
                          <span className="text-sm whitespace-nowrap flex-1">{item.label}</span>
                          {item.badge && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 uppercase tracking-wider">
                              {item.badge}
                            </span>
                          )}
                          {item.external && !collapsed && (
                            <ExternalLink className="w-3 h-3 text-slate-600" />
                          )}
                        </>
                      )}
                    </>
                  );
                  return item.external ? (
                    <a
                      key={item.href}
                      href={item.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={collapsed ? item.label : undefined}
                      className={linkCls}
                    >
                      {inner}
                    </a>
                  ) : (
                    <Link
                      key={item.href}
                      href={item.href}
                      title={collapsed ? item.label : undefined}
                      onClick={onLinkClick}
                      className={linkCls}
                    >
                      {inner}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

function SidebarFooter({
  collapsed,
  user,
  logout,
}: {
  collapsed: boolean;
  user: { full_name?: string; email?: string } | null;
  logout: () => void;
}) {
  return (
    <div className="border-t border-slate-800/50 p-3 shrink-0">
      {collapsed ? (
        <button
          onClick={logout}
          title="Logout"
          className="w-full flex items-center justify-center py-2.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
        >
          <LogOut className="w-[18px] h-[18px]" />
        </button>
      ) : (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center shrink-0 text-xs font-bold text-white">
            {user?.full_name?.charAt(0) || 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {user?.full_name || 'User'}
            </p>
            <p className="text-xs text-slate-500 truncate">
              {user?.email || ''}
            </p>
          </div>
          <button
            onClick={logout}
            title="Logout"
            className="text-slate-400 hover:text-white transition-colors shrink-0"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { collapsed, toggle, mobileOpen, closeMobile } = useSidebar();
  const MINI_STATS = useMiniStats();

  const touchStartX = useRef<number | null>(null);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (touchStartX.current === null) return;
      const deltaX = e.changedTouches[0].clientX - touchStartX.current;
      if (deltaX < -80) {
        closeMobile();
      }
      touchStartX.current = null;
    },
    [closeMobile]
  );

  if (isMobile) {
    return (
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              key="mobile-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
              onClick={closeMobile}
            />
            <motion.aside
              key="mobile-sidebar"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ duration: 0.25, ease: 'easeInOut' }}
              className="fixed left-0 top-0 bottom-0 z-50 w-[280px] bg-[#0F172A] border-r border-slate-800 flex flex-col overflow-hidden"
              onTouchStart={handleTouchStart}
              onTouchEnd={handleTouchEnd}
            >
              <div className="flex items-center justify-between h-14 px-3 border-b border-slate-800/50 shrink-0">
                <div className="flex items-center gap-2 overflow-hidden">
                  <img src="/logo.svg" alt="Abenix" className="w-8 h-8 shrink-0" />
                  <span className="text-sm font-bold text-white whitespace-nowrap">
                    Abenix
                  </span>
                </div>
                <button
                  onClick={closeMobile}
                  className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="px-3 pt-3 pb-1 shrink-0">
                <div className="grid grid-cols-2 gap-2">
                  {MINI_STATS.map((s) => (
                    <div
                      key={s.label}
                      className="bg-slate-800/50 rounded-lg p-2 border border-slate-700/30"
                    >
                      <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                      <p className="text-[10px] text-slate-500 leading-tight">
                        {s.label}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <SidebarNav
                collapsed={false}
                pathname={pathname}
                onLinkClick={closeMobile}
                userRole={user?.role}
              />

              <SidebarFooter
                collapsed={false}
                user={user}
                logout={() => {
                  closeMobile();
                  logout();
                }}
              />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    );
  }

  return (
    <motion.aside
      animate={{ width: collapsed ? 64 : 260 }}
      transition={{ duration: 0.2, ease: 'easeInOut' }}
      className="fixed left-0 top-0 bottom-0 z-40 bg-[#0F172A] border-r border-slate-800 flex flex-col overflow-hidden"
    >
      <div className="flex items-center justify-between h-14 px-3 border-b border-slate-800/50 shrink-0">
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 overflow-hidden"
          >
            <img src="/logo.svg" alt="Abenix" className="w-8 h-8 shrink-0" />
            <span className="text-sm font-bold text-white whitespace-nowrap">
              Abenix
            </span>
          </motion.div>
        )}
        <button
          onClick={toggle}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors shrink-0"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </button>
      </div>

      {!collapsed && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="px-3 pt-3 pb-1 shrink-0"
        >
          <div className="grid grid-cols-2 gap-2">
            {MINI_STATS.map((s) => (
              <div
                key={s.label}
                className="bg-slate-800/50 rounded-lg p-2 border border-slate-700/30"
              >
                <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                <p className="text-[10px] text-slate-500 leading-tight">
                  {s.label}
                </p>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      <SidebarNav collapsed={collapsed} pathname={pathname} userRole={user?.role} />

      <SidebarFooter collapsed={collapsed} user={user} logout={logout} />
    </motion.aside>
  );
}
