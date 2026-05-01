'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Activity, Bot, Copy, Check, Play, Loader2, AlertCircle, Gauge, Zap, Sparkles, Terminal,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

interface Agent {
  id: string;
  name: string;
  slug?: string;
  description?: string;
  agent_type?: string;
  status?: string;
}

interface Scenario { id: string; label: string; hint: string }

const SCENARIOS: Scenario[] = [
  { id: 'steady_burst',      label: 'Steady burst',       hint: 'N requests spread evenly across the run' },
  { id: 'thundering_herd',   label: 'Thundering herd',    hint: 'All N requests fire at t=0 — stresses cold paths' },
  { id: 'ramp_up',           label: 'Ramp up',            hint: 'concurrency=1 → target over 30s' },
  { id: 'warm_then_spike',   label: 'Warm-up then spike', hint: '10 warm-ups, then full concurrency burst' },
  { id: 'mixed_payloads',    label: 'Mixed payloads',     hint: 'Alternates small and large messages' },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function LoadPlaygroundPage() {
  const { data: agentsResp } = useApi<Agent[]>('/api/agents?limit=100');
  const agents = agentsResp || [];

  const [agentId, setAgentId] = useState<string>('');
  const [scenario, setScenario] = useState<string>('steady_burst');
  const [requests, setRequests] = useState<number>(50);
  const [concurrency, setConcurrency] = useState<number>(10);
  const [sample, setSample] = useState<string>('ping');
  const [userPrompt, setUserPrompt] = useState<string>('');

  const [code, setCode] = useState<string>('');
  const [modelUsed, setModelUsed] = useState<string>('');
  const [generating, setGenerating] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [output, setOutput] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedAgent = agents.find((a) => a.id === agentId);

  useEffect(() => {
    if (!agentId && agents.length > 0) setAgentId(agents[0].id);
  }, [agents, agentId]);

  const generate = async () => {
    if (!agentId) return;
    setGenerating(true);
    setError(null);
    setCode('');
    try {
      const target = agents.find((a) => a.id === agentId);
      const resp = await apiFetch<{ code: string; model_used: string }>('/api/load-playground/generate', {
        method: 'POST',
        body: JSON.stringify({
          target: {
            id: agentId,
            slug: target?.slug || '',
            name: target?.name || '',
            type: 'agent',
          },
          scenario,
          requests,
          concurrency,
          message_sample: sample,
          user_prompt: userPrompt,
        }),
      });
      if (resp.error) throw new Error(String((resp.error as any)?.message || resp.error));
      setCode(resp.data?.code || '');
      setModelUsed(resp.data?.model_used || '');
    } catch (e: any) {
      setError(e?.message || 'generate failed');
    } finally {
      setGenerating(false);
    }
  };

  const execute = async () => {
    if (!code) return;
    setExecuting(true);
    setOutput([]);
    setError(null);
    try {
      const token = localStorage.getItem('access_token') || '';
      const resp = await fetch(`${API_URL}/api/load-playground/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ code }),
      });
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (const chunk of parts) {
          const lines = chunk.split('\n');
          let event = '', data = '';
          for (const l of lines) {
            if (l.startsWith('event: ')) event = l.slice(7).trim();
            else if (l.startsWith('data: ')) data = l.slice(6);
          }
          if (!event) continue;
          try {
            const payload = JSON.parse(data || '{}');
            if (event === 'line') setOutput((xs) => [...xs, payload.text]);
            else if (event === 'status') setOutput((xs) => [...xs, `── ${payload.message}`]);
            else if (event === 'error') {
              setOutput((xs) => [...xs, `ERROR: ${payload.message}`]);
              setError(payload.message);
            } else if (event === 'done') {
              setOutput((xs) => [...xs, `── done (exit ${payload.exit_code ?? '?'})`]);
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e: any) {
      setError(e?.message || 'execute failed');
    } finally {
      setExecuting(false);
    }
  };

  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Gauge className="w-6 h-6 text-cyan-400" /> Load Test Playground
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Pick an agent, describe the load shape, get an AI-generated Python script, then run it live.
            Reports p50/p95/p99 + throughput + failure buckets.
          </p>
        </div>
      </div>

      {/* Config */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Bot className="w-4 h-4 text-cyan-400" /> Target
          </h2>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Agent / Pipeline</label>
            <select
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} {a.agent_type === 'oob' ? '(OOB)' : ''}
                </option>
              ))}
            </select>
            {selectedAgent?.description && (
              <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{selectedAgent.description}</p>
            )}
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Message sample (what every request sends)</label>
            <input
              type="text"
              value={sample}
              onChange={(e) => setSample(e.target.value)}
              placeholder="ping"
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Extra instructions (optional)</label>
            <textarea
              rows={2}
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
              placeholder="e.g. also record HTTP response sizes"
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500 font-mono"
            />
          </div>
        </div>

        <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" /> Load Shape
          </h2>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Scenario</label>
            <select
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
            >
              {SCENARIOS.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
            <p className="text-[11px] text-slate-500 mt-1">{SCENARIOS.find((s) => s.id === scenario)?.hint}</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">Total requests</label>
              <input
                type="number"
                min={1} max={2000}
                value={requests}
                onChange={(e) => setRequests(Math.max(1, Math.min(2000, parseInt(e.target.value) || 0)))}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">Concurrency</label>
              <input
                type="number"
                min={1} max={200}
                value={concurrency}
                onChange={(e) => setConcurrency(Math.max(1, Math.min(200, parseInt(e.target.value) || 0)))}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>
          <button
            onClick={generate}
            disabled={!agentId || generating}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium hover:shadow-lg hover:shadow-cyan-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Generate script
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm px-4 py-2.5 flex items-center gap-2">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {/* Code + Run */}
      {code && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/50">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-semibold text-white">Generated load test</h2>
              {modelUsed && (
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{modelUsed}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={copy}
                className="text-xs px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300 hover:border-cyan-500/50 inline-flex items-center gap-1"
              >
                {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
              <button
                onClick={execute}
                disabled={executing}
                className="text-xs px-3 py-1 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20 inline-flex items-center gap-1 disabled:opacity-50"
              >
                {executing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                {executing ? 'Running…' : 'Run'}
              </button>
            </div>
          </div>
          <pre className="bg-slate-950/70 text-slate-200 text-[11.5px] font-mono px-5 py-4 overflow-x-auto max-h-[520px]">
{code}
          </pre>
        </div>
      )}

      {(output.length > 0 || executing) && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 overflow-hidden">
          <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-800/50">
            <Zap className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Live output</h2>
            {executing && <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-auto" />}
          </div>
          <pre className="bg-slate-950/70 text-slate-200 text-[11.5px] font-mono px-5 py-4 overflow-x-auto max-h-[420px]">
{output.join('\n')}
          </pre>
        </div>
      )}
    </motion.div>
  );
}
