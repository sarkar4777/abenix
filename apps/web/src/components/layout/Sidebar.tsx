'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
  Book,
  HelpCircle,
  Wand2,
  Code2,
  Gauge,
  Cpu,
  CircuitBoard,
  FileJson,
  Inbox,
  Brain,
  FlaskConical,
  Webhook,
  Wrench,
  X,
  Zap,
  UserCircle2,
  BookOpen,
  ExternalLink,
  Workflow,
  Network,
  Archive,
  Video,
  ShieldAlert,
  UserCog,
  Scale,
  Bell,
  Radar,
  Milestone,
  Sprout,
  BellRing,
  Home,
  LayoutGrid,
  ChevronDown,
  History,
  LineChart,
  Boxes,
  KeyRound,
  ListChecks,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/stores/sidebar';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { holds, type MyPermissions } from '@/lib/capabilities';
import { useNotificationStore } from '@/stores/notificationStore';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';
import {
  badgeText,
  cacheMode,
  readCachedMode,
  saveSidebarMode,
  useInboxCounts,
  type SidebarMode,
} from '@/lib/inbox';


interface NavItem {
  label: string;
  icon: any;
  href: string;
  feature?: string;          // permissions.features key — must be true
  adminOnly?: boolean;       // hard role gate (admin only)
  capability?: string;       // permissions.capabilities must hold it
  badge?: string;            // tiny badge (e.g. "new", count)
  orCapability?: string;     // shown without the feature when this capability is held
  liveCount?: 'reviews' | 'inbox'; // badge from a live count
  external?: boolean;        // open in new tab (e.g. /docs)
  requires?: 'marketplace' | 'monetization'; // runtime switch from /api/platform/features
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
      { label: 'Needs you',     icon: BellRing,        href: '/inbox',      liveCount: 'inbox' },
      { label: 'Dashboard',     icon: LayoutDashboard, href: '/dashboard',  feature: 'view_dashboard' },
      { label: 'My Agents',     icon: Bot,             href: '/agents',     feature: 'create_agents' },
      { label: 'AI Chat',       icon: MessageSquare,   href: '/chat',       feature: 'use_chat' },
      { label: 'Alerts',        icon: AlertTriangle,   href: '/alerts',     feature: 'view_alerts' },
    ],
  },
  {
    id: 'build',
    label: 'BUILD',
    defaultOpen: true,
    items: [
      { label: 'Agent Builder',     icon: Wand2,    href: '/builder',           feature: 'use_builder' },
      { label: 'Manage agents',     icon: ListChecks, href: '/agents/manage', feature: 'create_agents' },
      { label: 'Tools Catalogue',   icon: Wrench,   href: '/tools',             feature: 'use_builder' },
      { label: 'Decisions',         icon: Scale,    href: '/decisions',         capability: 'decisions.view' },
      { label: 'Source Watch',      icon: Radar,    href: '/sources' },
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
    defaultOpen: true,
    items: [
      { label: 'SDK Playground',  icon: Code2, href: '/sdk-playground',  feature: 'use_sdk_playground' },
      { label: 'Load Playground', icon: Gauge, href: '/load-playground', feature: 'use_load_playground' },
      { label: 'Triggers',        icon: Zap,   href: '/triggers',        feature: 'use_triggers' },
      { label: 'Evaluations',     icon: FlaskConical, href: '/evals',   capability: 'evals.run' },
      { label: 'Meetings',        icon: Video, href: '/meetings',        feature: 'use_meetings' },
    ],
  },
  {
    id: 'monitor',
    label: 'MONITOR',
    defaultOpen: true,
    items: [
      { label: 'Observability',icon: Gauge,    href: '/observability',   feature: 'view_executions' },
      { label: 'Executions',  icon: Activity,  href: '/executions',      feature: 'view_executions' },
      { label: 'Live Debug',  icon: Radio,     href: '/executions/live', feature: 'view_executions' },
      { label: 'Analytics',   icon: BarChart3, href: '/analytics',       feature: 'view_analytics' },
      { label: 'Moderation',  icon: ShieldCheck, href: '/moderation',    feature: 'view_alerts' },
      { label: 'Autonomy',    icon: Milestone, href: '/autonomy',        capability: 'autonomy.view' },
      { label: 'Improvements', icon: Sprout,   href: '/improvements',    capability: 'improvements.view' },
    ],
  },
  {
    id: 'monetize',
    label: 'MARKETPLACE',
    defaultOpen: false,
    items: [
      { label: 'Marketplace', icon: Store,      href: '/marketplace', feature: 'use_marketplace', requires: 'marketplace' },
      { label: 'Creator Hub', icon: DollarSign, href: '/creator',     feature: 'publish_to_marketplace', requires: 'marketplace' },
    ],
  },
  {
    id: 'admin',
    label: 'ADMIN',
    defaultOpen: false,
    items: [
      // Platform operations stay hard admin gates
      { label: 'Cluster Health',    icon: Cpu,         href: '/admin/cluster',      adminOnly: true },
      { label: 'Scaling',           icon: Gauge,       href: '/admin/scaling',      adminOnly: true },
      { label: 'Tool Scaling',      icon: Gauge,       href: '/admin/tool-scaling', adminOnly: true },
      { label: 'Pipeline Scaling',  icon: Gauge,       href: '/admin/pipeline-scaling', adminOnly: true },
      { label: 'Archives',          icon: Archive,     href: '/admin/archives',     adminOnly: true },
      { label: 'Dead Letter Queue', icon: Inbox,       href: '/admin/dlq',          adminOnly: true },
      { label: 'Audit log',         icon: History,     href: '/admin/audit',        adminOnly: true },
      { label: 'Models catalogue',  icon: Boxes,       href: '/admin/models',       adminOnly: true },
      { label: 'Market data',       icon: LineChart,   href: '/admin/market-sources', adminOnly: true },
      // Tenant settings follow the manage_settings flag from ROLE_FEATURES
      { label: 'Model Selection',   icon: Cpu,         href: '/admin/llm-settings', feature: 'manage_settings' },
      { label: 'Tool Configuration', icon: Wrench,     href: '/admin/tool-config',  feature: 'manage_settings' },
      { label: 'LLM Pricing',       icon: DollarSign,  href: '/admin/llm-pricing',  feature: 'manage_settings' },
      { label: 'Connectors',        icon: Plug,        href: '/admin/connectors',   feature: 'manage_settings' },
      { label: 'Marketplace & Billing', icon: Store,   href: '/admin/marketplace',  feature: 'manage_settings' },
      { label: 'Events',            icon: Bell,        href: '/settings/webhooks',  capability: 'events.manage' },
      // Moderation + Alerts already render under MONITOR for view_alerts
      // Governance follows capabilities, so a tenant can hand it to non-admins
      { label: 'Risk & Controls',   icon: ShieldAlert, href: '/admin/risk',         capability: 'risk.view' },
      // People + access
      { label: 'Team',              icon: Users,       href: '/settings/team',      feature: 'manage_team' },
      { label: 'Roles',             icon: KeyRound,    href: '/admin/rbac',         adminOnly: true },
      { label: 'Permissions',       icon: UserCog,     href: '/admin/permissions',  capability: 'permissions.manage' },
    ],
  },
  {
    id: 'workspace',
    label: 'WORKSPACE',
    defaultOpen: true,
    items: [
      { label: 'Approvals',      icon: ShieldCheck, href: '/approvals' },
      // held content reviewers and marketplace admins share one inbox
      { label: 'Review inbox',   icon: Inbox, href: '/review-queue', feature: 'review_queue', orCapability: 'moderation.review', liveCount: 'reviews' },
      { label: 'MCP Servers',    icon: Plug, href: '/mcp',                feature: 'manage_mcp' },
      { label: 'Edge',           icon: CircuitBoard, href: '/edge' },
      { label: 'API Keys',       icon: Key,  href: '/settings/api-keys',  feature: 'manage_api_keys' },
      { label: 'Cognify config',  icon: Plug, href: '/settings/cognify' },
      { label: 'GDPR (right to erasure)', icon: Plug, href: '/settings/gdpr' },
      { label: 'Integrations',   icon: Plug, href: '/settings/integrations', feature: 'manage_settings' },
      { label: 'Settings',       icon: Settings,   href: '/settings' },
      { label: 'Help',           icon: HelpCircle, href: '/help' },
      { label: 'Developer docs', icon: Book,       href: '/docs',     external: true },
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
    { label: 'Total Agents', value: String(stats?.total_agents ?? 0), color: 'text-cyan-400', bg: 'bg-cyan-500/10', href: '/agents?tab=all' },
    { label: 'Active', value: String(stats?.active_executions ?? 0), color: 'text-emerald-400', bg: 'bg-emerald-500/10', href: '/executions?status=running' },
    { label: 'Runs today', value: String(stats?.today_executions ?? 0), color: 'text-amber-400', bg: 'bg-amber-500/10', href: '/executions?since=today' },
    { label: 'Failed today', value: String(stats?.today_failed ?? 0), color: 'text-red-400', bg: 'bg-red-500/10', href: '/executions?since=today&status=failed' },
  ];
}

function useMyPermissions() {
  const { data } = useApi<MyPermissions>('/api/me/permissions');
  return data;
}

// waiting held content, refreshed when the socket says the queue changed
function useReviewCount(enabled: boolean): number {
  const tick = useNotificationStore((s) => s.moderationQueueTick);
  const { data, mutate } = useApi<{ pending: number }>(enabled ? '/api/moderation/reviews/count' : null);
  const refresh = useRef(mutate);
  refresh.current = mutate;
  useEffect(() => {
    if (tick && enabled) refresh.current();
  }, [tick, enabled]);
  return data?.pending ?? 0;
}

export interface NavContext {
  perms: MyPermissions | null | undefined;
  isAdmin: boolean;
  switches: Partial<Record<'marketplace' | 'monetization', boolean>>;
}

// Flags that are admin-only in ROLE_FEATURES stay hidden until the
// permissions call lands, so a slow network never flashes admin items.
const ADMIN_DEFAULT_FEATURES = ['review_queue', 'manage_settings', 'manage_team'];

export function itemVisible(item: NavItem, { perms, isAdmin, switches }: NavContext): boolean {
  const features = perms?.features || {};
  if (item.adminOnly && !isAdmin) return false;
  if (item.requires && !switches[item.requires]) return false;
  if (item.capability && !holds(perms?.capabilities, item.capability)) return false;
  const viaCapability = !!item.orCapability && holds(perms?.capabilities, item.orCapability);
  if (item.feature && features[item.feature] === false && !viaCapability) return false;
  if (item.feature && !perms && ADMIN_DEFAULT_FEATURES.includes(item.feature) && !isAdmin) return false;
  return true;
}

// groups with at least one visible item, never an empty header
export function visibleNavGroups(ctx: NavContext): NavGroup[] {
  return NAV_GROUPS
    .map((group) => ({ ...group, items: group.items.filter((item) => itemVisible(item, ctx)) }))
    .filter((g) => g.items.length > 0);
}

interface EssentialSpec { href: string; label?: string; icon?: NavItem['icon']; builders?: boolean; capability?: string }

const ESSENTIALS: EssentialSpec[] = [
  { href: '/inbox' },
  // reviewers need their queue and its count without opening all tools
  { href: '/review-queue', capability: 'moderation.review' },
  { href: '/dashboard', label: 'Home', icon: Home },
  { href: '/agents', label: 'Agents' },
  { href: '/chat' },
  { href: '/knowledge', label: 'Knowledge' },
  { href: '/executions', label: 'Monitor' },
  { href: '/builder', builders: true },
  { href: '/autonomy', builders: true },
  { href: '/improvements', builders: true },
];

const ALL_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export function essentialItems(ctx: NavContext, role?: string): NavItem[] {
  const builder = ctx.isAdmin || role === 'creator';
  return ESSENTIALS.flatMap((spec) => {
    const item = ALL_ITEMS.find((i) => i.href === spec.href);
    if (!item || (spec.builders && !builder) || !itemVisible(item, ctx)) return [];
    if (spec.capability && !holds(ctx.perms?.capabilities, spec.capability)) return [];
    return [{ ...item, label: spec.label ?? item.label, icon: spec.icon ?? item.icon }];
  });
}

export function adminEssentials(ctx: NavContext): NavItem[] {
  if (!ctx.isAdmin) return [];
  return (NAV_GROUPS.find((g) => g.id === 'admin')?.items ?? []).filter((i) => itemVisible(i, ctx));
}

function isActive(item: NavItem, pathname: string): boolean {
  return (
    pathname === item.href ||
    (item.href === '/settings' && pathname.startsWith('/settings/') && !pathname.startsWith('/settings/team') && !pathname.startsWith('/settings/api-keys'))
  );
}

// the server copy wins once it lands, localStorage only paints the first frame
function useSidebarMode(): [SidebarMode, (m: SidebarMode) => void] {
  const [mode, setMode] = useState<SidebarMode>(() =>
    typeof window === 'undefined' ? 'essentials' : readCachedMode() ?? 'essentials',
  );
  const { data } = useApi<{ sidebar_mode: SidebarMode }>('/api/me/ui-prefs', { dedupingInterval: 60_000 });
  const touched = useRef(false);
  useEffect(() => {
    const server = data?.sidebar_mode;
    if (!server || touched.current) return;
    setMode(server);
    cacheMode(server);
  }, [data]);
  const change = useCallback((m: SidebarMode) => {
    touched.current = true;
    setMode(m);
    saveSidebarMode(m);
  }, []);
  return [mode, change];
}

function CountBadge({ n, testId, label }: { n: number; testId: string; label: string }) {
  if (n <= 0) return null;
  return (
    <span
      data-testid={testId}
      aria-label={label}
      className="text-[10px] min-w-[18px] text-center px-1.5 py-0.5 rounded-full bg-amber-500/25 text-amber-200"
    >
      {badgeText(n)}
    </span>
  );
}

function NavLink({
  item,
  collapsed,
  active,
  onLinkClick,
  counts,
}: {
  item: NavItem;
  collapsed: boolean;
  active: boolean;
  onLinkClick?: () => void;
  counts: { reviews: number; inbox: number };
}) {
  const live = item.liveCount ? counts[item.liveCount] : 0;
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
      {collapsed && item.liveCount === 'inbox' && live > 0 && (
        <span className="absolute top-1 right-2 w-2 h-2 rounded-full bg-amber-400" aria-hidden />
      )}
      {!collapsed && (
        <>
          <span className="text-sm whitespace-nowrap flex-1">{item.label}</span>
          {item.badge && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 uppercase tracking-wider">
              {item.badge}
            </span>
          )}
          {item.liveCount === 'reviews' && (
            <CountBadge n={live} testId="sidebar-review-count" label={`${live} waiting for review`} />
          )}
          {item.liveCount === 'inbox' && (
            <CountBadge n={live} testId="sidebar-inbox-count" label={`${live} waiting on you`} />
          )}
          {item.external && <ExternalLink className="w-3 h-3 text-slate-600" />}
        </>
      )}
    </>
  );
  const title = collapsed ? (live > 0 ? `${item.label} (${live})` : item.label) : undefined;
  return item.external ? (
    <a href={item.href} target="_blank" rel="noopener noreferrer" title={title} className={linkCls} data-nav={item.href}>
      {inner}
    </a>
  ) : (
    <Link href={item.href} prefetch={false} title={title} onClick={onLinkClick} className={linkCls} data-nav={item.href}>
      {inner}
    </Link>
  );
}

export function SidebarNav({
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
  const switches = usePlatformFeatures();
  const isAdmin = !!perms?.is_admin || userRole === 'admin';
  const ctx: NavContext = { perms, isAdmin, switches };
  const reviewCount = useReviewCount(holds(perms?.capabilities, 'moderation.review'));
  const { counts: inbox } = useInboxCounts();
  const counts = { reviews: reviewCount, inbox: inbox?.total ?? 0 };
  const [mode, setMode] = useSidebarMode();
  const [adminOpen, setAdminOpen] = useState(false);

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

  const groups = visibleNavGroups(ctx);
  const essentials = essentialItems(ctx, userRole);
  const adminItems = adminEssentials(ctx);
  const inEssentials = [...essentials, ...adminItems].some((i) => isActive(i, pathname));
  // a page opened from the palette or a link still shows where you are
  const here = !inEssentials ? groups.flatMap((g) => g.items).find((i) => isActive(i, pathname)) : undefined;

  const toggle = (
    <div className="px-2 pb-2 pt-1 border-t border-slate-800/50 shrink-0">
      <button
        type="button"
        onClick={() => setMode(mode === 'all' ? 'essentials' : 'all')}
        aria-pressed={mode === 'all'}
        data-testid="sidebar-mode-toggle"
        data-mode={mode}
        title={collapsed ? (mode === 'all' ? 'Show essentials only' : 'Show all tools') : undefined}
        className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors ${collapsed ? 'justify-center px-0' : ''}`}
      >
        <LayoutGrid className="w-4 h-4 shrink-0" />
        {!collapsed && <span>{mode === 'all' ? 'Show essentials only' : 'Show all tools'}</span>}
      </button>
    </div>
  );

  if (mode === 'essentials') {
    return (
      <>
        <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-0.5" data-testid="sidebar-essentials" aria-label="Main">
          {essentials.map((item) => (
            <NavLink key={item.href} item={item} collapsed={collapsed} active={isActive(item, pathname)} onLinkClick={onLinkClick} counts={counts} />
          ))}
          {adminItems.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setAdminOpen((o) => !o)}
                aria-expanded={adminOpen || collapsed}
                data-testid="sidebar-admin-toggle"
                title={collapsed ? 'Admin' : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors ${collapsed ? 'justify-center px-0' : ''}`}
              >
                <ShieldCheck className="w-[18px] h-[18px] shrink-0" />
                {!collapsed && (
                  <>
                    <span className="text-sm flex-1 text-left">Admin</span>
                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${adminOpen ? 'rotate-180' : ''}`} />
                  </>
                )}
              </button>
              {(adminOpen || collapsed) && (
                <div className={collapsed ? '' : 'ml-3 border-l border-slate-800 pl-1'} data-testid="sidebar-admin-items">
                  {adminItems.map((item) => (
                    <NavLink key={item.href} item={item} collapsed={collapsed} active={isActive(item, pathname)} onLinkClick={onLinkClick} counts={counts} />
                  ))}
                </div>
              )}
            </div>
          )}
          {here && (
            <div className="pt-3" data-testid="sidebar-current-page">
              {!collapsed && <p className="text-[10px] uppercase tracking-wider text-slate-500 px-3 py-1">You are here</p>}
              <NavLink item={here} collapsed={collapsed} active onLinkClick={onLinkClick} counts={counts} />
            </div>
          )}
        </nav>
        {toggle}
      </>
    );
  }

  return (
    <>
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-1" data-testid="sidebar-all" aria-label="Main">
        {groups.map(group => {
          const open = openGroups[group.id] ?? !!group.defaultOpen;
          const isPinned = group.id === 'pinned';
          return (
            <div key={group.id}>
              {!collapsed && !isPinned && (
                <button
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={open}
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
              {/* links stay in the DOM when a group is shut, so search and automation still find them */}
              <div
                className={`space-y-0.5 mb-2 overflow-hidden transition-[max-height] duration-200 ${
                  open || collapsed || isPinned ? 'max-h-[1500px]' : 'max-h-0'
                }`}
                aria-hidden={!(open || collapsed || isPinned)}
              >
                <div>
                  {group.items.map(item => (
                    <NavLink key={item.href} item={item} collapsed={collapsed} active={isActive(item, pathname)} onLinkClick={onLinkClick} counts={counts} />
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </nav>
      {toggle}
    </>
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
          aria-label="Log out"
          className="w-full flex items-center justify-center py-2.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
        >
          <LogOut className="w-[18px] h-[18px]" />
          <span className="sr-only">Log out</span>
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
            aria-label="Log out"
            className="text-slate-400 hover:text-white transition-colors shrink-0"
          >
            <LogOut className="w-4 h-4" />
            <span className="sr-only">Log out</span>
          </button>
        </div>
      )}
    </div>
  );
}

// route -> label, so the top bar names every page the way the sidebar does
export const NAV_ROUTE_LABELS: Record<string, string> = Object.fromEntries(
  NAV_GROUPS.flatMap((g) => g.items.filter((i) => !i.external).map((i) => [i.href, i.label])),
);

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
                  <img src="/logo.svg" alt="Abenix" className="w-9 h-9 shrink-0" />
                  <span className="text-base font-bold text-white whitespace-nowrap">
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
                    <Link
                      key={s.label}
                      href={s.href}
                      data-testid="mini-stat"
                      className="block bg-slate-800/50 rounded-lg p-2 border border-slate-700/30 hover:border-cyan-500/40 transition-colors"
                    >
                      <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                      <p className="text-[10px] text-slate-500 leading-tight">
                        {s.label}
                      </p>
                    </Link>
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
            <img src="/logo.svg" alt="Abenix" className="w-9 h-9 shrink-0" />
            <span className="text-base font-bold text-white whitespace-nowrap">
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
              <Link
                key={s.label}
                href={s.href}
                data-testid="mini-stat"
                className="block bg-slate-800/50 rounded-lg p-2 border border-slate-700/30 hover:border-cyan-500/40 transition-colors"
              >
                <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                <p className="text-[10px] text-slate-500 leading-tight">
                  {s.label}
                </p>
              </Link>
            ))}
          </div>
        </motion.div>
      )}

      <SidebarNav collapsed={collapsed} pathname={pathname} userRole={user?.role} />

      <SidebarFooter collapsed={collapsed} user={user} logout={logout} />
    </motion.aside>
  );
}
