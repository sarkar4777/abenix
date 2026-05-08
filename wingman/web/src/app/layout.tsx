import './globals.css';
import type { ReactNode } from 'react';
import Sidebar from './components/Sidebar';

export const metadata = {
  title: 'Wingman — Trading Workbench',
  description: 'Energy commodities trading workspace powered by Abenix.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-wingman-bg text-white ambient-bg">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 overflow-x-hidden">{children}</main>
        </div>
      </body>
    </html>
  );
}
