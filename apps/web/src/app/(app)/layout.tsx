'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import Sidebar from '@/components/layout/Sidebar';
import TopBar from '@/components/layout/TopBar';
import StatusBar from '@/components/layout/StatusBar';
import { ToastContainer } from '@/components/ui/Toast';
import CommandPalette from '@/components/ui/CommandPalette';
import OfflineBanner from '@/components/ui/OfflineBanner';
import { useSidebar } from '@/stores/sidebar';
import { useIsMobile } from '@/hooks/useMediaQuery';

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (loading) return;
    const token = localStorage.getItem('access_token');
    if (!token || !user) {
      router.replace('/');
      return;
    }
    setChecked(true);
  }, [loading, user, router]);

  if (loading || !checked) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#0B0F19]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
          <p className="text-sm text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

function AppShell({ children }: { children: React.ReactNode }) {
  const { collapsed } = useSidebar();
  const isMobile = useIsMobile();

  return (
    <div className="h-screen flex flex-col bg-[#0B0F19] overflow-hidden">
      <Sidebar />
      <motion.div
        animate={{ marginLeft: isMobile ? 0 : (collapsed ? 64 : 260) }}
        transition={{ duration: 0.2, ease: 'easeInOut' }}
        className="flex-1 flex flex-col min-h-0"
      >
        <TopBar />
        <main className="flex-1 overflow-y-auto p-3 md:p-6">
          {children}
        </main>
        {!isMobile && <StatusBar />}
      </motion.div>
      <ToastContainer />
      <CommandPalette />
      <OfflineBanner />
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGuard>
        <AppShell>{children}</AppShell>
      </AuthGuard>
    </AuthProvider>
  );
}
