// @ts-nocheck — Pre-existing type issues with dynamic model_config fields
'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import dynamic from 'next/dynamic';

const PipelineDAGPreview = dynamic(
  () => import('@/components/shared/PipelineDAGPreview'),
  { ssr: false, loading: () => <div className="h-[250px] bg-slate-900/30 rounded-xl animate-pulse" /> }
);

import {
  ArrowLeft,
  BarChart3,
  Bot,
  Calendar,
  CheckCircle2,
  Cloud,
  Code,
  Copy,
  FileText,
  GraduationCap,
  Mail,
  MessageSquare,
  Scale,
  Star,
  Users,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface AgentDetail {
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
  system_prompt: string | null;
  is_subscribed: boolean;
  created_at: string | null;
}

interface Review {
  id: string;
  agent_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string | null;
  user_name: string | null;
  user_avatar: string | null;
}

interface ReviewMeta {
  total: number;
  page: number;
  per_page: number;
  avg_rating: number;
  distribution: Record<string, number>;
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

const categoryColors: Record<string, { bg: string; text: string; border: string }> = {
  productivity: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/20' },
  research: { bg: 'bg-violet-500/10', text: 'text-violet-400', border: 'border-violet-500/20' },
  engineering: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20' },
  communication: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' },
  analytics: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/20' },
  legal: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/20' },
};

type Tab = 'overview' | 'reviews' | 'api' | 'changelog';

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

function RatingBar({ count, total, starNum }: { count: number; total: number; starNum: number }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500 w-4 text-right">{starNum}</span>
      <Star className="w-3 h-3 text-amber-400 fill-amber-400" />
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 w-8">{count}</span>
    </div>
  );
}

export default function AgentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const agentId = params.id as string;

  const [tab, setTab] = useState<Tab>('overview');
  const [subscribing, setSubscribing] = useState(false);
  const searchParams = useSearchParams();
  const [subscribed, setSubscribed] = useState(false);

  const [reviewPage, setReviewPage] = useState(1);

  const [newRating, setNewRating] = useState(5);
  const [newComment, setNewComment] = useState('');
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewError, setReviewError] = useState('');

  const { data: agent, isLoading: loading } = useApi<AgentDetail>(
    agentId ? `/api/marketplace/${agentId}` : null,
  );

  usePageTitle(agent?.name || 'Agent Details');

  const reviewsPath =
    tab === 'reviews' && agentId
      ? `/api/agents/${agentId}/reviews?page=${reviewPage}&per_page=10`
      : null;
  const {
    data: reviews,
    meta: reviewMetaRaw,
    isLoading: reviewsLoading,
    mutate: mutateReviews,
  } = useApi<Review[]>(reviewsPath);
  const reviewMeta = reviewMetaRaw as unknown as ReviewMeta | null;

  useEffect(() => {
    if (agent) {
      setSubscribed(agent.is_subscribed);
    }
  }, [agent]);

  useEffect(() => {
    if (searchParams.get('subscribed') === 'true') {
      setSubscribed(true);
    }
  }, [searchParams]);

  const handleSubscribe = async () => {
    if (!agent) return;
    setSubscribing(true);
    try {
      const res = await apiFetch<{
        checkout_url?: string;
        id?: string;
      }>(`/api/marketplace/subscribe/${agent.id}`, {
        method: 'POST',
        body: JSON.stringify({ plan_type: 'free' }),
      });
      if (res.data?.checkout_url) {
        window.location.href = res.data.checkout_url;
        return;
      }
      if (res.data) {
        setSubscribed(true);
      }
    } catch {
      // skip
    } finally {
      setSubscribing(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!agentId) return;
    setSubmittingReview(true);
    setReviewError('');
    try {
      const res = await apiFetch<Review>(`/api/agents/${agentId}/reviews`, {
        method: 'POST',
        body: JSON.stringify({ rating: newRating, comment: newComment || null }),
      });
      if (res.error) {
        setReviewError(res.error);
      } else {
        setNewComment('');
        setNewRating(5);
        mutateReviews();
      }
    } catch {
      setReviewError('Failed to submit review');
    } finally {
      setSubmittingReview(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-slate-500 mb-4">Agent not found</p>
        <Link href="/marketplace" className="text-sm text-cyan-400 hover:text-cyan-300">
          Back to Marketplace
        </Link>
      </div>
    );
  }

  const IconComp = (agent.icon_url && iconMap[agent.icon_url]) || Bot;
  const colors = categoryColors[agent.category || ''] || {
    bg: 'bg-purple-500/10',
    text: 'text-purple-400',
    border: 'border-purple-500/20',
  };
  const tools = (agent.model_config as Record<string, unknown>)?.tools as string[] | undefined;
  const mcpExtensions = (agent.model_config as Record<string, unknown>)?.mcp_extensions as
    | Record<string, unknown>[]
    | undefined;
  const model = (agent.model_config as Record<string, unknown>)?.model as string | undefined;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'reviews', label: 'Reviews' },
    { key: 'api', label: 'API' },
    { key: 'changelog', label: 'Changelog' },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="max-w-[1100px] space-y-6"
    >
      {/* Back */}
      <button
        onClick={() => router.push('/marketplace')}
        className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Marketplace
      </button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start gap-6">
        <div className={`w-16 h-16 rounded-xl ${colors.bg} flex items-center justify-center shrink-0`}>
          <IconComp className={`w-8 h-8 ${colors.text}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-bold text-white">{agent.name}</h1>
            <span className="text-xs text-slate-500 font-mono">v{agent.version}</span>
          </div>
          <p className="text-sm text-slate-400 mb-3">by {agent.creator_name || 'Unknown'}</p>
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5">
              <StarRating rating={agent.avg_rating} size="md" />
              <span className="text-sm text-slate-400">
                {agent.avg_rating > 0 ? agent.avg_rating.toFixed(1) : 'No ratings'}
              </span>
              {agent.review_count > 0 && (
                <span className="text-xs text-slate-500">({agent.review_count} reviews)</span>
              )}
            </div>
            <span className="flex items-center gap-1 text-sm text-slate-500">
              <Users className="w-4 h-4" />
              {agent.subscriber_count} subscriber{agent.subscriber_count !== 1 ? 's' : ''}
            </span>
            {agent.category && (
              <span className={`text-xs ${colors.text} ${colors.bg} border ${colors.border} px-2 py-0.5 rounded-full capitalize`}>
                {agent.category}
              </span>
            )}
            {agent.is_free ? (
              <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                Free
              </span>
            ) : (
              <span className="text-xs font-medium text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded-full">
                ${agent.marketplace_price}/mo
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2 shrink-0 w-full sm:w-auto">
          {subscribed ? (
            <>
              <span className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg w-full sm:w-auto">
                <CheckCircle2 className="w-4 h-4" />
                Subscribed
              </span>
              <Link
                href={`/agents/${agent.id}/chat`}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all w-full sm:w-auto"
              >
                <MessageSquare className="w-4 h-4" />
                Chat
              </Link>
            </>
          ) : (
            <button
              onClick={handleSubscribe}
              disabled={subscribing}
              className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all disabled:opacity-50 w-full sm:w-auto"
            >
              {subscribing ? 'Subscribing...' : 'Subscribe'}
            </button>
          )}
        </div>
      </div>

      {searchParams.get('subscribed') === 'true' && (
        <div className="mx-6 mt-4 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
          <p className="text-sm text-emerald-400">Successfully subscribed to this agent!</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-700/50">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-500 border-transparent hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
              <h2 className="text-sm font-semibold text-white mb-3">Description</h2>
              <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap">
                {agent.description}
              </p>
            </div>

            {/* Pipeline DAG Preview (for pipeline agents) */}
            {agent.model_config?.mode === 'pipeline' && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
                <h2 className="text-sm font-semibold text-white mb-3">Pipeline Workflow</h2>
                <p className="text-xs text-slate-500 mb-3">Visual representation of the execution flow. Each node is a processing step connected in a directed acyclic graph (DAG).</p>
                <PipelineDAGPreview agentId={agent.id} token={typeof window !== 'undefined' ? localStorage.getItem('access_token') || '' : ''} height={250} />
              </div>
            )}

            {/* Input Parameters */}
            {(() => {
              const vars = agent.model_config?.input_variables || [];
              return vars.length > 0 ? (
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
                  <h2 className="text-sm font-semibold text-white mb-3">Input Parameters</h2>
                  <p className="text-xs text-slate-500 mb-3">Required and optional parameters for this agent. Pass via SDK context or the chat interface.</p>
                  <div className="space-y-2">
                    {vars.map((v: { name: string; type?: string; description?: string; required?: boolean; default?: string }) => (
                      <div key={v.name} className="flex items-start gap-3 p-2 bg-slate-900/30 rounded-lg border border-slate-700/30">
                        <div className="flex items-center gap-2">
                          <code className="text-xs text-cyan-400 font-mono">{v.name}</code>
                          {v.required && <span className="text-[8px] px-1 py-0.5 bg-red-500/10 text-red-400 rounded">required</span>}
                          {v.type && <span className="text-[8px] px-1 py-0.5 bg-slate-700/50 text-slate-400 rounded">{v.type}</span>}
                        </div>
                        {v.description && <p className="text-[10px] text-slate-500 flex-1">{v.description}</p>}
                        {v.default && <span className="text-[9px] text-slate-600">default: {String(v.default)}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
                  <h2 className="text-sm font-semibold text-white mb-3">How to Use</h2>
                  <p className="text-xs text-slate-400">This agent accepts free-form text input. Simply describe your task in natural language via the chat interface or SDK.</p>
                </div>
              );
            })()}

            {/* Example Prompts */}
            {agent.model_config?.example_prompts && agent.model_config.example_prompts.length > 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
                <h2 className="text-sm font-semibold text-white mb-3">Example Prompts</h2>
                <div className="space-y-2">
                  {agent.model_config.example_prompts.map((prompt: string, i: number) => (
                    <button
                      key={i}
                      onClick={() => navigator.clipboard.writeText(prompt)}
                      className="w-full text-left p-3 bg-slate-900/30 rounded-lg border border-slate-700/30 hover:border-cyan-500/30 transition-colors group"
                    >
                      <p className="text-xs text-slate-300 group-hover:text-cyan-400 transition-colors">{prompt}</p>
                      <p className="text-[9px] text-slate-600 mt-1">Click to copy</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {agent.system_prompt && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
                <h2 className="text-sm font-semibold text-white mb-3">System Prompt</h2>
                <pre className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap font-mono bg-slate-900/50 rounded-lg p-4 max-h-80 overflow-y-auto">
                  {agent.system_prompt}
                </pre>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">Details</h3>
              <dl className="space-y-3">
                {model && (
                  <div>
                    <dt className="text-[11px] text-slate-500">Model</dt>
                    <dd className="text-xs text-slate-300 font-mono">{model.replace(/-\d{8}$/, '')}</dd>
                  </div>
                )}
                <div>
                  <dt className="text-[11px] text-slate-500">Version</dt>
                  <dd className="text-xs text-slate-300">{agent.version}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-slate-500">Type</dt>
                  <dd className="text-xs text-slate-300 capitalize">{agent.agent_type}</dd>
                </div>
                {agent.created_at && (
                  <div>
                    <dt className="text-[11px] text-slate-500">Published</dt>
                    <dd className="text-xs text-slate-300">
                      {new Date(agent.created_at).toLocaleDateString('en-US', {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                      })}
                    </dd>
                  </div>
                )}
              </dl>
            </div>

            {tools && tools.length > 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
                  Built-in Tools
                </h3>
                <div className="space-y-1.5">
                  {tools.map((tool) => (
                    <div
                      key={tool}
                      className="flex items-center gap-2 text-xs text-slate-400"
                    >
                      <Wrench className="w-3 h-3 text-slate-500" />
                      <span className="capitalize">{tool.replace(/_/g, ' ')}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {mcpExtensions && mcpExtensions.length > 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
                  MCP Integrations
                </h3>
                <div className="space-y-1.5">
                  {mcpExtensions.map((ext, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 text-xs text-slate-400"
                    >
                      <div className="w-1.5 h-1.5 rounded-full bg-cyan-400/60" />
                      <span>{(ext as Record<string, unknown>).name as string}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'reviews' && (
        <div className="space-y-6">
          {/* Rating summary */}
          {reviewMeta && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
              <div className="grid grid-cols-2 gap-8">
                <div className="flex flex-col items-center justify-center">
                  <span className="text-4xl font-bold text-white">
                    {reviewMeta.avg_rating > 0 ? reviewMeta.avg_rating.toFixed(1) : '--'}
                  </span>
                  <StarRating rating={reviewMeta.avg_rating} size="md" />
                  <span className="text-xs text-slate-500 mt-1">{reviewMeta.total} reviews</span>
                </div>
                <div className="space-y-2">
                  {[5, 4, 3, 2, 1].map((n) => (
                    <RatingBar
                      key={n}
                      starNum={n}
                      count={reviewMeta.distribution[String(n)] || 0}
                      total={reviewMeta.total}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Write review */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-white mb-4">Write a Review</h3>
            <div className="flex items-center gap-1 mb-3">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => setNewRating(n)}
                  className="p-0.5"
                >
                  <Star
                    className={`w-5 h-5 transition-colors ${
                      n <= newRating
                        ? 'text-amber-400 fill-amber-400'
                        : 'text-slate-600 hover:text-slate-400'
                    }`}
                  />
                </button>
              ))}
            </div>
            <textarea
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              placeholder="Share your experience with this agent..."
              rows={3}
              className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 resize-none"
            />
            {reviewError && <p className="text-xs text-red-400 mt-2">{reviewError}</p>}
            <button
              onClick={handleSubmitReview}
              disabled={submittingReview}
              className="mt-3 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all disabled:opacity-50"
            >
              {submittingReview ? 'Submitting...' : 'Submit Review'}
            </button>
          </div>

          {/* Reviews list */}
          {reviewsLoading ? (
            <div className="flex items-center justify-center py-10">
              <div className="w-6 h-6 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
            </div>
          ) : (reviews ?? []).length === 0 ? (
            <div className="text-center py-10">
              <p className="text-sm text-slate-500">No reviews yet. Be the first to review this agent.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {(reviews ?? []).map((review) => (
                <div
                  key={review.id}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-slate-700/50 flex items-center justify-center text-xs text-slate-400 font-medium">
                        {(review.user_name || 'U').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm text-white font-medium">
                          {review.user_name || 'Anonymous'}
                        </p>
                        <StarRating rating={review.rating} />
                      </div>
                    </div>
                    {review.created_at && (
                      <span className="text-[11px] text-slate-500">
                        {new Date(review.created_at).toLocaleDateString('en-US', {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                        })}
                      </span>
                    )}
                  </div>
                  {review.comment && (
                    <p className="text-sm text-slate-400 leading-relaxed mt-2">
                      {review.comment}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Review pagination */}
          {reviewMeta && reviewMeta.total > 10 && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setReviewPage((p) => Math.max(1, p - 1))}
                disabled={reviewPage === 1}
                className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/40 border border-slate-700/50 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <span className="text-xs text-slate-500">
                Page {reviewPage} of {Math.ceil(reviewMeta.total / 10)}
              </span>
              <button
                onClick={() => setReviewPage((p) => p + 1)}
                disabled={reviewPage >= Math.ceil(reviewMeta.total / 10)}
                className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/40 border border-slate-700/50 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'api' && (
        <div className="space-y-6">
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
            <h2 className="text-sm font-semibold text-white mb-4">API Usage</h2>
            <p className="text-xs text-slate-400 mb-4">
              Use this agent programmatically via the Abenix API.
            </p>

            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500 font-mono">Start a chat session</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(
                      `curl -X POST ${API_URL}/api/agents/${agent.id}/execute \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -H "Content-Type: application/json" \\\n  -d '{"message": "Hello"}'`
                    )}
                    className="text-slate-500 hover:text-white transition-colors"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <pre className="text-xs text-slate-300 font-mono bg-slate-900/50 rounded-lg p-4 overflow-x-auto">
{`curl -X POST ${API_URL}/api/agents/${agent.id}/execute \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Hello"}'`}
                </pre>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500 font-mono">Get agent details</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(
                      `curl ${API_URL}/api/marketplace/${agent.id} \\\n  -H "Authorization: Bearer YOUR_TOKEN"`
                    )}
                    className="text-slate-500 hover:text-white transition-colors"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <pre className="text-xs text-slate-300 font-mono bg-slate-900/50 rounded-lg p-4 overflow-x-auto">
{`curl ${API_URL}/api/marketplace/${agent.id} \\
  -H "Authorization: Bearer YOUR_TOKEN"`}
                </pre>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500 font-mono">Subscribe to this agent</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(
                      `curl -X POST ${API_URL}/api/marketplace/subscribe/${agent.id} \\\n  -H "Authorization: Bearer YOUR_TOKEN" \\\n  -H "Content-Type: application/json" \\\n  -d '{"plan_type": "free"}'`
                    )}
                    className="text-slate-500 hover:text-white transition-colors"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <pre className="text-xs text-slate-300 font-mono bg-slate-900/50 rounded-lg p-4 overflow-x-auto">
{`curl -X POST ${API_URL}/api/marketplace/subscribe/${agent.id} \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"plan_type": "free"}'`}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'changelog' && (
        <div className="space-y-4">
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
            <div className="flex items-start gap-4">
              <div className="w-2 h-2 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium text-white">v{agent.version}</span>
                  <span className="text-xs text-slate-500">Initial release</span>
                </div>
                <p className="text-xs text-slate-400">
                  First published version of {agent.name}.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
