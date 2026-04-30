import Link from 'next/link';
import { FileQuestion, Home } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="p-8 max-w-2xl mx-auto">
      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-8 text-center">
        <FileQuestion className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h1 className="text-xl font-semibold text-white">Page not found</h1>
        <p className="text-sm text-slate-400 mt-1">
          This route doesn&apos;t exist in ResolveAI. Head back to the dashboard
          and pick an entry from the left nav.
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 mt-4 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-sm font-medium transition-colors"
        >
          <Home className="w-3.5 h-3.5" /> Back to dashboard
        </Link>
      </div>
    </div>
  );
}
