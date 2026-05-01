'use client';

/**
 * Knowledge Engine Dashboard — graph stats, cognify controls, search playground,
 * feedback, and interactive graph visualization for a knowledge base.
 */

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Activity, ArrowLeft, BarChart3, Brain, CheckCircle2, ChevronDown,
  Clock, Database, GitBranch, Loader2, Play, Search, Sparkles,
  ThumbsDown, ThumbsUp, TrendingUp, XCircle, Zap, Bot, Lock, Network,
} from 'lucide-react';
import Link from 'next/link';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface KBDetail {
  id: string;
  name: string;
  project_id: string | null;
  agent_id: string | null;
  default_visibility?: string | null;
}

interface AgentGrant {
  id: string;
  agent_id: string;
  collection_id: string;
  permission: string;
  agent_name?: string;
  agent_slug?: string;
}

interface GraphStats {
  entity_count: number;
  relationship_count: number;
  entities_by_type: Record<string, number>;
  top_entities: { name: string; type: string; mentions: number; description: string }[];
  graph_enabled: boolean;
  last_cognified_at: string | null;
  neo4j_available: boolean;
  doc_count: number;
}

interface CognifyJob {
  id: string;
  status: string;
  entities_extracted: number;
  relationships_extracted: number;
  documents_processed: number;
  tokens_used: number;
  cost_usd: number;
  duration_seconds: number | null;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

interface SearchResult {
  content: string;
  score: number;
  source: string;
  source_type: string;
  metadata: Record<string, unknown>;
}

export default function KnowledgeEnginePage() {
  const params = useParams();
  const router = useRouter();
  const kbId = params.id as string;

  const [stats, setStats] = useState<GraphStats | null>(null);
  const [jobs, setJobs] = useState<CognifyJob[]>([]);
  const [kb, setKb] = useState<KBDetail | null>(null);
  const [agentGrants, setAgentGrants] = useState<AgentGrant[]>([]);
  const [loading, setLoading] = useState(true);
  const [cognifying, setCognifying] = useState(false);

  // Terminal vs running — any job not in complete/failed is still running.
  // We surface the running one as a sticky banner + disable the Run button
  // so users can see progress instead of wondering if anything is happening.
  const runningJob = jobs.find(
    (j) => !['complete', 'completed', 'ready', 'failed', 'error'].includes(
      (j.status || '').toLowerCase(),
    ),
  ) || null;

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'vector' | 'graph' | 'hybrid'>('hybrid');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchMeta, setSearchMeta] = useState<Record<string, unknown> | null>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Load stats, jobs, kb detail, and agent grants (reverse lookup).
  const loadData = useCallback(async () => {
    if (!token) return;
    try {
      const [statsRes, jobsRes, kbRes, grantsRes] = await Promise.all([
        fetch(`${API_URL}/api/knowledge-engines/${kbId}/graph-stats`, { headers }),
        fetch(`${API_URL}/api/knowledge-engines/${kbId}/cognify-jobs`, { headers }),
        fetch(`${API_URL}/api/knowledge-bases/${kbId}`, { headers }),
        fetch(`${API_URL}/api/knowledge-collections/${kbId}/agents`, { headers }),
      ]);
      const statsBody = await statsRes.json();
      const jobsBody = await jobsRes.json();
      const kbBody = await kbRes.json();
      const grantsBody = await grantsRes.json();
      if (statsBody.data) setStats(statsBody.data);
      if (jobsBody.data) setJobs(jobsBody.data);
      if (kbBody.data) setKb(kbBody.data);
      // Enrich grants with agent names (best effort; ignore failures).
      if (Array.isArray(grantsBody.data)) {
        const grants: AgentGrant[] = grantsBody.data;
        try {
          const agentsRes = await fetch(`${API_URL}/api/agents?limit=500`, { headers });
          const agentsBody = await agentsRes.json();
          const agents = (agentsBody.data || []) as { id: string; name: string; slug: string }[];
          const byId = new Map(agents.map((a) => [a.id, a]));
          setAgentGrants(
            grants.map((g) => ({
              ...g,
              agent_name: byId.get(g.agent_id)?.name,
              agent_slug: byId.get(g.agent_id)?.slug,
            })),
          );
        } catch {
          setAgentGrants(grants);
        }
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [kbId, token]);

  useEffect(() => { loadData(); }, [loadData]);

  // Keep polling while a cognify job is running so the banner updates.
  useEffect(() => {
    if (!runningJob) return;
    const h = setInterval(loadData, 4000);
    return () => clearInterval(h);
  }, [runningJob?.id, loadData]);

  // Trigger cognify
  const triggerCognify = async () => {
    setCognifying(true);
    try {
      await fetch(`${API_URL}/api/knowledge-engines/${kbId}/cognify`, {
        method: 'POST', headers, body: JSON.stringify({}),
      });
      // Poll initial state; the running-job effect above keeps refreshing.
      await loadData();
    } catch { /* ignore */ }
    setCognifying(false);
  };

  // Search
  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const res = await fetch(`${API_URL}/api/knowledge-engines/${kbId}/search`, {
        method: 'POST', headers,
        body: JSON.stringify({ query: searchQuery, mode: searchMode, top_k: 10 }),
      });
      const body = await res.json();
      if (body.data) {
        setSearchResults(body.data.results || []);
        setSearchMeta(body.data);
      }
    } catch { /* ignore */ }
    setSearching(false);
  };

  // Feedback
  const submitFeedback = async (rating: number) => {
    try {
      await fetch(`${API_URL}/api/knowledge-engines/${kbId}/feedback`, {
        method: 'POST', headers,
        body: JSON.stringify({
          query: searchQuery, search_mode: searchMode, rating,
          result_entity_ids: searchResults.filter(r => r.source_type === 'entity').map(r => r.metadata.pg_id).filter(Boolean),
        }),
      });
    } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 text-cyan-500 animate-spin" />
      </div>
    );
  }

  const entityTypes = stats?.entities_by_type || {};
  const typeColors: Record<string, string> = {
    person: 'bg-blue-500', organization: 'bg-purple-500', concept: 'bg-cyan-500',
    location: 'bg-emerald-500', event: 'bg-amber-500', technology: 'bg-red-500',
    product: 'bg-pink-500', metric: 'bg-orange-500', document: 'bg-slate-500',
  };

  return (
    <div className="space-y-6">
      {/* Header — back nav goes to the KB list (there is no /knowledge/[id]
          URL route; the KB detail is state-based inside /knowledge). */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push('/knowledge')}
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white"
          data-testid="engine-back"
        >
          <ArrowLeft className="w-4 h-4" /> Back to knowledge bases
        </button>
        <div className="flex items-center gap-3 ml-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-600 flex items-center justify-center">
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">{kb?.name || 'Knowledge Engine'}</h1>
            <p className="text-xs text-slate-500">Graph + Vector Hybrid Memory</p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs ${
            stats?.neo4j_available ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
          }`}>
            <Database className="w-3 h-3" />
            Neo4j {stats?.neo4j_available ? 'Connected' : 'Offline'}
          </div>
          <button
            onClick={triggerCognify}
            disabled={cognifying || !!runningJob}
            className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            data-testid="run-cognify"
          >
            {(cognifying || runningJob) ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {runningJob ? `Cognify: ${runningJob.status}…` : (cognifying ? 'Starting…' : 'Run Cognify')}
          </button>
        </div>
      </div>

      {/* Running Cognify job banner — live progress while the background
          cognify-worker extracts entities. Without this, users clicked
          "Run Cognify" and had no way to tell if anything was happening. */}
      {runningJob && (
        <div
          data-testid="cognify-running-banner"
          className="flex items-start gap-3 rounded-xl border border-emerald-500/40 bg-gradient-to-r from-emerald-500/10 to-cyan-500/10 p-4"
        >
          <Loader2 className="w-5 h-5 text-emerald-300 animate-spin mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-emerald-200">
              Cognify in progress — extracting entities &amp; relationships
            </div>
            <div className="text-xs text-slate-300 mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <span>Status: <span className="text-emerald-300 font-mono">{runningJob.status}</span></span>
              <span>Documents processed: <span className="text-white">{runningJob.documents_processed || 0}</span></span>
              <span>Entities so far: <span className="text-white">{runningJob.entities_extracted || 0}</span></span>
              <span>Relationships so far: <span className="text-white">{runningJob.relationships_extracted || 0}</span></span>
              <span>Tokens: <span className="text-white">{(runningJob.tokens_used || 0).toLocaleString()}</span></span>
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Live — this banner refreshes every few seconds and disappears when the run finishes.
            </div>
          </div>
        </div>
      )}

      {/* Project / scoping / ontology strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3" data-testid="kb-meta-strip">
        {/* Project + ontology */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-slate-500">
            <Network className="w-3.5 h-3.5 text-violet-400" />
            Ontology & schema
          </div>
          {kb?.project_id ? (
            <Link
              href={`/knowledge/projects/${kb.project_id}/ontology`}
              className="text-sm font-semibold text-violet-300 hover:text-violet-200 inline-flex items-center gap-1.5"
              data-testid="kb-ontology-link"
            >
              View project ontology →
            </Link>
          ) : (
            <span className="text-xs text-slate-500">Not in a project</span>
          )}
          <p className="text-[11px] text-slate-500 mt-1">
            Edit entity types, relationship types, and activate schema versions for the whole project.
          </p>
        </div>

        {/* Agents using this KB */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-slate-500">
            <Bot className="w-3.5 h-3.5 text-cyan-400" />
            Used by agents
          </div>
          {agentGrants.length === 0 ? (
            <span className="text-xs text-slate-500">No agents granted yet.</span>
          ) : (
            <div className="flex flex-wrap gap-1.5" data-testid="kb-agent-grants">
              {agentGrants.slice(0, 8).map((g) => (
                <Link
                  key={g.id}
                  href={`/agents/${g.agent_id}`}
                  className="text-[11px] bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 rounded px-1.5 py-0.5 hover:bg-cyan-500/20"
                  title={`${g.permission} grant`}
                >
                  {g.agent_name || g.agent_slug || g.agent_id.slice(0, 8)}
                </Link>
              ))}
              {agentGrants.length > 8 && (
                <span className="text-[11px] text-slate-500">+{agentGrants.length - 8} more</span>
              )}
            </div>
          )}
          <p className="text-[11px] text-slate-500 mt-2">
            Agents read this collection through the <code className="text-cyan-300">knowledge_search</code> tool.
          </p>
        </div>

        {/* Visibility / RLS */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-slate-500">
            <Lock className="w-3.5 h-3.5 text-emerald-400" />
            Access scope
          </div>
          <p className="text-sm text-slate-200">
            {kb?.default_visibility === 'private' ? 'Private to grantees'
              : kb?.default_visibility === 'tenant' ? 'Tenant-wide'
              : 'Project members'}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            Tenant isolation is enforced at every query. User-level access is checked via{' '}
            <span className="text-slate-300">UserCollectionGrant</span> for private collections.
          </p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Entities', value: stats?.entity_count || 0, icon: GitBranch, color: 'text-cyan-400' },
          { label: 'Relationships', value: stats?.relationship_count || 0, icon: Activity, color: 'text-emerald-400' },
          { label: 'Documents', value: stats?.doc_count || 0, icon: Database, color: 'text-purple-400' },
          { label: 'Last Cognified', value: stats?.last_cognified_at ? new Date(stats.last_cognified_at).toLocaleDateString() : 'Never', icon: Clock, color: 'text-amber-400' },
        ].map((stat) => (
          <div key={stat.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
              <span className="text-xs text-slate-500">{stat.label}</span>
            </div>
            <p className="text-2xl font-bold text-white">
              {typeof stat.value === 'number' ? stat.value.toLocaleString() : stat.value}
            </p>
          </div>
        ))}
      </div>

      {/* Entity Type Breakdown */}
      {Object.keys(entityTypes).length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-cyan-400" />
            Entity Types
          </h3>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(entityTypes).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
              <div key={type} className="flex items-center gap-2 bg-slate-900/50 rounded-lg px-3 py-2">
                <div className={`w-2.5 h-2.5 rounded-full ${typeColors[type] || 'bg-slate-500'}`} />
                <span className="text-xs text-slate-300 capitalize">{type}</span>
                <span className="text-xs font-bold text-white">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top Entities */}
      {(stats?.top_entities || []).length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            Top Entities
          </h3>
          <div className="space-y-2">
            {(stats?.top_entities || []).map((e, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span className="w-5 text-center text-slate-600 font-bold">{i + 1}</span>
                <div className={`w-2 h-2 rounded-full ${typeColors[e.type] || 'bg-slate-500'}`} />
                <span className="text-white font-medium flex-1">{e.name}</span>
                <span className="text-slate-500 capitalize">{e.type}</span>
                <span className="text-slate-400">{e.mentions} mentions</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search Playground */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Search className="w-4 h-4 text-cyan-400" />
          Search Playground
        </h3>
        <div className="flex gap-2 mb-3">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Ask a question about your knowledge base..."
            className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <div className="relative">
            <select
              value={searchMode}
              onChange={(e) => setSearchMode(e.target.value as typeof searchMode)}
              className="px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white appearance-none pr-8 focus:outline-none focus:border-cyan-500"
            >
              <option value="hybrid">Hybrid</option>
              <option value="vector">Vector Only</option>
              <option value="graph">Graph Only</option>
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="px-4 py-2 bg-cyan-500/10 text-cyan-400 rounded-lg hover:bg-cyan-500/20 disabled:opacity-40 text-sm flex items-center gap-2"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>

        {/* Search metadata */}
        {searchMeta && (
          <div className="flex gap-4 mb-3 text-[10px] text-slate-500">
            <span>Mode: <span className="text-slate-300">{searchMeta.mode_used as string}</span></span>
            <span>Vector: <span className="text-slate-300">{searchMeta.vector_count as number}</span></span>
            <span>Graph: <span className="text-slate-300">{searchMeta.graph_count as number}</span></span>
            {(searchMeta.entities_found as string[] || []).length > 0 && (
              <span>Entities: <span className="text-cyan-400">{(searchMeta.entities_found as string[]).join(', ')}</span></span>
            )}
            <span>Latency: <span className="text-slate-300">{searchMeta.latency_ms as number}ms</span></span>
          </div>
        )}

        {/* Results */}
        {searchResults.length > 0 && (
          <div className="space-y-2">
            {searchResults.map((r, i) => (
              <div key={i} className="bg-slate-900/50 border border-slate-700/30 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold text-slate-500">#{i + 1}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    r.source_type === 'entity' ? 'bg-cyan-500/10 text-cyan-400'
                    : r.source_type === 'relationship' ? 'bg-emerald-500/10 text-emerald-400'
                    : r.source_type === 'graph_context' ? 'bg-purple-500/10 text-purple-400'
                    : 'bg-slate-700 text-slate-400'
                  }`}>
                    {r.source_type}
                  </span>
                  <span className="text-[10px] text-slate-500">{r.source}</span>
                  <span className="text-[10px] text-slate-600 ml-auto">score: {r.score.toFixed(3)}</span>
                </div>
                <p className="text-xs text-slate-300 whitespace-pre-wrap">{r.content}</p>
              </div>
            ))}

            {/* Feedback */}
            <div className="flex items-center gap-2 pt-2 border-t border-slate-700/50">
              <span className="text-[10px] text-slate-500">Were these results helpful?</span>
              <button onClick={() => submitFeedback(1)} className="p-1.5 text-slate-500 hover:text-emerald-400 hover:bg-emerald-500/10 rounded">
                <ThumbsUp className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => submitFeedback(-1)} className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded">
                <ThumbsDown className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Cognify Job History */}
      {jobs.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            Cognify History
          </h3>
          <div className="space-y-2">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center gap-3 bg-slate-900/30 rounded-lg px-3 py-2 text-xs">
                {job.status === 'complete' ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : job.status === 'failed' ? (
                  <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                ) : (
                  <Loader2 className="w-4 h-4 text-cyan-400 animate-spin shrink-0" />
                )}
                <span className="text-slate-300">{job.documents_processed} docs</span>
                <span className="text-slate-500">→</span>
                <span className="text-cyan-400">{job.entities_extracted} entities</span>
                <span className="text-slate-500">+</span>
                <span className="text-emerald-400">{job.relationships_extracted} rels</span>
                {job.duration_seconds && (
                  <span className="text-slate-500 ml-auto">{job.duration_seconds.toFixed(1)}s</span>
                )}
                {job.cost_usd > 0 && (
                  <span className="text-slate-500">${job.cost_usd.toFixed(4)}</span>
                )}
                <span className="text-slate-600">{new Date(job.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
