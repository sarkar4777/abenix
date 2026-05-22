import './globals.css';
import type { Metadata } from 'next';
import SidebarLayout from './_sidebar_layout';

export const metadata: Metadata = {
  title: 'ContractIQ — Energy Contract Intelligence',
  description: 'AI-powered analysis of PPAs, gas supply agreements, and energy contracts',
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
      </body>
    </html>
  );
}
