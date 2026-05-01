'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  BarChart3, Upload, MapPin, TrendingUp, Gauge, MessageSquare,
  FileText, LogOut, HelpCircle, Palmtree,
} from 'lucide-react';

function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('st_token'); }
function getUser() { if (typeof window === 'undefined') return null; try { return JSON.parse(localStorage.getItem('st_user') || 'null'); } catch { return null; } }

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Data', icon: Upload, href: '/upload' },
  { label: 'Regional Analytics', icon: MapPin, href: '/regional' },
  { label: 'Deep Analytics', icon: TrendingUp, href: '/analytics' },
  { label: 'Simulations', icon: Gauge, href: '/simulations', highlight: true },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
  { label: 'Reports', icon: FileText, href: '/reports', highlight: true },
];

export default function SidebarLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (pathname === '/') { setReady(true); return; }
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
    setReady(true);
  }, [pathname, router]);

  if (pathname === '/') return <>{children}</>;

  if (!ready) return (
    <div className="min-h-screen bg-[#021A0F] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-green-500/30 border-t-green-500 rounded-full animate-spin" />
    </div>
  );

  const logout = () => {
    localStorage.removeItem('st_token');
    localStorage.removeItem('st_refresh_token');
    localStorage.removeItem('st_user');
    router.replace('/');
  };

  return (
    <div className="min-h-screen bg-[#021A0F] flex">
      {/* Sidebar */}
      <div className="w-64 border-r border-green-900/50 p-4 flex flex-col shrink-0 bg-[#031F12]">
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-green-600/20 border border-green-500/30 flex items-center justify-center">
            <Palmtree className="w-5 h-5 text-green-400" />
          </div>
          <div>
            <span className="text-lg font-bold text-white">Saudi Tourism</span>
            <p className="text-[9px] text-green-500/70 uppercase tracking-wider">Ministry of Tourism</p>
          </div>
        </div>
        <nav className="space-y-1 flex-1">
          {NAV_ITEMS.map((item: any) => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname?.startsWith(item.href));
            const baseClasses = 'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all';
            let classes = '';
            if (item.highlight && !isActive) {
              classes = 'text-green-300 bg-gradient-to-r from-green-600/10 to-green-500/5 border border-green-600/20 hover:border-green-500/40';
            } else if (isActive) {
              classes = 'text-white bg-green-700/30 border border-green-600/30';
            } else {
              classes = 'text-green-200/60 hover:text-white hover:bg-green-800/30';
            }
            return (
              <a key={item.href} href={item.href} className={`${baseClasses} ${classes}`}>
                <item.icon className={`w-4 h-4 ${isActive ? 'text-green-400' : item.highlight ? 'text-green-400' : ''}`} /> {item.label}
              </a>
            );
          })}
        </nav>
        <div className="border-t border-green-900/50 pt-4">
          <p className="text-xs text-green-300/50 mb-1">{user?.full_name}</p>
          <p className="text-[10px] text-green-400/30 mb-3">{user?.email}</p>
          <button onClick={logout} className="flex items-center gap-2 text-xs text-green-300/40 hover:text-red-400 transition-colors">
            <LogOut className="w-3.5 h-3.5" /> Sign Out
          </button>
        </div>
      </div>
      {/* Main content */}
      <div className="flex-1 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}
