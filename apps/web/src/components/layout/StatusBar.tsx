'use client';

import { useAuth } from '@/contexts/AuthContext';
import { useApi } from '@/hooks/useApi';

interface LiveStats {
  active_executions: number;
  today_executions: number;
  today_failed: number;
}

// Every number here comes from the platform, nothing is filled in for show.
export default function StatusBar() {
  const { user } = useAuth();
  const { data: stats, error } = useApi<LiveStats>('/api/analytics/live-stats', { refreshInterval: 30_000 });
  const online = !error;

  return (
    <footer className="h-7 bg-[#0F172A] border-t border-slate-800 flex items-center justify-between px-4 shrink-0" data-testid="status-bar">
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5" data-testid="status-online">
          <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-emerald-400' : 'bg-rose-400'}`} />
          {online ? 'online' : 'API unreachable'}
        </span>
      </div>
      <div className="flex items-center gap-3 text-xs text-slate-500">
        {stats && (
          <>
            <span data-testid="status-running">{stats.active_executions} running</span>
            <span className="text-slate-600">|</span>
            <span data-testid="status-today">{stats.today_executions} runs today</span>
            {stats.today_failed > 0 && (
              <>
                <span className="text-slate-600">|</span>
                <span className="text-rose-300/80">{stats.today_failed} failed</span>
              </>
            )}
            <span className="text-slate-600">|</span>
          </>
        )}
        <span className="text-slate-400">{user?.full_name || 'User'}</span>
      </div>
    </footer>
  );
}
