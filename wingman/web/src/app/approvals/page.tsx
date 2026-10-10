'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ShieldAlert, CheckCircle2, XCircle, Loader2, Clock, Crosshair, Inbox as InboxIcon, Beaker, CheckSquare, Square } from 'lucide-react';
import HeroBar from '../components/HeroBar';
import ExplainerPanel from '../components/ExplainerPanel';
import { APPROVALS_EXPLAINER } from '../components/explainer-specs';

interface Approval {
  id: string;
  title?: string;
  payload?: Record<string, any>;
  status?: string;
  required_signoffs?: number;
  signoff_count?: number;
  expires_at?: string | null;
  created_at?: string | null;
  agent_execution_id?: string | null;
  gate_kind?: string | null;
}

const STATUS_FILTERS = [
  { id: 'pending',  label: 'Pending' },
  { id: 'approved', label: 'Approved' },
  { id: 'denied',   label: 'Denied' },
  { id: 'expired',  label: 'Expired' },
];

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<string>('pending');
  const [items, setItems] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (f: string) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/wingman/approvals?status=${encodeURIComponent(f)}`);
      const j = await r.json();
      setItems(j.data || []);
      setSelected(new Set());
    } catch { setItems([]); }
    setLoading(false);
  };

  useEffect(() => { load(filter); }, [filter]);

  const decide = async (id: string, action: 'approve' | 'deny') => {
    setActing(id);
    setError(null);
    try {
      const r = await fetch(`/api/wingman/approvals/${id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: action === 'approve' ? 'desk-approved' : 'desk-denied' }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        setError(`Could not ${action}: ${typeof j?.detail === 'string' ? j.detail : `HTTP ${r.status}`}`);
      }
      await load(filter);
    } catch {
      setError(`Could not ${action}, Wingman is not reachable. Nothing was recorded.`);
    }
    setActing(null);
  };

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) => {
      if (prev.size === items.length) return new Set();
      return new Set(items.map((i) => i.id));
    });

  const bulkDecide = async (action: 'approve' | 'deny') => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    const ids = Array.from(selected);
    // Fire all in parallel; the SDK takes one decision per gate.
    setError(null);
    const results = await Promise.all(ids.map((id) =>
      fetch(`/api/wingman/approvals/${id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: action === 'approve' ? 'desk-bulk-approved' : 'desk-bulk-denied' }),
      }).then((r) => r.ok).catch(() => false),
    ));
    const failed = results.filter((ok) => !ok).length;
    if (failed) setError(`${failed} of ${ids.length} could not be ${action === 'approve' ? 'approved' : 'denied'}, they are still in the list.`);
    setBulkBusy(false);
    await load(filter);
  };

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="HITL APPROVALS"
        title="The desk's gate queue"
        subtitle="Every broker acknowledgement, strategy activation, and trade gate routes through here. The SDK's approvals client is the only path the platform sees — no Wingman-side decision state."
        rightSlot={
          <div className="flex flex-col items-end gap-1 text-[10px]">
            <span className="text-slate-500 uppercase tracking-wider">queue</span>
            <span className="text-xs font-mono font-semibold text-cyan-300" data-testid="approvals-count">{items.length}</span>
          </div>
        }
      />

      <ExplainerPanel spec={APPROVALS_EXPLAINER} />

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            data-testid={`filter-${f.id}`}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
              filter === f.id
                ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                : 'border-slate-800 bg-slate-900/30 text-slate-400 hover:text-white hover:bg-slate-800/40'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" data-testid="approvals-error"
          className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {loading && (
        <div className="border border-slate-800 rounded-xl p-6 text-center text-[12px] text-slate-500">
          <Loader2 className="w-4 h-4 mx-auto animate-spin mb-2" /> Loading…
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-700 p-8" data-testid="approvals-empty">
          <div className="text-center text-[13px] text-slate-300 mb-1 font-semibold">
            No <span className="text-emerald-300">{filter}</span> approvals
          </div>
          <div className="text-center text-[11px] text-slate-500 mb-4">
            Generate one by triggering a gate from any of these pages:
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl mx-auto">
            <Link href="/mispricing" className="block rounded-lg border border-slate-800 bg-slate-950/40 hover:border-emerald-500/40 hover:bg-emerald-500/[0.04] p-4 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <Crosshair className="w-4 h-4 text-fuchsia-300" />
                <span className="text-[12px] font-semibold text-white">Price at Risk Lens</span>
              </div>
              <div className="text-[10px] text-slate-400 leading-snug">Score a corridor → click <span className="text-emerald-300">Open approval gate</span> on the trade card. Generates <span className="font-mono text-emerald-300">trade.execute</span>.</div>
            </Link>
            <Link href="/inbox" className="block rounded-lg border border-slate-800 bg-slate-950/40 hover:border-cyan-500/40 hover:bg-cyan-500/[0.04] p-4 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <InboxIcon className="w-4 h-4 text-cyan-300" />
                <span className="text-[12px] font-semibold text-white">Broker Inbox</span>
              </div>
              <div className="text-[10px] text-slate-400 leading-snug">Classify + extract any broker email → it auto-routes here as a <span className="font-mono text-cyan-300">broker.ack</span> gate.</div>
            </Link>
            <Link href="/strategy" className="block rounded-lg border border-slate-800 bg-slate-950/40 hover:border-violet-500/40 hover:bg-violet-500/[0.04] p-4 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <Beaker className="w-4 h-4 text-violet-300" />
                <span className="text-[12px] font-semibold text-white">Strategy Lab</span>
              </div>
              <div className="text-[10px] text-slate-400 leading-snug">Backtest + Activate a strategy → fires a <span className="font-mono text-violet-300">strategy.activate</span> gate for desk-head signoff.</div>
            </Link>
          </div>
        </div>
      )}

      {!loading && items.length > 0 && filter === 'pending' && (
        <div className="mb-3 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 flex items-center justify-between gap-3 flex-wrap" data-testid="approvals-bulk-bar">
          <button
            onClick={toggleAll}
            className="inline-flex items-center gap-2 text-[11px] text-slate-300 hover:text-white"
          >
            {selected.size === items.length && items.length > 0
              ? <CheckSquare className="w-3.5 h-3.5 text-emerald-300" />
              : <Square className="w-3.5 h-3.5" />}
            <span>{selected.size === items.length ? 'Deselect all' : 'Select all'}</span>
            <span className="text-slate-500">· {selected.size} selected of {items.length}</span>
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => bulkDecide('deny')}
              disabled={selected.size === 0 || bulkBusy}
              data-testid="bulk-deny"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold border border-rose-500/30 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20 disabled:opacity-40"
            >
              {bulkBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
              Deny selected
            </button>
            <button
              onClick={() => bulkDecide('approve')}
              disabled={selected.size === 0 || bulkBusy}
              data-testid="bulk-approve"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold border border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
            >
              {bulkBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
              Approve selected
            </button>
          </div>
        </div>
      )}

      {!loading && items.length > 0 && (
        <div className="space-y-3" data-testid="approvals-list">
          {items.map((a) => (
            <ApprovalCard
              key={a.id}
              approval={a}
              acting={acting === a.id}
              decide={decide}
              filter={filter}
              selected={selected.has(a.id)}
              onToggle={() => toggleOne(a.id)}
              selectable={filter === 'pending'}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  approval, acting, decide, filter, selected, onToggle, selectable,
}: {
  approval: Approval;
  acting: boolean;
  decide: (id: string, action: 'approve' | 'deny') => void;
  filter: string;
  selected?: boolean;
  onToggle?: () => void;
  selectable?: boolean;
}) {
  const expiresAt = approval.expires_at ? new Date(approval.expires_at) : null;
  const expiresLabel = expiresAt ? `${expiresAt.toLocaleDateString()} ${expiresAt.toLocaleTimeString()}` : null;
  const isPending = (approval.status || '').toLowerCase() === 'pending';
  const offer = approval.payload?.offer || null;
  const status = (approval.status || 'pending').toLowerCase();
  const tone =
    status === 'approved' ? 'border-emerald-500/30 bg-emerald-500/[0.04]' :
    status === 'denied'   ? 'border-rose-500/30 bg-rose-500/[0.04]' :
    status === 'expired'  ? 'border-amber-500/20 bg-amber-500/[0.03]' :
    'border-slate-800 bg-slate-900/40';

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl border p-4 ${tone}`}
      data-testid={`approval-${approval.id}`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0 flex items-start gap-2">
          {selectable && onToggle && (
            <button
              onClick={onToggle}
              data-testid={`select-${approval.id}`}
              className="mt-0.5 shrink-0 text-slate-500 hover:text-emerald-300"
              title={selected ? 'Deselect' : 'Select for bulk action'}
            >
              {selected ? <CheckSquare className="w-3.5 h-3.5 text-emerald-300" /> : <Square className="w-3.5 h-3.5" />}
            </button>
          )}
          <div className="min-w-0">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
            <ShieldAlert className="w-3 h-3" />
            {approval.gate_kind || 'gate'} · {approval.id.slice(0, 8)}
          </div>
          <div className="text-base font-semibold text-white mt-0.5 truncate" title={approval.title || ''}>
            {approval.title || '(untitled gate)'}
          </div>
          </div>
        </div>
        <div className="text-right shrink-0 flex flex-col items-end gap-1">
          <span className={`text-[9px] uppercase tracking-wider font-bold rounded px-1.5 py-0.5 border ${
            status === 'approved' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' :
            status === 'denied'   ? 'border-rose-500/40 bg-rose-500/10 text-rose-200' :
            status === 'expired'  ? 'border-amber-500/40 bg-amber-500/10 text-amber-200' :
                                    'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
          }`}>{status}</span>
          <div className="text-[10px] text-slate-500">
            {approval.signoff_count ?? 0} / {approval.required_signoffs ?? 1} signoffs
          </div>
        </div>
      </div>

      {offer && (
        <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
          {Object.entries({
            volume: offer.volume_mt ? `${offer.volume_mt} MT` : null,
            grade: offer.grade,
            port: offer.port,
            pricing: offer.pricing,
            validity: offer.validity,
          }).filter(([, v]) => v).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 px-2 py-1 rounded bg-slate-950/40">
              <span className="text-slate-500 capitalize">{k}</span>
              <span className="text-slate-200 truncate text-right">{v}</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-[10px] text-slate-500 flex items-center gap-2">
          <Clock className="w-3 h-3" />
          {expiresLabel ? <>expires {expiresLabel}</> : <>no expiry</>}
          {approval.agent_execution_id && (
            <>· exec #{approval.agent_execution_id.slice(0, 8)}</>
          )}
        </div>
        {isPending && filter === 'pending' && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => decide(approval.id, 'deny')}
              disabled={acting}
              data-testid={`deny-${approval.id}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-rose-500/30 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
            >
              {acting ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
              Deny
            </button>
            <button
              onClick={() => decide(approval.id, 'approve')}
              disabled={acting}
              data-testid={`approve-${approval.id}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
            >
              {acting ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
              Approve
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
