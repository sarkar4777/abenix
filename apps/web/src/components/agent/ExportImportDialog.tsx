'use client';

import { useState, useRef } from 'react';
import { Download, Upload, X, FileText, Check, Loader2 } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Props {
  open: boolean;
  onClose: () => void;
  agentId?: string;
  agentName?: string;
  mode: 'export' | 'import';
  onImported?: (agentId: string) => void;
}

export default function ExportImportDialog({ open, onClose, agentId, agentName, mode, onImported }: Props) {
  const [loading, setLoading] = useState(false);
  const [yamlContent, setYamlContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : '';

  if (!open) return null;

  const exportAgent = async () => {
    if (!agentId) return;
    setLoading(true); setError(null);
    try {
      const resp = await fetch(`${API_URL}/api/agents/${agentId}/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await resp.json();
      if (body.data) {
        const yaml = JSON.stringify(body.data, null, 2);
        setYamlContent(yaml);

        // Also trigger download
        const blob = new Blob([yaml], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${agentName?.replace(/\s+/g, '-').toLowerCase() || 'agent'}.json`;
        a.click();
        URL.revokeObjectURL(url);
        setSuccess('Exported successfully');
      } else {
        setError(body.error?.message || 'Export failed');
      }
    } catch { setError('Network error'); }
    finally { setLoading(false); }
  };

  const importAgent = async () => {
    if (!yamlContent.trim()) { setError('Paste or upload agent config'); return; }
    setLoading(true); setError(null);
    try {
      const parsed = JSON.parse(yamlContent);
      const agentData = parsed.agent || parsed;

      const resp = await fetch(`${API_URL}/api/agents/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ agent: agentData }),
      });
      const body = await resp.json();
      if (body.data?.id) {
        setSuccess(`Imported: ${body.data.name}`);
        onImported?.(body.data.id);
      } else {
        setError(body.error?.message || 'Import failed');
      }
    } catch (e) {
      setError(e instanceof SyntaxError ? 'Invalid JSON format' : 'Import failed');
    }
    finally { setLoading(false); }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setYamlContent(reader.result as string);
    reader.readAsText(file);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            {mode === 'export' ? <Download className="w-4 h-4 text-emerald-400" /> : <Upload className="w-4 h-4 text-cyan-400" />}
            <h2 className="text-sm font-semibold text-white">{mode === 'export' ? `Export "${agentName}"` : 'Import Agent / Pipeline'}</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {mode === 'export' ? (
            <>
              <p className="text-xs text-slate-400">Export this agent as a JSON template file. You can import it on another instance or share it with others.</p>
              <button onClick={exportAgent} disabled={loading}
                className="w-full py-2.5 bg-gradient-to-r from-emerald-500 to-cyan-500 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                {loading ? 'Exporting...' : 'Download Template'}
              </button>
            </>
          ) : (
            <>
              <p className="text-xs text-slate-400">Import an agent from a JSON template. Paste the content below or upload a file.</p>
              <div className="flex gap-2">
                <input type="file" ref={fileRef} onChange={handleFileUpload} accept=".json,.yaml,.yml" className="hidden" />
                <button onClick={() => fileRef.current?.click()}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-700/50">
                  <FileText className="w-3 h-3" /> Upload File
                </button>
              </div>
              <textarea
                value={yamlContent} onChange={e => setYamlContent(e.target.value)}
                placeholder='{"agent": {"name": "...", "description": "...", ...}}'
                rows={8}
                className="w-full px-3 py-2 text-[10px] font-mono bg-slate-900/50 border border-slate-700 rounded-lg text-slate-300 focus:outline-none focus:border-cyan-500 resize-none"
              />
              <button onClick={importAgent} disabled={loading || !yamlContent.trim()}
                className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                {loading ? 'Importing...' : 'Import Agent'}
              </button>
            </>
          )}

          {error && <p className="text-xs text-red-400">{error}</p>}
          {success && <p className="text-xs text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> {success}</p>}
        </div>
      </div>
    </div>
  );
}
