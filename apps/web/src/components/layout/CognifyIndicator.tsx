'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, Loader2, Network, XCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS = 4000;

type Job = {
  id: string;
  kb_id: string;
  kb_name: string;
  status: string;
  documents_processed: number;
  entities_extracted: number;
  relationships_extracted: number;
  tokens_used: number;
  cost_usd: number;
  duration_seconds: number | null;
  created_at: string | null;
  completed_at: string | null;
  error_message: string | null;
};

type State = { running: Job[]; recent: Job[] };

const STATUS_LABEL: Record<string, string> = {
  pending: 'queued',
  extracting: 'extracting entities',
  resolving: 'resolving entities',
  graphing: 'writing graph',
  embedding: 'embedding',
  complete: 'complete',
  failed: 'failed',
};

function fmtDuration(seconds: number | null): string {
  if (!seconds || seconds < 1) return '';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

export default function CognifyIndicator() {
  const router = useRouter();
  const [state, setState] = useState<State>({ running: [], recent: [] });
  const [open, setOpen] = useState(false);
  const popRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
        if (!token) return;
        const res = await fetch(`${API_URL}/api/knowledge-engines/cognify/active`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const body = await res.json();
        if (!cancelled && body?.data) setState(body.data);
      } catch {
        /* ignore */
      }
    };

    const schedule = () => {
      const delay = state.running.length === 0 ? POLL_MS * 4 : POLL_MS;
      timer = setTimeout(async () => {
        await tick();
        if (!cancelled) schedule();
      }, delay);
    };

    tick();
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [state.running.length]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (
        popRef.current && !popRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  const running = state.running.length;
  const failedRecently = state.recent.filter(j => j.status === 'failed').length;
  const completedRecently = state.recent.filter(j => j.status === 'complete').length;

  if (running === 0 && failedRecently === 0 && completedRecently === 0) return null;

  const tone = running > 0
    ? { ring: 'border-cyan-500/40', text: 'text-cyan-300', bg: 'bg-cyan-500/10', dot: 'bg-cyan-400' }
    : failedRecently > 0
    ? { ring: 'border-rose-500/40', text: 'text-rose-300', bg: 'bg-rose-500/10', dot: 'bg-rose-400' }
    : { ring: 'border-emerald-500/40', text: 'text-emerald-300', bg: 'bg-emerald-500/10', dot: 'bg-emerald-400' };

  const label = running > 0
    ? `Cognify · ${running}`
    : failedRecently > 0
    ? `Cognify · ${failedRecently} failed`
    : `Cognify · done`;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={() => setOpen(o => !o)}
        title={running > 0
          ? `Cognify is processing ${running} knowledge base${running === 1 ? '' : 's'}`
          : failedRecently > 0
          ? `${failedRecently} cognify job${failedRecently === 1 ? '' : 's'} failed in the last hour`
          : `${completedRecently} cognify job${completedRecently === 1 ? '' : 's'} completed in the last hour`}
        className={`flex items-center gap-1.5 h-7 pl-2 pr-2.5 rounded-full border ${tone.ring} ${tone.bg} ${tone.text} text-[11px] font-medium hover:brightness-125 transition-all`}
        data-testid="cognify-indicator"
      >
        {running > 0 ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : failedRecently > 0 ? (
          <XCircle className="w-3 h-3" />
        ) : (
          <CheckCircle2 className="w-3 h-3" />
        )}
        <span>{label}</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            ref={popRef}
            initial={{ opacity: 0, y: -6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.96 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-9 w-80 bg-slate-800 border border-slate-700/60 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-[100]"
          >
            <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
              <Network className="w-4 h-4 text-cyan-400" />
              <h3 className="text-sm font-semibold text-white">Knowledge graph indexing</h3>
            </div>
            <div className="max-h-[320px] overflow-y-auto">
              {state.running.length === 0 && state.recent.length === 0 ? (
                <p className="px-4 py-6 text-xs text-slate-500 text-center">No activity right now.</p>
              ) : (
                <>
                  {state.running.length > 0 && (
                    <div className="px-2 py-2">
                      <p className="px-2 text-[10px] uppercase tracking-wider text-slate-500 mb-1">Running</p>
                      {state.running.map(j => (
                        <button
                          key={j.id}
                          onClick={() => { setOpen(false); router.push(`/knowledge/${j.kb_id}/engine`); }}
                          className="w-full text-left px-2 py-2 rounded-lg hover:bg-slate-700/40 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <Loader2 className="w-3 h-3 text-cyan-400 animate-spin shrink-0" />
                            <p className="text-xs text-white font-medium truncate flex-1">{j.kb_name}</p>
                            <span className="text-[10px] text-cyan-300 shrink-0">{STATUS_LABEL[j.status] || j.status}</span>
                          </div>
                          <p className="text-[10px] text-slate-500 mt-0.5 ml-5 truncate">
                            {j.documents_processed} docs · {j.entities_extracted} entities · {j.relationships_extracted} rels
                          </p>
                        </button>
                      ))}
                    </div>
                  )}
                  {state.recent.length > 0 && (
                    <div className="px-2 py-2 border-t border-slate-700/30">
                      <p className="px-2 text-[10px] uppercase tracking-wider text-slate-500 mb-1">Recent</p>
                      {state.recent.map(j => (
                        <button
                          key={j.id}
                          onClick={() => { setOpen(false); router.push(`/knowledge/${j.kb_id}/engine`); }}
                          className="w-full text-left px-2 py-2 rounded-lg hover:bg-slate-700/40 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            {j.status === 'complete' ? (
                              <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                            ) : (
                              <XCircle className="w-3 h-3 text-rose-400 shrink-0" />
                            )}
                            <p className="text-xs text-white font-medium truncate flex-1">{j.kb_name}</p>
                            <span className={`text-[10px] shrink-0 ${j.status === 'complete' ? 'text-emerald-300' : 'text-rose-300'}`}>
                              {j.status}{fmtDuration(j.duration_seconds) ? ` · ${fmtDuration(j.duration_seconds)}` : ''}
                            </span>
                          </div>
                          {j.status === 'failed' && j.error_message ? (
                            <p className="text-[10px] text-rose-400/80 mt-0.5 ml-5 truncate" title={j.error_message}>
                              {j.error_message.slice(0, 80)}
                            </p>
                          ) : (
                            <p className="text-[10px] text-slate-500 mt-0.5 ml-5 truncate">
                              {j.entities_extracted} entities · {j.relationships_extracted} rels
                            </p>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
