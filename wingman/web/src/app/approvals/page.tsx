'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { ShieldAlert, CheckCircle2, XCircle, Loader2, Clock } from 'lucide-react';
import HeroBar from '../components/HeroBar';

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

  const load = async (f: string) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/wingman/approvals?status=${encodeURIComponent(f)}`);
      const j = await r.json();
      setItems(j.data || []);
    } catch { setItems([]); }
    setLoading(false);
  };

  useEffect(() => { load(filter); }, [filter]);

  const decide = async (id: string, action: 'approve' | 'deny') => {
    setActing(id);
    try {
      await fetch(`/api/wingman/approvals/${id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: action === 'approve' ? 'desk-approved' : 'desk-denied' }),
      });
      await load(filter);
    } catch { /* keep list as-is */ }
    setActing(null);
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

      {loading && (
        <div className="border border-slate-800 rounded-xl p-6 text-center text-[12px] text-slate-500">
          <Loader2 className="w-4 h-4 mx-auto animate-spin mb-2" /> Loading…
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-[12px] text-slate-500" data-testid="approvals-empty">
          No <span className="text-slate-300 font-semibold">{filter}</span> approvals — broker acknowledgements and strategy activations land here.
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
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  approval, acting, decide, filter,
}: {
  approval: Approval;
  acting: boolean;
  decide: (id: string, action: 'approve' | 'deny') => void;
  filter: string;
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
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
            <ShieldAlert className="w-3 h-3" />
            {approval.gate_kind || 'gate'} · {approval.id.slice(0, 8)}
          </div>
          <div className="text-base font-semibold text-white mt-0.5 truncate" title={approval.title || ''}>
            {approval.title || '(untitled gate)'}
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
