import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import { OrganizationJsonLd } from '@/components/seo/JsonLd';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: {
    default: 'Abenix - AI Agent Marketplace',
    template: '%s | Abenix',
  },
  icons: {
    icon: '/favicon.svg',
    apple: '/favicon.svg',
  },
  description:
    'Create, deploy, share, and monetize AI agents with Abenix. The enterprise AI agent marketplace platform.',
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000',
  ),
  openGraph: {
    type: 'website',
    siteName: 'Abenix',
    title: 'Abenix - AI Agent Marketplace',
    description:
      'Create, deploy, share, and monetize AI agents with Abenix.',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'Abenix - AI Agent Marketplace',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Abenix - AI Agent Marketplace',
    description:
      'Create, deploy, share, and monetize AI agents with Abenix.',
    images: ['/og-image.png'],
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  themeColor: '#0B0F19',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} font-sans min-h-screen antialiased`}
      >
        <OrganizationJsonLd />
        {children}
      </body>
    </html>
  );
}
