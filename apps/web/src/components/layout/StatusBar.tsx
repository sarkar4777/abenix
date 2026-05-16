'use client';

import { GitBranch } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

export default function StatusBar() {
  const { user } = useAuth();

  return (
    <footer className="h-7 bg-[#0F172A] border-t border-slate-800 flex items-center justify-between px-4 shrink-0">
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <GitBranch className="w-3 h-3" />
          main
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          online
        </span>
        <span>2 workers</span>
      </div>
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span>0 processing</span>
        <span className="text-slate-600">|</span>
        <span>247 completed</span>
        <span className="text-slate-600">|</span>
        <span className="text-slate-400">{user?.full_name || 'User'}</span>
      </div>
    </footer>
  );
}
