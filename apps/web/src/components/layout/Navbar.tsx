'use client';

import { motion } from 'framer-motion';
import {
  Book,
  Boxes,
  Hammer,
} from 'lucide-react';

const navLinks = [
  { label: 'Capabilities', icon: Boxes, href: '#features' },
  { label: 'How it works', icon: Hammer, href: '#how-it-works' },
  { label: 'Docs', icon: Book, href: '/docs' },
];

export default function Navbar() {
  return (
    <motion.nav
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="fixed top-0 left-0 right-0 z-50 bg-[#0B0F19]/80 backdrop-blur-xl border-b border-slate-800/50"
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <img src="/logo.svg" alt="Abenix" className="w-8 h-8" />
            <span className="text-lg font-bold text-white">Abenix</span>
          </div>
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white">
            PLATFORM
          </span>
          <span className="text-xs text-slate-500 hidden sm:inline">
            An Agent for Every Use Case
          </span>
        </div>

        <div className="hidden md:flex items-center gap-1">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/50 transition-colors"
            >
              <link.icon className="w-4 h-4" />
              {link.label}
            </a>
          ))}
        </div>

        <div />
      </div>
    </motion.nav>
  );
}
