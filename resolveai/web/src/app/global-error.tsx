'use client';

/**
 * Root error boundary. Next.js renders this when even `layout.tsx`
 * throws (where the regular `error.tsx` can't help). Keeps the
 * "click anywhere without breaking" promise — worst case the user
 * still gets a readable recovery card, not a blank page.
 */
import { useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('ResolveAI global error:', error);
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body style={{ margin: 0, background: '#0B0F19', color: '#e5e7eb', fontFamily: 'ui-sans-serif, system-ui, sans-serif', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ maxWidth: 520, padding: '2rem', border: '1px solid rgba(244,63,94,0.3)', borderRadius: 12, background: 'rgba(244,63,94,0.05)' }}>
          <div style={{ display: 'flex', gap: 12 }}>
            <AlertTriangle style={{ color: '#fb7185', width: 24, height: 24, flexShrink: 0, marginTop: 2 }} />
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: 'white' }}>ResolveAI hit a hard error.</h1>
              <p style={{ fontSize: 14, margin: '0.5rem 0', color: '#cbd5e1' }}>
                The page layout itself failed to render — usually a transient
                deploy race. Click retry, or reload the browser.
              </p>
              {error.message && (
                <pre style={{ marginTop: 12, padding: 10, background: 'rgba(15,23,42,0.6)', border: '1px solid rgba(100,116,139,0.4)', borderRadius: 6, fontSize: 11, color: '#fecaca', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {error.message.slice(0, 600)}
                </pre>
              )}
              <button
                onClick={reset}
                style={{ marginTop: 16, padding: '6px 12px', background: '#06b6d4', color: '#020617', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <RefreshCw style={{ width: 14, height: 14 }} /> Retry
              </button>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
