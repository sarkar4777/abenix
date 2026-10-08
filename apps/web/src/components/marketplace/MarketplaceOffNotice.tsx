'use client';

import Link from 'next/link';
import { Info } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';

// Shown where the marketplace is reachable by link while it is switched off.
export default function MarketplaceOffNotice({ what }: { what: string }) {
  const { loaded, marketplace } = usePlatformFeatures();
  const { user } = useAuth();
  if (!loaded || marketplace) return null;
  return (
    <div role="status" data-testid="marketplace-off" className="flex items-start gap-2 rounded-lg border border-slate-600/50 bg-slate-800/40 px-4 py-3 text-sm text-slate-300">
      <Info className="w-4 h-4 mt-0.5 shrink-0 text-cyan-400" />
      <p>
        The marketplace is switched off on this deployment. {what} Share an agent with your organisation from the
        builder with Publish, then My Organization.{' '}
        {user?.role === 'admin' ? (
          <Link href="/admin/marketplace" className="text-cyan-400 hover:underline">Turn it on</Link>
        ) : (
          'An admin can turn it on.'
        )}
      </p>
    </div>
  );
}
