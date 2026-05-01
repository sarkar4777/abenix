'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
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
  type LucideIcon,
} from 'lucide-react';

interface Command {
  id: string;
  label: string;
  icon: LucideIcon;
  href?: string;
  action?: () => void;
  category: string;
  keywords?: string[];
  shortcut?: string;
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
    id: 'nav-builder',
    label: 'Builder',
    icon: Wrench,
    href: '/builder',
    category: 'Navigation',
    keywords: ['create', 'build', 'canvas', 'flow'],
  },
  ...(process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false'
    ? [{
        id: 'nav-marketplace',
        label: 'Marketplace',
        icon: Store,
        href: '/marketplace',
        category: 'Navigation',
        keywords: ['browse', 'shop', 'discover', 'store'],
      }]
    : []),
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
    keywords: ['creator', 'earnings', 'revenue', 'payouts'],
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
    href: '/team',
    category: 'Navigation',
    keywords: ['members', 'invite', 'organization'],
  },
  ...(process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false'
    ? [{
        id: 'nav-billing',
        label: 'Billing',
        icon: CreditCard,
        href: '/settings/billing',
        category: 'Navigation',
        keywords: ['plan', 'subscription', 'payment', 'pricing'],
      }]
    : []),
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
  ...(process.env.NEXT_PUBLIC_ENABLE_MONETIZATION !== 'false'
    ? [{
        id: 'action-browse-marketplace',
        label: 'Browse Marketplace',
        icon: Store,
        href: '/marketplace',
        category: 'Actions',
        keywords: ['browse', 'discover', 'explore', 'shop'],
      }]
    : []),
];

const ALL_COMMANDS: Command[] = [...NAVIGATION_COMMANDS, ...ACTION_COMMANDS];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filteredCommands = useMemo(() => {
    if (!query.trim()) return ALL_COMMANDS;

    const lowerQuery = query.toLowerCase();
    return ALL_COMMANDS.filter((cmd) => {
      if (cmd.label.toLowerCase().includes(lowerQuery)) return true;
      if (cmd.category.toLowerCase().includes(lowerQuery)) return true;
      if (
        cmd.keywords?.some((kw) => kw.toLowerCase().includes(lowerQuery))
      ) {
        return true;
      }
      return false;
    });
  }, [query]);

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
    return () => document.removeEventListener('keydown', handleKeyDown);
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
        <div className="fixed inset-0 z-[60] flex justify-center">
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
                placeholder="Search commands..."
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
                <div className="px-4 py-8 text-center text-sm text-slate-500">
                  No commands found for &ldquo;{query}&rdquo;
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
