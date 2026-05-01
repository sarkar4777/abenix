'use client';

/**
 * CodeExecutorConfig — Specialized config for the `code_executor` tool.
 *
 * Shows: code editor (monospace textarea), variables JSON editor,
 * extra_modules request input, and categorized module reference.
 */

import { useState } from 'react';
import { Plus, Shield, X } from 'lucide-react';

interface CodeExecutorConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

const CORE_MODULES = [
  'math', 'statistics', 'decimal', 'fractions', 'cmath',
  'datetime', 'calendar', 'time', 'zoneinfo',
  'json', 'csv', 're', 'string', 'textwrap', 'html', 'xml',
  'collections', 'itertools', 'functools', 'operator', 'copy',
  'dataclasses', 'typing', 'enum', 'abc',
  'hashlib', 'base64', 'binascii', 'struct', 'codecs',
  'io', 'pprint', 'difflib',
  'random', 'uuid', 'array', 'bisect', 'heapq',
  'contextlib', 'warnings',
];

const EXTENDED_MODULES: { name: string; desc: string }[] = [
  { name: 'pandas', desc: 'DataFrames & data analysis' },
  { name: 'numpy', desc: 'Numerical computing' },
  { name: 'scipy', desc: 'Scientific computing' },
  { name: 'openpyxl', desc: 'Excel .xlsx read/write' },
  { name: 'xlrd', desc: 'Excel .xls read' },
  { name: 'xlsxwriter', desc: 'Excel .xlsx write' },
  { name: 'reportlab', desc: 'PDF generation' },
  { name: 'fpdf', desc: 'Simple PDF generation' },
  { name: 'matplotlib', desc: 'Charts & plots' },
  { name: 'seaborn', desc: 'Statistical visualization' },
  { name: 'plotly', desc: 'Interactive charts' },
  { name: 'bs4', desc: 'HTML parsing (BeautifulSoup)' },
  { name: 'lxml', desc: 'XML/HTML processing' },
  { name: 'PIL', desc: 'Image processing (Pillow)' },
  { name: 'sklearn', desc: 'Machine learning' },
  { name: 'pptx', desc: 'PowerPoint generation' },
  { name: 'tabulate', desc: 'Table formatting' },
  { name: 'zipfile', desc: 'ZIP archives' },
  { name: 'gzip', desc: 'GZIP compression' },
];

export default function CodeExecutorConfig({ values, onChange }: CodeExecutorConfigProps) {
  const code = (values.code as string) || '';
  const variablesStr = typeof values.variables === 'string'
    ? values.variables
    : (values.variables ? JSON.stringify(values.variables, null, 2) : '');
  const extraModules = Array.isArray(values.extra_modules) ? values.extra_modules as string[] : [];
  const [newModule, setNewModule] = useState('');

  const addModule = () => {
    const mod = newModule.trim().toLowerCase();
    if (mod && !extraModules.includes(mod)) {
      onChange({ ...values, extra_modules: [...extraModules, mod] });
      setNewModule('');
    }
  };

  return (
    <div className="space-y-4">
      {/* Code editor */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">code</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <div className="relative">
          <textarea
            value={code}
            onChange={(e) => onChange({ ...values, code: e.target.value })}
            placeholder={`# Python code to execute
import pandas as pd
import json

# Pipeline data from upstream nodes
data = context["previous_node"]

# Process data
df = pd.DataFrame(data)
result = {"summary": df.describe().to_dict()}

# Save Excel file
import openpyxl, io
buf = io.BytesIO()
df.to_excel(buf, index=False)
path = save_export("output.xlsx", buf.getvalue())
print(json.dumps({"file_path": path, **result}))`}
            rows={14}
            spellCheck={false}
            className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-[11px] font-mono text-emerald-300 placeholder-slate-700 resize-y focus:outline-none focus:border-cyan-500 leading-relaxed"
            style={{ tabSize: 4 }}
            onKeyDown={(e) => {
              if (e.key === 'Tab') {
                e.preventDefault();
                const start = e.currentTarget.selectionStart;
                const end = e.currentTarget.selectionEnd;
                const val = e.currentTarget.value;
                e.currentTarget.value = val.substring(0, start) + '    ' + val.substring(end);
                e.currentTarget.selectionStart = e.currentTarget.selectionEnd = start + 4;
                onChange({ ...values, code: e.currentTarget.value });
              }
            }}
          />
          <div className="absolute top-2 right-2 text-[8px] text-slate-600 bg-slate-950/80 px-1.5 py-0.5 rounded">
            Python 3 &middot; 30s timeout
          </div>
        </div>
        <p className="text-[8px] text-slate-600 mt-1">
          Use <code className="text-cyan-500/70">print()</code> for output. Last expression captured as result. Pipeline data via <code className="text-cyan-500/70">context["node_id"]</code>.
        </p>
      </div>

      {/* Variables */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">variables</span>
          <span className="text-slate-600 text-[8px]">optional</span>
        </label>
        <textarea
          value={variablesStr}
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              onChange({ ...values, variables: parsed });
            } catch {
              onChange({ ...values, variables: e.target.value });
            }
          }}
          placeholder={'{\n  "input_data": "value"\n}'}
          rows={3}
          spellCheck={false}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-[10px] font-mono text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* Extra modules request */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <Shield className="w-3 h-3" />
          <span className="font-mono text-slate-500">extra_modules</span>
          <span className="text-slate-600 text-[8px]">LLM-validated</span>
        </label>
        {extraModules.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1.5">
            {extraModules.map((mod) => (
              <span key={mod} className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-500/10 text-amber-400 rounded text-[10px] font-mono">
                {mod}
                <button
                  onClick={() => onChange({ ...values, extra_modules: extraModules.filter((m) => m !== mod) })}
                  className="text-amber-400/50 hover:text-red-400"
                ><X className="w-2.5 h-2.5" /></button>
              </span>
            ))}
          </div>
        )}
        <div className="flex gap-1.5">
          <input
            type="text"
            value={newModule}
            onChange={(e) => setNewModule(e.target.value)}
            placeholder="e.g. sympy, networkx, shapely..."
            className="flex-1 px-2.5 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-[10px] font-mono text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
            onKeyDown={(e) => e.key === 'Enter' && addModule()}
          />
          <button
            onClick={addModule}
            disabled={!newModule.trim()}
            className="px-2 py-1.5 bg-amber-500/10 text-amber-400 rounded hover:bg-amber-500/20 disabled:opacity-30 transition-colors"
          >
            <Plus className="w-3 h-3" />
          </button>
        </div>
        <p className="text-[8px] text-slate-600 mt-1">
          Request additional Python packages. Each is validated by an LLM safety review before execution. Packages that provide network/system access will be rejected.
        </p>
      </div>

      {/* File I/O hint */}
      <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-2.5">
        <p className="text-[9px] text-emerald-400 font-medium mb-1">File Generation</p>
        <p className="text-[8px] text-slate-400">
          Use <code className="text-emerald-400/80">save_export("file.xlsx", bytes_data)</code> or <code className="text-emerald-400/80">open("file.xlsx", "wb")</code> to write files.
          Supports Excel, PDF, images, CSV, and any binary format.
        </p>
      </div>

      {/* Extended modules reference */}
      <details className="group">
        <summary className="flex items-center gap-1.5 text-[9px] text-slate-500 cursor-pointer hover:text-slate-300">
          Extended libraries ({EXTENDED_MODULES.length} packages)
        </summary>
        <div className="mt-2 space-y-1">
          {EXTENDED_MODULES.map((mod) => (
            <div key={mod.name} className="flex items-center gap-2 text-[9px]">
              <span className="font-mono text-cyan-400/70 w-20 shrink-0">{mod.name}</span>
              <span className="text-slate-600">{mod.desc}</span>
            </div>
          ))}
        </div>
      </details>

      {/* Core modules reference */}
      <details className="group">
        <summary className="flex items-center gap-1.5 text-[9px] text-slate-500 cursor-pointer hover:text-slate-300">
          Core modules ({CORE_MODULES.length} stdlib)
        </summary>
        <div className="mt-2 flex flex-wrap gap-1">
          {CORE_MODULES.map((mod) => (
            <span key={mod} className="text-[8px] px-1.5 py-0.5 bg-slate-800/50 text-slate-500 rounded font-mono">
              {mod}
            </span>
          ))}
        </div>
      </details>
    </div>
  );
}
