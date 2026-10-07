'use client';

import { useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Upload, FileSpreadsheet, Loader2, AlertTriangle, CheckCircle2, Bot, ArrowLeft, X,
} from 'lucide-react';
import { apiFetch, ApiError } from '@/lib/api-client';
import {
  type ColumnType, type ImportCapabilities, type ImportPreview, type ImportResult, type PortfolioSchema,
  agentHref, fmtBytes, snakeCase,
} from './shared';

interface ColState {
  index: number;
  source: string;
  include: boolean;
  name: string;
  label: string;
  type: ColumnType;
  samples: string[];
  note: string | null;
  existing: boolean;
}

interface Props {
  caps: ImportCapabilities;
  existingDomains: string[];
  target?: PortfolioSchema | null;
  onCancel: () => void;
  onDone: (r: ImportResult) => void;
  onView: (s: PortfolioSchema) => void;
}

const TYPE_HELP: Record<ColumnType, string> = {
  text: 'Text',
  number: 'Number',
  date: 'Date',
  boolean: 'Yes / no',
};

const DOMAIN_RE = /^[a-z][a-z0-9_]*$/;

const inputCls =
  'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none';
const labelCls = 'text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 block';

function singular(label: string): string {
  const w = label.trim().split(/\s+/).pop()?.toLowerCase() || 'record';
  if (w.endsWith('ies')) return `${w.slice(0, -3)}y`;
  if (w.endsWith('s') && !w.endsWith('ss')) return w.slice(0, -1);
  return w;
}

export default function SpreadsheetImport({ caps, existingDomains, target, onCancel, onDone, onView }: Props) {
  const reupload = !!target;
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [reading, setReading] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [cols, setCols] = useState<ColState[]>([]);
  const [label, setLabel] = useState(target?.label || '');
  const [domain, setDomain] = useState(target?.domain_name || '');
  const [domainTouched, setDomainTouched] = useState(reupload);
  const [noun, setNoun] = useState(target?.record_noun || '');
  const [nouns, setNouns] = useState(target?.record_noun_plural || '');
  const [titleIdx, setTitleIdx] = useState<number>(-1);
  const [mode, setMode] = useState<'replace' | 'append'>('replace');
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const [errorList, setErrorList] = useState<string[]>([]);
  const [result, setResult] = useState<ImportResult | null>(null);

  const xlsx = caps.formats.includes('xlsx');
  const accept = xlsx ? '.csv,.tsv,.txt,.xlsx' : '.csv,.tsv,.txt';

  const pickFile = async (f: File | null) => {
    setError('');
    setErrorList([]);
    if (!f) return;
    const ext = f.name.toLowerCase().split('.').pop() || '';
    if (ext === 'xlsx' && !xlsx) {
      setError('Excel files can\'t be read on this server yet. In Excel choose File, Save As, CSV (comma delimited) and upload the CSV.');
      return;
    }
    if (!['csv', 'tsv', 'txt', 'xlsx'].includes(ext)) {
      setError(`Upload a .csv file${xlsx ? ' or an .xlsx file' : ''}. ${f.name} is not one.`);
      return;
    }
    if (f.size > caps.max_bytes) {
      setError(`${f.name} is ${(f.size / (1024 * 1024)).toFixed(1)} MB. The limit is ${fmtBytes(caps.max_bytes)}. Split it into smaller files, create the schema from the first and append the rest.`);
      return;
    }
    setFile(f);
    setReading(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      if (target) fd.append('domain_name', target.domain_name);
      const res = await apiFetch<ImportPreview>('/api/portfolio-schemas/import/preview', { method: 'POST', body: fd, silent: true });
      const pv = res.data!;
      const existing = new Set((pv.existing_columns || []).map(c => c.name));
      setPreview(pv);
      setCols(pv.columns.map(c => ({
        index: c.index, source: c.source, include: true, name: c.name, label: c.label,
        type: c.type, samples: c.samples, note: c.note, existing: existing.has(c.name),
      })));
      const t = pv.columns.find(c => c.name === pv.suggested_title_column) || pv.columns[0];
      setTitleIdx(t ? t.index : -1);
      if (!reupload) {
        const base = f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
        const nice = base ? base[0].toUpperCase() + base.slice(1) : 'My records';
        setLabel(l => l || nice);
        if (!domainTouched) setDomain(snakeCase(label || nice, 'my_data', 50));
        setNouns(n => n || 'records');
        setNoun(n => n || 'record');
      }
    } catch (e: any) {
      setFile(null);
      setPreview(null);
      setError(e?.message || 'The file could not be read.');
    }
    setReading(false);
  };

  const onLabel = (v: string) => {
    setLabel(v);
    if (!domainTouched) setDomain(snakeCase(v, 'my_data', 50));
  };

  const included = cols.filter(c => c.include);
  const nameCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of cols) if (c.include) m.set(c.name, (m.get(c.name) || 0) + 1);
    return m;
  }, [cols]);
  const dupNames = Array.from(nameCounts.entries()).filter(([, n]) => n > 1).map(([k]) => k);
  const reserved = new Set(['id', 'owner_id', 'created_at']);
  const reservedUsed = included.filter(c => reserved.has(c.name)).map(c => c.name);
  const domainOk = DOMAIN_RE.test(domain) && domain.length <= 50;
  const domainTaken = !reupload && existingDomains.includes(domain);
  const titleCol = included.find(c => c.index === titleIdx);
  const titleOk = !!titleCol;

  const formProblems: string[] = [];
  if (!reupload) {
    if (!label.trim()) formProblems.push('Give the schema a name.');
    if (!domainOk) formProblems.push('The tool name must start with a letter and use only lowercase letters, digits and underscores.');
    if (domainTaken) formProblems.push(`You already have a schema called ${domain}. Pick another name, or open it and use Add rows.`);
    if (!noun.trim() || !nouns.trim()) formProblems.push('Say what one row is and what several rows are, for example trade and trades.');
  }
  if (!included.length) formProblems.push('Tick at least one column to import.');
  if (dupNames.length) formProblems.push(`Two columns share the name ${dupNames.join(', ')}. Rename one of them.`);
  if (reservedUsed.length) formProblems.push(`${reservedUsed.join(', ')} is used by the platform. Rename that column.`);
  if (included.length && !titleOk) formProblems.push('Pick which column names each row.');

  const updateCol = (i: number, patch: Partial<ColState>) =>
    setCols(prev => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const doImport = async () => {
    if (!file || formProblems.length) return;
    setImporting(true);
    setError('');
    setErrorList([]);
    const plan = {
      domain_name: reupload ? target!.domain_name : domain,
      label: reupload ? target!.label : label.trim(),
      record_noun: reupload ? target!.record_noun : noun.trim(),
      record_noun_plural: reupload ? target!.record_noun_plural : nouns.trim(),
      title_column: titleCol?.name,
      mode: reupload ? mode : 'create',
      columns: cols.map(c => ({
        index: c.index, source: c.source, include: c.include, name: c.name, label: c.label.trim() || c.source, type: c.type,
      })),
    };
    const fd = new FormData();
    fd.append('file', file);
    fd.append('plan', JSON.stringify(plan));
    try {
      const res = await apiFetch<ImportResult>('/api/portfolio-schemas/import', { method: 'POST', body: fd, silent: true });
      setResult(res.data!);
      onDone(res.data!);
    } catch (e: any) {
      setError(e?.message || 'The import failed.');
      if (e instanceof ApiError) {
        const skipped = (e.details?.skipped as { row: number; reason: string }[] | undefined) || [];
        const problems = (e.details?.problems as string[] | undefined) || [];
        setErrorList([...problems, ...skipped.slice(0, 10).map(s => `Row ${s.row}: ${s.reason}`)]);
      }
    }
    setImporting(false);
  };

  if (result) {
    const s = result.schema;
    return (
      <div data-testid="ps-import-done" className="bg-slate-800/30 border border-emerald-500/30 rounded-xl p-4 sm:p-5 space-y-4">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white break-words">
              {result.mode === 'create' ? `${s.label} is ready` : `${s.label} updated`}
            </h3>
            <p className="text-xs text-slate-300 mt-1">
              Imported <strong className="text-white">{result.rows_imported.toLocaleString()}</strong> row{result.rows_imported !== 1 ? 's' : ''}
              {result.rows_replaced > 0 && <> and replaced {result.rows_replaced.toLocaleString()} of your earlier rows</>}.
              {result.rows_skipped > 0 && <> Skipped {result.rows_skipped.toLocaleString()}.</>}
              {' '}Agents reach this data through the tool <code className="text-purple-300">{s.tool_name}</code>.
            </p>
          </div>
        </div>
        {result.notes.length > 0 && (
          <ul className="text-[11px] text-slate-400 list-disc pl-5 space-y-0.5">
            {result.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}
        {result.skipped.length > 0 && (
          <details className="bg-amber-500/5 border border-amber-500/30 rounded-lg p-3 text-[11px] text-amber-200">
            <summary className="cursor-pointer font-medium">Why {result.rows_skipped} row{result.rows_skipped !== 1 ? 's were' : ' was'} skipped</summary>
            <ul className="mt-2 space-y-0.5 break-words">
              {result.skipped.map((r, i) => <li key={i}>Row {r.row}: {r.reason}</li>)}
            </ul>
            {result.rows_skipped > result.skipped.length && (
              <p className="mt-1 text-amber-300/70">and {result.rows_skipped - result.skipped.length} more. Fix them in the file and use Add rows, Append.</p>
            )}
          </details>
        )}
        <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
          <p className="text-[10px] uppercase tracking-wider text-purple-300 font-semibold mb-1">Next step</p>
          <p className="text-[11px] text-slate-300 mb-3">
            Make an agent that answers questions about these {s.record_noun_plural}. The builder opens with the tool already added
            and a starter prompt. Save it, publish it, then ask it something.
          </p>
          <div className="flex flex-wrap gap-2">
            <Link
              href={agentHref(s)}
              data-testid="ps-use-in-agent"
              className="px-3 py-2 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium inline-flex items-center gap-1.5"
            >
              <Bot className="w-3.5 h-3.5" /> Use in an agent
            </Link>
            <button onClick={() => onView(s)} className="px-3 py-2 text-xs rounded-lg border border-slate-700 text-slate-300 hover:text-white">
              View the schema and my rows
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-4 sm:px-5 py-4 border-b border-slate-700/50 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white break-words">
            {reupload ? `Add rows to ${target!.label}` : 'Create from a spreadsheet'}
          </h3>
          <p className="text-[11px] text-slate-400">
            {reupload
              ? 'Upload a file with the same columns. New columns are added to the table.'
              : 'Each row becomes a record your agents can list, search and total.'}
          </p>
        </div>
        <button onClick={onCancel} className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-400 hover:text-white inline-flex items-center gap-1">
          <X className="w-3 h-3" /> Cancel
        </button>
      </div>

      <div className="p-4 sm:p-5 space-y-5">
        <div>
          <label htmlFor="ps-import-file" className={labelCls}>1 · Choose a file</label>
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0] || null); }}
            className={`rounded-lg border-2 border-dashed p-5 text-center transition-colors ${dragging ? 'border-purple-400 bg-purple-500/10' : 'border-slate-700 bg-slate-900/30'}`}
          >
            {reading ? (
              <p className="text-xs text-slate-300 inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Reading {file?.name}…</p>
            ) : file && preview ? (
              <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-slate-300">
                <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                <span className="break-all">{file.name}</span>
                <span className="text-slate-500">· {preview.total_rows.toLocaleString()} rows · {preview.columns.length} columns</span>
                <button onClick={() => fileRef.current?.click()} className="text-purple-300 hover:text-purple-200 underline">Choose another</button>
              </div>
            ) : (
              <>
                <Upload className="w-6 h-6 text-slate-500 mx-auto mb-2" />
                <p className="text-xs text-slate-300">
                  Drop a file here or{' '}
                  <button onClick={() => fileRef.current?.click()} className="text-purple-300 hover:text-purple-200 underline">browse</button>
                </p>
                <p className="text-[10px] text-slate-500 mt-1">
                  {xlsx ? 'CSV or Excel (.xlsx, first sheet)' : 'CSV only on this server. Save Excel sheets as CSV first'}.
                  {' '}First row holds the column names. Up to {caps.max_rows.toLocaleString()} rows and {fmtBytes(caps.max_bytes)}.
                </p>
              </>
            )}
            <input
              ref={fileRef}
              id="ps-import-file"
              data-testid="ps-import-file-input"
              type="file"
              accept={accept}
              className="sr-only"
              onChange={e => { const f = e.target.files?.[0] || null; e.target.value = ''; pickFile(f); }}
            />
          </div>
        </div>

        {error && (
          <div role="alert" className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-300 break-words">
            <p className="flex items-start gap-2"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {error}</p>
            {errorList.length > 0 && (
              <ul className="list-disc pl-6 mt-1.5 space-y-0.5">{errorList.map((m, i) => <li key={i}>{m}</li>)}</ul>
            )}
          </div>
        )}

        {preview && (
          <>
            {(preview.warnings.length > 0 || preview.skipped_on_read_count > 0) && (
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-[11px] text-amber-200 space-y-1">
                {preview.warnings.map((w, i) => <p key={i}>{w}</p>)}
                {preview.skipped_on_read_count > 0 && (
                  <p>
                    {preview.skipped_on_read_count} row{preview.skipped_on_read_count !== 1 ? 's' : ''} can&apos;t be read and will be skipped
                    {preview.skipped_on_read[0] ? `, for example row ${preview.skipped_on_read[0].row} ${preview.skipped_on_read[0].reason}` : ''}.
                  </p>
                )}
              </div>
            )}

            {!reupload && (
              <div className="space-y-3">
                <p className={labelCls}>2 · Name it</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="ps-import-label" className={labelCls}>Name</label>
                    <input id="ps-import-label" value={label} onChange={e => onLabel(e.target.value)} maxLength={255} placeholder="e.g. Energy trading book" className={inputCls} />
                  </div>
                  <div>
                    <label htmlFor="ps-import-domain" className={labelCls}>Tool name</label>
                    <div className="flex items-center gap-1">
                      <span className="text-[11px] text-slate-500 font-mono">portfolio_</span>
                      <input
                        id="ps-import-domain"
                        value={domain}
                        onChange={e => { setDomainTouched(true); setDomain(e.target.value.toLowerCase().replace(/\s+/g, '_')); }}
                        maxLength={50}
                        aria-invalid={!domainOk || domainTaken}
                        className={`${inputCls} font-mono`}
                      />
                    </div>
                    <p className={`text-[10px] mt-1 ${!domainOk || domainTaken ? 'text-red-400' : 'text-slate-500'}`}>
                      {domainTaken
                        ? 'Already used by another schema.'
                        : !domainOk
                          ? 'Lowercase letters, digits and underscores, starting with a letter.'
                          : 'Agents call the data by this name. It can\'t change later.'}
                    </p>
                  </div>
                  <div>
                    <label htmlFor="ps-import-noun" className={labelCls}>One row is a…</label>
                    <input id="ps-import-noun" value={noun} onChange={e => setNoun(e.target.value)} maxLength={50} placeholder="trade" className={inputCls} />
                  </div>
                  <div>
                    <label htmlFor="ps-import-nouns" className={labelCls}>Several rows are…</label>
                    <input
                      id="ps-import-nouns"
                      value={nouns}
                      onChange={e => setNouns(e.target.value)}
                      onBlur={() => { if (!noun.trim() && nouns.trim()) setNoun(singular(nouns)); }}
                      maxLength={50}
                      placeholder="trades"
                      className={inputCls}
                    />
                  </div>
                </div>
              </div>
            )}

            {reupload && (
              <fieldset className="space-y-2">
                <legend className={labelCls}>2 · What to do with your current rows</legend>
                {(['replace', 'append'] as const).map(m => (
                  <label key={m} className="flex items-start gap-2 text-xs text-slate-300 cursor-pointer">
                    <input type="radio" name="ps-mode" checked={mode === m} onChange={() => setMode(m)} className="mt-0.5 accent-purple-500" />
                    <span>
                      <strong className="text-white">{m === 'replace' ? 'Replace my rows' : 'Append'}</strong>
                      <span className="text-slate-400">
                        {m === 'replace'
                          ? ` · delete the rows you uploaded before and keep only this file (${target?.my_rows ?? 0} now). Other people's rows stay.`
                          : ' · keep your rows and add the ones in this file.'}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}

            <div className="space-y-2">
              <p className={labelCls}>3 · Check the columns</p>
              <p className="text-[11px] text-slate-400">
                Untick columns you don&apos;t need, rename them, and fix a type if the guess is wrong. A row whose value doesn&apos;t fit
                its column type is skipped and listed afterwards.
              </p>
              <div className="space-y-2">
                {cols.map((c, i) => (
                  <div
                    key={c.index}
                    className={`grid grid-cols-[auto,1fr] sm:grid-cols-[auto,minmax(0,1.2fr),minmax(0,1fr),8rem] gap-2 items-start rounded-lg border p-2.5 ${c.include ? 'border-slate-700/60 bg-slate-900/30' : 'border-slate-800 bg-slate-900/10 opacity-60'}`}
                  >
                    <input
                      type="checkbox"
                      checked={c.include}
                      onChange={e => updateCol(i, { include: e.target.checked })}
                      aria-label={`Import ${c.source}`}
                      className="mt-2 accent-purple-500"
                    />
                    <div className="min-w-0">
                      <input
                        value={c.label}
                        onChange={e => updateCol(i, { label: e.target.value })}
                        aria-label={`Label for ${c.source}`}
                        disabled={!c.include}
                        className={inputCls}
                      />
                      <p className="text-[10px] text-slate-500 mt-1 font-mono break-all">
                        <input
                          value={c.name}
                          onChange={e => updateCol(i, { name: e.target.value })}
                          onBlur={e => updateCol(i, { name: snakeCase(e.target.value, `column_${c.index + 1}`) })}
                          aria-label={`Column name for ${c.source}`}
                          disabled={!c.include}
                          className={`bg-transparent border-b ${nameCounts.get(c.name)! > 1 || reserved.has(c.name) ? 'border-red-500 text-red-300' : 'border-slate-700 text-slate-400'} focus:outline-none focus:border-purple-500 w-full sm:w-auto`}
                        />
                        {c.existing && <span className="ml-1 text-emerald-400 not-italic">already in the table</span>}
                        {reupload && !c.existing && c.include && <span className="ml-1 text-amber-300">new column</span>}
                      </p>
                    </div>
                    <p className="col-start-2 sm:col-start-auto text-[10px] text-slate-500 break-words min-w-0 sm:pt-2">
                      {c.samples.length ? c.samples.join(' · ') : <em>empty</em>}
                      {c.note && <span className="block text-slate-600">{c.note}</span>}
                    </p>
                    <select
                      value={c.type}
                      onChange={e => updateCol(i, { type: e.target.value as ColumnType })}
                      disabled={!c.include || c.existing}
                      aria-label={`Type for ${c.source}`}
                      title={c.existing ? 'The table already stores this column with this type' : undefined}
                      className={`col-start-2 sm:col-start-auto ${inputCls}`}
                    >
                      {(Object.keys(TYPE_HELP) as ColumnType[]).map(t => <option key={t} value={t}>{TYPE_HELP[t]}</option>)}
                    </select>
                  </div>
                ))}
              </div>
            </div>

            {!reupload && (
              <div>
                <label htmlFor="ps-import-title" className={labelCls}>Which column names each row?</label>
                <select id="ps-import-title" value={titleIdx} onChange={e => setTitleIdx(Number(e.target.value))} className={inputCls}>
                  {!titleOk && <option value={-1}>Choose a column</option>}
                  {included.map(c => <option key={c.index} value={c.index}>{c.label || c.name}</option>)}
                </select>
                <p className="text-[10px] text-slate-500 mt-1">Agents show this value when they list or search rows, like a trade reference or a customer name.</p>
              </div>
            )}

            <div>
              <p className={labelCls}>First rows</p>
              <div className="overflow-x-auto rounded-lg border border-slate-700/50">
                <table className="min-w-full text-[11px]">
                  <thead className="bg-slate-900/60 text-slate-400">
                    <tr>{included.map(c => <th key={c.index} className="px-2 py-1.5 text-left font-medium whitespace-nowrap">{c.label || c.name}</th>)}</tr>
                  </thead>
                  <tbody>
                    {preview.rows.slice(0, 5).map((r, ri) => (
                      <tr key={ri} className="border-t border-slate-800">
                        {included.map(c => <td key={c.index} className="px-2 py-1 text-slate-300 whitespace-nowrap max-w-[14rem] truncate">{r[c.index]}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[10px] text-slate-500 mt-1">
                Showing {Math.min(5, preview.rows.length)} of {preview.total_rows.toLocaleString()} rows. The rows you import belong to you, other people see only their own.
              </p>
            </div>

            {formProblems.length > 0 && (
              <ul className="text-[11px] text-amber-300 list-disc pl-5 space-y-0.5">
                {formProblems.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                onClick={doImport}
                disabled={importing || formProblems.length > 0}
                data-testid="ps-import-submit"
                className="px-4 py-2 text-xs rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                {importing
                  ? 'Importing…'
                  : reupload
                    ? (mode === 'replace' ? 'Replace my rows' : `Append ${preview.total_rows.toLocaleString()} rows`)
                    : `Create and import ${preview.total_rows.toLocaleString()} rows`}
              </button>
              <button onClick={onCancel} className="px-3 py-2 text-xs rounded-lg border border-slate-700 text-slate-400 hover:text-white inline-flex items-center gap-1">
                <ArrowLeft className="w-3 h-3" /> Back
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
