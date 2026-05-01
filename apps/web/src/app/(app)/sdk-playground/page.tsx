'use client';

import { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Code2, Sparkles, Play, Copy, Check, Loader2, Terminal,
  FileCode2, Boxes, Zap, AlertCircle, Database, BookOpen,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

interface Asset {
  id: string;
  name: string;
  slug?: string;
  description?: string;
  agent_type?: string;
  category?: string;
}

interface UseCase {
  id: string;
  label: string;
  description: string;
}

const USE_CASES: UseCase[] = [
  { id: 'one_shot', label: 'One-Shot Execution', description: 'Simple execute() call' },
  { id: 'stream', label: 'Streaming', description: 'Stream events as they arrive' },
  { id: 'chat_create', label: 'Chat · Create thread', description: 'Start a persistent chat thread' },
  { id: 'chat_send', label: 'Chat · Send turn', description: 'Append a user msg, get response, persist' },
  { id: 'chat_list', label: 'Chat · List threads', description: 'List my saved threads (sidebar)' },
  { id: 'chat_history', label: 'Chat · Get history', description: 'Fetch full thread + messages' },
  { id: 'chat_delegated', label: 'Chat · Delegated (act_as)', description: 'Standalone-app delegation pattern' },
  { id: 'kb_search', label: 'KB Search', description: 'Hybrid vector + graph search' },
  { id: 'kb_cognify', label: 'Cognify', description: 'Build knowledge graph' },
  { id: 'kb_subject', label: 'KB · Subject collection', description: 'Per-user KB namespace' },
  { id: 'batch', label: 'Batch', description: 'Process multiple inputs' },
  { id: 'hitl', label: 'HITL', description: 'Human-in-the-loop gates' },
  { id: 'custom', label: 'Custom', description: 'AI generates from description' },
];

export default function SDKPlaygroundPage() {
  const { data: agents } = useApi<Asset[]>('/api/agents?limit=100');
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [sdk, setSdk] = useState<'python' | 'typescript'>('python');
  const [useCase, setUseCase] = useState<string>('one_shot');
  const [userPrompt, setUserPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [code, setCode] = useState('');
  const [explanation, setExplanation] = useState('');
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState('');
  const [stderr, setStderr] = useState('');
  const [copied, setCopied] = useState(false);
  const [search, setSearch] = useState('');

  const filteredAgents = (agents || []).filter(a =>
    !search ||
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.slug?.toLowerCase().includes(search.toLowerCase())
  );

  const generate = async () => {
    if (!selectedAsset) return;
    setGenerating(true);
    setCode('');
    setExplanation('');
    setOutput('');
    setStderr('');
    try {
      const res = await apiFetch<any>('/api/sdk-playground/generate', {
        method: 'POST',
        body: JSON.stringify({
          asset: { type: 'agent', id: selectedAsset.id, slug: selectedAsset.slug, name: selectedAsset.name },
          sdk,
          use_case: useCase,
          user_prompt: userPrompt,
        }),
      });
      const data = res.data || {};
      setCode(data.code || '');
      setExplanation(data.explanation || '');
    } catch (e) {
      setCode(`// Error: ${e}`);
    }
    setGenerating(false);
  };

  const runCode = async () => {
    if (!code) return;
    setRunning(true);
    setOutput('');
    setStderr('');
    try {
      // Raw fetch for SSE streaming
      const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const res = await fetch(`${apiUrl}/api/sdk-playground/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ code, language: sdk }),
      });
      if (!res.body) {
        setStderr('No response body');
        setRunning(false);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) currentEvent = line.slice(7).trim();
          else if (line.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));
              if (currentEvent === 'stdout') setOutput(p => p + (data.text || ''));
              else if (currentEvent === 'stderr') setStderr(p => p + (data.text || ''));
              else if (currentEvent === 'error') setStderr(p => p + (data.message || '') + '\n');
            } catch { /* skip */ }
            currentEvent = '';
          }
        }
      }
    } catch (e) {
      setStderr(String(e));
    }
    setRunning(false);
  };

  const copyCode = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
              <Code2 className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                SDK Code Playground
                <Sparkles className="w-4 h-4 text-purple-400" />
              </h1>
              <p className="text-sm text-slate-400">Generate SDK code, test it, ship it to your product.</p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Left: Configuration */}
          <div className="col-span-4 space-y-4">
            {/* Asset Picker */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <label className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Boxes className="w-3.5 h-3.5 text-cyan-400" /> Select Agent
              </label>
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search agents..."
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none mb-2"
              />
              <div className="max-h-60 overflow-y-auto space-y-1">
                {filteredAgents.map(a => (
                  <button
                    key={a.id}
                    onClick={() => setSelectedAsset(a)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                      selectedAsset?.id === a.id
                        ? 'bg-cyan-500/10 border border-cyan-500/30 text-white'
                        : 'border border-transparent text-slate-400 hover:bg-slate-800/50 hover:text-white'
                    }`}
                  >
                    <div className="font-medium">{a.name}</div>
                    {a.slug && <div className="text-[10px] text-slate-500 font-mono">{a.slug}</div>}
                  </button>
                ))}
              </div>
            </div>

            {/* SDK Picker */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <label className="text-xs font-semibold text-white uppercase tracking-wider mb-3 block">SDK</label>
              <div className="grid grid-cols-2 gap-2">
                {(['python', 'typescript'] as const).map(s => (
                  <button
                    key={s}
                    onClick={() => setSdk(s)}
                    className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                      sdk === s
                        ? 'bg-gradient-to-r from-cyan-500/20 to-purple-500/20 border border-cyan-500/30 text-white'
                        : 'bg-slate-900/30 border border-slate-700 text-slate-400 hover:text-white'
                    }`}
                  >
                    {s === 'python' ? 'Python' : 'TypeScript'}
                  </button>
                ))}
              </div>
            </div>

            {/* Use Case Picker */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <label className="text-xs font-semibold text-white uppercase tracking-wider mb-3 block">Use Case</label>
              <div className="space-y-1">
                {USE_CASES.map(uc => (
                  <button
                    key={uc.id}
                    onClick={() => setUseCase(uc.id)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                      useCase === uc.id
                        ? 'bg-purple-500/10 border border-purple-500/30 text-white'
                        : 'border border-transparent text-slate-400 hover:bg-slate-800/50 hover:text-white'
                    }`}
                  >
                    <div className="font-medium">{uc.label}</div>
                    <div className="text-[10px] text-slate-500">{uc.description}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Custom Prompt */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <label className="text-xs font-semibold text-white uppercase tracking-wider mb-2 block">
                Refine (optional)
              </label>
              <textarea
                value={userPrompt}
                onChange={e => setUserPrompt(e.target.value)}
                placeholder="e.g., Add retry logic, handle rate limits, batch 10 inputs..."
                rows={3}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none resize-none"
              />
              <button
                onClick={generate}
                disabled={!selectedAsset || generating}
                className="w-full mt-3 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-xs font-semibold py-2.5 rounded-lg hover:shadow-lg hover:shadow-cyan-500/20 disabled:opacity-30 transition-all flex items-center justify-center gap-2"
              >
                {generating ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</> : <><Sparkles className="w-3.5 h-3.5" /> Generate Code</>}
              </button>
            </div>
          </div>

          {/* Right: Code & Output */}
          <div className="col-span-8 space-y-4">
            {/* Code Block */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
                <div className="flex items-center gap-2">
                  <FileCode2 className="w-4 h-4 text-cyan-400" />
                  <span className="text-xs font-semibold text-white">Generated Code</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-300">{sdk}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={copyCode}
                    disabled={!code}
                    className="px-3 py-1.5 text-[10px] rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 disabled:opacity-30 transition-colors flex items-center gap-1"
                  >
                    {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />} {copied ? 'Copied' : 'Copy'}
                  </button>
                  <button
                    onClick={runCode}
                    disabled={!code || running || sdk !== 'python'}
                    title={sdk !== 'python' ? 'In-browser execution is Python-only. Copy the snippet and run it locally with Node + @abenix/sdk.' : 'Run code in sandbox'}
                    className="px-3 py-1.5 text-[10px] rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-30 transition-colors flex items-center gap-1"
                  >
                    {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />} Run
                  </button>
                </div>
              </div>
              <pre className="p-4 text-xs text-slate-300 font-mono overflow-x-auto min-h-[300px] max-h-[500px] overflow-y-auto">
                {code || (
                  <span className="text-slate-600">
                    {selectedAsset ? 'Click "Generate Code" to create SDK code for ' + selectedAsset.name : 'Select an agent to start'}
                  </span>
                )}
              </pre>
            </div>

            {/* Explanation */}
            {explanation && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <BookOpen className="w-4 h-4 text-cyan-400 mt-0.5" />
                  <p className="text-xs text-slate-300 leading-relaxed">{explanation}</p>
                </div>
              </motion.div>
            )}

            {/* Output Panel */}
            {(output || stderr || running) && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
                  <div className="flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-emerald-400" />
                    <span className="text-xs font-semibold text-white">Output</span>
                  </div>
                  {running && <Loader2 className="w-3 h-3 animate-spin text-emerald-400" />}
                </div>
                <div className="p-4 space-y-2 max-h-[300px] overflow-y-auto">
                  {output && (
                    <pre className="text-xs text-emerald-400 font-mono whitespace-pre-wrap">{output}</pre>
                  )}
                  {stderr && (
                    <div className="border-l-2 border-red-500 pl-3">
                      <pre className="text-xs text-red-400 font-mono whitespace-pre-wrap">{stderr}</pre>
                    </div>
                  )}
                </div>
              </div>
            )}

            {sdk === 'typescript' && code && (
              <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-3 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-amber-400 mt-0.5" />
                <p className="text-xs text-slate-300">
                  TypeScript execution is coming soon. Copy the code and run it in your own Node.js environment.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
