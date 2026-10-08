'use client';

import { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  BarChart3,
  Bot,
  Calendar,
  Cloud,
  Code,
  FileText,
  GraduationCap,
  Mail,
  Scale,
  Search,
  Star,
  Store,
  Users,
  ChevronDown,
  Wrench,
  Plus,
  RefreshCw,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import MarketplaceOffNotice from '@/components/marketplace/MarketplaceOffNotice';
import { usePageTitle } from '@/hooks/usePageTitle';
import { SkeletonAgentCard } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';
import { usePlatformFeatures, plainError } from '@/hooks/usePlatformFeatures';
import { useMyPermissions } from '@/lib/capabilities';
import PageHeader from '@/components/layout/PageHeader';

interface MarketplaceAgent {
  id: string;
  name: string;
  slug: string;
  description: string;
  agent_type: string;
  category: string | null;
  icon_url: string | null;
  version: string;
  model_config: Record<string, unknown> | null;
  marketplace_price: number;
  is_free: boolean;
  creator_name: string | null;
  avg_rating: number;
  review_count: number;
  subscriber_count: number;
  created_at: string | null;
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
  Store,
};

const categoryColors: Record<string, { bg: string; text: string; border: string }> = {
  productivity: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/20' },
  research: { bg: 'bg-violet-500/10', text: 'text-violet-400', border: 'border-violet-500/20' },
  engineering: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20' },
  communication: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' },
  analytics: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/20' },
  legal: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/20' },
};

const CATEGORIES = [
  { key: '', label: 'All' },
  { key: 'productivity', label: 'Productivity' },
  { key: 'research', label: 'Research' },
  { key: 'engineering', label: 'Engineering' },
  { key: 'communication', label: 'Communication' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'legal', label: 'Legal' },
];

const SORT_OPTIONS = [
  { key: 'popular', label: 'Most Popular' },
  { key: 'newest', label: 'Newest' },
  { key: 'top_rated', label: 'Top Rated' },
  { key: 'price_low', label: 'Price: Low to High' },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
};

const item = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3 } },
};

function StarRating({ rating, size = 'sm' }: { rating: number; size?: 'sm' | 'md' }) {
  const stars = [];
  const cls = size === 'sm' ? 'w-3 h-3' : 'w-4 h-4';
  for (let i = 1; i <= 5; i++) {
    if (i <= Math.floor(rating)) {
      stars.push(<Star key={i} className={`${cls} text-amber-400 fill-amber-400`} />);
    } else if (i - rating < 1 && i - rating > 0) {
      stars.push(
        <span key={i} className="relative inline-flex">
          <Star className={`${cls} text-slate-600`} />
          <span className="absolute inset-0 overflow-hidden" style={{ width: `${(rating % 1) * 100}%` }}>
            <Star className={`${cls} text-amber-400 fill-amber-400`} />
          </span>
        </span>
      );
    } else {
      stars.push(<Star key={i} className={`${cls} text-slate-600`} />);
    }
  }
  return <span className="inline-flex items-center gap-0.5">{stars}</span>;
}

export default function MarketplacePage() {
  usePageTitle('Marketplace');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [category, setCategory] = useState('');
  const [sort, setSort] = useState('popular');
  const [page, setPage] = useState(1);
  const [sortOpen, setSortOpen] = useState(false);
  const perPage = 24;
  const switches = usePlatformFeatures();
  const { perms } = useMyPermissions();
  const canList = !!perms?.features?.publish_to_marketplace;
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    debounceRef.current = setTimeout(
      () => setDebouncedSearch(search),
      search ? 300 : 0,
    );
    return () => clearTimeout(debounceRef.current);
  }, [search]);

  const params = new URLSearchParams();
  if (debouncedSearch) params.set('search', debouncedSearch);
  if (category) params.set('category', category);
  params.set('sort', sort);
  params.set('page', String(page));
  params.set('per_page', String(perPage));

  const { data: agents, meta, isLoading: storeLoading, error: loadError, mutate } =
    useApi<MarketplaceAgent[]>(
      switches.marketplace ? `/api/marketplace?${params.toString()}` : null,
      { keepPreviousData: true },
    );
  const loading = !switches.loaded || storeLoading;
  const paid = switches.monetization;
  const sortOptions = SORT_OPTIONS.filter((o) => paid || o.key !== 'price_low');

  const total = (meta?.total as number) ?? 0;

  const totalPages = Math.ceil(total / perPage);
  const sortLabel = sortOptions.find((s) => s.key === sort)?.label ?? 'Sort';

  if (switches.loaded && !switches.marketplace) {
    return (
      <div className="space-y-6 max-w-[1400px]" data-testid="marketplace-page-off">
        <PageHeader
          title="Agent Marketplace"
          icon={Store}
          purpose="Agents built by people on this platform and checked by an admin. Install one and run it like your own."
          storageKey="marketplace"
        />
        <MarketplaceOffNotice what="Nothing can be browsed, listed or installed while it is off." />
        <EmptyState
          icon={Store}
          title="The marketplace is off"
          description="Your own agents and the built-in ones are still on My Agents."
          actionLabel="Go to My Agents"
          actionHref="/agents"
        />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      <PageHeader
        title="Agent Marketplace"
        icon={Store}
        purpose={`Agents built by people on this platform and checked by an admin. Install one and run it like your own. ${paid ? 'Some listings are paid.' : 'Every listing is free.'}`}
        primaryAction={
          canList
            ? { label: 'List your agent', href: '/creator', icon: Plus, testId: 'marketplace-list-agent' }
            : { label: 'Go to My Agents', href: '/agents', icon: Bot }
        }
        steps={[
          'Search or pick a category to find an agent.',
          'Open a card to read what it does, its tools and its reviews.',
          'Install it. It then shows in My Agents and runs like one you built.',
        ]}
        docSlug="08-howto/14-marketplace-and-monetization"
        storageKey="marketplace"
      />

      <div className="relative w-full max-w-xl">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search agents by name or description..."
          aria-label="Search the marketplace"
          data-testid="marketplace-search"
          className="w-full pl-12 pr-4 py-3 bg-slate-800/60 border border-slate-700/50 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 transition-all"
        />
      </div>

      {/* Filters Row */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2 overflow-x-auto flex-nowrap pb-1">
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              onClick={() => {
                setCategory(c.key);
                setPage(1);
              }}
              className={`px-3 py-2 md:py-1.5 text-xs font-medium rounded-full border transition-all whitespace-nowrap ${
                category === c.key
                  ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30'
                  : 'bg-slate-800/40 text-slate-400 border-slate-700/50 hover:text-white hover:border-slate-600/50'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        <div className="relative">
          <button
            onClick={() => setSortOpen(!sortOpen)}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-slate-400 bg-slate-800/40 border border-slate-700/50 rounded-lg hover:text-white transition-colors"
          >
            {sortLabel}
            <ChevronDown className="w-3 h-3" />
          </button>
          {sortOpen && (
            <div className="absolute right-0 mt-1 w-44 bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl shadow-black/30 z-30 py-1">
              {sortOptions.map((s) => (
                <button
                  key={s.key}
                  onClick={() => {
                    setSort(s.key);
                    setSortOpen(false);
                    setPage(1);
                  }}
                  className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                    sort === s.key
                      ? 'text-cyan-400 bg-cyan-500/5'
                      : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Results count */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {total} agent{total !== 1 ? 's' : ''} found
        </p>
      </div>

      {loadError && !loading && (
        <div role="alert" data-testid="marketplace-error" className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-300">
          <span>Could not load the store. {plainError(loadError)}</span>
          <button onClick={() => mutate()} className="inline-flex items-center gap-1.5 text-cyan-400 hover:underline">
            <RefreshCw className="w-3.5 h-3.5" /> Try again
          </button>
        </div>
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonAgentCard key={i} />
          ))}
        </div>
      ) : (agents ?? []).length === 0 ? (
        <EmptyState
          icon={Store}
          title={search || category ? 'No agents found' : 'Nothing listed yet'}
          description={
            search || category
              ? 'No agents match your search. Try another word or clear the category.'
              : canList
                ? 'Be the first. List one of your agents for free from Creator Hub.'
                : 'Agents show here once someone lists one and an admin approves it.'
          }
          actionLabel={search || category || !canList ? undefined : 'List an agent'}
          actionHref={search || category || !canList ? undefined : '/creator'}
        />
      ) : (
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {(agents ?? []).map((agent) => {
            const IconComp = (agent.icon_url && iconMap[agent.icon_url]) || Bot;
            const colors = categoryColors[agent.category || ''] || {
              bg: 'bg-purple-500/10',
              text: 'text-purple-400',
              border: 'border-purple-500/20',
            };
            const tools = (agent.model_config as Record<string, unknown>)?.tools as string[] | undefined;

            return (
              <motion.div key={agent.id} variants={item}>
                <Link
                  href={`/marketplace/${agent.id}`}
                  data-testid="market-card"
                  className="block bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 hover:bg-slate-800/40 transition-all group"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className={`w-10 h-10 rounded-lg ${colors.bg} flex items-center justify-center`}>
                      <IconComp className={`w-5 h-5 ${colors.text}`} />
                    </div>
                    {agent.is_free || !paid ? (
                      <span className="text-[10px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                        Free
                      </span>
                    ) : (
                      <span className="text-[10px] font-medium text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded-full">
                        ${agent.marketplace_price}/mo
                      </span>
                    )}
                  </div>

                  <h3 className="text-sm font-semibold text-white mb-0.5 group-hover:text-cyan-400 transition-colors">
                    {agent.name}
                  </h3>
                  <p className="text-[11px] text-slate-500 mb-2">
                    by {agent.creator_name || 'Unknown'}
                  </p>
                  <p className="text-xs text-slate-400 line-clamp-2 mb-3 leading-relaxed">
                    {agent.description}
                  </p>

                  <div className="flex items-center gap-2 flex-wrap mb-3">
                    {agent.category && (
                      <span className={`text-[10px] ${colors.text} ${colors.bg} border ${colors.border} px-1.5 py-0.5 rounded capitalize`}>
                        {agent.category}
                      </span>
                    )}
                    {agent.model_config?.mode === 'pipeline' ? (
                      <span className="text-[10px] text-teal-400 bg-teal-500/10 border border-teal-500/20 px-1.5 py-0.5 rounded">
                        Pipeline
                      </span>
                    ) : (
                      <span className="text-[10px] text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-1.5 py-0.5 rounded">
                        Agent
                      </span>
                    )}
                    {tools && tools.length > 0 && (
                      <span className="flex items-center gap-1 text-[10px] text-slate-400 bg-slate-800/50 border border-slate-700/30 px-1.5 py-0.5 rounded">
                        <Wrench className="w-2.5 h-2.5" />
                        {tools.length} tool{tools.length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>

                  <div className="pt-3 border-t border-slate-700/30 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <StarRating rating={agent.avg_rating} />
                      <span className="text-[11px] text-slate-500">
                        {agent.avg_rating > 0 ? agent.avg_rating.toFixed(1) : ''}
                        {agent.review_count > 0 && ` (${agent.review_count})`}
                      </span>
                    </div>
                    <span className="flex items-center gap-1 text-[11px] text-slate-500" title={paid ? 'Subscribers' : 'Installs'}>
                      <Users className="w-3 h-3" />
                      {agent.subscriber_count}
                    </span>
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </motion.div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/40 border border-slate-700/50 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
            let pageNum: number;
            if (totalPages <= 5) {
              pageNum = i + 1;
            } else if (page <= 3) {
              pageNum = i + 1;
            } else if (page >= totalPages - 2) {
              pageNum = totalPages - 4 + i;
            } else {
              pageNum = page - 2 + i;
            }
            return (
              <button
                key={pageNum}
                onClick={() => setPage(pageNum)}
                className={`w-8 h-8 text-xs rounded-lg border transition-colors ${
                  page === pageNum
                    ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30'
                    : 'text-slate-400 bg-slate-800/40 border-slate-700/50 hover:text-white'
                }`}
              >
                {pageNum}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/40 border border-slate-700/50 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </motion.div>
  );
}
