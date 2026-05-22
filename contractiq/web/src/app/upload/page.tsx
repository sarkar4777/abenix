'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, CloudUpload, CheckCircle, Loader2, Clock, AlertCircle, X,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}
function getUser() {
  if (typeof window === 'undefined') return null;
  try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; }
}

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

const CONTRACT_TYPES = ['ppa', 'gas', 'tolling', 'vppa'] as const;

const ACCEPTED_TYPES = [
  'application/pdf',
  'text/plain',
];
const ACCEPTED_EXTENSIONS = ['.pdf', '.txt', '.text'];

const AGENTS = [
  { id: 'document_ingester', name: 'Document Ingester', desc: 'Parse document structure' },
  { id: 'commercial_extractor', name: 'Commercial Extractor', desc: 'Pricing, volumes, escalation' },
  { id: 'technical_extractor', name: 'Technical Extractor', desc: 'Assets, capacity, technology' },
  { id: 'legal_extractor', name: 'Legal Extractor', desc: 'Force majeure, termination, liability' },
  { id: 'financial_extractor', name: 'Financial Extractor', desc: 'Payment terms, guarantees, LDs' },
  { id: 'clause_classifier', name: 'Clause Classifier', desc: 'Categorize & risk-rate clauses' },
  { id: 'asset_registry', name: 'Asset Registry', desc: 'Build structured asset records' },
  { id: 'event_extractor', name: 'Event Extractor', desc: 'Milestones, deadlines, renewals' },
  { id: 'risk_analyzer', name: 'Risk Analyzer', desc: 'Risk scores by category' },
  { id: 'knowledge_graph', name: 'Knowledge Graph', desc: 'Index into Neo4j via Cognify' },
  { id: 'synthesis', name: 'Synthesizer', desc: 'Combine all extracted data' },
];

type AgentStatus = 'pending' | 'running' | 'complete' | 'error';

function isAcceptedFile(f: File): boolean {
  if (ACCEPTED_TYPES.includes(f.type)) return true;
  const ext = '.' + f.name.split('.').pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

export default function ContractIQUploadPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [contractType, setContractType] = useState<string>('ppa');
  const [title, setTitle] = useState('');
  const [partyA, setPartyA] = useState('');
  const [partyB, setPartyB] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [contractId, setContractId] = useState<string | null>(null);
  const [agentStatuses, setAgentStatuses] = useState<Record<string, { status: AgentStatus; progress: number }>>({});
  const [errorMsg, setErrorMsg] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
  }, [router]);

  const acceptFile = useCallback((f: File | null | undefined) => {
    if (!f) return;
    if (isAcceptedFile(f) && f.size <= 50 * 1024 * 1024) {
      setFile(f);
      setErrorMsg('');
      // Auto-derive title from filename so the button isn't blocked
      // when the user forgets to type a title.
      setTitle(prev => prev || f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim());
    } else {
      setErrorMsg('Please upload a PDF or text file under 50MB');
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    acceptFile(e.dataTransfer.files[0]);
  }, [acceptFile]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    acceptFile(e.target.files?.[0]);
  };

  const startExtraction = async (cid: string) => {
    setExtracting(true);
    const initial: Record<string, { status: AgentStatus; progress: number }> = {};
    AGENTS.forEach(a => { initial[a.id] = { status: 'pending', progress: 0 }; });
    setAgentStatuses(initial);

    const token = getToken();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_URL}/api/contractiq/contracts/${cid}/extract`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        setErrorMsg('Extraction failed to start');
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.event === 'status') {
              setAgentStatuses(prev => ({
                ...prev,
                [evt.agent]: {
                  status: evt.status as AgentStatus,
                  progress: evt.status === 'complete' ? 100 : evt.status === 'running' ? 50 : 0,
                },
              }));
            } else if (evt.event === 'done') {
              setContractId(evt.contract_id);
            } else if (evt.event === 'error') {
              setErrorMsg(evt.message || 'Extraction error');
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setErrorMsg(`Extraction error: ${e.message}`);
      }
    }
  };

  const handleUpload = async () => {
    if (!file || !title) { setErrorMsg('Title and file are required'); return; }
    setUploading(true);
    setErrorMsg('');
    try {
      const token = getToken();

      // Upload file via multipart form
      const formData = new FormData();
      formData.append('file', file);
      formData.append('title', title);
      formData.append('contract_type', contractType);
      if (partyA) formData.append('counterparty_a', partyA);
      if (partyB) formData.append('counterparty_b', partyB);

      const res = await fetch(`${API_URL}/api/contractiq/contracts/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        let msg = `HTTP ${res.status}${res.statusText ? ': ' + res.statusText : ''}`;
        try { const j = JSON.parse(text); msg = j.error?.message || j.error || j.detail || msg; } catch {}
        setErrorMsg(msg); setUploading(false); return;
      }
      const json = await res.json();
      if (json.error) { setErrorMsg(json.error.message || json.error || 'Upload failed'); setUploading(false); return; }

      const cid = json.data?.id;
      if (!cid) { setErrorMsg('Upload succeeded but no contract ID returned'); setUploading(false); return; }

      setContractId(cid);
      setUploading(false);

      // Start extraction via SSE
      await startExtraction(cid);
    } catch {
      setErrorMsg('Upload failed. Is the API running?');
      setUploading(false);
    }
  };

  const allComplete = extracting && AGENTS.every(a => agentStatuses[a.id]?.status === 'complete');
  const hasError = extracting && Object.values(agentStatuses).some(s => s.status === 'error');
  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };

  if (!user) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  const statusIcon = (s: AgentStatus) => {
    if (s === 'complete') return <CheckCircle className="w-4 h-4 text-emerald-400" />;
    if (s === 'running') return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
    if (s === 'error') return <AlertCircle className="w-4 h-4 text-red-400" />;
    return <Clock className="w-4 h-4 text-slate-600" />;
  };

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      <div className="p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          <div>
            <h1 className="text-xl font-bold text-white">Upload Contract</h1>
            <p className="text-sm text-slate-400 mt-1">Upload a PPA or gas contract for AI-powered extraction and analysis</p>
          </div>

          {!extracting ? (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">Contract Type</label>
                  <select value={contractType} onChange={e => setContractType(e.target.value)}
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white text-sm focus:border-emerald-500 focus:outline-none">
                    {CONTRACT_TYPES.map(t => <option key={t} value={t}>{t.toUpperCase()}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">Contract Title</label>
                  <input type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Solar PPA - Project Sunrise"
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">Party A (Buyer)</label>
                  <input type="text" value={partyA} onChange={e => setPartyA(e.target.value)} placeholder="e.g. Acme Energy Corp"
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none" />
                </div>
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">Party B (Seller)</label>
                  <input type="text" value={partyB} onChange={e => setPartyB(e.target.value)} placeholder="e.g. SunPower LLC"
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none" />
                </div>
              </div>

              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors ${
                  dragOver ? 'border-emerald-500 bg-emerald-500/5' : file ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-slate-700 hover:border-slate-600'
                }`}
              >
                {file ? (
                  <div className="flex items-center justify-center gap-3">
                    <FileText className="w-8 h-8 text-emerald-400" />
                    <div className="text-left">
                      <p className="text-sm text-white font-medium">{file.name}</p>
                      <p className="text-xs text-slate-400">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                    <button onClick={() => setFile(null)} className="ml-4 text-slate-500 hover:text-red-400"><X className="w-4 h-4" /></button>
                  </div>
                ) : (
                  <>
                    <CloudUpload className="w-10 h-10 text-slate-600 mx-auto mb-3" />
                    <p className="text-sm text-slate-400">Drag and drop your contract file here</p>
                    <p className="text-xs text-slate-600 mt-1">or</p>
                    <label className="inline-block mt-3 px-4 py-2 rounded-lg bg-slate-800 text-sm text-white cursor-pointer hover:bg-slate-700 transition-colors">
                      Browse Files
                      <input type="file" accept=".pdf,.txt,.text" onChange={handleFileSelect} className="hidden" />
                    </label>
                    <p className="text-xs text-slate-600 mt-3">PDF or TXT, max 50MB</p>
                  </>
                )}
              </div>

              {errorMsg && <p className="text-red-400 text-xs flex items-center gap-1"><AlertCircle className="w-3.5 h-3.5" /> {errorMsg}</p>}

              <button onClick={handleUpload} disabled={!file || !title || uploading}
                className="w-full bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold py-3 rounded-lg shadow-lg hover:shadow-emerald-500/30 transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50">
                {uploading ? <><Loader2 className="w-5 h-5 animate-spin" /> Uploading…</> : <><Upload className="w-4 h-4" /> Upload &amp; Extract</>}
              </button>
              {!file && <p className="text-[11px] text-slate-500 text-center">Select a file to enable upload.</p>}
              {file && !title && <p className="text-[11px] text-amber-400 text-center">Enter a title to enable upload.</p>}
            </motion.div>
          ) : (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white mb-4">Extraction Pipeline — 10 AI Agents</h2>
                <div className="grid grid-cols-2 gap-3">
                  {AGENTS.map(agent => {
                    const st = agentStatuses[agent.id] || { status: 'pending' as AgentStatus, progress: 0 };
                    return (
                      <motion.div key={agent.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
                        className={`border rounded-lg p-3 transition-colors ${
                          st.status === 'complete' ? 'border-emerald-500/30 bg-emerald-500/5' :
                          st.status === 'running' ? 'border-cyan-500/30 bg-cyan-500/5' :
                          st.status === 'error' ? 'border-red-500/30 bg-red-500/5' :
                          'border-slate-700/50 bg-slate-800/20'
                        }`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-white">{agent.name}</span>
                          {statusIcon(st.status)}
                        </div>
                        <p className="text-[10px] text-slate-500 mb-2">{agent.desc}</p>
                        <div className="h-1 bg-slate-700/50 rounded-full overflow-hidden">
                          <motion.div className={`h-full rounded-full ${
                            st.status === 'complete' ? 'bg-emerald-500' :
                            st.status === 'error' ? 'bg-red-500' : 'bg-cyan-500'
                          }`}
                            initial={{ width: 0 }} animate={{ width: `${st.progress}%` }} transition={{ duration: 0.3 }} />
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </div>

              {errorMsg && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
                  <p className="text-sm text-red-400 flex items-center gap-2"><AlertCircle className="w-4 h-4" /> {errorMsg}</p>
                </div>
              )}

              {allComplete && (
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                  className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-5 text-center">
                  <CheckCircle className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
                  <p className="text-sm text-white font-medium">Extraction Complete</p>
                  <p className="text-xs text-slate-400 mt-1">All 10 agents have finished analyzing your contract.</p>
                  <div className="flex items-center justify-center gap-3 mt-4">
                    {contractId && (
                      <a href={`/contracts/${contractId}`}
                        className="px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
                        View Contract Details
                      </a>
                    )}
                    <a href="/contracts" className="px-4 py-2 rounded-lg bg-slate-700 text-white text-sm font-medium hover:bg-slate-600 transition-colors">
                      All Contracts
                    </a>
                  </div>
                </motion.div>
              )}
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
