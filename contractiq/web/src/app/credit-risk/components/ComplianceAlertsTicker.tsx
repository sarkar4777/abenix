'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Bell, BellRing, CheckCircle2 } from 'lucide-react';

interface Alert {
  id: string;
  counterparty_id: string | null;
  counterparty_name: string | null;
  alert_type: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  description: string | null;
  status: 'open' | 'acknowledged' | 'resolved';
  raised_at: string | null;
}

interface Resp {
  items: Alert[];
  status_counts: { open: number; acknowledged: number; resolved: number };
  severity_counts: { info: number; warning: number; critical: number };
}

const SEV_STYLE = {
  info:     'border-cyan-500/30 bg-cyan-500/5 text-cyan-200',
  warning:  'border-amber-500/30 bg-amber-500/5 text-amber-200',
  critical: 'border-rose-500/30 bg-rose-500/5 text-rose-200',
};

const TYPE_LABEL: Record<string, string> = {
  LICENSE_EXPIRING:       'License expiring',
  SANCTION_LIST_ADDED:    'Sanctions update',
  KYC_OVERDUE:            'KYC overdue',
  CREDIT_LIMIT_BREACHED:  'Credit limit',
  RATING_DOWNGRADE:       'Rating downgrade',
  DOCUMENT_GAP:           'Document gap',
  REGULATORY_CHANGE:      'Regulatory change',
};

function fmtAgo(iso: string | null) {
  if (!iso) return '';
  const dt = Date.now() - new Date(iso).getTime();
  if (dt < 60_000) return 'just now';
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)}m ago`;
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)}h ago`;
  return `${Math.floor(dt / 86_400_000)}d ago`;
}

export default function ComplianceAlertsTicker() {
  const [data, setData] = useState<Resp | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const token = localStorage.getItem('contractiq_token') || '';
      const r = await fetch('/api/contractiq/compliance-alerts?status=open', { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) return;
      const j = await r.json();
      setData(j?.data || null);
    } catch {}
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  const ack = async (id: string) => {
    try {
      const token = localStorage.getItem('contractiq_token') || '';
      await fetch(`/api/contractiq/compliance-alerts/${id}/acknowledge`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      await load();
    } catch {}
  };

  const runSweep = async () => {
    setBusy(true);
    try {
      const token = localStorage.getItem('contractiq_token') || '';
      await fetch('/api/contractiq/compliance-alerts/sweep', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      await load();
    } finally { setBusy(false); }
  };

  if (!data) return null;
  const { items, severity_counts } = data;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5" data-testid="compliance-alerts">
      <div className="flex items-baseline justify-between mb-4">
        <div className="flex items-center gap-2">
          {severity_counts.critical > 0
            ? <BellRing className="w-4 h-4 text-rose-400 animate-pulse" />
            : <Bell className="w-4 h-4 text-amber-400" />}
          <h2 className="text-base font-semibold text-white">Compliance warnings</h2>
          <span className="text-[10px] text-slate-500">
            {severity_counts.critical > 0 && <span className="text-rose-400 font-semibold mr-2">{severity_counts.critical} critical</span>}
            {severity_counts.warning > 0 && <span className="text-amber-400 mr-2">{severity_counts.warning} warning</span>}
            {severity_counts.info > 0 && <span className="text-cyan-400">{severity_counts.info} info</span>}
          </span>
        </div>
        <button
          onClick={runSweep}
          disabled={busy}
          data-testid="run-sweep"
          className="text-[11px] text-slate-400 hover:text-white px-2.5 py-1 border border-slate-700 rounded-md hover:bg-slate-800/50 disabled:opacity-40 transition-colors"
        >
          {busy ? 'Sweeping…' : 'Run sweep now'}
        </button>
      </div>

      {items.length === 0 ? (
        <p className="text-xs text-emerald-400 italic flex items-center gap-1.5"><CheckCircle2 className="w-3 h-3" /> No open compliance warnings.</p>
      ) : (
        <ul className="space-y-2">
          {items.map(a => (
            <li key={a.id} className={`rounded-md border p-3 ${SEV_STYLE[a.severity]}`} data-testid={`alert-${a.severity}`}>
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-semibold truncate">{a.title}</p>
                    <span className="text-[9px] uppercase tracking-wider opacity-70 shrink-0">{TYPE_LABEL[a.alert_type] ?? a.alert_type}</span>
                  </div>
                  {a.counterparty_name && (
                    <p className="text-[11px] opacity-80 mt-0.5">{a.counterparty_name} · {fmtAgo(a.raised_at)}</p>
                  )}
                  {a.description && <p className="text-[11px] opacity-70 mt-1 leading-relaxed">{a.description}</p>}
                </div>
                <button
                  onClick={() => ack(a.id)}
                  data-testid={`ack-${a.id}`}
                  className="text-[10px] uppercase tracking-wider px-2 py-1 border border-current/40 rounded hover:bg-current/10 shrink-0"
                >
                  Ack
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
