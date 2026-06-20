'use client';

// Dev docs moved to the public /docs route so they're reachable without
// auth and openable in a new tab. This page just forwards anyone who
// still lands on the old URL.

import { useEffect } from 'react';
import { useSearchParams } from 'next/navigation';

export default function DevDocsRedirect() {
  const params = useSearchParams();
  useEffect(() => {
    const slug = params.get('slug');
    const target = slug ? `/docs?slug=${encodeURIComponent(slug)}` : '/docs';
    window.location.replace(target);
  }, [params]);

  return (
    <main className="min-h-[60vh] flex items-center justify-center text-slate-400">
      <p className="text-sm">Redirecting to /docs…</p>
      <noscript>
        <a href="/docs" className="text-sm text-cyan-300 underline ml-2">
          Open documentation
        </a>
      </noscript>
    </main>
  );
}
