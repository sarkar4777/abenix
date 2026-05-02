import './globals.css';
import type { Metadata } from 'next';
import SidebarLayout from './_sidebar_layout';
import ToastViewport from '@/components/ToastViewport';

export const metadata: Metadata = {
  title: 'Saudi Tourism Analytics — Ministry of Tourism',
  description: 'AI-powered tourism analytics platform for the Kingdom of Saudi Arabia',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>
        <SidebarLayout>{children}</SidebarLayout>
        <ToastViewport />
      </body>
    </html>
  );
}
