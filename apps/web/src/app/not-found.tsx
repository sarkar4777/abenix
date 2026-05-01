'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Home, Search } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
      <div className="max-w-md text-center px-6">
        <motion.div
          animate={{ y: [-5, 5] }}
          transition={{
            duration: 3,
            repeat: Infinity,
            repeatType: 'reverse',
            ease: 'easeInOut',
          }}
        >
          <span className="text-8xl font-bold bg-gradient-to-r from-cyan-400 to-purple-500 bg-clip-text text-transparent select-none">
            404
          </span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.4 }}
          className="text-xl font-semibold text-white mt-4"
        >
          Page Not Found
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25, duration: 0.4 }}
          className="text-sm text-slate-400 mt-2"
        >
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35, duration: 0.4 }}
          className="mt-8 flex items-center gap-3 justify-center"
        >
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-semibold shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-0.5 transition-all duration-200"
          >
            <Home className="w-4 h-4" />
            Go Home
          </Link>
          <Link
            href="/agents"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-700/50 border border-slate-600 text-slate-300 text-sm font-semibold hover:bg-slate-700 hover:text-white hover:-translate-y-0.5 transition-all duration-200"
          >
            <Search className="w-4 h-4" />
            Search
          </Link>
        </motion.div>
      </div>
    </div>
  );
}
