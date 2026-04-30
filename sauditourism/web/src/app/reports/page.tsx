'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { FileText, Play, Loader2, Clock, ChevronRight } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

async function safeFetch(url: string, opts?: any) {
  const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(600000) });
  const text = await res.text();
  try { return JSON.parse(text); } catch { return { data: null, error: { message: text.slice(0, 200) } }; }
}

export default function ReportsPage() {
  const [types, setTypes] = useState<any>({});
  const [reports, setReports] = useState<any[]>([]);
  const [generating, setGenerating] = useState('');
  const [viewReport, setViewReport] = useState<any>(null);

  useEffect(() => {
    (async () => {
      try {
        const [typesJson, reportsJson] = await Promise.all([
          safeFetch(`${API_URL}/api/st/reports/types`, { headers: { Authorization: `Bearer ${getToken()}` } }),
          safeFetch(`${API_URL}/api/st/reports`, { headers: { Authorization: `Bearer ${getToken()}` } }),
        ]);
        if (typesJson.data) setTypes(typesJson.data);
        if (reportsJson.data) setReports(reportsJson.data);
      } catch { }
    })();
  }, []);

  async function generateReport(type: string) {
    setGenerating(type);
    setViewReport(null);
    try {
      const json = await safeFetch(`${API_URL}/api/st/reports/generate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ type }),
      });
      if (json.data) {
        setViewReport(json.data);
        // Refresh list
        const reportsJson = await safeFetch(`${API_URL}/api/st/reports`, { headers: { Authorization: `Bearer ${getToken()}` } });
        if (reportsJson.data) setReports(reportsJson.data);
      }
    } catch { } finally { setGenerating(''); }
  }

  async function loadReport(id: string) {
    try {
      const json = await safeFetch(`${API_URL}/api/st/reports/${id}`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (json.data) setViewReport(json.data);
    } catch { }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Reports</h1>
        <p className="text-sm text-green-300/40 mt-1">AI-generated executive reports — via Abenix st-report-generator agent</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[350px_1fr] gap-6">
        {/* Left: Report types + history */}
        <div>
          <h2 className="text-sm font-semibold text-green-200 mb-3">Generate New Report</h2>
          <div className="space-y-3 mb-8">
            {Object.entries(types).map(([key, t]: [string, any]) => (
              <button key={key} onClick={() => generateReport(key)} disabled={!!generating}
                className="w-full text-left rounded-xl border border-green-800/40 bg-[#0A2818]/50 p-4 hover:border-green-600/50 transition-all disabled:opacity-50">
                <div className="flex items-center justify-between mb-1">
                  <h3 className="text-sm font-semibold text-white">{t.title}</h3>
                  {generating === key ? (
                    <Loader2 className="w-4 h-4 animate-spin text-green-400" />
                  ) : (
                    <Play className="w-4 h-4 text-green-500/30" />
                  )}
                </div>
                <p className="text-xs text-green-300/30">{t.description}</p>
              </button>
            ))}
          </div>

          {generating && (
            <div className="mb-6 p-4 rounded-xl border border-green-600/30 bg-green-900/20">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin text-green-400" />
                <span className="text-sm text-green-300">Generating report...</span>
              </div>
              <p className="text-xs text-green-400/30 mt-1">The st-report-generator agent is analyzing your data with financial_calculator and csv_analyzer tools</p>
            </div>
          )}

          {reports.length > 0 && (
            <>
              <h2 className="text-sm font-semibold text-green-200 mb-3">Previous Reports</h2>
              <div className="space-y-2">
                {reports.map((r: any) => (
                  <button key={r.id} onClick={() => loadReport(r.id)}
                    className="w-full text-left rounded-lg border border-green-800/30 bg-[#0A2818]/30 p-3 hover:border-green-600/50 transition-all flex items-center gap-3">
                    <FileText className="w-4 h-4 text-green-500/30 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-white truncate">{r.title}</p>
                      <p className="text-[10px] text-green-400/20">{new Date(r.created_at).toLocaleDateString()}</p>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-green-600/30" />
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Right: Report viewer */}
        <div>
          {viewReport ? (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-green-700/40 bg-[#0A2818]/70 p-6">
              <div className="flex items-center gap-2 mb-4 pb-4 border-b border-green-800/30">
                <FileText className="w-5 h-5 text-green-400" />
                <h2 className="text-lg font-bold text-white">{viewReport.title}</h2>
                <span className="text-[10px] text-green-400/20 ml-auto">{viewReport.created_at ? new Date(viewReport.created_at).toLocaleDateString() : ''}</span>
              </div>
              <div className="prose prose-invert prose-green max-w-none text-sm leading-relaxed"
                dangerouslySetInnerHTML={{
                  __html: (viewReport.content || '')
                    .replace(/^# (.*$)/gm, '<h1 class="text-xl font-bold text-white mt-6 mb-3">$1</h1>')
                    .replace(/^## (.*$)/gm, '<h2 class="text-lg font-semibold text-green-200 mt-5 mb-2">$1</h2>')
                    .replace(/^### (.*$)/gm, '<h3 class="text-sm font-semibold text-green-300 mt-4 mb-1">$1</h3>')
                    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                    .replace(/^- (.*$)/gm, '<li class="ml-4 text-green-200/60">$1</li>')
                    .replace(/^\d+\. (.*$)/gm, '<li class="ml-4 text-green-200/60">$1</li>')
                    .replace(/\|(.+)\|/gm, (match: string) => {
                      const cells = match.split('|').filter(Boolean).map(c => c.trim());
                      return `<tr>${cells.map(c => `<td class="px-3 py-1 border border-green-800/30 text-xs">${c}</td>`).join('')}</tr>`;
                    })
                    .replace(/---/g, '<hr class="border-green-800/30 my-4" />')
                    .replace(/\n/g, '<br/>')
                }} />
              {viewReport.agent_cost !== undefined && (
                <div className="mt-4 pt-3 border-t border-green-800/30">
                  <p className="text-[10px] text-green-400/20">Generated by st-report-generator &middot; Cost: ${viewReport.agent_cost?.toFixed(4)}</p>
                </div>
              )}
            </motion.div>
          ) : (
            <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-12 text-center">
              <FileText className="w-10 h-10 text-green-600/20 mx-auto mb-4" />
              <p className="text-green-300/30">Select a report type to generate</p>
              <p className="text-xs text-green-400/20 mt-2">Reports are generated by the st-report-generator agent using your uploaded datasets</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
