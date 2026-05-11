'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Inbox, ShieldAlert, Loader2, CheckCircle2, Brain } from 'lucide-react';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { INBOX_EXPLAINER } from '../components/explainer-specs';

const INBOX_PIPELINE = [
  { id: 'wingman-broker-classifier', label: 'Classifier', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'sklearn TF-IDF + LR via ml_model tool' },
  { id: 'ml_model', label: 'ML model', icon: 'cpu' as const, hint: 'deployed broker-intent-classifier v1.0.0' },
  { id: 'wingman-broker-parser', label: 'Parser', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'extract structured offer fields' },
  { id: 'approval_gate', label: 'HITL gate', kind: 'sink' as const, icon: 'shield' as const, hint: 'acknowledge approval' },
];

// DagDrawer takes the same shape; strip the agent-slug rows so only real
// tool steps end up as chips (matches the workbench page pattern).
const INBOX_EXPECTED_TOOLS = INBOX_PIPELINE
  .filter((p) => !p.id.startsWith('wingman-'))
  .map((p) => ({ id: p.id, label: p.label, hint: p.hint }));

interface Email { id: string; received_at: string; from: string; subject: string; body: string; }
interface Offer { id?: string; volume_mt?: number; grade?: string; port?: string; pricing?: string; basis?: string; validity?: string; quality_terms?: string; counterparty?: string; }
interface Classification { predicted_intent?: string; confidence?: number; top_3?: Array<{ label: string; p: number }>; urgency_score?: number; data_sources?: string[]; }

export default function InboxPage() {
  const [emails, setEmails] = useState<Email[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [parsed, setParsed] = useState<Record<string, Offer>>({});
  const [classifications, setClassifications] = useState<Record<string, Classification>>({});
  const [parsing, setParsing] = useState<string | null>(null);
  const [classifying, setClassifying] = useState<string | null>(null);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);
  const [acks, setAcks] = useState<Record<string, string>>({});
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    fetch('/api/wingman/inbox').then((r) => r.json()).then((j) => setEmails(j.data || []));
    const live = pollers.current;
    return () => {
      Object.values(live).forEach((t) => clearInterval(t));
    };
  }, []);

  const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);

  const classify = async (id: string) => {
    setClassifying(id);
    try {
      const r = await fetch(`/api/wingman/inbox/${id}/classify`, { method: 'POST' });
      const j = await r.json();
      const data = j.data;
      if (!data?.execution_id) {
        setClassifying(null);
        return;
      }
      // Open the DAG drawer first — SSE subscribes while the agent is still
      // running, so chips light up live instead of after-the-fact.
      setActiveExecution(data.execution_id);
      const t = setInterval(async () => {
        try {
          const rr = await fetch(`/api/wingman/classify-result/${data.execution_id}`);
          const jj = await rr.json();
          const status = (jj?.data?.status || '').toLowerCase();
          if (TERMINAL.has(status)) {
            setClassifications((prev) => ({ ...prev, [id]: jj.data?.classification || {} }));
            setClassifying((prev) => (prev === id ? null : prev));
            clearInterval(t);
            delete pollers.current[data.execution_id];
          }
        } catch { /* keep polling */ }
      }, 1500);
      pollers.current[data.execution_id] = t;
    } catch {
      setClassifying(null);
    }
  };

  const parse = async (id: string) => {
    setParsing(id);
    setSelected(id);
    try {
      const r = await fetch(`/api/wingman/inbox/${id}/parse`, { method: 'POST' });
      const j = await r.json();
      const data = j.data;
      if (!data?.execution_id) {
        setParsing(null);
        return;
      }
      setActiveExecution(data.execution_id);
      const t = setInterval(async () => {
        try {
          const rr = await fetch(`/api/wingman/parse-result/${data.execution_id}`);
          const jj = await rr.json();
          const status = (jj?.data?.status || '').toLowerCase();
          if (TERMINAL.has(status)) {
            setParsed((prev) => ({ ...prev, [id]: jj.data?.offer || {} }));
            setParsing((prev) => (prev === id ? null : prev));
            clearInterval(t);
            delete pollers.current[data.execution_id];
          }
        } catch { /* keep polling */ }
      }, 1500);
      pollers.current[data.execution_id] = t;
    } catch {
      setParsing(null);
    }
  };

  const acknowledge = async (offerId: string, emailId: string) => {
    const r = await fetch(`/api/wingman/offers/${offerId}/acknowledge`, { method: 'POST' });
    const j = await r.json();
    const aId = j?.data?.approval_id;
    if (aId) setAcks((prev) => ({ ...prev, [emailId]: aId }));
  };

  const classifiedCount = Object.keys(classifications).length;
  const parsedCount = Object.keys(parsed).length;

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="BROKER INBOX"
        title="Two hundred broker emails. One screen."
        subtitle="An ML intent classifier returns confidence + urgency on every email. A second pass extracts structured offer fields. Acknowledge runs through an HITL approval gate."
        rightSlot={
          <div className="flex items-center gap-3 text-[10px]">
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">queue</span>
              <span className="text-xs font-mono font-semibold text-white">{emails.length}</span>
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">classified</span>
              <span className="text-xs font-mono font-semibold text-cyan-300">{classifiedCount}</span>
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">parsed</span>
              <span className="text-xs font-mono font-semibold text-emerald-300">{parsedCount}</span>
            </span>
          </div>
        }
      />

      <ExplainerPanel spec={INBOX_EXPLAINER} />

      <PipelineStrip
        title="Pipeline · 2 agents · ML model · HITL gate"
        subtitle="Click classify or parse on any email — the ML model and parser fire in turn"
        nodes={INBOX_PIPELINE}
        executionId={activeExecution}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {emails.map((e) => {
          const offer = parsed[e.id];
          const ackId = acks[e.id];
          const cls = classifications[e.id];
          const conf = cls?.confidence ?? 0;
          const urgency = cls?.urgency_score ?? 0;
          return (
            <motion.div
              key={e.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className={`rounded-xl border ${selected === e.id ? 'border-emerald-500/40' : 'border-slate-800'} bg-slate-900/30 p-5`}
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                    <Inbox className="w-3 h-3" /> {e.from}
                  </div>
                  <div className="text-base font-semibold text-white mt-1">{e.subject}</div>
                  <div className="text-[10px] text-slate-600 mt-0.5">{new Date(e.received_at).toLocaleString()}</div>
                </div>
                {cls?.predicted_intent && (
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-[10px] uppercase tracking-wider font-bold border border-cyan-500/40 bg-cyan-500/10 text-cyan-200 rounded px-2 py-0.5">
                      {cls.predicted_intent}
                    </span>
                    <span className="text-[9px] text-slate-500 font-mono">
                      {(conf * 100).toFixed(0)}% conf
                      {urgency > 0.4 && <span className="ml-1.5 text-amber-300">· urgent {(urgency * 100).toFixed(0)}%</span>}
                    </span>
                  </div>
                )}
              </div>

              <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans bg-slate-950/40 rounded-lg p-3 mb-3 max-h-40 overflow-y-auto">{e.body}</pre>

              <div className="flex gap-2 mb-2">
                {!cls && (
                  <button
                    onClick={() => classify(e.id)}
                    disabled={classifying === e.id}
                    className="flex-1 px-3 py-2 rounded-lg border border-purple-500/40 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 text-xs font-semibold flex items-center justify-center gap-2"
                  >
                    {classifying === e.id ? <><Loader2 className="w-3 h-3 animate-spin" /> ML classifying...</> : <><Brain className="w-3 h-3" /> Classify intent (ML)</>}
                  </button>
                )}
                {!offer && (
                  <button
                    onClick={() => parse(e.id)}
                    disabled={parsing === e.id}
                    className="flex-1 px-3 py-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 text-xs font-semibold flex items-center justify-center gap-2"
                  >
                    {parsing === e.id ? <><Loader2 className="w-3 h-3 animate-spin" /> Parsing...</> : 'Extract structured offer'}
                  </button>
                )}
              </div>

              {cls?.top_3 && cls.top_3.length > 0 && !offer && (
                <div className="mb-2 px-3 py-2 rounded-lg border border-slate-800 bg-slate-950/40">
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">ML model top-3</div>
                  <div className="flex gap-2">
                    {cls.top_3.map((t, i) => (
                      <div key={i} className="flex-1">
                        <div className="text-[10px] text-slate-300 truncate">{t.label}</div>
                        <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                          <div className="h-full bg-cyan-400" style={{ width: `${Math.max(0, Math.min(1, t.p)) * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {offer && (
                <div className="border border-emerald-500/30 bg-emerald-500/5 rounded-lg p-3 mb-2 space-y-1.5 text-xs">
                  <div className="flex items-center gap-2 mb-1">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    <span className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300">Structured offer</span>
                  </div>
                  <Row k="Volume"   v={offer.volume_mt ? `${offer.volume_mt} MT` : '?'} />
                  <Row k="Grade"    v={offer.grade || '?'} />
                  <Row k="Port"     v={offer.port || '?'} />
                  <Row k="Pricing"  v={offer.pricing || '?'} />
                  <Row k="Validity" v={offer.validity || '?'} />
                  {offer.quality_terms && <Row k="Quality" v={offer.quality_terms} />}
                </div>
              )}

              {offer && offer.id && !ackId && (
                <button
                  onClick={() => acknowledge(offer.id!, e.id)}
                  className="w-full mt-1 px-3 py-2 rounded-lg border border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 text-xs font-semibold flex items-center justify-center gap-2"
                >
                  <ShieldAlert className="w-3 h-3" /> Open approval gate to acknowledge
                </button>
              )}
              {ackId && (
                <div className="text-[11px] text-slate-400 mt-2">
                  Approval gate opened — see <a href="/approvals" className="text-blue-300 hover:underline">queue</a>. Gate id: <span className="font-mono">{ackId.slice(0, 8)}</span>
                </div>
              )}
            </motion.div>
          );
        })}
      </div>

      <DagDrawer
        executionId={activeExecution}
        onClose={() => setActiveExecution(null)}
        expectedTools={INBOX_EXPECTED_TOOLS}
      />
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-500">{k}</span>
      <span className="text-slate-200 text-right">{v}</span>
    </div>
  );
}
