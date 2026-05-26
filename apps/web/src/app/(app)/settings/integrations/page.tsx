'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Check,
  X as XIcon,
  AlertTriangle,
  ExternalLink,
  Search,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

/**
 * Integrations dashboard.
 *
 * Lists every external integration the platform exposes via tools.
 * The actual env-var configuration lives at the deployment level
 * (helm secret in k8s, .env in dev-local) — this page is the
 * read-only "what's wired up?" view + an explainer of how to
 * configure each one.
 *
 * The UI inferring config-state from the live cluster is best-effort:
 * we GET /api/integrations/status (added separately) which checks
 * env-var presence + a quick health-probe per integration. If that
 * endpoint isn't there, we fall back to a static "unknown" state so
 * the page is still a useful catalogue.
 */

type IntegrationStatus = 'configured' | 'missing' | 'error' | 'unknown';

interface Integration {
  id: string;
  name: string;
  category: 'llm' | 'search' | 'observability' | 'comms' | 'storage' | 'data' | 'kyc' | 'meeting' | 'identity';
  description: string;
  envVars: string[];
  unlocks: string;          // which tools/features this integration unlocks
  docsUrl?: string;
}

const INTEGRATIONS: Integration[] = [
  // LLM / AI providers
  {
    id: 'anthropic',
    name: 'Anthropic (Claude)',
    category: 'llm',
    description: 'Default LLM provider for every agent. Required.',
    envVars: ['ANTHROPIC_API_KEY'],
    unlocks: 'every agent execution + every llm_call node',
    docsUrl: 'https://docs.anthropic.com/en/api/getting-started',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    category: 'llm',
    description: 'Alternative LLM + the moderation provider that backs the content-policy gate.',
    envVars: ['OPENAI_API_KEY'],
    unlocks: 'GPT-* models in agent picker + the moderation gate',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    category: 'llm',
    description: 'Gemini 1.5 Pro / Flash via the google-genai SDK.',
    envVars: ['GOOGLE_API_KEY'],
    unlocks: 'Gemini models in agent picker',
  },
  // Search / web
  {
    id: 'tavily',
    name: 'Tavily',
    category: 'search',
    description: 'Recency-biased web search tuned for research agents.',
    envVars: ['TAVILY_API_KEY'],
    unlocks: 'tavily_search tool',
  },
  // Storage
  {
    id: 'pinecone',
    name: 'Pinecone',
    category: 'storage',
    description: 'Managed vector index for knowledge bases + persona RAG.',
    envVars: ['PINECONE_API_KEY'],
    unlocks: 'knowledge_search, persona_rag, vector recall in memory tools',
  },
  {
    id: 's3',
    name: 'S3 / cloud storage',
    category: 'storage',
    description: 'Object store for KB uploads, ML models, code-asset zips, exports.',
    envVars: ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'S3_BUCKET'],
    unlocks: 'cloud_storage tool + multi-replica /data persistence',
  },
  // Comms
  {
    id: 'slack',
    name: 'Slack',
    category: 'comms',
    description: 'Per-tenant incoming webhook for /alerts notifications.',
    envVars: ['SLACK_WEBHOOK_URL (per-tenant in DB)'],
    unlocks: 'alert delivery + agent-completion notifications',
  },
  {
    id: 'smtp',
    name: 'SMTP email',
    category: 'comms',
    description: 'Outbound email relay used by the email_sender tool + tenant invites.',
    envVars: ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS'],
    unlocks: 'email_sender tool + team invite emails',
  },
  // Observability
  {
    id: 'sentry',
    name: 'Sentry',
    category: 'observability',
    description: 'Error tracking + release health.',
    envVars: ['SENTRY_DSN'],
    unlocks: 'crash reports across api / agent-runtime / web',
  },
  {
    id: 'otel',
    name: 'OpenTelemetry',
    category: 'observability',
    description: 'Distributed tracing — exports OTLP to Grafana Tempo / your backend.',
    envVars: ['OTEL_ENABLED', 'OTEL_ENDPOINT'],
    unlocks: 'cross-service traces in /executions detail',
  },
  // Data / finance
  {
    id: 'yahoo_finance',
    name: 'Yahoo Finance',
    category: 'data',
    description: 'Public market data — used by the yahoo_finance tool.',
    envVars: ['YAHOO_FINANCE_API_KEY (optional — public endpoint also works)'],
    unlocks: 'yahoo_finance tool',
  },
  {
    id: 'ecb',
    name: 'European Central Bank',
    category: 'data',
    description: 'FX rates from the ECB SDMX API. Public, no key required.',
    envVars: [],
    unlocks: 'ecb_rates tool',
  },
  {
    id: 'ember',
    name: 'Ember Climate',
    category: 'data',
    description: 'Public energy + emissions data.',
    envVars: [],
    unlocks: 'ember_climate tool',
  },
  {
    id: 'entso_e',
    name: 'ENTSO-E',
    category: 'data',
    description: 'Day-ahead European electricity prices.',
    envVars: ['ENTSO_E_TOKEN'],
    unlocks: 'entso_e tool',
  },
  // KYC
  {
    id: 'opensanctions',
    name: 'OpenSanctions',
    category: 'kyc',
    description: 'Sanctions screening list (OFAC, UN, EU, UK, etc.).',
    envVars: ['OPENSANCTIONS_API_KEY (or OPENSANCTIONS_DATA_PATH for self-hosted)'],
    unlocks: 'sanctions_screening, pep_screening, adverse_media tools',
  },
  {
    id: 'opencorporates',
    name: 'OpenCorporates',
    category: 'kyc',
    description: 'Company registry data — UBO discovery + legal-existence.',
    envVars: ['OPENCORPORATES_API_KEY'],
    unlocks: 'ubo_discovery, legal_existence_verifier tools',
  },
  // Meeting
  {
    id: 'livekit',
    name: 'LiveKit',
    category: 'meeting',
    description: 'WebRTC signalling + media SFU for the meeting bot.',
    envVars: ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'],
    unlocks: 'meeting_join / meeting_listen / meeting_speak / meeting_post_chat / meeting_leave tools',
  },
  // Source-control
  {
    id: 'github',
    name: 'GitHub',
    category: 'comms',
    description: 'Read repo metadata + issues. Used by the github_tool.',
    envVars: ['GITHUB_TOKEN'],
    unlocks: 'github_tool',
  },
  // Identity providers (SSO / OIDC). Configuring any of these makes the
  // matching "Sign in with X" button appear on the login page.
  {
    id: 'sso_google',
    name: 'Google sign-in (OIDC)',
    category: 'identity',
    description: 'Lets users sign in with their Google account. Redirect URI: $PUBLIC_API_BASE_URL/api/auth/oidc/google/callback',
    envVars: ['GOOGLE_OIDC_CLIENT_ID', 'GOOGLE_OIDC_CLIENT_SECRET', 'PUBLIC_API_BASE_URL', 'WEB_BASE_URL'],
    unlocks: '"Sign in with Google" on the login page',
    docsUrl: '/docs?slug=09-reference/05-sso',
  },
  {
    id: 'sso_github',
    name: 'GitHub sign-in (OAuth)',
    category: 'identity',
    description: 'Lets users sign in with their GitHub account. The user must have a verified primary email. Redirect URI: $PUBLIC_API_BASE_URL/api/auth/oidc/github/callback',
    envVars: ['GITHUB_OAUTH_CLIENT_ID', 'GITHUB_OAUTH_CLIENT_SECRET', 'PUBLIC_API_BASE_URL', 'WEB_BASE_URL'],
    unlocks: '"Sign in with GitHub" on the login page',
    docsUrl: '/docs?slug=09-reference/05-sso',
  },
  {
    id: 'sso_microsoft',
    name: 'Microsoft sign-in (Azure AD / OIDC)',
    category: 'identity',
    description: 'Lets users sign in with their Microsoft / Azure AD account. Redirect URI: $PUBLIC_API_BASE_URL/api/auth/oidc/microsoft/callback. Set MICROSOFT_OIDC_TENANT to your tenant GUID to restrict to one org.',
    envVars: ['MICROSOFT_OIDC_CLIENT_ID', 'MICROSOFT_OIDC_CLIENT_SECRET', 'MICROSOFT_OIDC_TENANT (default: common)', 'PUBLIC_API_BASE_URL', 'WEB_BASE_URL'],
    unlocks: '"Sign in with Microsoft" on the login page',
    docsUrl: '/docs?slug=09-reference/05-sso',
  },
];

const CATEGORY_LABEL: Record<string, string> = {
  llm: 'LLM providers',
  identity: 'Identity provider (SSO)',
  search: 'Web search',
  observability: 'Observability',
  comms: 'Communication',
  storage: 'Storage',
  data: 'Data feeds',
  kyc: 'KYC / compliance',
  meeting: 'Meeting / voice',
};

const STATUS_COLOR: Record<IntegrationStatus, string> = {
  configured: 'bg-green-500/15 text-green-300 border-green-500/30',
  missing: 'bg-slate-700/40 text-slate-400 border-slate-700',
  error: 'bg-red-500/15 text-red-300 border-red-500/30',
  unknown: 'bg-slate-700/40 text-slate-500 border-slate-700',
};

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  configured: 'Configured',
  missing: 'Not configured',
  error: 'Error',
  unknown: 'Status unknown',
};

function setupSnippets(envVars: string[]) {
  if (!envVars.length) return null;
  const cleaned = envVars.map(v => v.split(' ')[0].split('(')[0].trim()).filter(Boolean);
  const localExport = cleaned.map(v => `export ${v}=<value>`).join('\n');
  const dotEnv = cleaned.map(v => `${v}=<value>`).join('\n');
  const kubectl = `kubectl create secret generic abenix-secrets -n abenix \\
  ${cleaned.map(v => `--from-literal=${v}=<value>`).join(' \\\n  ')} \\
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/abenix-api deployment/abenix-agent-runtime-default -n abenix`;
  const helmSet = `helm upgrade abenix infra/helm/abenix \\
  ${cleaned.map(v => `--set secrets.${v.toLowerCase()}=<value>`).join(' \\\n  ')} \\
  --reuse-values`;
  return { localExport, dotEnv, kubectl, helmSet };
}

interface McpSummary { connections: number; registry: number; }

export default function IntegrationsPage() {
  const [statuses, setStatuses] = useState<Record<string, IntegrationStatus>>({});
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);
  const [mcp, setMcp] = useState<McpSummary>({ connections: 0, registry: 0 });
  const [isAdmin, setIsAdmin] = useState(false);

  const copyToClipboard = useCallback((text: string, key: string) => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(k => (k === key ? null : k)), 1500);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<Record<string, IntegrationStatus>>('/api/integrations/status');
        if (!cancelled && r && r.data) setStatuses(r.data);
      } catch {}
      try {
        const ssoR = await apiFetch<{ providers?: string[] }>('/api/auth/oidc/providers');
        const list = (ssoR?.data?.providers || []) as string[];
        if (!cancelled) {
          setStatuses((prev) => ({
            ...prev,
            sso_google: list.includes('google') ? 'configured' : 'missing',
            sso_github: list.includes('github') ? 'configured' : 'missing',
            sso_microsoft: list.includes('microsoft') ? 'configured' : 'missing',
          }));
        }
      } catch {}
      try {
        const meR = await apiFetch<{ user?: { role?: string } }>('/api/auth/me');
        const role = ((meR as any)?.data?.user?.role || (meR as any)?.data?.role || '') as string;
        if (!cancelled) setIsAdmin(role === 'admin' || role === 'owner');
      } catch {}
      try {
        const [cR, rR] = await Promise.all([
          apiFetch<unknown>('/api/mcp/connections'),
          apiFetch<unknown>('/api/mcp/registry'),
        ]);
        const cArr = Array.isArray((cR as any)?.data) ? (cR as any).data : ((cR as any)?.data?.connections || []);
        const rArr = Array.isArray((rR as any)?.data) ? (rR as any).data : ((rR as any)?.data?.items || (rR as any)?.data?.servers || []);
        if (!cancelled) setMcp({ connections: cArr.length, registry: rArr.length });
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  const filtered = INTEGRATIONS.filter(i => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      i.name.toLowerCase().includes(q) ||
      i.description.toLowerCase().includes(q) ||
      i.unlocks.toLowerCase().includes(q) ||
      i.envVars.some(v => v.toLowerCase().includes(q))
    );
  });

  const grouped = filtered.reduce<Record<string, Integration[]>>((acc, i) => {
    (acc[i.category] = acc[i.category] || []).push(i);
    return acc;
  }, {});

  const orderedCats = Object.keys(CATEGORY_LABEL).filter(c => grouped[c]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <header className="mb-6">
        <div className="flex items-baseline justify-between gap-3 flex-wrap mb-2">
          <h1 className="text-3xl font-semibold text-white">Integrations</h1>
          {isAdmin && (
            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-300">
              Admin — you can configure
            </span>
          )}
        </div>
        <p className="text-slate-400 max-w-3xl">
          External services the platform can talk to via its built-in tools. Click any row to see the exact command for local dev (<code className="text-cyan-300">.env</code>) AND for production (<code className="text-cyan-300">kubectl</code> / <code className="text-cyan-300">helm</code>). Only admins can change live values.
        </p>
      </header>

      <Link href="/mcp" className="block mb-6">
        <div className="rounded-xl border border-cyan-700/40 bg-cyan-900/15 p-4 hover:border-cyan-500/60 transition flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-cyan-200 mb-1">Need to add a runtime tool? Use MCP servers →</div>
            <p className="text-xs text-slate-300">
              MCP (Model Context Protocol) servers extend agent capabilities at runtime without redeploying. {mcp.registry} servers in the registry, {mcp.connections} connected.
            </p>
          </div>
          <div className="text-cyan-400 text-2xl shrink-0">↗</div>
        </div>
      </Link>

      <div className="mb-6 relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          placeholder="Search integrations…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search integrations"
          className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
        />
      </div>

      <div className="space-y-6">
        {orderedCats.map(cat => (
          <section
            key={cat}
            className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden"
          >
            <h2 className="px-5 py-3 text-sm font-semibold text-cyan-300 uppercase tracking-wider border-b border-slate-800">
              {CATEGORY_LABEL[cat]}
            </h2>
            <ul className="divide-y divide-slate-800/50">
              {grouped[cat].map(i => {
                const st: IntegrationStatus = statuses[i.id] || 'unknown';
                const isOpen = !!expanded[i.id];
                const snip = setupSnippets(i.envVars);
                return (
                  <li key={i.id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-3 flex-wrap">
                          <h3 className="text-white font-medium">{i.name}</h3>
                          <span
                            className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${STATUS_COLOR[st]}`}
                          >
                            {STATUS_LABEL[st]}
                          </span>
                        </div>
                        <p className="text-sm text-slate-400 mt-1">{i.description}</p>
                        <p className="text-xs text-slate-500 mt-2">
                          <span className="text-slate-300">Unlocks:</span> {i.unlocks}
                        </p>
                        {i.envVars.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {i.envVars.map(v => (
                              <code
                                key={v}
                                className="font-mono text-[11px] px-2 py-0.5 bg-slate-800/60 border border-slate-700 rounded text-cyan-300"
                              >
                                {v}
                              </code>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {i.docsUrl && (
                          <a
                            href={i.docsUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-slate-400 hover:text-cyan-300 inline-flex items-center gap-1"
                          >
                            Docs <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                        {snip && (
                          <button
                            onClick={() => setExpanded(prev => ({ ...prev, [i.id]: !prev[i.id] }))}
                            className="text-xs text-slate-300 hover:text-cyan-300 px-2 py-1 rounded border border-slate-700 hover:border-cyan-500/50"
                            aria-expanded={isOpen}
                            aria-label={`${isOpen ? 'Hide' : 'Show'} setup for ${i.name}`}
                          >
                            {isOpen ? 'Hide setup' : 'Setup'}
                          </button>
                        )}
                        {st === 'configured' ? (
                          <Check className="w-4 h-4 text-green-400" aria-label="configured" />
                        ) : st === 'error' ? (
                          <AlertTriangle className="w-4 h-4 text-red-400" aria-label="error" />
                        ) : (
                          <XIcon className="w-4 h-4 text-slate-600" aria-label="not configured" />
                        )}
                      </div>
                    </div>

                    {isOpen && snip && (
                      <div className="mt-4 space-y-3 text-[12px]">
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-slate-400">Local dev — shell export</div>
                            <button onClick={() => copyToClipboard(snip.localExport, `${i.id}-shell`)} className="text-[10px] px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded">{copied === `${i.id}-shell` ? '✓ copied' : 'Copy'}</button>
                          </div>
                          <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-emerald-300 overflow-x-auto">{snip.localExport}</pre>
                        </div>
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-slate-400">Local dev — .env file</div>
                            <button onClick={() => copyToClipboard(snip.dotEnv, `${i.id}-env`)} className="text-[10px] px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded">{copied === `${i.id}-env` ? '✓ copied' : 'Copy'}</button>
                          </div>
                          <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-emerald-300 overflow-x-auto">{snip.dotEnv}</pre>
                        </div>
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-slate-400">
                              Kubernetes (production) {!isAdmin && <span className="text-slate-500 ml-2">— admin role required to apply</span>}
                            </div>
                            <button onClick={() => copyToClipboard(snip.kubectl, `${i.id}-k8s`)} className="text-[10px] px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded">{copied === `${i.id}-k8s` ? '✓ copied' : 'Copy'}</button>
                          </div>
                          <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-cyan-200 overflow-x-auto">{snip.kubectl}</pre>
                        </div>
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-slate-400">Helm upgrade {!isAdmin && <span className="text-slate-500 ml-2">— admin role required</span>}</div>
                            <button onClick={() => copyToClipboard(snip.helmSet, `${i.id}-helm`)} className="text-[10px] px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded">{copied === `${i.id}-helm` ? '✓ copied' : 'Copy'}</button>
                          </div>
                          <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-cyan-200 overflow-x-auto">{snip.helmSet}</pre>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <p className="text-xs text-slate-500 mt-8">
        Note: live status is fetched from <code>/api/integrations/status</code>{' '}
        (best-effort). If you see &ldquo;status unknown&rdquo;, the endpoint
        isn&apos;t reporting on this instance — the catalogue is still
        accurate.
      </p>
    </div>
  );
}
