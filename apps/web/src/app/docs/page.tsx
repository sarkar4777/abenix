import { Suspense } from 'react';
import DocsContent from './DocsContent';

// Public developer docs. No auth wrapper — this route lives outside
// the (app) group on purpose so any visitor (or the home-page Docs
// link in a new tab) can reach it.

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Abenix — Developer documentation',
  description:
    'Architecture, runtime, SDKs, deployment, and how-to guides for the Abenix platform.',
};

export default function DocsPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-[60vh] flex items-center justify-center text-slate-500 text-sm">
          Loading docs…
        </div>
      }
    >
      <DocsContent />
    </Suspense>
  );
}
