import Link from 'next/link';
import { Inbox } from 'lucide-react';

export default function NotFound() {
  return (
    <main className="p-8 max-w-2xl mx-auto">
      <div className="rounded-xl ring-1 ring-slate-800 bg-slate-900/60 p-8 text-center">
        <h1 className="text-xl font-semibold text-white">Page not found</h1>
        <p className="text-sm text-slate-400 mt-1">QuoteIQ has two pages: the inbox and each email.</p>
        <Link href="/" className="inline-flex items-center gap-1.5 mt-4 px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-sm font-medium">
          <Inbox className="w-3.5 h-3.5" /> Back to the inbox
        </Link>
      </div>
    </main>
  );
}
