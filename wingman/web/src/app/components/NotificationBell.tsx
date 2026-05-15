'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { Bell, CheckCircle2, XCircle, Clock, Activity, Trash2 } from 'lucide-react';
import { useWingmanExecutions, WingmanNotification } from './WingmanExecutionsProvider';

const PAGE_LABEL: Record<string, string> = {
  desk: 'Desk Copilot',
  arbitrage: 'Arbitrage Workbench',
  mispricing: 'Mispricing Lens',
  scenarios: 'Forward Scenarios',
  graph: 'Knowledge Graph',
  operations: 'Operations Watch',
};

function ageStr(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

export default function NotificationBell() {
  const { notifications, active, unreadCount, markNotificationRead, clearAllNotifications } = useWingmanExecutions();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClickAway = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 rounded-lg border border-slate-800 bg-slate-900/50 hover:bg-slate-800/70 text-slate-300 hover:text-white"
        data-testid="wingman-notification-bell"
        title={unreadCount ? `${unreadCount} new` : 'No new notifications'}
      >
        <Bell className={`w-4 h-4 ${active.length > 0 ? 'text-emerald-400' : ''}`} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-emerald-500 text-slate-950 text-[9px] font-bold rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
        {active.length > 0 && unreadCount === 0 && (
          <span className="absolute -top-1 -right-1 bg-cyan-500 text-slate-950 text-[9px] font-bold rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center" title="background runs in flight">
            <Activity className="w-2.5 h-2.5" />
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-[380px] rounded-xl border border-slate-800 bg-slate-950/95 backdrop-blur-xl shadow-2xl z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <div>
              <div className="text-xs font-semibold text-white">Notifications</div>
              <div className="text-[10px] text-slate-500">
                {active.length} running · {notifications.length} completed
              </div>
            </div>
            {notifications.length > 0 && (
              <button
                onClick={clearAllNotifications}
                className="text-[10px] text-slate-400 hover:text-rose-300 flex items-center gap-1"
                title="Clear all"
              >
                <Trash2 className="w-3 h-3" /> clear
              </button>
            )}
          </div>

          {/* Running */}
          {active.length > 0 && (
            <div className="px-2 py-2 border-b border-slate-800/40 max-h-[180px] overflow-y-auto">
              <div className="text-[9px] uppercase tracking-wider text-cyan-300 px-2 mb-1">Running ({active.length})</div>
              {active.map((e) => (
                <Link
                  key={e.executionId}
                  href={`${e.pageId === 'arbitrage' ? '/workbench' : '/' + e.pageId}?exec=${e.executionId}`}
                  onClick={() => setOpen(false)}
                  className="block px-2 py-2 rounded hover:bg-slate-900/60"
                >
                  <div className="flex items-center gap-2 text-[11px]">
                    <Activity className="w-3 h-3 text-cyan-400 animate-pulse" />
                    <span className="text-slate-200 font-semibold">{PAGE_LABEL[e.pageId] || e.pageId}</span>
                    <span className="text-slate-500 font-mono text-[9px]">#{e.executionId.slice(0, 8)}</span>
                  </div>
                  {e.title && <div className="text-[10px] text-slate-400 mt-0.5 truncate ml-5">{e.title}</div>}
                  <div className="text-[9px] text-slate-600 mt-0.5 ml-5">{ageStr(e.startedAt)}</div>
                </Link>
              ))}
            </div>
          )}

          {/* Completed */}
          <div className="max-h-[300px] overflow-y-auto">
            {notifications.length === 0 && active.length === 0 ? (
              <div className="px-4 py-8 text-center text-[11px] text-slate-500">
                No runs yet. Fire any wingman page and it'll show up here.
              </div>
            ) : notifications.length === 0 ? (
              <div className="px-4 py-3 text-[10px] text-slate-500 italic">
                No completions yet. Background runs above will land here when they finish.
              </div>
            ) : (
              notifications.map((n: WingmanNotification) => {
                const Icon = n.status === 'completed' ? CheckCircle2 :
                            n.status === 'failed' ? XCircle :
                            Clock;
                const color = n.status === 'completed' ? 'text-emerald-400' :
                             n.status === 'failed' ? 'text-rose-400' :
                             'text-amber-400';
                return (
                  <Link
                    key={n.id}
                    href={n.href}
                    onClick={() => { markNotificationRead(n.id); setOpen(false); }}
                    className={`block px-3 py-2.5 hover:bg-slate-900/60 border-b border-slate-800/30 ${!n.read ? 'bg-slate-900/30' : ''}`}
                  >
                    <div className="flex items-center gap-2 text-[11px]">
                      <Icon className={`w-3 h-3 ${color}`} />
                      <span className="text-slate-200 font-semibold">{PAGE_LABEL[n.pageId] || n.pageId}</span>
                      <span className="ml-auto text-[9px] text-slate-500">{ageStr(n.finishedAt)}</span>
                      {!n.read && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5 ml-5 truncate">{n.title}</div>
                    <div className="text-[9px] text-slate-600 mt-0.5 ml-5 font-mono">#{n.executionId.slice(0, 8)} · {n.status}</div>
                  </Link>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
