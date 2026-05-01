'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle,
  ArrowLeft,
  Bell,
  BookOpen,
  Bot,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CreditCard,
  Globe,
  Headphones,
  Home,
  LogOut,
  Menu,
  Moon,
  Settings,
  ShieldCheck,
  Sparkles,
  User,
  UserPlus,
  XCircle,
  Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/stores/sidebar';
import {
  useNotificationStore,
  type Notification,
} from '@/stores/notificationStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/agents': 'My Agents',
  '/builder': 'Agent Builder',
  '/marketplace': 'Marketplace',
  '/chat': 'AI Chat',
  '/knowledge': 'Knowledge Bases',
  '/analytics': 'Analytics',
  '/mcp': 'MCP Servers',
  '/settings/api': 'API Keys',
  '/settings': 'Settings',
  '/team': 'Team',
  '/creator': 'Creator Hub',
};

const NOTIFICATION_ICONS: Record<string, typeof Bell> = {
  execution_complete: CheckCircle2,
  execution_failed: XCircle,
  new_subscriber: UserPlus,
  usage_warning: AlertTriangle,
  system_alert: Zap,
};

const NOTIFICATION_COLORS: Record<string, string> = {
  execution_complete: 'text-emerald-400 bg-emerald-500/10',
  execution_failed: 'text-red-400 bg-red-500/10',
  new_subscriber: 'text-cyan-400 bg-cyan-500/10',
  usage_warning: 'text-amber-400 bg-amber-500/10',
  system_alert: 'text-purple-400 bg-purple-500/10',
};

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function NotificationItem({
  notification,
  onRead,
  onClick,
}: {
  notification: Notification;
  onRead: (id: string) => void;
  onClick: (n: Notification) => void;
}) {
  const Icon = NOTIFICATION_ICONS[notification.type] || Bell;
  const colorClass = NOTIFICATION_COLORS[notification.type] || 'text-slate-400 bg-slate-500/10';

  return (
    <button
      onClick={() => onClick(notification)}
      className={`w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-700/30 ${
        notification.is_read ? 'opacity-60' : ''
      }`}
    >
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${colorClass}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-white truncate">
          {notification.title}
        </p>
        <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">
          {notification.message}
        </p>
        <p className="text-[10px] text-slate-500 mt-1">
          {timeAgo(notification.created_at)}
        </p>
      </div>
      {!notification.is_read && (
        <span className="w-2 h-2 rounded-full bg-cyan-400 shrink-0 mt-1.5" />
      )}
    </button>
  );
}

function resolveBackTarget(pathname: string): string | null {
  // KB detail / engine — state-based detail view, no /knowledge/{id} URL exists
  const kbEngineMatch = pathname.match(/^\/knowledge\/[^/]+\/engine\/?$/);
  if (kbEngineMatch) return '/knowledge';

  // Project ontology → project list (projects page is the natural parent)
  const ontologyMatch = pathname.match(/^\/knowledge\/projects\/[^/]+\/(ontology|members|correlations)\/?$/);
  if (ontologyMatch) return '/knowledge/projects';

  // Project detail → project list
  const projectMatch = pathname.match(/^\/knowledge\/projects\/[^/]+\/?$/);
  if (projectMatch) return '/knowledge/projects';

  // /knowledge/projects → /knowledge
  if (pathname === '/knowledge/projects' || pathname === '/knowledge/projects/') return '/knowledge';

  // Agent builder / detail / chat → /agents
  if (pathname.match(/^\/agents\/[^/]+\/(chat|edit|logs)\/?$/)) return '/agents';
  if (pathname.match(/^\/agents\/[^/]+\/?$/)) return '/agents';

  // Pipeline pages
  if (pathname.match(/^\/pipelines\/[^/]+\/?$/)) return '/pipelines';

  // ML model detail
  if (pathname.match(/^\/ml-models\/[^/]+\/?$/)) return '/ml-models';

  // Code asset detail
  if (pathname.match(/^\/code-runner\/[^/]+\/?$/)) return '/code-runner';

  // Admin sub-pages → dashboard (no /admin parent route)
  if (pathname.match(/^\/admin\/[^/]+\/?$/)) return '/dashboard';

  // Execution detail → executions list
  if (pathname.match(/^\/executions\/[^/]+\/?$/)) return '/executions';

  // Settings deep pages → /dashboard. /settings itself is a redirect
  // page (router.replace('/settings/profile')), so pointing back at
  // /settings would create a loop. Dashboard is the next-up surface.
  if (pathname.match(/^\/settings\/[^/]+\/?$/)) return '/dashboard';

  // Marketplace + ml-models + meetings detail → list parent
  if (pathname.match(/^\/marketplace\/[^/]+\/?$/)) return '/marketplace';
  if (pathname.match(/^\/ml-models\/[^/]+\/?$/)) return '/ml-models';
  if (pathname.match(/^\/meetings\/[^/]+\/?$/)) return '/meetings';

  // Code-runner detail
  if (pathname.match(/^\/code-runner\/[^/]+\/?$/)) return '/code-runner';

  // Fallback: no opinion, let router.back() handle it.
  return null;
}


/**
 * Reads the resolved standalone-app URLs from `/api/use-cases` so URLs
 * are NEVER hardcoded in the client bundle. Each deployment mode gives
 * us a correct href:
 *   • dev / start.sh   → http://localhost:3001|3002|3003
 *   • minikube / AKS   → http(s)://<subdomain>.<cluster-ip>.nip.io
 *   • custom domain    → http(s)://<subdomain>.<your-domain>
 * The API does the resolution based on per-app env vars with a host-
 * derived fallback.
 */
function UseCasesList({ onNavigate }: { onNavigate: () => void }) {
  // useApi already unwraps the ApiResponse envelope, so `data` IS the
  // list. The previous `resp?.data || resp?.rows || []` was a
  // second unwrap on an already-unwrapped array — it always yielded
  // `[]` and the dropdown sat on "Loading use cases…" forever.
  const { data, isLoading, error } = useApi<Array<{ key: string; label: string; description: string; url: string; color: string; icon: string; inline: boolean }>>(
    '/api/use-cases',
  );
  const items = Array.isArray(data) ? data : [];

  // Fallback colors so we don't wait on tailwind JIT for dynamic classes.
  const colorMap: Record<string, { bg: string; text: string; hover: string }> = {
    cyan:    { bg: 'bg-cyan-500/10',    text: 'text-cyan-400',    hover: 'group-hover:text-cyan-400' },
    emerald: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', hover: 'group-hover:text-emerald-400' },
    green:   { bg: 'bg-green-500/10',   text: 'text-green-400',   hover: 'group-hover:text-green-400' },
    indigo:  { bg: 'bg-indigo-500/10',  text: 'text-indigo-400',  hover: 'group-hover:text-indigo-400' },
    purple:  { bg: 'bg-purple-500/10',  text: 'text-purple-400',  hover: 'group-hover:text-purple-400' },
    rose:    { bg: 'bg-rose-500/10',    text: 'text-rose-400',    hover: 'group-hover:text-rose-400' },
  };

  const renderIcon = (icon?: string, color?: string) => {
    const c = colorMap[color || 'cyan']?.text || 'text-cyan-400';
    if (icon === 'globe')       return <Globe className={`w-5 h-5 ${c}`} />;
    if (icon === 'zap')         return <Zap className={`w-5 h-5 ${c}`} />;
    if (icon === 'headphones')  return <Headphones className={`w-5 h-5 ${c}`} />;
    if (icon === 'shield')      return <ShieldCheck className={`w-5 h-5 ${c}`} />;
    if (icon === 'cpu')         return <img src="/oraclenet-logo.svg" alt="" className="w-5 h-5" />;
    if (icon === 'example_app')  return <img src="/example_app-logo.svg" alt="" className="w-5 h-5" />;
    return <Sparkles className={`w-5 h-5 ${c}`} />;
  };

  return (
    <div className="p-2">
      {items.length === 0 ? (
        <div className="p-4 text-xs text-slate-500 text-center">
          {isLoading ? 'Loading use cases…' : error ? `Error: ${error}` : 'No use cases available'}
        </div>
      ) : items.map((item: any) => {
        const color = colorMap[item.color || 'cyan'] || colorMap.cyan;
        return (
          <a
            key={item.key}
            href={item.url}
            target={item.inline ? undefined : '_blank'}
            rel="noopener noreferrer"
            onClick={onNavigate}
            className="flex items-start gap-3 p-3 rounded-lg hover:bg-slate-700/50 transition-colors group"
            data-testid={`use-case-${item.key}`}
          >
            <div className={`w-9 h-9 rounded-lg ${color.bg} flex items-center justify-center shrink-0 mt-0.5`}>
              {renderIcon(item.icon, item.color)}
            </div>
            <div>
              <p className={`text-sm font-medium text-white ${color.hover} transition-colors`}>
                {item.label}{item.inline ? '' : ' ↗'}
              </p>
              <p className="text-[10px] text-slate-500 mt-0.5">{item.description}</p>
            </div>
          </a>
        );
      })}
    </div>
  );
}


export default function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { setMobileOpen } = useSidebar();
  const [showDropdown, setShowDropdown] = useState(false);
  const [useCasesOpen, setUseCasesOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const useCasesRef = useRef<HTMLDivElement>(null);

  const {
    notifications,
    unreadCount,
    panelOpen,
    togglePanel,
    setPanelOpen,
    fetchNotifications,
    fetchUnreadCount,
    markRead,
    markAllRead,
    connect,
    disconnect,
  } = useNotificationStore();

  useEffect(() => {
    if (user?.id) {
      fetchNotifications();
      fetchUnreadCount();
      connect(user.id);
    }
    return () => disconnect();
  }, [user?.id]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setPanelOpen(false);
      }
    }
    if (panelOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [panelOpen, setPanelOpen]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (useCasesRef.current && !useCasesRef.current.contains(e.target as Node)) {
        setUseCasesOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleNotificationClick = (n: Notification) => {
    if (!n.is_read) markRead(n.id);
    if (n.link) {
      setPanelOpen(false);
      router.push(n.link);
    }
  };

  const pageLabel = ROUTE_LABELS[pathname] || 'Dashboard';

  return (
    <header className="h-14 bg-[#111827]/80 backdrop-blur-xl border-b border-slate-800/50 flex items-center justify-between px-3 md:px-6 shrink-0 relative z-50">
      <div className="flex items-center gap-2 text-sm">
        <button
          onClick={() => setMobileOpen(true)}
          className="w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors md:hidden"
        >
          <Menu className="w-5 h-5" />
        </button>
        {/* Back button — only shows on pages other than /dashboard.
            Uses a route-aware parent map (via resolveBackTarget) to avoid
            the two historical bugs:
              1. /knowledge/{id}/engine did `router.push('/knowledge/{id}')`
                 — 404 because there's no such route.
              2. router.back() sometimes took users to an unrelated prior
                 page (e.g. Dashboard → Chat → Engine → back ⇒ Chat, not
                 Knowledge).
            Now every page in the tree has a deterministic logical parent;
            we fall back to router.back() only when we don't know, and to
            /dashboard only when history is empty. */}
        {pathname !== '/dashboard' && (
          <button
            onClick={() => {
              const target = resolveBackTarget(pathname || '');
              if (target) {
                router.push(target);
              } else if (typeof window !== 'undefined' && window.history.length > 1) {
                router.back();
              } else {
                router.push('/dashboard');
              }
            }}
            title="Back"
            aria-label="Back to previous page"
            className="hidden md:flex items-center gap-1 px-2 py-1 text-xs rounded-md text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
            data-testid="topbar-back"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back</span>
          </button>
        )}
        <button
          onClick={() => router.push('/dashboard')}
          title="Go to dashboard"
          className="hidden md:flex items-center hover:text-slate-300 transition-colors"
        >
          <Home className="w-4 h-4 text-slate-500" />
        </button>
        <ChevronRight className="w-3 h-3 text-slate-600 hidden md:block" />
        <span className="text-slate-300">{pageLabel}</span>
      </div>

      {/* Use Cases dropdown */}
      <div ref={useCasesRef} className="relative">
        <button
          onClick={() => setUseCasesOpen(!useCasesOpen)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
            useCasesOpen ? 'bg-cyan-500/10 text-cyan-400' : 'text-slate-400 hover:text-white hover:bg-slate-800/50',
          )}
        >
          <Sparkles className="w-4 h-4" />
          Use Cases
          <ChevronDown className={cn('w-3 h-3 transition-transform', useCasesOpen && 'rotate-180')} />
        </button>

        <AnimatePresence>
          {useCasesOpen && (
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              className="absolute left-0 top-10 w-72 bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-[100]"
            >
              <UseCasesList onNavigate={() => setUseCasesOpen(false)} />

              <div className="border-t border-slate-700/50 p-2">
                <a
                  href="/docs"
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setUseCasesOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-700/30 transition-colors"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  Developer Documentation
                </a>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative" ref={panelRef}>
          <button
            onClick={togglePanel}
            className="relative w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
          >
            <Bell className="w-[18px] h-[18px]" />
            {unreadCount > 0 && (
              <span className="absolute top-1 right-1 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white px-1">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>

          <AnimatePresence>
            {panelOpen && (
              <motion.div
                initial={{ opacity: 0, y: -8, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -8, scale: 0.95 }}
                transition={{ duration: 0.15 }}
                className="absolute right-0 top-11 w-80 bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-[100]"
              >
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
                  <h3 className="text-sm font-semibold text-white">
                    Notifications
                  </h3>
                  {unreadCount > 0 && (
                    <button
                      onClick={markAllRead}
                      className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
                    >
                      <CheckCheck className="w-3 h-3" />
                      Mark all read
                    </button>
                  )}
                </div>

                <div className="max-h-[400px] overflow-y-auto divide-y divide-slate-700/30">
                  {notifications.length === 0 ? (
                    <div className="px-4 py-8 text-center">
                      <Bell className="w-8 h-8 text-slate-600 mx-auto mb-2" />
                      <p className="text-xs text-slate-500">
                        No notifications yet
                      </p>
                    </div>
                  ) : (
                    notifications.slice(0, 20).map((n) => (
                      <NotificationItem
                        key={n.id}
                        notification={n}
                        onRead={markRead}
                        onClick={handleNotificationClick}
                      />
                    ))
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <button className="w-9 h-9 flex items-center justify-center rounded-lg text-slate-500 cursor-default">
          <Moon className="w-[18px] h-[18px]" />
        </button>

        <div className="relative">
          <button
            onClick={() => setShowDropdown(!showDropdown)}
            className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white"
          >
            {user?.full_name?.charAt(0) || 'U'}
          </button>

          <AnimatePresence>
            {showDropdown && (
              <>
                <div
                  className="fixed inset-0 z-[90]"
                  onClick={() => setShowDropdown(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: -8, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -8, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className="absolute right-0 top-11 w-56 bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-[100]"
                >
                  <div className="px-4 py-3 border-b border-slate-700/50">
                    <p className="text-sm font-medium text-white truncate">
                      {user?.full_name}
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {user?.email}
                    </p>
                  </div>
                  <div className="py-1">
                    {[
                      { icon: User, label: 'Profile', href: '/settings/profile' },
                      { icon: Settings, label: 'Settings', href: '/settings' },
                      ...(process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false'
                        ? [{ icon: CreditCard, label: 'Billing', href: '/settings/billing' }]
                        : []),
                    ].map((item) => (
                      <a
                        key={item.label}
                        href={item.href}
                        onClick={() => setShowDropdown(false)}
                        className="flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors"
                      >
                        <item.icon className="w-4 h-4 text-slate-400" />
                        {item.label}
                      </a>
                    ))}
                  </div>
                  <div className="border-t border-slate-700/50 py-1">
                    <button
                      onClick={() => {
                        setShowDropdown(false);
                        logout();
                      }}
                      className="flex items-center gap-3 px-4 py-2 text-sm text-red-400 hover:bg-slate-700/50 transition-colors w-full"
                    >
                      <LogOut className="w-4 h-4" />
                      Logout
                    </button>
                  </div>
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}
