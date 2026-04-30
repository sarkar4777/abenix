import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Industrial IoT — Abenix Showcase',
  description:
    'Pump vibration DSP + cold-chain telemetry reconstruction, wired to Abenix pipelines.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
