'use client';

export default function Footer() {
  return (
    <footer className="relative z-10 border-t border-slate-800/50 bg-[#0B0F19]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/logo.svg" alt="Abenix" className="w-7 h-7" />
            <span className="text-sm font-semibold text-white">Abenix</span>
            <span className="text-sm text-slate-600">
              &mdash; The platform for building, deploying, and orchestrating AI agents.
            </span>
          </div>
          <div className="flex items-center gap-4">
            <p className="text-sm text-slate-600">
              &copy; {new Date().getFullYear()} Abenix. All rights reserved.
            </p>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700/50">
              <div className="w-4 h-4 rounded bg-gradient-to-br from-cyan-500 to-purple-600" />
              <span className="text-xs text-slate-500">
                Agents using Gemini, Qwen, Claude and some bits n pieces of manual coding forged Abenix
              </span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
