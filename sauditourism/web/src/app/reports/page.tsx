'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { FileText, Play, Loader2, Clock, ChevronRight, Download, FileType2 } from 'lucide-react';
import { fetchWithToast, toastError, toastSuccess } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

export default function ReportsPage() {
  const [types, setTypes] = useState<any>({});
  const [reports, setReports] = useState<any[]>([]);
  const [generating, setGenerating] = useState('');
  const [viewReport, setViewReport] = useState<any>(null);

  useEffect(() => {
    (async () => {
      const headers = { Authorization: `Bearer ${getToken()}` };
      const [typesJson, reportsJson] = await Promise.all([
        fetchWithToast(`${API_URL}/api/st/reports/types`, { headers }, 'Failed to load report types'),
        fetchWithToast(`${API_URL}/api/st/reports`, { headers }, 'Failed to load reports'),
      ]);
      if (typesJson.data) setTypes(typesJson.data);
      if (reportsJson.data) setReports(reportsJson.data);
    })();
  }, []);

  async function generateReport(type: string) {
    setGenerating(type);
    setViewReport(null);
    const headers = { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' };
    const json = await fetchWithToast(
      `${API_URL}/api/st/reports/generate`,
      { method: 'POST', headers, body: JSON.stringify({ type }) },
      'Report generation failed',
    );
    if (json.data) {
      setViewReport(json.data);
      toastSuccess(`Report ready: ${json.data.title}`);
      const reportsJson = await fetchWithToast(
        `${API_URL}/api/st/reports`,
        { headers: { Authorization: `Bearer ${getToken()}` } },
        'Failed to refresh reports list',
      );
      if (reportsJson.data) setReports(reportsJson.data);
    }
    setGenerating('');
  }

  async function loadReport(id: string) {
    const json = await fetchWithToast(
      `${API_URL}/api/st/reports/${id}`,
      { headers: { Authorization: `Bearer ${getToken()}` } },
      'Failed to load report',
    );
    if (json.data) setViewReport(json.data);
  }

  async function exportReport(id: string, format: 'pdf' | 'docx') {
    try {
      const res = await fetch(`${API_URL}/api/st/reports/${id}/export?format=${format}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) {
        const text = await res.text();
        toastError(`Export ${format.toUpperCase()} failed`, text.slice(0, 160) || `HTTP ${res.status}`);
        return;
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = /filename="?([^";]+)"?/.exec(cd);
      const filename = m?.[1] || `report.${format}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toastSuccess(`Downloaded ${filename}`);
    } catch (e: any) {
      toastError(`Export ${format.toUpperCase()} failed`, e?.message || String(e));
    }
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
              <div className="flex items-center gap-2 mb-4">
                <button
                  onClick={() => navigator.clipboard?.writeText(viewReport.content || '')}
                  className="text-[11px] px-2.5 py-1.5 rounded-md border border-green-800/40 bg-green-900/30 text-green-200/70 hover:text-white transition-colors flex items-center gap-1.5"
                >
                  <FileText className="w-3 h-3" /> Copy
                </button>
                <button
                  onClick={() => exportReport(viewReport.id, 'pdf')}
                  className="text-[11px] px-2.5 py-1.5 rounded-md border border-green-700/50 bg-green-800/40 text-green-100 hover:bg-green-700/60 transition-colors flex items-center gap-1.5"
                >
                  <Download className="w-3 h-3" /> Download PDF
                </button>
                <button
                  onClick={() => exportReport(viewReport.id, 'docx')}
                  className="text-[11px] px-2.5 py-1.5 rounded-md border border-green-700/50 bg-green-800/40 text-green-100 hover:bg-green-700/60 transition-colors flex items-center gap-1.5"
                >
                  <FileType2 className="w-3 h-3" /> Download DOCX
                </button>
              </div>
              <div
                className="prose prose-invert prose-green max-w-none text-sm leading-relaxed
                  prose-headings:text-green-200 prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
                  prose-strong:text-white
                  prose-table:text-xs [&_table]:border [&_table]:border-green-800/40 [&_table]:rounded-lg [&_table]:overflow-hidden
                  prose-th:px-3 prose-th:py-1.5 prose-th:bg-green-900/40 prose-th:text-green-200
                  prose-td:px-3 prose-td:py-1.5 prose-td:border-green-800/30
                  prose-li:text-green-100/80 prose-p:text-green-100/80
                  prose-hr:border-green-800/30
                "
                dangerouslySetInnerHTML={{
                  // Prefer server-rendered HTML; fall back to plain-text wrapped in <pre>.
                  __html:
                    viewReport.content_html ||
                    `<pre style="white-space:pre-wrap">${(viewReport.content || '')
                      .replace(/&/g, '&amp;')
                      .replace(/</g, '&lt;')
                      .replace(/>/g, '&gt;')}</pre>`,
                }}
              />
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
