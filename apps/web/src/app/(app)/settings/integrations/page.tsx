'use client';

import { useEffect, useState } from 'react';
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
  category: 'llm' | 'search' | 'observability' | 'comms' | 'storage' | 'data' | 'kyc' | 'meeting';
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
];

const CATEGORY_LABEL: Record<string, string> = {
  llm: 'LLM providers',
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

export default function IntegrationsPage() {
  const [statuses, setStatuses] = useState<Record<string, IntegrationStatus>>({});
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // /api/integrations/status is best-effort — if missing, we
        // render "unknown" and the page is still useful as a catalogue.
        const r = await apiFetch<Record<string, IntegrationStatus>>('/api/integrations/status');
        if (!cancelled && r && r.data) {
          setStatuses(r.data);
        }
      } catch {
        // Endpoint not implemented yet — leave statuses empty.
      }
    })();
    return () => {
      cancelled = true;
    };
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
        <h1 className="text-3xl font-semibold text-white mb-2">Integrations</h1>
        <p className="text-slate-400 max-w-3xl">
          External services the platform can talk to via its built-in tools.
          Configure each by setting the listed environment variables in your
          deployment (helm secret for k8s, <code className="text-cyan-300">.env</code> for{' '}
          <code className="text-cyan-300">dev-local.sh</code>).
          See the{' '}
          <Link href="/help" className="text-cyan-400 hover:underline">
            help docs
          </Link>{' '}
          for full setup instructions.
        </p>
      </header>

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
                        {st === 'configured' ? (
                          <Check className="w-4 h-4 text-green-400" aria-label="configured" />
                        ) : st === 'error' ? (
                          <AlertTriangle className="w-4 h-4 text-red-400" aria-label="error" />
                        ) : (
                          <XIcon className="w-4 h-4 text-slate-600" aria-label="not configured" />
                        )}
                      </div>
                    </div>
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
