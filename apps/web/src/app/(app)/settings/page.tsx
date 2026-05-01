'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { usePageTitle } from '@/hooks/usePageTitle';

export default function SettingsPage() {
  usePageTitle('Settings');
  const router = useRouter();

  useEffect(() => {
    router.replace('/settings/profile');
  }, [router]);

  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
    </div>
  );
}
