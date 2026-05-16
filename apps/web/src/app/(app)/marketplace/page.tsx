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
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { SkeletonAgentCard } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';

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

  const { data: agents, meta, isLoading: loading } =
    useApi<MarketplaceAgent[]>(
      `/api/marketplace?${params.toString()}`,
      { keepPreviousData: true },
    );

  const total = (meta?.total as number) ?? 0;

  const totalPages = Math.ceil(total / perPage);
  const sortLabel = SORT_OPTIONS.find((s) => s.key === sort)?.label ?? 'Sort';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      {/* Hero */}
      <div className="relative rounded-2xl overflow-hidden bg-gradient-to-br from-slate-900 via-[#0e1629] to-slate-900 border border-slate-700/50 px-4 py-6 md:px-8 md:py-10">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(6,182,212,0.08),_transparent_60%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_rgba(139,92,246,0.06),_transparent_60%)]" />
        <div className="relative z-10">
          <h1 className="text-3xl font-bold text-white tracking-tight">Agent Marketplace</h1>
          <p className="text-slate-400 mt-2 max-w-lg">
            Discover, install, and deploy pre-built AI agents. From research assistants to data analysts, find the right agent for your workflow.
          </p>
          <div className="mt-6 relative w-full max-w-xl">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search agents by name or description..."
              className="w-full pl-12 pr-4 py-3 bg-slate-800/60 border border-slate-700/50 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 transition-all"
            />
          </div>
        </div>
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
              {SORT_OPTIONS.map((s) => (
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
          title="No agents found"
          description="No agents match your search criteria. Try adjusting your filters."
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
                  className="block bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 hover:bg-slate-800/40 transition-all group"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className={`w-10 h-10 rounded-lg ${colors.bg} flex items-center justify-center`}>
                      <IconComp className={`w-5 h-5 ${colors.text}`} />
                    </div>
                    {agent.is_free ? (
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
                    <span className="flex items-center gap-1 text-[11px] text-slate-500">
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
