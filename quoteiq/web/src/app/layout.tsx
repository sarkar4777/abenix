import type { Metadata } from 'next';

import { ToastHost } from '@/components/ToastHost';
import { TopBar } from '@/components/TopBar';
import './globals.css';

export const metadata: Metadata = {
  title: 'QuoteIQ',
  description:
    'RFQ emails for a wire and cable manufacturer: each line matched to a product, a quote or a clarification drafted for review. Every step runs on Abenix.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-200 antialiased">
        <TopBar />
        {children}
        <ToastHost />
      </body>
    </html>
  );
}
