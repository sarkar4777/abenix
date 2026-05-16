import './globals.css';
import type { ReactNode } from 'react';
import Sidebar from './components/Sidebar';
import { WingmanExecutionsProvider } from './components/WingmanExecutionsProvider';

export const metadata = {
  title: 'Wingman — Trading Workbench',
  description: 'Energy commodities trading workspace powered by Bodhi.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-wingman-bg text-white ambient-bg">
        <WingmanExecutionsProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-x-hidden">{children}</main>
          </div>
        </WingmanExecutionsProvider>
      </body>
    </html>
  );
}
