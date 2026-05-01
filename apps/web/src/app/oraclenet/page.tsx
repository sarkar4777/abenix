'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, Send, BookOpen, Radio, Users, GitBranch, ShieldAlert,
  Sparkles, Loader2, Download, FileText, Copy, Check, ChevronDown,
  Clock, DollarSign, Zap, ArrowRight, RotateCcw, History,
  AlertTriangle, CheckCircle, XCircle, Activity, Search, Eye,
  TrendingUp, Shield, Target, Layers, ArrowLeft, Network,
} from 'lucide-react';

// ─── Config ──────────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const CONFIGURED_API_KEY = process.env.NEXT_PUBLIC_ORACLENET_API_KEY || '';

function getAuthHeaders(): Record<string, string> {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token');
    if (token) return { 'Authorization': `Bearer ${token}` };
  }
  if (CONFIGURED_API_KEY) {
    if (CONFIGURED_API_KEY.startsWith('af_')) return { 'X-API-Key': CONFIGURED_API_KEY };
    return { 'Authorization': `Bearer ${CONFIGURED_API_KEY}` };
  }
  return {};
}

function isAuthenticated(): boolean {
  if (typeof window !== 'undefined' && localStorage.getItem('access_token')) return true;
  if (CONFIGURED_API_KEY) return true;
  return false;
}

// ─── Types ───────────────────────────────────────────────────────────────────

type Phase = 'input' | 'analyzing' | 'brief' | 'error';
type Depth = 'quick' | 'standard' | 'deep';
type AgentStatus = 'pending' | 'running' | 'complete' | 'failed';

interface AgentCard {
  id: string;
  label: string;
  icon: React.ElementType;
  status: AgentStatus;
  progress: number;
  message: string;
  duration?: number;
}

interface LogEntry {
  timestamp: Date;
  agent: string;
  message: string;
  type: 'info' | 'success' | 'error';
}

interface Scenario {
  title: string;
  probability: number;
  description: string;
  drivers: string[];
}

interface Stakeholder {
  name: string;
  impact: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  details: string;
}

interface CascadeEffect {
  order: number;
  effect: string;
  likelihood: string;
}

interface Risk {
  title: string;
  severity: 'high' | 'medium' | 'low';
  probability: number;
  description: string;
}

interface BriefData {
  summary: string;
  confidence: number;
  recommendation: string;
  scenarios: Scenario[];
  stakeholders: Stakeholder[];
  cascadeEffects: CascadeEffect[];
  risks: Risk[];
  conditions: string[];
  monitoringTriggers: string[];
}

interface PastAnalysis {
  id: string;
  query: string;
  date: Date;
  confidence: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const EXAMPLE_PROMPTS = [
  'We are considering raising prices by 15% across our SaaS product line in Q3 2026. Our current churn rate is 4.2% monthly and we have 2,400 enterprise customers.',
  'Should India impose export controls on rare earth minerals given current geopolitical tensions with China and growing domestic semiconductor manufacturing ambitions?',
  'Our PE fund is evaluating a $200M acquisition of a European wind farm operator with 340MW installed capacity and a pipeline of 500MW in permitting stages.',
  'We\'re considering open-sourcing our core product to compete with a VC-funded competitor who just raised $80M Series C.',
];

const DEPTH_OPTIONS: { value: Depth; label: string; time: string; desc: string }[] = [
  { value: 'quick', label: 'Quick', time: '2-3 min', desc: 'Key insights fast' },
  { value: 'standard', label: 'Standard', time: '5-8 min', desc: 'Balanced analysis' },
  { value: 'deep', label: 'Deep', time: '10-15 min', desc: 'Exhaustive research' },
];

const INITIAL_AGENTS: AgentCard[] = [
  { id: 'decision_parser', label: 'Decision Parser', icon: Search, status: 'pending', progress: 0, message: 'Waiting to start...' },
  { id: 'historian', label: 'Historian', icon: BookOpen, status: 'pending', progress: 0, message: 'Waiting...' },
  { id: 'current_state', label: 'Current State', icon: Radio, status: 'pending', progress: 0, message: 'Waiting...' },
  { id: 'stakeholder_sim', label: 'Stakeholder Sim', icon: Users, status: 'pending', progress: 0, message: 'Waiting...' },
  { id: 'second_order', label: 'Second-Order', icon: GitBranch, status: 'pending', progress: 0, message: 'Waiting...' },
  { id: 'contrarian', label: 'Contrarian', icon: ShieldAlert, status: 'pending', progress: 0, message: 'Waiting...' },
  { id: 'synthesizer', label: 'Synthesizer', icon: Sparkles, status: 'pending', progress: 0, message: 'Waiting...' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

function parseSynthesizerOutput(raw: unknown, depth = 0): BriefData | null {
  if (!raw || depth > 5) return null;

  let text = '';
  if (typeof raw === 'string') {
    text = raw;
  } else if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>;
    // If it has a "response" field (llm_call wrapper), unwrap and recurse
    if (obj.response && typeof obj.response === 'string') {
      return parseSynthesizerOutput(obj.response, depth + 1);
    }
    // If it already has brief fields, use it directly
    if (obj.executive_summary || obj.scenarios || obj.recommendation) {
      return mapToBriefData(obj);
    }
    text = JSON.stringify(obj);
  }

  // Strip markdown code block wrappers — handle multiple formats.
  // The synthesizer output may be truncated (output_message was limited
  // to 5000 chars before the fix) so we must handle partial JSON.
  let cleaned = text;

  // Remove markdown code block delimiters
  const codeBlockMatch = cleaned.match(/```(?:json)?\s*\n?([\s\S]*?)(?:```|$)/);
  if (codeBlockMatch) {
    cleaned = codeBlockMatch[1].trim();
  } else {
    cleaned = cleaned.replace(/^```\s*/, '').replace(/\s*```$/, '').trim();
  }

  // Try parsing the cleaned text
  let obj: Record<string, unknown> = {};
  try {
    obj = JSON.parse(cleaned);
  } catch {
    // Find the outermost JSON object in the text
    const firstBrace = cleaned.indexOf('{');
    const lastBrace = cleaned.lastIndexOf('}');
    if (firstBrace >= 0 && lastBrace > firstBrace) {
      try {
        obj = JSON.parse(cleaned.slice(firstBrace, lastBrace + 1));
      } catch {
        // JSON is truncated — try to repair by closing open braces/brackets
        let partial = cleaned.slice(firstBrace);
        // Count open braces/brackets
        let opens = 0; let openBrackets = 0;
        for (const ch of partial) {
          if (ch === '{') opens++;
          else if (ch === '}') opens--;
          else if (ch === '[') openBrackets++;
          else if (ch === ']') openBrackets--;
        }
        // Truncate at last complete value (before a trailing comma)
        partial = partial.replace(/,\s*"[^"]*"?\s*:?\s*("?[^"{}[\]]*)?$/, '');
        partial += ']'.repeat(Math.max(0, openBrackets)) + '}'.repeat(Math.max(0, opens));
        try {
          obj = JSON.parse(partial);
        } catch {
          return null;
        }
      }
    } else {
      return null;
    }
  }

  // If parsed object has a response wrapper, unwrap it
  if (obj.response && typeof obj.response === 'string' && !obj.executive_summary && !obj.scenarios) {
    return parseSynthesizerOutput(obj.response, depth + 1);
  }

  return mapToBriefData(obj);
}

function mapToBriefData(obj: Record<string, unknown>): BriefData {

  // Map the synthesizer's JSON schema to our BriefData interface
  // The synthesizer may use different field names than our frontend expects
  const scenarios = (obj.scenarios as Array<Record<string, unknown>> || []).map((s) => ({
    title: String(s.name || s.title || 'Scenario'),
    probability: Math.round(Number(s.probability || 0) * (Number(s.probability) <= 1 ? 100 : 1)),
    description: String(s.description || ''),
    drivers: (s.key_drivers || s.drivers || []) as string[],
  }));

  const stakeholders = ((obj.stakeholder_impacts || obj.stakeholder_map || obj.stakeholders || []) as Array<Record<string, unknown>>).map((s: Record<string, unknown>) => ({
    name: String(s.stakeholder || s.name || s.group || 'Stakeholder'),
    impact: String(s.likely_actions?.toString() || s.impact || s.evidence || ''),
    sentiment: (String(s.sentiment || 'neutral')) as 'positive' | 'negative' | 'neutral',
    details: String(s.evidence || s.details || s.timeline || ''),
  }));

  const cascadeEffects = ((obj.cascade_effects || obj.cascadeEffects || []) as Array<Record<string, unknown>>).map((c: Record<string, unknown>) => ({
    order: Number(c.order || 1),
    effect: String(c.effect || c.trigger || ''),
    likelihood: String(c.severity || c.likelihood || c.probability || 'Medium'),
  }));

  const risks = ((obj.contrarian_analysis || obj.risks || []) as Array<Record<string, unknown>>).map((r: Record<string, unknown>) => ({
    title: String(r.argument || r.title || r.name || 'Risk'),
    severity: (String(r.severity || 'medium')) as 'high' | 'medium' | 'low',
    probability: Math.round(Number(r.probability || 0) * (Number(r.probability) <= 1 ? 100 : 1)),
    description: String(r.evidence || r.description || r.mitigation || ''),
  }));

  const rec = obj.recommendation as Record<string, unknown> | string | undefined;
  const recommendation = typeof rec === 'string' ? rec :
    typeof rec === 'object' && rec ? `${rec.action || ''} ${rec.timing ? `(Timing: ${rec.timing})` : ''}`.trim() : '';

  const confidence = obj.confidence_score || obj.confidence || (rec && typeof rec === 'object' ? rec.confidence : null);

  return {
    summary: String(obj.executive_summary || obj.summary || ''),
    confidence: Math.min(100, Math.max(0, Math.round(Number(confidence || 70) * (Number(confidence) <= 1 ? 100 : 1)))),
    recommendation: String(recommendation || ''),
    scenarios,
    stakeholders,
    cascadeEffects,
    risks,
    conditions: (obj.key_assumptions || obj.conditions || []) as string[],
    monitoringTriggers: (obj.monitoring_triggers || obj.monitoringTriggers || []) as string[],
  };
}

function buildErrorBrief(rawOutput: string, agentErrors: Record<string, string>): BriefData {
  const failedAgents = Object.entries(agentErrors);
  const errorSummary = failedAgents.length > 0
    ? `${failedAgents.length} agent(s) failed: ${failedAgents.map(([id, err]) => `${id}: ${err.slice(0, 100)}`).join('; ')}`
    : 'Pipeline completed but output could not be parsed.';

  return {
    summary: rawOutput
      ? `Raw synthesizer output (unparsed):\n\n${rawOutput.slice(0, 3000)}`
      : errorSummary,
    confidence: 0,
    recommendation: '',
    scenarios: [],
    stakeholders: [],
    cascadeEffects: [],
    risks: failedAgents.map(([id, err]) => ({
      title: `Agent failure: ${id}`,
      severity: 'high' as const,
      probability: 100,
      description: err,
    })),
    conditions: [],
    monitoringTriggers: [],
  };
}

// ─── Sub-Components ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: AgentStatus }) {
  const config = {
    pending: { color: 'bg-slate-700 text-slate-400', label: 'Pending' },
    running: { color: 'bg-cyan-500/20 text-cyan-400', label: 'Running' },
    complete: { color: 'bg-emerald-500/20 text-emerald-400', label: 'Complete' },
    failed: { color: 'bg-red-500/20 text-red-400', label: 'Failed' },
  };
  const c = config[status];
  return (
    <span className={cn('text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider', c.color)}>
      {c.label}
    </span>
  );
}

function StatusIcon({ status }: { status: AgentStatus }) {
  switch (status) {
    case 'complete': return <CheckCircle className="w-4 h-4 text-emerald-400" />;
    case 'failed': return <XCircle className="w-4 h-4 text-red-400" />;
    case 'running': return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
    default: return <Clock className="w-4 h-4 text-slate-600" />;
  }
}

function ConfidenceGauge({ value }: { value: number }) {
  const color = value >= 75 ? 'text-emerald-400' : value >= 50 ? 'text-amber-400' : 'text-red-400';
  const bgColor = value >= 75 ? 'bg-emerald-400' : value >= 50 ? 'bg-amber-400' : 'bg-red-400';
  return (
    <div className="flex items-center gap-4">
      <div className="relative w-20 h-20">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgb(30,41,59)" strokeWidth="8" />
          <circle
            cx="50" cy="50" r="42" fill="none" stroke="currentColor"
            strokeWidth="8" strokeLinecap="round"
            strokeDasharray={`${value * 2.64} ${264 - value * 2.64}`}
            className={color}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={cn('text-lg font-bold', color)}>{value}%</span>
        </div>
      </div>
      <div>
        <p className="text-sm text-slate-400">Confidence Level</p>
        <div className="flex items-center gap-2 mt-1">
          <div className={cn('w-2 h-2 rounded-full', bgColor)} />
          <span className={cn('text-sm font-medium', color)}>
            {value >= 75 ? 'High' : value >= 50 ? 'Moderate' : 'Low'} Confidence
          </span>
        </div>
      </div>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: 'positive' | 'negative' | 'neutral' }) {
  const config = {
    positive: { color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', label: 'Positive' },
    negative: { color: 'bg-red-500/20 text-red-400 border-red-500/30', label: 'Negative' },
    neutral: { color: 'bg-amber-500/20 text-amber-400 border-amber-500/30', label: 'Neutral' },
  };
  const c = config[sentiment];
  return (
    <span className={cn('text-xs font-medium px-2 py-0.5 rounded-full border', c.color)}>
      {c.label}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: 'high' | 'medium' | 'low' }) {
  const config = {
    high: 'bg-red-500/20 text-red-400',
    medium: 'bg-amber-500/20 text-amber-400',
    low: 'bg-emerald-500/20 text-emerald-400',
  };
  return (
    <span className={cn('text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase', config[severity])}>
      {severity}
    </span>
  );
}

// ─── Agent Card ──────────────────────────────────────────────────────────────

function AgentCardComponent({ agent, onClick, isSelected }: { agent: AgentCard; onClick?: () => void; isSelected?: boolean }) {
  const Icon = agent.icon;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      onClick={onClick}
      className={cn(
        'relative rounded-xl border p-4 transition-all duration-300 cursor-pointer hover:brightness-110',
        'bg-slate-900/60 backdrop-blur-sm',
        isSelected && 'ring-2 ring-cyan-400/50',
        agent.status === 'running' && 'border-cyan-500/50 shadow-[0_0_20px_rgba(6,182,212,0.15)]',
        agent.status === 'complete' && 'border-emerald-500/30',
        agent.status === 'failed' && 'border-red-500/30',
        agent.status === 'pending' && 'border-slate-700/50',
      )}
    >
      {agent.status === 'running' && (
        <div className="absolute inset-0 rounded-xl border border-cyan-500/30 animate-pulse pointer-events-none" />
      )}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className={cn(
            'w-9 h-9 rounded-lg flex items-center justify-center',
            agent.status === 'running' ? 'bg-cyan-500/20' :
            agent.status === 'complete' ? 'bg-emerald-500/15' :
            agent.status === 'failed' ? 'bg-red-500/15' :
            'bg-slate-800',
          )}>
            <Icon className={cn(
              'w-4.5 h-4.5',
              agent.status === 'running' ? 'text-cyan-400' :
              agent.status === 'complete' ? 'text-emerald-400' :
              agent.status === 'failed' ? 'text-red-400' :
              'text-slate-500',
            )} />
          </div>
          <div>
            <h4 className="text-sm font-medium text-white">{agent.label}</h4>
            {agent.duration != null && (
              <p className="text-[10px] text-slate-500">{formatDuration(agent.duration)}</p>
            )}
          </div>
        </div>
        <StatusIcon status={agent.status} />
      </div>

      <div className="mb-2">
        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <motion.div
            className={cn(
              'h-full rounded-full',
              agent.status === 'running' ? 'bg-cyan-500' :
              agent.status === 'complete' ? 'bg-emerald-500' :
              agent.status === 'failed' ? 'bg-red-500' :
              'bg-slate-700',
            )}
            initial={{ width: 0 }}
            animate={{ width: `${agent.progress}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </div>

      <p className={cn(
        'text-xs truncate',
        agent.status === 'running' ? 'text-cyan-300/70' :
        agent.status === 'complete' ? 'text-emerald-300/60' :
        'text-slate-500',
      )}>
        {agent.message}
      </p>
    </motion.div>
  );
}

// ─── DAG Layout ──────────────────────────────────────────────────────────────

function AgentDAG({ agents, selectedAgent, onSelectAgent }: { agents: AgentCard[]; selectedAgent: string | null; onSelectAgent: (id: string) => void }) {
  const rows = [
    [agents[0]],                         // Decision Parser
    [agents[1], agents[2], agents[3]],   // Historian, Current State, Stakeholder Sim
    [agents[4], agents[5]],              // Second-Order, Contrarian
    [agents[6]],                         // Synthesizer
  ];

  return (
    <div className="space-y-4">
      {rows.map((row, i) => (
        <div key={i} className="flex justify-center gap-4">
          {row.map((agent) => (
            <div key={agent.id} className="w-full max-w-[240px]">
              <AgentCardComponent
                agent={agent}
                isSelected={selectedAgent === agent.id}
                onClick={() => onSelectAgent(agent.id)}
              />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ─── Agent Detail Panel ─────────────────────────────────────────────────────

const AGENT_ENV_VARS: Record<string, string[]> = {
  decision_parser: ['ANTHROPIC_API_KEY or OPENAI_API_KEY'],
  historian: ['TAVILY_API_KEY (or BRAVE_SEARCH_API_KEY, SERPAPI_API_KEY)', 'ANTHROPIC_API_KEY'],
  current_state: ['TAVILY_API_KEY', 'NEWS_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'FRED_API_KEY', 'ANTHROPIC_API_KEY'],
  stakeholder_sim: ['TAVILY_API_KEY', 'ANTHROPIC_API_KEY'],
  second_order: ['TAVILY_API_KEY', 'ANTHROPIC_API_KEY'],
  contrarian: ['TAVILY_API_KEY', 'ANTHROPIC_API_KEY'],
  synthesizer: ['ANTHROPIC_API_KEY (uses strongest model)'],
};

const AGENT_IO: Record<string, { inputs: string[]; output: string; depends: string[] }> = {
  decision_parser: { inputs: ['context.message (user decision prompt)'], output: 'decision_parser.response', depends: [] },
  historian: { inputs: ['decision_parser.response'], output: 'historian.response', depends: ['decision_parser'] },
  current_state: { inputs: ['decision_parser.response'], output: 'current_state.response', depends: ['decision_parser'] },
  stakeholder_sim: { inputs: ['decision_parser.response'], output: 'stakeholder_sim.response', depends: ['decision_parser'] },
  second_order: { inputs: ['decision_parser.response', 'historian.response', 'current_state.response', 'stakeholder_sim.response'], output: 'second_order.response', depends: ['historian', 'current_state', 'stakeholder_sim'] },
  contrarian: { inputs: ['decision_parser.response', 'historian.response', 'current_state.response', 'stakeholder_sim.response'], output: 'contrarian.response', depends: ['historian', 'current_state', 'stakeholder_sim'] },
  synthesizer: { inputs: ['All 5 agent responses via template variables'], output: 'Decision Brief JSON', depends: ['historian', 'current_state', 'stakeholder_sim', 'second_order', 'contrarian'] },
};

const AGENT_TOOLS: Record<string, string[]> = {
  decision_parser: ['llm_call'],
  historian: ['tavily_search', 'http_client', 'academic_search'],
  current_state: ['tavily_search', 'http_client', 'market_data', 'yahoo_finance', 'news_feed', 'current_time'],
  stakeholder_sim: ['tavily_search', 'http_client'],
  second_order: ['tavily_search', 'code_executor', 'financial_calculator'],
  contrarian: ['tavily_search', 'http_client', 'academic_search'],
  synthesizer: ['llm_call'],
};

function AgentDetailPanel({ agent, logs, onClose }: { agent: AgentCard; logs: LogEntry[]; onClose: () => void }) {
  const agentLogs = logs.filter(l => l.agent === agent.id);
  const envVars = AGENT_ENV_VARS[agent.id] || [];
  const tools = AGENT_TOOLS[agent.id] || [];
  const io = AGENT_IO[agent.id];
  const Icon = agent.icon;

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className="bg-slate-900/80 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4 space-y-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">{agent.label}</h3>
          <StatusIcon status={agent.status} />
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white text-xs">Close</button>
      </div>

      {agent.duration != null && (
        <p className="text-xs text-slate-400">Duration: {formatDuration(agent.duration)}</p>
      )}

      <div>
        <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-1">Tools Used</h4>
        <div className="flex flex-wrap gap-1">
          {tools.map(t => (
            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/50 font-mono">{t}</span>
          ))}
        </div>
      </div>

      {io && (
        <div>
          <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-1">Data Flow</h4>
          <div className="space-y-1.5">
            <div>
              <span className="text-[10px] text-slate-500 uppercase">Inputs:</span>
              {io.inputs.map(inp => (
                <p key={inp} className="text-[10px] text-emerald-400/80 font-mono ml-2">{`{{${inp}}}`}</p>
              ))}
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase">Output key:</span>
              <p className="text-[10px] text-amber-400/80 font-mono ml-2">{io.output}</p>
            </div>
            {io.depends.length > 0 && (
              <div>
                <span className="text-[10px] text-slate-500 uppercase">Depends on:</span>
                <div className="flex flex-wrap gap-1 mt-0.5 ml-2">
                  {io.depends.map(d => (
                    <span key={d} className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono">{d}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div>
        <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-1">Required Env Variables</h4>
        <div className="space-y-0.5">
          {envVars.map(v => (
            <p key={v} className="text-[10px] text-slate-500 font-mono">{v}</p>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-1">Activity Log ({agentLogs.length} events)</h4>
        <div className="max-h-40 overflow-y-auto space-y-0.5 bg-slate-950/50 rounded p-2">
          {agentLogs.length === 0 ? (
            <p className="text-[10px] text-slate-600 italic">No activity yet</p>
          ) : (
            agentLogs.map((log, i) => (
              <div key={i} className="flex gap-2 text-[10px]">
                <span className="text-slate-600 shrink-0 font-mono">{log.timestamp.toLocaleTimeString()}</span>
                <span className={cn(
                  log.type === 'success' ? 'text-emerald-400' :
                  log.type === 'error' ? 'text-red-400' : 'text-slate-400',
                )}>{log.message}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Live Feed ───────────────────────────────────────────────────────────────

function LiveFeed({ logs }: { logs: LogEntry[] }) {
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="mt-6 rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-700/50 bg-slate-800/30">
        <Activity className="w-3.5 h-3.5 text-cyan-400" />
        <span className="text-xs font-medium text-slate-300">Live Agent Feed</span>
        <div className="ml-auto flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          <span className="text-[10px] text-slate-500">{logs.length} events</span>
        </div>
      </div>
      <div ref={feedRef} className="max-h-48 overflow-y-auto p-3 space-y-1.5 font-mono text-xs">
        {logs.map((log, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-start gap-2"
          >
            <span className="text-slate-600 shrink-0 w-16">
              {log.timestamp.toLocaleTimeString('en-US', { hour12: false })}
            </span>
            <span className={cn(
              'shrink-0 w-28 truncate font-medium',
              log.type === 'success' ? 'text-emerald-400' :
              log.type === 'error' ? 'text-red-400' :
              'text-cyan-400',
            )}>
              [{log.agent}]
            </span>
            <span className="text-slate-400">{log.message}</span>
          </motion.div>
        ))}
        {logs.length === 0 && (
          <p className="text-slate-600 text-center py-4">Waiting for agent activity...</p>
        )}
      </div>
    </div>
  );
}

// ─── Brief Tabs ──────────────────────────────────────────────────────────────

const BRIEF_TABS = [
  { id: 'summary', label: 'Executive Summary', icon: FileText },
  { id: 'scenarios', label: 'Scenarios', icon: Layers },
  { id: 'stakeholders', label: 'Stakeholders', icon: Users },
  { id: 'cascade', label: 'Cascade Effects', icon: GitBranch },
  { id: 'risks', label: 'Risks', icon: AlertTriangle },
  { id: 'recommendation', label: 'Recommendation', icon: Target },
  { id: 'provenance', label: 'Decision Provenance', icon: Network },
] as const;

type BriefTab = typeof BRIEF_TABS[number]['id'];

function BriefView({ brief }: { brief: BriefData }) {
  const [activeTab, setActiveTab] = useState<BriefTab>('summary');
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const text = JSON.stringify(brief, null, 2);
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [brief]);

  const handleDownloadMd = useCallback(() => {
    let md = `# OracleNet Decision Brief\n\n## Executive Summary\n${brief.summary}\n\n**Confidence:** ${brief.confidence}%\n\n## Recommendation\n${brief.recommendation}\n\n`;
    md += `## Scenarios\n${brief.scenarios.map(s => `### ${s.title} (${s.probability}%)\n${s.description}\n- Drivers: ${s.drivers.join(', ')}`).join('\n\n')}\n\n`;
    md += `## Stakeholders\n${brief.stakeholders.map(s => `### ${s.name} [${s.sentiment}]\n${s.details}`).join('\n\n')}\n\n`;
    md += `## Cascade Effects\n${brief.cascadeEffects.map(e => `- **Order ${e.order}:** ${e.effect} (${e.likelihood})`).join('\n')}\n\n`;
    md += `## Risks\n${brief.risks.map(r => `### ${r.title} [${r.severity}] - ${r.probability}%\n${r.description}`).join('\n\n')}\n\n`;
    md += `## Conditions\n${brief.conditions.map(c => `- ${c}`).join('\n')}\n\n## Monitoring Triggers\n${brief.monitoringTriggers.map(t => `- ${t}`).join('\n')}`;
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'oraclenet-brief.md';
    a.click();
    URL.revokeObjectURL(url);
  }, [brief]);

  const handleDownloadJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(brief, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'oraclenet-brief.json';
    a.click();
    URL.revokeObjectURL(url);
  }, [brief]);

  return (
    <div>
      {/* Export buttons */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <button
          onClick={handleDownloadJson}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 rounded-lg transition-colors"
        >
          <Download className="w-3.5 h-3.5" /> Download JSON
        </button>
        <button
          onClick={handleDownloadMd}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 rounded-lg transition-colors"
        >
          <FileText className="w-3.5 h-3.5" /> Download Markdown
        </button>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 rounded-lg transition-colors"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? 'Copied!' : 'Copy to Clipboard'}
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 overflow-x-auto pb-1 -mx-1 px-1">
        {BRIEF_TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg whitespace-nowrap transition-all',
                activeTab === tab.id
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent',
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
        >
          {activeTab === 'summary' && (
            <div className="space-y-6">
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-6">
                <h3 className="text-lg font-semibold text-white mb-4">Executive Summary</h3>
                <p className="text-sm text-slate-300 leading-relaxed">{brief.summary}</p>
              </div>
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-6">
                <ConfidenceGauge value={brief.confidence} />
              </div>
            </div>
          )}

          {activeTab === 'scenarios' && (
            <div className="grid gap-4 md:grid-cols-2">
              {brief.scenarios.length === 0 && (
                <div className="col-span-2 text-center py-8">
                  <p className="text-sm text-slate-500">No scenarios were extracted from this analysis.</p>
                  <p className="text-xs text-slate-600 mt-1">This may indicate the output was truncated. Try running a new analysis.</p>
                </div>
              )}
              {brief.scenarios.map((s, i) => (
                <div key={i} className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-5">
                  <div className="flex items-start justify-between mb-3">
                    <h4 className="text-sm font-semibold text-white">{s.title}</h4>
                    <span className="text-xs font-bold text-cyan-400">{s.probability}%</span>
                  </div>
                  <div className="w-full h-2 bg-slate-800 rounded-full mb-3 overflow-hidden">
                    <motion.div
                      className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 rounded-full"
                      initial={{ width: 0 }}
                      animate={{ width: `${s.probability}%` }}
                      transition={{ duration: 0.8, delay: i * 0.1 }}
                    />
                  </div>
                  <p className="text-xs text-slate-400 mb-3">{s.description}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {s.drivers.map((d, j) => (
                      <span key={j} className="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-400 rounded-full">
                        {d}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'stakeholders' && (
            <div className="space-y-3">
              {brief.stakeholders.length === 0 && (
                <div className="text-center py-8"><p className="text-sm text-slate-500">No stakeholder analysis extracted.</p><p className="text-xs text-slate-600 mt-1">Try running a new analysis — the output may have been truncated.</p></div>
              )}
              {brief.stakeholders.map((s, i) => (
                <div key={i} className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-5">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-white">{s.name}</h4>
                    <SentimentBadge sentiment={s.sentiment} />
                  </div>
                  <p className="text-xs text-slate-500 mb-2">{s.impact}</p>
                  <p className="text-xs text-slate-400">{s.details}</p>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'cascade' && (
            <div className="space-y-3">
              {[1, 2, 3].map((order) => {
                const effects = brief.cascadeEffects.filter(e => e.order === order);
                if (effects.length === 0) return null;
                return (
                  <div key={order}>
                    <div className="flex items-center gap-2 mb-2">
                      <div className={cn(
                        'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold',
                        order === 1 ? 'bg-cyan-500/20 text-cyan-400' :
                        order === 2 ? 'bg-purple-500/20 text-purple-400' :
                        'bg-amber-500/20 text-amber-400',
                      )}>
                        {order}
                      </div>
                      <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                        {order === 1 ? 'First' : order === 2 ? 'Second' : 'Third'}-Order Effects
                      </span>
                      {order < 3 && <ArrowRight className="w-3.5 h-3.5 text-slate-600 ml-auto" />}
                    </div>
                    <div className="space-y-2 ml-9">
                      {effects.map((e, i) => (
                        <div key={i} className="rounded-lg border border-slate-700/50 bg-slate-900/40 p-3 flex items-center justify-between">
                          <span className="text-xs text-slate-300">{e.effect}</span>
                          <span className={cn(
                            'text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 ml-3',
                            e.likelihood === 'Very High' ? 'bg-red-500/20 text-red-400' :
                            e.likelihood === 'High' ? 'bg-amber-500/20 text-amber-400' :
                            e.likelihood === 'Medium' ? 'bg-cyan-500/20 text-cyan-400' :
                            'bg-slate-700 text-slate-400',
                          )}>
                            {e.likelihood}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {activeTab === 'risks' && (
            <div className="space-y-3">
              {brief.risks
                .sort((a, b) => {
                  const order = { high: 0, medium: 1, low: 2 };
                  return order[a.severity] - order[b.severity];
                })
                .map((r, i) => (
                  <div key={i} className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-5">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className={cn(
                          'w-4 h-4',
                          r.severity === 'high' ? 'text-red-400' :
                          r.severity === 'medium' ? 'text-amber-400' :
                          'text-emerald-400',
                        )} />
                        <h4 className="text-sm font-semibold text-white">{r.title}</h4>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500">{r.probability}% likely</span>
                        <SeverityBadge severity={r.severity} />
                      </div>
                    </div>
                    <p className="text-xs text-slate-400">{r.description}</p>
                    <div className="mt-2 w-full h-1 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          r.severity === 'high' ? 'bg-red-500' :
                          r.severity === 'medium' ? 'bg-amber-500' :
                          'bg-emerald-500',
                        )}
                        style={{ width: `${r.probability}%` }}
                      />
                    </div>
                  </div>
                ))}
            </div>
          )}

          {activeTab === 'recommendation' && (
            <div className="space-y-4">
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-6">
                <h3 className="text-lg font-semibold text-white mb-3">Recommendation</h3>
                <p className="text-sm text-slate-300 leading-relaxed">{brief.recommendation}</p>
              </div>
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-6">
                <h4 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-cyan-400" /> Conditions for Success
                </h4>
                <ul className="space-y-2">
                  {brief.conditions.map((c, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                      <div className="w-1.5 h-1.5 rounded-full bg-cyan-500 mt-1.5 shrink-0" />
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-6">
                <h4 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400" /> Monitoring Triggers
                </h4>
                <ul className="space-y-2">
                  {brief.monitoringTriggers.map((t, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                      <div className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {activeTab === 'provenance' && (
            <ProvenanceDAG brief={brief} />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ─── Provenance DAG ─────────────────────────────────────────────────────────

const AGENT_COLORS: Record<string, { fill: string; border: string }> = {
  input: { fill: '#1e3a5f', border: '#3b82f6' },
  historian: { fill: '#713f12', border: '#f59e0b' },
  current_state: { fill: '#064e3b', border: '#10b981' },
  stakeholder_sim: { fill: '#581c87', border: '#a855f7' },
  second_order: { fill: '#9a3412', border: '#f97316' },
  contrarian: { fill: '#991b1b', border: '#ef4444' },
  synthesizer: { fill: '#1e3a5f', border: '#06b6d4' },
  recommendation: { fill: '#14532d', border: '#22c55e' },
};

function ProvenanceDAG({ brief }: { brief: BriefData }) {
  const [selected, setSelected] = useState<string | null>(null);

  // Build the provenance graph from the brief data
  const nodes: Array<{ id: string; label: string; type: string; detail?: string }> = [
    { id: 'input', label: 'Decision Prompt', type: 'input', detail: brief.summary?.slice(0, 200) },
  ];
  const edges: Array<{ from: string; to: string; label?: string }> = [];

  // Layer 1: historian, current_state, stakeholder_sim
  const layer1 = ['historian', 'current_state', 'stakeholder_sim'];
  const layer2 = ['second_order', 'contrarian'];

  layer1.forEach(a => {
    nodes.push({ id: a, label: a.replace(/_/g, ' '), type: a });
    edges.push({ from: 'input', to: a, label: 'analyzes' });
  });

  // Layer 2 depends on layer 1
  layer2.forEach(a => {
    nodes.push({ id: a, label: a.replace(/_/g, ' '), type: a });
    layer1.forEach(dep => edges.push({ from: dep, to: a, label: 'informs' }));
  });

  // Synthesizer depends on all 5
  nodes.push({ id: 'synthesizer', label: 'Synthesizer', type: 'synthesizer', detail: brief.recommendation?.slice(0, 200) });
  [...layer1, ...layer2].forEach(a => edges.push({ from: a, to: 'synthesizer', label: 'feeds' }));

  // Add insight nodes from scenarios
  brief.scenarios?.forEach((s, i) => {
    const id = `scenario_${i}`;
    nodes.push({ id, label: s.title, type: 'synthesizer', detail: s.description });
    edges.push({ from: 'synthesizer', to: id, label: 'produces' });
  });

  // Final recommendation
  nodes.push({ id: 'recommendation', label: 'Final Recommendation', type: 'recommendation', detail: brief.recommendation });
  edges.push({ from: 'synthesizer', to: 'recommendation', label: 'recommends' });

  // Layout: 5 columns (input → L1 → L2 → synth → outputs)
  const layers: string[][] = [
    ['input'],
    layer1,
    layer2,
    ['synthesizer'],
    ['recommendation', ...brief.scenarios?.map((_, i) => `scenario_${i}`) || []],
  ];

  const nw = 160, nh = 44, gx = 60, gy = 20;
  const positions: Record<string, { x: number; y: number }> = {};
  layers.forEach((layer, col) => {
    const offsetY = (layers.reduce((mx, l) => Math.max(mx, l.length), 0) - layer.length) * (nh + gy) / 2;
    layer.forEach((nid, row) => {
      positions[nid] = { x: 24 + col * (nw + gx), y: 24 + offsetY + row * (nh + gy) };
    });
  });

  const svgWidth = layers.length * (nw + gx) + 48;
  const svgHeight = Math.max(...layers.map(l => l.length)) * (nh + gy) + 80;
  const selNode = nodes.find(n => n.id === selected);

  return (
    <div className="space-y-3" data-testid="provenance-dag">
      <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
          <Network className="w-3.5 h-3.5 text-cyan-400" />
          Decision Provenance Graph
          <span className="text-slate-600 font-normal normal-case">
            ({nodes.length} nodes, {edges.length} connections)
          </span>
        </h3>
        <p className="text-[10px] text-slate-500 mb-3">
          Trace how the 6 agents contributed to the final recommendation. Click any node to see details.
        </p>
        <div className="overflow-x-auto">
          <svg width={svgWidth} height={svgHeight} data-testid="provenance-svg">
            {/* Column labels */}
            {['Prompt', 'Layer 1: Research', 'Layer 2: Analysis', 'Synthesis', 'Outputs'].map((lbl, i) => (
              <text key={i} x={24 + i * (nw + gx) + nw / 2} y={14} textAnchor="middle" fill="#475569" fontSize={9} fontWeight={600}>{lbl}</text>
            ))}
            {/* Edges */}
            {edges.map((e, i) => {
              const from = positions[e.from], to = positions[e.to];
              if (!from || !to) return null;
              return <line key={i} x1={from.x + nw} y1={from.y + nh / 2} x2={to.x} y2={to.y + nh / 2} stroke="#334155" strokeWidth={1.2} markerEnd="url(#prov-arrow)" />;
            })}
            <defs>
              <marker id="prov-arrow" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
                <polygon points="0 0,7 2.5,0 5" fill="#475569" />
              </marker>
            </defs>
            {/* Nodes */}
            {nodes.map(n => {
              const pos = positions[n.id];
              if (!pos) return null;
              const c = AGENT_COLORS[n.type] || AGENT_COLORS.input;
              const isSel = selected === n.id;
              return (
                <g key={n.id} className="cursor-pointer" onClick={() => setSelected(isSel ? null : n.id)} data-testid={`prov-node-${n.id}`}>
                  <rect x={pos.x} y={pos.y} width={nw} height={nh} rx={6} fill={c.fill} stroke={isSel ? '#f59e0b' : c.border} strokeWidth={isSel ? 2.5 : 1.5} />
                  <text x={pos.x + nw / 2} y={pos.y + nh / 2 + 4} textAnchor="middle" fill="#e2e8f0" fontSize={10} fontWeight={500}>
                    {n.label.length > 18 ? n.label.slice(0, 16) + '…' : n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        {selNode && (
          <div className="mt-3 border-t border-slate-700/50 pt-3" data-testid="prov-detail">
            <p className="text-xs font-semibold text-white mb-1">{selNode.label}</p>
            {selNode.detail && <p className="text-[10px] text-slate-400 max-h-20 overflow-y-auto">{selNode.detail}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function OracleNetPage() {
  const [phase, setPhase] = useState<Phase>('input');
  const [query, setQuery] = useState('');
  const [depth, setDepth] = useState<Depth>('standard');
  const [agents, setAgents] = useState<AgentCard[]>(INITIAL_AGENTS);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [brief, setBrief] = useState<BriefData | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [agentErrors, setAgentErrors] = useState<Record<string, string>>({});
  const [rawOutput, setRawOutput] = useState<string>('');
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [pastAnalyses, setPastAnalyses] = useState<PastAnalysis[]>([]);
  const [elapsedTime, setElapsedTime] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const historyRef = useRef<HTMLDivElement>(null);

  const [hasAuth, setHasAuth] = useState(false);

  useEffect(() => {
    setHasAuth(isAuthenticated());
  }, []);

  // Load past analyses from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem('oraclenet_history');
      if (saved) setPastAnalyses(JSON.parse(saved));
    } catch {}
  }, []);

  // Close history dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setShowHistory(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Timer for elapsed time
  useEffect(() => {
    if (phase === 'analyzing') {
      setElapsedTime(0);
      timerRef.current = setInterval(() => setElapsedTime(t => t + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase]);

  const addLog = useCallback((agent: string, message: string, type: LogEntry['type'] = 'info') => {
    setLogs(prev => [...prev, { timestamp: new Date(), agent, message, type }]);
  }, []);

  const updateAgent = useCallback((id: string, updates: Partial<AgentCard>) => {
    setAgents(prev => prev.map(a => a.id === id ? { ...a, ...updates } : a));
  }, []);

  const startAnalysis = useCallback(async () => {
    if (!query.trim()) return;
    setPhase('analyzing');
    setAgents(INITIAL_AGENTS.map(a => ({ ...a })));
    setLogs([]);
    setBrief(null);
    setAnalysisError(null);
    setAgentErrors({});
    setRawOutput('');

    if (hasAuth) {
      // Try real API with SSE
      try {
        abortRef.current = new AbortController();
        const res = await fetch(`${API_URL}/api/oraclenet/analyze`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
          },
          body: JSON.stringify({ decision_prompt: query, depth }),
          signal: abortRef.current.signal,
        });

        if (res.ok && res.headers.get('content-type')?.includes('text/event-stream')) {
          // SSE streaming — parse Abenix's format:
          // "event: node_start\ndata: {json}\n\n"
          // "event: token\ndata: {\"text\":\"...\"}\n\n"  ← final output
          // "event: done\ndata: {metadata}\n\n"           ← signals completion
          const reader = res.body?.getReader();
          const decoder = new TextDecoder();
          if (reader) {
            let buffer = '';
            let currentEventType = '';
            let capturedOutput = ''; // accumulate token events for the final brief
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                // Stream ended — if we captured output, show the brief
                if (capturedOutput && phase !== 'brief') {
                  const parsed = parseSynthesizerOutput(capturedOutput);
                  if (parsed && parsed.summary) {
                    setBrief(parsed);
                  } else {
                    setBrief({
                      ...buildErrorBrief(rawOutput, agentErrors),
                      summary: capturedOutput.slice(0, 5000),
                      confidence: 50,
                    });
                  }
                  setAgents(prev => prev.map(a => ({ ...a, status: 'complete', progress: 100, message: 'Complete' })));
                  setPhase('brief');
                  addLog('synthesizer', 'Decision Brief ready', 'success');
                } else if (!capturedOutput && phase !== 'brief') {
                  // Stream ended without output — use mock
                  setBrief(buildErrorBrief(rawOutput, agentErrors));
                  setAgents(prev => prev.map(a => ({ ...a, status: 'complete', progress: 100, message: 'Complete' })));
                  setPhase('brief');
                }
                break;
              }
              buffer += decoder.decode(value, { stream: true });
              const blocks = buffer.split('\n');
              buffer = blocks.pop() || '';
              for (const line of blocks) {
                // Track the SSE event type line
                if (line.startsWith('event: ')) {
                  currentEventType = line.slice(7).trim();
                  continue;
                }
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.slice(6));
                    const eventType = currentEventType || data.event || '';
                    currentEventType = '';

                    if (eventType === 'node_start') {
                      const nodeId = data.node_id || '';
                      updateAgent(nodeId, {
                        status: 'running',
                        progress: 10,
                        message: `${data.label || data.tool_name || nodeId} started...`,
                      });
                      addLog(nodeId, `Started (${data.tool_name || 'processing'})`, 'info');
                    } else if (eventType === 'node_complete') {
                      const nodeId = data.node_id || '';
                      const isOk = data.status === 'completed' || data.status === 'success';
                      updateAgent(nodeId, {
                        status: isOk ? 'complete' : 'failed',
                        progress: 100,
                        message: isOk ? 'Complete' : (data.error || 'Failed'),
                        duration: data.duration_ms,
                      });
                      addLog(nodeId, isOk ? `Done in ${formatDuration(data.duration_ms || 0)}` : `Failed: ${data.error || 'unknown'}`, isOk ? 'success' : 'error');
                      // Capture per-agent errors for error display
                      if (!isOk && data.error) {
                        setAgentErrors(prev => ({ ...prev, [nodeId]: data.error }));
                      }
                      // Capture output preview for successful agents
                      if (isOk && data.output_preview) {
                        addLog(nodeId, `Output: ${String(data.output_preview).slice(0, 200)}`, 'info');
                      }
                    } else if (eventType === 'node_progress') {
                      updateAgent(data.node_id, {
                        progress: data.progress || 50,
                        message: data.message || 'Processing...',
                      });
                      if (data.message) addLog(data.node_id, data.message, 'info');
                    } else if (eventType === 'token') {
                      // Capture the synthesizer's final output text
                      if (data.text) {
                        capturedOutput += data.text;
                        setRawOutput(capturedOutput); // Store for error display
                      }
                    } else if (eventType === 'done') {
                      // Pipeline complete — parse captured output as Decision Brief
                      addLog('pipeline', `Analysis complete in ${formatDuration(data.duration_ms || 0)}`, 'success');
                      if (capturedOutput) {
                        const parsed = parseSynthesizerOutput(capturedOutput);
                        if (parsed && parsed.summary) {
                          setBrief(parsed);
                        } else {
                          // Try the raw text as a brief summary
                          setBrief({
                            ...buildErrorBrief(rawOutput, agentErrors),
                            summary: capturedOutput.slice(0, 5000),
                            confidence: 50,
                          });
                        }
                      } else {
                        setBrief(buildErrorBrief(rawOutput, agentErrors));
                      }
                      setAgents(prev => prev.map(a => ({ ...a, status: 'complete', progress: 100, message: 'Complete' })));
                      setPhase('brief');
                    } else if (eventType === 'pipeline_complete' || eventType === 'complete') {
                      // Alternative event name
                      const rawOutput = typeof data.output === 'string' ? data.output : JSON.stringify(data.output);
                      const parsed = parseSynthesizerOutput(rawOutput || capturedOutput);
                      if (parsed && parsed.summary) {
                        setBrief(parsed);
                      } else {
                        setBrief(buildErrorBrief(rawOutput, agentErrors));
                      }
                      setAgents(prev => prev.map(a => ({ ...a, status: 'complete', progress: 100, message: 'Complete' })));
                      setPhase('brief');
                    } else if (eventType === 'pipeline_error' || eventType === 'error') {
                      const errMsg = data.error || data.message || 'Pipeline failed';
                      addLog('pipeline', errMsg, 'error');
                      setAnalysisError(errMsg);
                      setBrief(buildErrorBrief(capturedOutput, agentErrors));
                      setPhase('error');
                    }
                  } catch {}
                }
              }
            }
          }
        } else if (res.ok) {
          // Non-streaming: got a session ID, poll for status
          const data = await res.json();
          const sessionId = data.data?.session_id || data.session_id;
          if (sessionId) {
            const pollInterval = setInterval(async () => {
              try {
                const pollRes = await fetch(`${API_URL}/api/oraclenet/sessions/${sessionId}`, {
                  headers: getAuthHeaders(),
                });
                const pollData = await pollRes.json();
                const session = pollData.data || pollData;

                // Update agent states from session
                if (session.agents) {
                  for (const [agentId, agentState] of Object.entries(session.agents as Record<string, { status: AgentStatus; progress?: number; message?: string; duration_ms?: number }>)) {
                    updateAgent(agentId, {
                      status: agentState.status,
                      progress: agentState.progress || (agentState.status === 'complete' ? 100 : 50),
                      message: agentState.message || agentState.status,
                      duration: agentState.duration_ms,
                    });
                  }
                }

                if (session.status === 'completed') {
                  clearInterval(pollInterval);
                  try {
                    const output = typeof session.output === 'string' ? JSON.parse(session.output) : session.output;
                    setBrief(output || buildErrorBrief(rawOutput, agentErrors));
                  } catch {
                    setBrief(buildErrorBrief(rawOutput, agentErrors));
                  }
                  setPhase('brief');
                } else if (session.status === 'failed') {
                  clearInterval(pollInterval);
                  setAnalysisError('Pipeline execution failed. Check agent logs for details.');
                  setBrief(buildErrorBrief(rawOutput, agentErrors));
                  setPhase('error');
                }
              } catch (pollErr) {
                clearInterval(pollInterval);
                setAnalysisError(`Polling error: ${pollErr instanceof Error ? pollErr.message : 'Unknown'}`);
                setPhase('error');
              }
            }, 3000);
          } else {
            setAnalysisError('Unexpected API response format. Expected SSE stream or session ID.');
            setPhase('error');
          }
        } else {
          setAnalysisError(`API returned HTTP ${res.status}. Check that the OracleNet pipeline agent is seeded and the API is running.`);
          setPhase('error');
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setAnalysisError(`Connection error: ${(err as Error).message}. Is the API running?`);
          setPhase('error');
        }
      }
    } else {
      // No auth — show error, not simulation
      setAnalysisError('Authentication required. Log in at the home page or configure NEXT_PUBLIC_ORACLENET_API_KEY in .env.local.');
      setPhase('error');
    }
  }, [query, depth, hasAuth, addLog, updateAgent, agentErrors, rawOutput]);

  const resetAnalysis = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setPhase('input');
    setQuery('');
    setAgents(INITIAL_AGENTS.map(a => ({ ...a })));
    setLogs([]);
    setBrief(null);
    setElapsedTime(0);
  }, []);

  return (
    <div className="min-h-screen bg-[#0B0F19] text-white">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-[#0B0F19]/80 backdrop-blur-xl border-b border-slate-800/50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <a href="/" className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors mr-2">
              <ArrowLeft className="w-4 h-4" />
            </a>
            <img src="/oraclenet-logo.svg" alt="OracleNet" className="w-10 h-10" />
            <div>
              <h1 className="text-sm font-bold text-white leading-tight">OracleNet</h1>
              <p className="text-[10px] text-slate-500 leading-tight">Multi-Agent Decision Intelligence</p>
            </div>
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white hidden sm:inline">
              BETA
            </span>
          </div>

          <div className="flex items-center gap-2">
            {phase === 'analyzing' && (
              <div className="flex items-center gap-2 mr-3">
                <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                <span className="text-xs text-slate-400 font-mono">
                  {Math.floor(elapsedTime / 60)}:{String(elapsedTime % 60).padStart(2, '0')}
                </span>
              </div>
            )}

            {/* History button */}
            <div className="relative" ref={historyRef}>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/50 transition-colors"
              >
                <History className="w-4 h-4" />
                <span className="hidden sm:inline">History</span>
              </button>

              <AnimatePresence>
                {showHistory && (
                  <motion.div
                    initial={{ opacity: 0, y: -5, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -5, scale: 0.97 }}
                    transition={{ duration: 0.15 }}
                    className="absolute right-0 top-full mt-2 w-80 max-h-80 overflow-y-auto rounded-xl border border-slate-700/50 bg-[#0F172A] shadow-2xl z-50"
                  >
                    <div className="p-3 border-b border-slate-700/50">
                      <p className="text-xs font-medium text-slate-400">Past Analyses</p>
                    </div>
                    {pastAnalyses.length === 0 ? (
                      <div className="p-6 text-center">
                        <Clock className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                        <p className="text-xs text-slate-500">No past analyses yet</p>
                      </div>
                    ) : (
                      <div className="p-2 space-y-1">
                        {pastAnalyses.map((a) => (
                          <button
                            key={a.id}
                            onClick={() => {
                              setQuery(a.query);
                              setShowHistory(false);
                              setPhase('input');
                            }}
                            className="w-full text-left p-2.5 rounded-lg hover:bg-slate-800/50 transition-colors group"
                          >
                            <p className="text-xs text-slate-300 truncate group-hover:text-white transition-colors">
                              {a.query}
                            </p>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-[10px] text-slate-600">
                                {new Date(a.date).toLocaleDateString()}
                              </span>
                              <span className="text-[10px] text-cyan-500">{a.confidence}% confidence</span>
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main Content ────────────────────────────────────────────────────── */}
      <main className="pt-14 min-h-screen">
        <AnimatePresence mode="wait">
          {/* ── Phase 1: Input ──────────────────────────────────────────────── */}
          {phase === 'input' && (
            <motion.div
              key="input"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
              className="max-w-3xl mx-auto px-4 sm:px-6 py-12 md:py-20"
            >
              {/* Hero */}
              <div className="text-center mb-10">
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                  className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center mx-auto mb-5 shadow-lg shadow-cyan-500/20"
                >
                  <Brain className="w-8 h-8 text-white" />
                </motion.div>
                <h2 className="text-2xl md:text-3xl font-bold text-white mb-3">
                  OracleNet Decision Intelligence
                </h2>
                <p className="text-sm text-slate-400 max-w-lg mx-auto leading-relaxed">
                  Seven specialized AI agents collaborate to analyze your decision from every angle.
                  Historical precedents, stakeholder dynamics, second-order effects, and contrarian perspectives — synthesized into an actionable brief.
                </p>
              </div>

              {/* Textarea */}
              <div className="relative mb-4">
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Describe the decision you're facing in detail. Include context, constraints, and what you need to decide..."
                  className="w-full h-40 p-4 rounded-xl bg-slate-900/60 border border-slate-700/50 text-sm text-slate-200 placeholder:text-slate-600 resize-none focus:outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500/50 transition-all"
                />
                <div className="absolute bottom-3 right-3 text-[10px] text-slate-600">
                  {query.length} chars
                </div>
              </div>

              {/* Example chips */}
              <div className="mb-6">
                <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-2">Example decisions</p>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLE_PROMPTS.map((prompt, i) => (
                    <button
                      key={i}
                      onClick={() => setQuery(prompt)}
                      className="text-xs text-slate-500 hover:text-cyan-400 px-3 py-1.5 rounded-lg bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/30 hover:border-cyan-500/30 transition-all truncate max-w-[280px]"
                    >
                      {prompt.slice(0, 60)}...
                    </button>
                  ))}
                </div>
              </div>

              {/* Depth selector */}
              <div className="mb-6">
                <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-2">Analysis depth</p>
                <div className="grid grid-cols-3 gap-2">
                  {DEPTH_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setDepth(opt.value)}
                      className={cn(
                        'p-3 rounded-xl border text-left transition-all',
                        depth === opt.value
                          ? 'border-cyan-500/50 bg-cyan-500/10 shadow-[0_0_15px_rgba(6,182,212,0.1)]'
                          : 'border-slate-700/50 bg-slate-900/40 hover:border-slate-600/50',
                      )}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className={cn('text-sm font-medium', depth === opt.value ? 'text-cyan-400' : 'text-slate-300')}>
                          {opt.label}
                        </span>
                        {depth === opt.value && <Zap className="w-3.5 h-3.5 text-cyan-400" />}
                      </div>
                      <p className="text-[10px] text-slate-500">{opt.time}</p>
                      <p className="text-[10px] text-slate-600">{opt.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Auth notice */}
              {!hasAuth && (
                <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                  <p className="text-xs text-cyan-300">
                    <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />
                    Sign in to run real analysis with live agents.{' '}
                    <a href="/" className="text-cyan-400 hover:underline font-medium">Log in here</a>{' '}
                    <span className="text-slate-500">
                      (or set <code className="text-cyan-400/70">NEXT_PUBLIC_ORACLENET_API_KEY</code> in <code className="text-cyan-400/70">.env.local</code>).
                      Without auth, a simulated demo will run.
                    </span>
                  </p>
                </div>
              )}

              {/* Submit button */}
              <button
                onClick={startAnalysis}
                disabled={!query.trim()}
                className={cn(
                  'w-full py-3.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all',
                  query.trim()
                    ? 'bg-gradient-to-r from-cyan-500 to-purple-600 text-white hover:shadow-lg hover:shadow-cyan-500/20 hover:scale-[1.01] active:scale-[0.99]'
                    : 'bg-slate-800 text-slate-600 cursor-not-allowed',
                )}
              >
                <Send className="w-4 h-4" />
                Analyze Decision
              </button>
            </motion.div>
          )}

          {/* ── Phase 2: Analyzing ──────────────────────────────────────────── */}
          {phase === 'analyzing' && (
            <motion.div
              key="analyzing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
              className="max-w-4xl mx-auto px-4 sm:px-6 py-8"
            >
              {/* Query recap */}
              <div className="mb-6 p-4 rounded-xl bg-slate-900/40 border border-slate-700/50">
                <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1">Analyzing</p>
                <p className="text-sm text-slate-300 line-clamp-2">{query}</p>
              </div>

              {/* Progress header */}
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
                  <div>
                    <h3 className="text-sm font-semibold text-white">Agents Working</h3>
                    <p className="text-[10px] text-slate-500">
                      {agents.filter(a => a.status === 'complete').length} of {agents.length} complete
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-xs text-slate-400 font-mono">
                    {Math.floor(elapsedTime / 60)}:{String(elapsedTime % 60).padStart(2, '0')}
                  </p>
                  <p className="text-[10px] text-slate-600">{DEPTH_OPTIONS.find(d => d.value === depth)?.time} est.</p>
                </div>
              </div>

              {/* Overall progress bar */}
              <div className="mb-8">
                <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 rounded-full"
                    animate={{ width: `${Math.round((agents.filter(a => a.status === 'complete').length / agents.length) * 100)}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
              </div>

              {/* Agent DAG + Detail Panel */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2">
                  <AgentDAG agents={agents} selectedAgent={selectedAgent} onSelectAgent={(id) => setSelectedAgent(prev => prev === id ? null : id)} />
                </div>
                <div className="lg:col-span-1">
                  <AnimatePresence mode="wait">
                    {selectedAgent && agents.find(a => a.id === selectedAgent) ? (
                      <AgentDetailPanel
                        key={selectedAgent}
                        agent={agents.find(a => a.id === selectedAgent)!}
                        logs={logs}
                        onClose={() => setSelectedAgent(null)}
                      />
                    ) : (
                      <motion.div
                        key="hint"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="bg-slate-900/40 border border-slate-700/30 rounded-xl p-4 text-center"
                      >
                        <Eye className="w-5 h-5 text-slate-600 mx-auto mb-2" />
                        <p className="text-xs text-slate-500">Click an agent card to view its tools, env variables, and activity log</p>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>

              {/* Live Feed */}
              <LiveFeed logs={logs} />
            </motion.div>
          )}

          {/* ── Phase: Error ──────────────────────────────────────────────── */}
          {phase === 'error' && (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="max-w-3xl mx-auto px-4 sm:px-6 py-8 space-y-6"
            >
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
                  <div>
                    <h2 className="text-lg font-semibold text-red-300">Analysis Failed</h2>
                    <p className="text-sm text-slate-400 mt-1">{analysisError || 'One or more agents encountered errors during execution.'}</p>
                  </div>
                </div>
              </div>

              {/* Per-agent error details */}
              {Object.keys(agentErrors).length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-slate-300">Agent Errors</h3>
                  {Object.entries(agentErrors).map(([agentId, error]) => (
                    <div key={agentId} className="bg-slate-900/60 border border-red-500/20 rounded-lg p-3">
                      <p className="text-xs text-red-400 font-mono font-semibold">{agentId}</p>
                      <p className="text-xs text-slate-400 mt-1 whitespace-pre-wrap">{error}</p>
                    </div>
                  ))}
                </div>
              )}

              {/* Raw output if available */}
              {rawOutput && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-slate-300">Raw Pipeline Output</h3>
                  <pre className="bg-slate-950/80 border border-slate-700/50 rounded-lg p-4 text-xs text-slate-400 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap font-mono">
                    {rawOutput.slice(0, 5000)}
                  </pre>
                </div>
              )}

              {/* Suggestions */}
              <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-2">Troubleshooting</h3>
                <ul className="text-xs text-slate-400 space-y-1.5 list-disc list-inside">
                  <li>Check that <code className="text-cyan-400">ANTHROPIC_API_KEY</code> is set (required for all agents)</li>
                  <li>Check that <code className="text-cyan-400">TAVILY_API_KEY</code> is set (required for web search)</li>
                  <li>Verify your decision prompt is detailed enough (include entity, industry, constraints)</li>
                  <li>Check the Live Agent Feed below for specific tool call failures</li>
                  <li>Try a simpler decision prompt first to verify the pipeline works</li>
                </ul>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3">
                <button
                  onClick={() => { setPhase('input'); setAnalysisError(null); setAgentErrors({}); setRawOutput(''); }}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-semibold"
                >
                  <RotateCcw className="w-4 h-4" />
                  Try Again
                </button>
                {rawOutput && (
                  <button
                    onClick={() => {
                      const blob = new Blob([rawOutput], { type: 'text/plain' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url; a.download = 'oraclenet-raw-output.txt'; a.click();
                      URL.revokeObjectURL(url);
                    }}
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 text-sm"
                  >
                    <Download className="w-4 h-4" />
                    Download Raw Output
                  </button>
                )}
              </div>

              {/* Show live feed even on error */}
              <LiveFeed logs={logs} />
            </motion.div>
          )}

          {/* ── Phase 3: Brief ──────────────────────────────────────────────── */}
          {(phase === 'brief') && brief && (
            <motion.div
              key="brief"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="max-w-4xl mx-auto px-4 sm:px-6 py-8"
            >
              {/* Brief header */}
              <div className="mb-6 p-4 rounded-xl bg-gradient-to-r from-cyan-500/10 to-purple-500/10 border border-cyan-500/20">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <CheckCircle className="w-4 h-4 text-emerald-400" />
                      <h3 className="text-sm font-semibold text-white">Decision Brief Ready</h3>
                    </div>
                    <p className="text-xs text-slate-400 line-clamp-1">{query}</p>
                  </div>
                  <div className="text-right shrink-0 ml-4">
                    <p className="text-lg font-bold text-cyan-400">{brief.confidence}%</p>
                    <p className="text-[10px] text-slate-500">Confidence</p>
                  </div>
                </div>
              </div>

              {/* Brief content */}
              <BriefView brief={brief} />

              {/* New Analysis button */}
              <div className="mt-10 text-center">
                <button
                  onClick={resetAnalysis}
                  className="inline-flex items-center gap-2 px-6 py-3 text-sm font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 rounded-xl transition-colors hover:text-white"
                >
                  <RotateCcw className="w-4 h-4" />
                  New Analysis
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* ── Background Decorations ──────────────────────────────────────────── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden -z-10">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-cyan-500/5 rounded-full blur-[120px]" />
        <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-purple-500/5 rounded-full blur-[120px]" />
      </div>
    </div>
  );
}
