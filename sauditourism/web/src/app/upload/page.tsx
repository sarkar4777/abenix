'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Upload, FileText, Loader2, CheckCircle2, AlertCircle, Trash2, Database } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

export default function UploadPage() {
  const [datasets, setDatasets] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);
  const [dragOver, setDragOver] = useState(false);

  async function loadDatasets() {
    try {
      const res = await fetch(`${API_URL}/api/st/datasets`, { headers: { Authorization: `Bearer ${getToken()}` } });
      const json = await res.json();
      if (json.data) setDatasets(json.data);
    } catch { }
  }

  useEffect(() => { loadDatasets(); }, []);

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('title', file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' '));
      const res = await fetch(`${API_URL}/api/st/datasets/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: formData,
      });
      const json = await res.json();
      setUploadResult(json.data || json.error);
      await loadDatasets();
    } catch (e: any) {
      setUploadResult({ error: e.message });
    } finally {
      setUploading(false);
    }
  }

  async function seedData() {
    setSeeding(true);
    try {
      const res = await fetch(`${API_URL}/api/st/datasets/seed`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      await loadDatasets();
    } catch { } finally { setSeeding(false); }
  }

  async function deleteDataset(id: string) {
    await fetch(`${API_URL}/api/st/datasets/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    await loadDatasets();
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  }, []);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Upload & Analyze</h1>
          <p className="text-sm text-green-300/40 mt-1">Upload CSV, PDF, or text tourism datasets</p>
        </div>
        <button onClick={seedData} disabled={seeding}
          className="px-4 py-2 rounded-lg bg-green-700/30 border border-green-600/30 text-green-300 text-xs hover:bg-green-700/50 transition-all flex items-center gap-2 disabled:opacity-50">
          {seeding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
          {seeding ? 'Seeding...' : 'Seed All Test Data'}
        </button>
      </div>

      {/* Upload Zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-2xl border-2 border-dashed p-12 text-center transition-all ${dragOver ? 'border-green-500 bg-green-900/20' : 'border-green-800/40 bg-[#0A2818]/30 hover:border-green-600/50'}`}
      >
        {uploading ? (
          <div className="flex flex-col items-center">
            <Loader2 className="w-10 h-10 text-green-400 animate-spin mb-4" />
            <p className="text-green-300">Uploading & extracting via Abenix...</p>
            <p className="text-xs text-green-400/30 mt-2">The st-data-extractor agent is analyzing your file</p>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 text-green-500/40 mx-auto mb-4" />
            <p className="text-green-200/60 mb-2">Drag & drop a CSV, PDF, or text file</p>
            <p className="text-xs text-green-400/30 mb-4">Visitor arrivals, hotel occupancy, revenue data, satisfaction surveys, strategy reports</p>
            <label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-green-700/30 border border-green-600/30 text-green-300 text-sm cursor-pointer hover:bg-green-700/50 transition-all">
              <Upload className="w-4 h-4" /> Choose File
              <input type="file" accept=".csv,.pdf,.txt" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
            </label>
          </>
        )}
      </div>

      {/* Upload result */}
      {uploadResult && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className={`mt-4 p-4 rounded-xl border ${uploadResult.error ? 'border-red-800/50 bg-red-900/20' : 'border-green-700/50 bg-green-900/20'}`}>
          {uploadResult.error ? (
            <div className="flex items-center gap-2"><AlertCircle className="w-4 h-4 text-red-400" /><span className="text-sm text-red-300">{uploadResult.error.message || uploadResult.error}</span></div>
          ) : (
            <div className="flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-green-400" /><span className="text-sm text-green-300">Uploaded: {uploadResult.title} ({uploadResult.status}){uploadResult.row_count ? ` — ${uploadResult.row_count} rows` : ''}</span></div>
          )}
        </motion.div>
      )}

      {/* Dataset List */}
      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-4 text-green-200">Your Datasets ({datasets.length})</h2>
        {datasets.length === 0 ? (
          <p className="text-sm text-green-400/30">No datasets yet. Upload a file or seed test data above.</p>
        ) : (
          <div className="space-y-3">
            {datasets.map((d: any) => (
              <motion.div key={d.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="flex items-center gap-4 p-4 rounded-xl border border-green-800/40 bg-[#0A2818]/50 hover:border-green-600/50 transition-all">
                <FileText className="w-5 h-5 text-green-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-white truncate">{d.title}</p>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${d.status === 'analyzed' ? 'bg-green-500/20 text-green-300 border border-green-500/30' : d.status === 'error' ? 'bg-red-500/20 text-red-300 border border-red-500/30' : 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30'}`}>{d.status}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-green-400/30 mt-1">
                    <span>{d.dataset_type}</span>
                    {d.row_count && <span>{d.row_count} rows</span>}
                    {d.file_size && <span>{(d.file_size / 1024).toFixed(1)} KB</span>}
                    <span>{d.filename}</span>
                  </div>
                  {d.summary && <p className="text-xs text-green-300/30 mt-1 truncate">{d.summary}</p>}
                </div>
                <button onClick={() => deleteDataset(d.id)} className="text-green-600/30 hover:text-red-400 transition-colors">
                  <Trash2 className="w-4 h-4" />
                </button>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
