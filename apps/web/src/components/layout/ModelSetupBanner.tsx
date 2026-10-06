'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useIsAdmin } from '@/hooks/useToolConfig';

type ProviderMap = Record<string, { configured: boolean; reason: string | null }>;

// Shown on every page until at least one model provider has a key, so a fresh
// install says what to do before the first agent run fails.
export default function ModelSetupBanner() {
  const [ready, setReady] = useState<boolean | null>(null);
  const isAdmin = useIsAdmin();

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const r = await apiFetch<ProviderMap>('/api/llm/available-providers', { silent: true, throwOnError: false });
      if (cancelled || !r.data) return;
      setReady(Object.values(r.data).some((p) => p?.configured));
    };
    check();
    const t = setInterval(check, 30_000);
    // coming back from the settings tab rechecks at once
    const onFocus = () => document.visibilityState === 'visible' && check();
    document.addEventListener('visibilitychange', onFocus);
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      clearInterval(t);
      document.removeEventListener('visibilitychange', onFocus);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  if (ready !== false) return null;
  return (
    <div
      role="alert"
      data-testid="model-setup-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-100"
    >
      <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
      <span className="font-medium">No AI model is connected, so agents cannot run yet.</span>
      {isAdmin ? (
        <span className="flex flex-wrap items-center gap-x-3">
          <Link href="/admin/tool-config" className="text-amber-300 underline hover:text-amber-200" data-testid="model-setup-add-key">
            Add an Anthropic, OpenAI, Google or Azure key
          </Link>
          <span className="text-amber-200/70">or</span>
          <Link href="/admin/llm-settings" className="text-amber-300 underline hover:text-amber-200" data-testid="model-setup-subscription">
            use a Claude subscription
          </Link>
        </span>
      ) : (
        <span className="text-amber-200/80">Ask an admin to add a model key under Admin, Tool Configuration.</span>
      )}
    </div>
  );
}
