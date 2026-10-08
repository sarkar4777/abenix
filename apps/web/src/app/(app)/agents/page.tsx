'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { usePageTitle } from '@/hooks/usePageTitle';
import {
  BarChart3,
  Bot,
  Calendar,
  Cloud,
  Code,
  FileText,
  GraduationCap,
  Info,
  Mail,
  MessageSquare,
  Pencil,
  Plus,
  Scale,
  Search,
  Trash2,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { SkeletonAgentCard } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';
import DeleteWithDependents from '@/components/ui/DeleteWithDependents';
import DeletedAgents from '@/components/agent/DeletedAgents';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';
import { toastError, toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface Agent {
  id: string;
  name: string;
  slug: string;
  description: string;
  agent_type: string;
  status: string;
  version: string;
  icon_url: string | null;
  category: string | null;
  creator_id?: string;
  is_published?: boolean;
  model_config: {
    model: string;
    temperature: number;
    tools: string[];
  } | null;
}

const iconMap: Record<string, LucideIcon> = {
  FileText,
  GraduationCap,
  Code,
  Mail,
  BarChart3,
  Calendar,
  Cloud,
  Scale,
  Bot,
};

const categoryColors: Record<string, { bg: string; text: string }> = {
  productivity: { bg: 'bg-cyan-500/10', text: 'text-cyan-400' },
  research: { bg: 'bg-violet-500/10', text: 'text-violet-400' },
  engineering: { bg: 'bg-emerald-500/10', text: 'text-emerald-400' },
  communication: { bg: 'bg-amber-500/10', text: 'text-amber-400' },
  analytics: { bg: 'bg-blue-500/10', text: 'text-blue-400' },
  legal: { bg: 'bg-rose-500/10', text: 'text-rose-400' },
};

const statusStyles: Record<string, string> = {
  active: 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/20',
  paused: 'text-amber-400 bg-amber-500/10 border border-amber-500/20',
  draft: 'text-slate-400 bg-slate-500/10 border border-slate-500/20',
  archived: 'text-red-400 bg-red-500/10 border border-red-500/20',
};

type Tab = 'my' | 'all' | 'prebuilt' | 'marketplace';
const TABS: Tab[] = ['my', 'all', 'prebuilt', 'marketplace'];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

const item = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3 } },
};

export default function AgentsPage() {
  usePageTitle('My Agents');
  const { marketplace: marketplaceOn } = usePlatformFeatures();
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<Tab>('my');
  // ?tab=all from the dashboard card opens the matching list
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab') as Tab | null;
    if (t && TABS.includes(t)) setTab(t);
  }, []);
  const [category, setCategory] = useState('');
  const [sortBy, setSortBy] = useState('newest');
  const [viewMode, setViewMode] = useState<'grid' | 'grouped'>('grouped');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const LIMIT = 20;

  // Push the tab filter to the API so pagination aligns with what's
  // rendered. Without this, the first page of "prebuilt" was all custom
  // agents (sorted newest-first) which the client-side filter removed
  // → empty list despite "94 agents available" in the footer.
  const typeParam = tab === 'prebuilt' ? '&scope=prebuilt' : tab === 'my' ? '&scope=mine' : tab === 'marketplace' ? '&published=true' : '';
  const apiUrl = `/api/agents?search=${encodeURIComponent(search)}&category=${encodeURIComponent(category)}&sort=${sortBy}&limit=${LIMIT}&offset=${page * LIMIT}${typeParam}`;
  const { data: agents, isLoading: loading, meta, mutate } = useApi<Agent[]>(apiUrl);

  // Used to bucket the "My Agents" tab count against the active session.
  const { data: perms } = useApi<{ user_id: string; is_admin?: boolean }>('/api/me/permissions');
  const currentUserId = perms?.user_id ?? null;
  const [deleting, setDeleting] = useState<Agent | null>(null);
  const canDelete = (a: Agent) => a.agent_type !== 'oob' && (!!perms?.is_admin || (!!currentUserId && a.creator_id === currentUserId));

  // Fan out one unbounded list-fetch so each tab can carry its own count
  // independent of the paginated visible slice. Without this the header
  // showed the global total ("162 agents available") while the My Agents
  // tab rendered a single card — clients clicked thinking it was broken.
  const [tabCounts, setTabCounts] = useState<Record<Tab, number>>({ my: 0, all: 0, prebuilt: 0, marketplace: 0 });
  const [categories, setCategories] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { agents: all } = await fetchAllAgents<Agent>();
      if (cancelled) return;
      const myCount = currentUserId
        ? all.filter((a) => a.creator_id === currentUserId).length
        : 0;
      const prebuiltCount = all.filter((a) => a.agent_type === 'oob').length;
      const marketplaceCount = all.filter((a) => a.is_published === true).length;
      setTabCounts({ my: myCount, all: all.length, prebuilt: prebuiltCount, marketplace: marketplaceCount });
      setCategories(Array.from(new Set(all.map((a) => a.category).filter((c): c is string => !!c))).sort());
    })();
    return () => { cancelled = true; };
  }, [currentUserId, agents]);

  const filtered = agents ?? [];

  // Header now reflects the active tab, not the global total.
  const total = tabCounts[tab];
  // Paginator still needs the server's authoritative count for the
  // current tab — meta.total is already scope-aware via typeParam above.
  const paginationTotal = (meta?.total as number) || filtered.length;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'my', label: 'My Agents' },
    { key: 'all', label: 'All' },
    { key: 'prebuilt', label: 'Pre-Built' },
    ...(marketplaceOn ? [{ key: 'marketplace' as Tab, label: 'Marketplace' }] : []),
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      <PageHeader
        title="Agents"
        icon={Bot}
        purpose="Find, chat with and edit the agents you can use, your own and the built-in ones. For everyone who runs or builds agents."
        meta={
          <span className="rounded-full border border-slate-700/50 bg-slate-800/50 px-2 py-0.5 text-xs text-slate-400">
            {total} agent{total !== 1 ? 's' : ''} available
          </span>
        }
        primaryAction={{ label: 'New Agent', href: '/builder', icon: Plus }}
        steps={[
          'Pick a tab to see your own agents, all agents or the built-in ones.',
          'Open Chat to talk to an agent, or Docs to see how to call it from your code.',
          'Use Edit to change its instructions, tools or knowledge in the builder.',
          'Deleted agents stay in Recently deleted at the bottom so you can bring them back.',
        ]}
        docSlug="08-howto/02-add-an-agent"
        storageKey="agents"
      />

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex bg-slate-800/50 rounded-lg p-1 border border-slate-700/50 overflow-x-auto">
          {tabs.map((t) => (
            <button
              key={t.key}
              data-testid={`agents-tab-${t.key}`}
              aria-pressed={tab === t.key}
              onClick={() => { setTab(t.key); setPage(0); }}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                tab === t.key
                  ? 'bg-cyan-500/10 text-cyan-400 font-medium'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {t.label} ({tabCounts[t.key]})
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0 md:max-w-2xl">
          <div className="relative basis-full sm:basis-auto flex-1 min-w-0 sm:min-w-[12rem]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="Search agents..."
              aria-label="Search agents"
              className="w-full pl-10 pr-4 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
          </div>
          <select
            aria-label="Filter by category"
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(0); }}
            className="min-w-0 flex-1 sm:flex-none bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
          >
            <option value="">All Categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
            ))}
          </select>
          <select
            aria-label="Sort agents"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="min-w-0 flex-1 sm:flex-none bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="name">Name A-Z</option>
          </select>
          <div className="flex shrink-0 items-center bg-slate-800/50 rounded-lg border border-slate-700 p-0.5">
            <button onClick={() => setViewMode('grid')} className={`px-2 py-1 rounded text-xs transition-colors ${viewMode === 'grid' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>Grid</button>
            <button onClick={() => setViewMode('grouped')} className={`px-2 py-1 rounded text-xs transition-colors ${viewMode === 'grouped' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>Grouped</button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonAgentCard key={i} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Bot}
          title={search || category ? 'No agents match' : tab === 'my' ? 'No custom agents yet' : tab === 'marketplace' ? 'Nothing listed in the marketplace yet' : 'No agents found'}
          description={search || category ? 'Try another search or clear the category filter.' : tab === 'my' ? 'Create your first agent to get started.' : tab === 'marketplace' ? 'Publish an agent with marketplace visibility from the builder to list it here.' : 'Try adjusting your search or filters.'}
          actionLabel={!search && !category && tab === 'my' ? 'Create Agent' : undefined}
          actionHref={!search && !category && tab === 'my' ? '/builder' : undefined}
        />
      ) : viewMode === 'grouped' && !category ? (
        <div className="space-y-4">
          {(() => {
            const groups: Record<string, typeof filtered> = {};
            filtered.forEach(a => {
              const cat = a.category || 'uncategorized';
              if (!groups[cat]) groups[cat] = [];
              groups[cat].push(a);
            });
            return Object.entries(groups).sort(([a], [b]) => a === 'uncategorized' ? 1 : b === 'uncategorized' ? -1 : a.localeCompare(b)).map(([cat, catAgents]) => (
              <div key={cat} className="bg-slate-800/10 rounded-xl border border-slate-800/30 overflow-hidden">
                <button
                  onClick={() => setCollapsedGroups(prev => { const n = new Set(prev); n.has(cat) ? n.delete(cat) : n.add(cat); return n; })}
                  className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/30 transition-colors"
                >
                  <span className="text-sm font-medium text-white capitalize">{cat}</span>
                  <span className="text-xs text-slate-500">{catAgents.length} agent{catAgents.length !== 1 ? 's' : ''}</span>
                </button>
                {!collapsedGroups.has(cat) && (
                  <motion.div variants={container} initial="hidden" animate="show" className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4 pt-0">
                    {catAgents.map((agent) => {
                      const GroupedIconComp = (agent.icon_url && iconMap[agent.icon_url]) || Bot;
                      return (
                      <motion.div key={agent.id} variants={item} className="relative bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-all group">
                        {canDelete(agent) && (
                          <button
                            onClick={(e) => { e.stopPropagation(); setDeleting(agent); }}
                            data-testid={`agent-delete-${agent.id}`}
                            className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 p-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
                            aria-label={`Delete ${agent.name}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                        {/* /agents/[id] has no index page — only /info, /chat, /memories. */}
                        <a href={`/agents/${agent.id}/info`} className="block">
                          <div className="flex items-start gap-3 mb-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-cyan-500/10 flex items-center justify-center text-lg shrink-0"><GroupedIconComp className="w-5 h-5 text-cyan-300" /></div>
                            <div className="min-w-0"><p className="text-sm font-semibold text-white truncate">{agent.name}</p><p className="text-[10px] text-slate-500">{agent.agent_type} · v{agent.version || '1.0'}</p></div>
                          </div>
                          <p className="text-xs text-slate-400 line-clamp-2 mb-3">{agent.description}</p>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[10px] px-2 py-0.5 rounded-full ${(categoryColors[agent.category || ''] || { bg: 'bg-slate-800/50', text: 'text-slate-400' }).bg} ${(categoryColors[agent.category || ''] || { bg: '', text: 'text-slate-400' }).text}`}>{agent.category || 'uncategorized'}</span>
                            {agent.agent_type === 'oob' && <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">built-in</span>}
                          </div>
                        </a>
                      </motion.div>
                      );
                    })}
                  </motion.div>
                )}
              </div>
            ));
          })()}
        </div>
      ) : (
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {filtered.map((agent) => (
            <motion.div
              key={agent.id}
              variants={item}
              className="relative bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-all group"
            >
              {canDelete(agent) && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleting(agent);
                  }}
                  data-testid={`agent-delete-${agent.id}`}
                  className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 p-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
                  aria-label="Delete agent"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
              <div className="flex items-start justify-between mb-3">
                {(() => {
                  const IconComp = (agent.icon_url && iconMap[agent.icon_url]) || Bot;
                  const colors = categoryColors[agent.category || ''] || categoryColors.productivity;
                  return (
                    <div className={`w-10 h-10 rounded-lg ${colors.bg} flex items-center justify-center`}>
                      <IconComp className={`w-5 h-5 ${colors.text}`} />
                    </div>
                  );
                })()}
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    statusStyles[agent.status] || statusStyles.draft
                  }`}
                >
                  {agent.status}
                </span>
              </div>

              <h3 className="text-sm font-semibold text-white mb-1 group-hover:text-cyan-400 transition-colors">
                {agent.name}
              </h3>
              <p className="text-xs text-slate-500 line-clamp-2 mb-3">
                {agent.description}
              </p>

              <div className="flex items-center gap-2 flex-wrap mb-4">
                {agent.category && (
                  <span className="text-[10px] text-slate-400 bg-slate-800/50 border border-slate-700/30 px-1.5 py-0.5 rounded capitalize">
                    {agent.category}
                  </span>
                )}
                {(agent.model_config as Record<string, unknown>)?.mode === 'pipeline' && (
                  <span className="text-[10px] text-purple-400 bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 rounded">
                    Pipeline
                  </span>
                )}
                {agent.model_config?.model && (
                  <span className="text-[10px] font-mono text-slate-400 bg-slate-800/50 border border-slate-700/30 px-1.5 py-0.5 rounded">
                    {agent.model_config.model.replace(/-\d{8}$/, '')}
                  </span>
                )}
                {agent.model_config?.tools && (
                  <span className="flex items-center gap-1 text-[10px] text-slate-400 bg-slate-800/50 border border-slate-700/30 px-1.5 py-0.5 rounded">
                    <Wrench className="w-2.5 h-2.5" />
                    {agent.model_config.tools.length}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2 pt-3 border-t border-slate-700/30">
                <Link
                  href={`/agents/${agent.id}/chat`}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-xs font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Chat
                </Link>
                <Link
                  href={`/agents/${agent.id}/info`}
                  className="flex items-center justify-center gap-1.5 px-3 py-2 bg-transparent border border-slate-600 text-slate-400 text-xs rounded-lg hover:text-white hover:bg-slate-800 transition-colors"
                  title="API docs, triggers, and integration guide"
                >
                  <Info className="w-3.5 h-3.5" />
                  Docs
                </Link>
                <Link
                  href={`/builder?agent=${agent.id}`}
                  className="flex items-center justify-center gap-1.5 px-3 py-2 bg-transparent border border-slate-600 text-slate-400 text-xs rounded-lg hover:text-white hover:bg-slate-800 transition-colors"
                >
                  <Pencil className="w-3.5 h-3.5" />
                  Edit
                </Link>
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* Pagination */}
      {paginationTotal > LIMIT && (
        <div className="flex items-center justify-between mt-6">
          <p className="text-xs text-slate-500">
            Showing {page * LIMIT + 1}&ndash;{Math.min((page + 1) * LIMIT, paginationTotal)} of {paginationTotal} agents
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={(page + 1) * LIMIT >= paginationTotal}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
      <DeleteWithDependents
        open={!!deleting}
        onClose={() => setDeleting(null)}
        resource={`/api/agents/${deleting?.id}`}
        name={deleting?.name || ''}
        what="agent"
        note="Its run history stays. You can restore it from Recently deleted at the bottom of this page."
        onConfirm={async (force) => {
          if (!deleting) return;
          try {
            await apiFetch(`/api/agents/${deleting.id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
            toastSuccess(`${deleting.name} deleted`, 'Restore it from Recently deleted below.');
            mutate();
          } catch (e: any) {
            toastError('Delete failed', e?.message || 'Unknown error');
          }
        }}
      />
      <DeletedAgents refreshKey={agents} onRestored={() => mutate()} />
    </motion.div>
  );
}
