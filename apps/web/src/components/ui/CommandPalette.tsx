'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api-client';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  LayoutDashboard,
  Bot,
  Wrench,
  Store,
  Database,
  BarChart3,
  Zap,
  Sparkles,
  Settings,
  Users,
  CreditCard,
  Key,
  Plus,
  Activity,
  Brain,
  Code2,
  FileText,
  Server,
  Scale,
  ShieldCheck,
  BellRing,
  UserCog,
  Gauge,
  User,
  type LucideIcon,
} from 'lucide-react';
import { holds, useMyPermissions } from '@/lib/capabilities';

interface RemoteResult {
  category: string;
  label: string;
  subtitle?: string;
  href: string;
}

function iconForCategory(c: string): LucideIcon {
  switch (c) {
    case 'Agents':       return Bot;
    case 'Pipelines':    return Wrench;
    case 'Knowledge':    return Database;
    case 'ML Models':    return Brain;
    case 'Code Assets':  return Code2;
    case 'Executions':   return Activity;
    case 'Runs':         return Activity;
    case 'Pages':        return FileText;
    case 'Decisions':    return Scale;
    default:             return Server;
  }
}

interface Command {
  id: string;
  label: string;
  icon: LucideIcon;
  href?: string;
  action?: () => void;
  category: string;
  keywords?: string[];
  shortcut?: string;
  requires?: 'marketplace' | 'monetization';
  capability?: string;
  // the label for someone who can look but not change
  viewLabel?: string;
  feature?: string;
}

const NAVIGATION_COMMANDS: Command[] = [
  {
    id: 'nav-dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    href: '/dashboard',
    category: 'Navigation',
    keywords: ['home', 'overview', 'main'],
  },
  {
    id: 'nav-agents',
    label: 'Agents',
    icon: Bot,
    href: '/agents',
    category: 'Navigation',
    keywords: ['my agents', 'list', 'bots'],
  },
  {
    id: 'nav-inbox',
    label: 'Needs you',
    icon: BellRing,
    href: '/inbox',
    category: 'Navigation',
    keywords: ['inbox', 'waiting', 'todo', 'to do', 'my approvals'],
  },
  {
    id: 'nav-decisions',
    label: 'Decisions',
    icon: Scale,
    href: '/decisions',
    category: 'Navigation',
    keywords: ['rules', 'business rules', 'decision table', 'policy', 'policies', 'excel'],
    capability: 'decisions.view',
  },
  {
    id: 'nav-approvals',
    label: 'Approvals',
    icon: ShieldCheck,
    href: '/approvals',
    category: 'Navigation',
    keywords: ['sign off', 'sign-off', 'approve', 'approver', 'approvers', 'who can approve', 'deny', 'review', 'requests'],
  },
  {
    id: 'nav-builder',
    label: 'Builder',
    icon: Wrench,
    href: '/builder',
    category: 'Navigation',
    keywords: ['create', 'build', 'canvas', 'flow'],
  },
  {
    id: 'nav-marketplace',
    label: 'Marketplace',
    icon: Store,
    href: '/marketplace',
    category: 'Navigation',
    keywords: ['browse', 'shop', 'discover', 'store'],
    requires: 'marketplace',
  },
  {
    id: 'nav-knowledge',
    label: 'Knowledge',
    icon: Database,
    href: '/knowledge',
    category: 'Navigation',
    keywords: ['knowledge base', 'documents', 'rag', 'upload'],
  },
  {
    id: 'nav-analytics',
    label: 'Analytics',
    icon: BarChart3,
    href: '/analytics',
    category: 'Navigation',
    keywords: ['stats', 'metrics', 'charts', 'usage'],
  },
  {
    id: 'nav-mcp',
    label: 'MCP Servers',
    icon: Zap,
    href: '/mcp',
    category: 'Navigation',
    keywords: ['mcp', 'integrations', 'tools', 'servers'],
  },
  {
    id: 'nav-creator',
    label: 'Creator Hub',
    icon: Sparkles,
    href: '/creator',
    category: 'Navigation',
    keywords: ['creator', 'listings', 'installs'],
    requires: 'marketplace',
  },
  {
    id: 'nav-settings',
    label: 'Settings',
    icon: Settings,
    href: '/settings',
    category: 'Navigation',
    keywords: ['preferences', 'config', 'profile'],
  },
  {
    id: 'nav-team',
    label: 'Team',
    icon: Users,
    href: '/settings/team',
    category: 'Settings',
    viewLabel: 'Team (view only)',
    feature: 'manage_team',
    keywords: ['members', 'invite', 'organization', 'people', 'approve', 'approver', 'approvers', 'who can approve', 'can approve decisions', 'sign off', 'reviewers', 'roles'],
  },
  {
    id: 'nav-permissions',
    label: 'Permissions',
    icon: UserCog,
    href: '/admin/permissions',
    category: 'Settings',
    keywords: ['roles', 'access', 'capabilities', 'decision reviewers', 'who can approve'],
    capability: 'permissions.manage',
  },
  {
    id: 'nav-risk',
    label: 'Risk & Controls',
    icon: Gauge,
    href: '/admin/risk',
    category: 'Settings',
    keywords: ['risk tier', 'sign-off', 'approvals needed', 'controls', 'governance'],
    capability: 'risk.view',
  },
  {
    id: 'nav-profile',
    label: 'Profile',
    icon: User,
    href: '/settings/profile',
    category: 'Settings',
    keywords: ['password', 'name', 'account'],
  },
  {
    id: 'nav-billing',
    label: 'Billing',
    icon: CreditCard,
    href: '/settings/billing',
    category: 'Navigation',
    keywords: ['plan', 'subscription', 'payment', 'pricing'],
    requires: 'monetization',
  },
  {
    id: 'nav-api-keys',
    label: 'API Keys',
    icon: Key,
    href: '/settings/api-keys',
    category: 'Navigation',
    keywords: ['api', 'keys', 'tokens', 'access'],
  },
];

const ACTION_COMMANDS: Command[] = [
  {
    id: 'action-new-agent',
    label: 'New Agent',
    icon: Plus,
    href: '/builder',
    category: 'Actions',
    keywords: ['create', 'new', 'build', 'agent'],
    shortcut: '\u2318N',
  },
  {
    id: 'action-browse-marketplace',
    label: 'Browse Marketplace',
    icon: Store,
    href: '/marketplace',
    category: 'Actions',
    keywords: ['browse', 'discover', 'explore', 'shop'],
    requires: 'marketplace',
  },
];

const ALL_COMMANDS: Command[] = [...NAVIGATION_COMMANDS, ...ACTION_COMMANDS];

// pages and settings match by name, category or a plain word for what they do
export function matchCommands(query: string, commands: Command[] = ALL_COMMANDS): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  return commands.filter((cmd) =>
    cmd.label.toLowerCase().includes(q) ||
    cmd.category.toLowerCase().includes(q) ||
    !!cmd.keywords?.some((kw) => kw.toLowerCase().includes(q)),
  );
}

// what this person sees: pages they can't use drop out, Team becomes view only for members
export function commandsFor(perms: { capabilities?: string[]; is_admin?: boolean; features?: Record<string, boolean> } | null | undefined, commands: Command[] = ALL_COMMANDS): Command[] {
  return commands
    .filter((c) => !c.capability || !perms || holds(perms.capabilities, c.capability))
    .map((c) => (c.feature && perms && !perms.is_admin && perms.features?.[c.feature] !== true && c.viewLabel ? { ...c, label: c.viewLabel } : c));
}

// run logs and file dumps make poor results, a label that is mostly symbols is dropped
export function isJunkLabel(label: string): boolean {
  const t = (label || '').replace(/\s+/g, '');
  if (!t) return true;
  if (/(.)\1{5,}/.test(t)) return true;
  const plain = (t.match(/[\p{L}\p{N}]/gu) || []).length;
  return plain / t.length < 0.5;
}

interface DecisionHit { key: string; name: string; description?: string }

// decisions by name, key or description, as palette results
export function decisionResults(rows: DecisionHit[], q: string): RemoteResult[] {
  const needle = q.trim().toLowerCase();
  const words = needle.split(/\s+/).filter(Boolean);
  return rows
    .filter((d) => {
      const hay = `${d.name} ${d.key} ${d.description || ''}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .slice(0, 6)
    .map((d) => ({ category: 'Decisions', label: d.name, subtitle: d.key, href: `/decisions/${encodeURIComponent(d.key)}` }));
}

export const OPEN_PALETTE_EVENT = 'abenix:open-command-palette';

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [remoteResults, setRemoteResults] = useState<RemoteResult[]>([]);
  const { marketplace, monetization } = usePlatformFeatures();
  const { perms } = useMyPermissions();
  const commands = useMemo(
    () => commandsFor(perms, ALL_COMMANDS.filter((c) => !c.requires || (c.requires === 'marketplace' ? marketplace : monetization))),
    [marketplace, monetization, perms],
  );
  const canSeeDecisions = !perms || holds(perms.capabilities, 'decisions.view');

  // Hit /api/search whenever the query stabilises. Local commands still match
  // instantly; remote results stream in for agents/pipelines/KB/ML/etc.
  useEffect(() => {
    const q = query.trim();
    if (!q) { setRemoteResults([]); return; }
    let cancelled = false;
    const handle = setTimeout(async () => {
      const [search, decisions] = await Promise.all([
        apiFetch<{ results: RemoteResult[] }>(`/api/search?q=${encodeURIComponent(q)}&limit=6`, { silent: true }).catch(() => ({ data: null })),
        canSeeDecisions && q.length >= 2
          ? apiFetch<DecisionHit[]>('/api/decisions', { silent: true }).catch(() => ({ data: null }))
          : Promise.resolve({ data: null as DecisionHit[] | null }),
      ]);
      if (cancelled) return;
      // keep server pages the local list lacks, like the admin screens
      const local = new Set(ALL_COMMANDS.map((c) => c.href).filter(Boolean));
      const server = (search.data?.results || []).filter((r) => (r.category !== 'Pages' || !local.has(r.href)) && !isJunkLabel(r.label));
      const mine = decisionResults(decisions.data || [], q);
      const seen = new Set(server.map((r) => r.href));
      setRemoteResults([...mine.filter((r) => !seen.has(r.href)), ...server]);
    }, 180);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [query, canSeeDecisions]);

  const filteredCommands = useMemo(() => {
    if (!query.trim()) return commands;

    const localMatches = matchCommands(query, commands);

    const remoteAsCommands: Command[] = remoteResults.map((r, i) => ({
      id: `remote-${r.category}-${i}-${r.href}`,
      label: r.label,
      icon: iconForCategory(r.category),
      href: r.href,
      category: r.category,
      keywords: r.subtitle ? [r.subtitle] : [],
    }));

    return [...localMatches, ...remoteAsCommands];
  }, [query, remoteResults, commands]);

  const groupedCommands = useMemo(() => {
    const groups: { category: string; commands: Command[] }[] = [];
    const categoryMap = new Map<string, Command[]>();

    for (const cmd of filteredCommands) {
      const existing = categoryMap.get(cmd.category);
      if (existing) {
        existing.push(cmd);
      } else {
        const arr = [cmd];
        categoryMap.set(cmd.category, arr);
        groups.push({ category: cmd.category, commands: arr });
      }
    }

    return groups;
  }, [filteredCommands]);

  const flatCommands = useMemo(
    () => groupedCommands.flatMap((g) => g.commands),
    [groupedCommands],
  );

  const executeCommand = useCallback(
    (cmd: Command) => {
      setOpen(false);
      setQuery('');
      setSelectedIndex(0);

      if (cmd.action) {
        cmd.action();
      } else if (cmd.href) {
        router.push(cmd.href);
      }
    },
    [router],
  );

  const handleOpen = useCallback(() => {
    setOpen(true);
    setQuery('');
    setSelectedIndex(0);
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
    setQuery('');
    setSelectedIndex(0);
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K to open
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (open) {
          handleClose();
        } else {
          handleOpen();
        }
      }

      // Cmd+N / Ctrl+N for new agent
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        router.push('/builder');
      }

      // Escape to close
      if (e.key === 'Escape' && open) {
        handleClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    // the search button in the top bar opens it too
    const openFromButton = () => handleOpen();
    window.addEventListener(OPEN_PALETTE_EVENT, openFromButton);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener(OPEN_PALETTE_EVENT, openFromButton);
    };
  }, [open, handleOpen, handleClose, router]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
      // Small delay to allow animation to start
      const timer = setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.querySelector(
      '[data-selected="true"]',
    );
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  // Keyboard navigation within the palette
  const handleInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev < flatCommands.length - 1 ? prev + 1 : 0,
      );
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev > 0 ? prev - 1 : flatCommands.length - 1,
      );
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (flatCommands[selectedIndex]) {
        executeCommand(flatCommands[selectedIndex]);
      }
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[60] flex justify-center" role="dialog" aria-modal="true" aria-label="Search" data-testid="command-palette">
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={handleClose}
          />

          {/* Dialog */}
          <motion.div
            className="relative top-[20%] mx-4 h-fit w-full max-w-lg overflow-hidden rounded-2xl border border-slate-700/50 bg-slate-800/95 shadow-2xl backdrop-blur-xl"
            initial={{ opacity: 0, scale: 0.95, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
          >
            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-slate-700/50 px-4 py-3">
              <Search size={18} className="shrink-0 text-slate-400" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleInputKeyDown}
                aria-label="Search pages, agents, runs and more"
                data-testid="command-palette-input"
                placeholder="Search pages, agents, pipelines, knowledge, models, runs..."
                className="flex-1 bg-transparent text-sm text-white placeholder-slate-500 outline-none"
              />
              <kbd className="hidden rounded-md border border-slate-600 bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-400 sm:inline-block">
                ESC
              </kbd>
            </div>

            {/* Results */}
            <div
              ref={listRef}
              className="max-h-[320px] overflow-y-auto py-2"
            >
              {flatCommands.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-slate-400" data-testid="command-palette-empty">
                  <p>Nothing found for &ldquo;{query}&rdquo;.</p>
                  <div className="mt-3 flex flex-wrap justify-center gap-2">
                    <button type="button" onClick={() => executeCommand({ id: 'docs-q', label: 'docs', icon: FileText, category: 'Help', href: `/docs?q=${encodeURIComponent(query.trim())}` })} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-cyan-200 hover:bg-slate-700/40" data-testid="command-palette-search-docs">
                      Search the docs for &ldquo;{query.trim()}&rdquo;
                    </button>
                    <button type="button" onClick={() => executeCommand({ id: 'help', label: 'help', icon: FileText, category: 'Help', href: '/help' })} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700/40" data-testid="command-palette-help">
                      Open Help
                    </button>
                  </div>
                </div>
              )}

              {groupedCommands.map((group) => {
                return (
                  <div key={group.category}>
                    {/* Category header */}
                    <div className="px-4 py-2 text-xs font-medium uppercase tracking-wider text-slate-500">
                      {group.category}
                    </div>

                    {/* Commands */}
                    {group.commands.map((cmd) => {
                      const globalIndex = flatCommands.indexOf(cmd);
                      const isSelected = globalIndex === selectedIndex;
                      const CmdIcon = cmd.icon;

                      return (
                        <button
                          key={cmd.id}
                          data-selected={isSelected}
                          data-testid="command-palette-item"
                          data-category={cmd.category}
                          data-href={cmd.href || ''}
                          onClick={() => executeCommand(cmd)}
                          onMouseEnter={() =>
                            setSelectedIndex(globalIndex)
                          }
                          className={`mx-2 flex w-[calc(100%-16px)] items-center gap-3 rounded-lg px-4 py-2.5 text-left transition-colors ${
                            isSelected
                              ? 'bg-slate-700/30'
                              : 'hover:bg-slate-700/30'
                          }`}
                        >
                          <CmdIcon
                            size={20}
                            className={
                              isSelected
                                ? 'shrink-0 text-cyan-400'
                                : 'shrink-0 text-slate-400'
                            }
                          />
                          <span
                            className={`flex-1 text-sm ${
                              isSelected
                                ? 'text-white'
                                : 'text-slate-300'
                            }`}
                          >
                            {cmd.label}
                          </span>
                          {cmd.shortcut && (
                            <kbd className="rounded-md border border-slate-600 bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-400">
                              {cmd.shortcut}
                            </kbd>
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            {/* Footer */}
            <div className="flex items-center gap-4 border-t border-slate-700/50 px-4 py-2">
              <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
                <kbd className="rounded border border-slate-600 bg-slate-700/50 px-1 py-0.5 text-[10px] leading-none">
                  &uarr;
                </kbd>
                <kbd className="rounded border border-slate-600 bg-slate-700/50 px-1 py-0.5 text-[10px] leading-none">
                  &darr;
                </kbd>
                navigate
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
                <kbd className="rounded border border-slate-600 bg-slate-700/50 px-1 py-0.5 text-[10px] leading-none">
                  &crarr;
                </kbd>
                select
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
                <kbd className="rounded border border-slate-600 bg-slate-700/50 px-1 py-0.5 text-[10px] leading-none">
                  esc
                </kbd>
                close
              </span>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
