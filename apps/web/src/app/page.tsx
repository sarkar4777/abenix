import type { Metadata } from 'next';
import ParticleBackground from '@/components/ui/ParticleBackground';
import Navbar from '@/components/layout/Navbar';
import HeroSection from '@/components/landing/HeroSection';
import FeaturesSection from '@/components/landing/FeaturesSection';
import HowItWorks from '@/components/landing/HowItWorks';
import Footer from '@/components/layout/Footer';

export const metadata: Metadata = {
  title: 'Abenix — The open-source AI agent platform',
  description:
    'Open-source AI agent platform that thinks in graphs. Atlas ontology canvas, knowledge engine, multimodal pipelines, 100+ built-in tools, sandboxed code execution, MCP, observability, RBAC, and autoscaling runtime pools.',
};

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden">
      <ParticleBackground />
      <Navbar />
      <HeroSection />
      <FeaturesSection />
      <HowItWorks />
      <Footer />
    </main>
  );
}
