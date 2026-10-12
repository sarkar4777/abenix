'use client';

import { useRef, useState } from 'react';
import { FileUp, X } from 'lucide-react';
import { fieldHelp, fieldLabel, isFileLike, isSecret, LIST_HINT, type FieldDecl } from '@/lib/telemetry/sources';

const BINARY = /\.(desc|pb|bin|der|p12|pfx)$/i;

// one field from a declaration, the same renderer for every transport and decoder
export default function FieldInput({
  field, value, onChange, problem, stored, onReplace, idPrefix = 'tel-cfg',
}: {
  field: FieldDecl;
  value: unknown;
  onChange: (v: unknown) => void;
  problem?: string | null;
  // a secret is already stored, so the field shows it as kept until replaced
  stored?: boolean;
  onReplace?: () => void;
  idPrefix?: string;
}) {
  const id = `${idPrefix}-${field.key}`;
  const label = fieldLabel(field);
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const bad = problem || fileErr;
  const cls = `w-full rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600 ${bad ? 'border-rose-500/60' : 'border-slate-700'}`;
  const v = value === undefined || value === null ? '' : value;
  const { help, example } = fieldHelp(field);

  const readFile = (f: File) => {
    setFileErr(null);
    if (f.size > 1024 * 1024) { setFileErr('That file is over 1 MB. Pick the certificate, key or schema file itself.'); return; }
    const r = new FileReader();
    r.onload = () => {
      const res = String(r.result || '');
      // binary files go as base64, text files as they are
      onChange(BINARY.test(f.name) ? `base64:${res.split(',')[1] ?? ''}` : res);
      setFileName(f.name);
    };
    r.onerror = () => setFileErr('Could not read that file. Try again or pick another one.');
    if (BINARY.test(f.name)) r.readAsDataURL(f);
    else r.readAsText(f);
  };

  let input: React.ReactNode;
  if (stored && isSecret(field)) {
    input = (
      <div className="flex items-center gap-2 text-xs text-slate-300" data-testid={`${id}-kept`}>
        <span className="font-mono">••••••••</span> stored, never shown
        <button type="button" className="text-cyan-300 hover:underline" onClick={onReplace}>Replace</button>
      </div>
    );
  } else if (field.kind === 'bool') {
    input = (
      <label className="flex items-center gap-2 text-sm text-slate-200">
        <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} className="accent-cyan-500" data-testid={id} />
        {label}
      </label>
    );
  } else if (field.kind === 'select') {
    input = (
      <select id={id} value={String(v)} onChange={(e) => onChange(e.target.value)} className={cls} data-testid={id}>
        {!field.required && <option value="">Not set</option>}
        {field.required && !v && <option value="">Pick one</option>}
        {(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  } else if (isFileLike(field)) {
    const secret = isSecret(field);
    input = (
      <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input ref={fileRef} id={id} type="file" accept={field.accept} className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ''; }} data-testid={id} />
        <button type="button" onClick={() => fileRef.current?.click()} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">
          <FileUp className="h-3.5 w-3.5" /> {v ? 'Pick another file' : 'Upload a file'}
        </button>
        {v ? (
          <span className="inline-flex items-center gap-1 text-xs text-slate-300">
            {fileName || 'File set'}
            <button type="button" aria-label={`Remove ${label}`} onClick={() => { onChange(''); setFileName(null); }} className="p-0.5 text-slate-400 hover:text-white"><X className="h-3 w-3" /></button>
          </span>
        ) : <span className="text-xs text-slate-500">{field.accept ? `${field.accept.replace(/,/g, ', ')} file` : secret ? 'Upload the file, it is stored encrypted and never shown' : 'Upload the file or paste it below'}</span>}
      </div>
      {!secret && (
        <textarea
          aria-label={`${label}, pasted`}
          value={typeof v === 'string' && !v.startsWith('base64:') ? v : ''}
          onChange={(e) => { onChange(e.target.value); setFileName(null); }}
          rows={3}
          spellCheck={false}
          placeholder="-----BEGIN CERTIFICATE-----"
          className={`${cls} font-mono text-xs`}
          data-testid={`${id}-paste`}
        />
      )}
      </div>
    );
  } else if (field.kind === 'text' || field.kind === 'list' || field.kind === 'json') {
    input = (
      <textarea
        id={id}
        value={Array.isArray(v) ? v.join('\n') : typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v)}
        onChange={(e) => onChange(e.target.value)}
        rows={field.kind === 'json' ? 4 : 2}
        placeholder={example}
        spellCheck={false}
        className={`${cls} font-mono`}
        data-testid={id}
      />
    );
  } else {
    input = (
      <input
        id={id}
        type={isSecret(field) ? 'password' : field.kind === 'int' ? 'number' : 'text'}
        inputMode={field.kind === 'int' ? 'numeric' : undefined}
        value={String(v)}
        onChange={(e) => onChange(e.target.value)}
        placeholder={example || (field.default !== undefined && field.default !== null ? String(field.default) : undefined)}
        autoComplete={isSecret(field) ? 'new-password' : 'off'}
        spellCheck={false}
        className={`${cls} ${field.kind === 'url' ? 'font-mono' : ''}`}
        data-testid={id}
      />
    );
  }

  return (
    <div data-field={field.key}>
      {field.kind !== 'bool' && (
        <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-300">
          {label} {!field.required && <span className="font-normal text-slate-500">(optional)</span>}
        </label>
      )}
      {input}
      {bad ? (
        <p className="mt-1 text-xs text-rose-300" role="alert" data-testid={`${id}-problem`}>{bad}</p>
      ) : field.kind !== 'bool' && (help || example || field.kind === 'list') ? (
        <p className="mt-1 text-xs text-slate-400" data-testid={`${id}-help`}>
          {help}
          {field.kind === 'list' ? `${help ? ' ' : ''}${LIST_HINT}` : ''}
          {example && !isFileLike(field) ? <> {help || field.kind === 'list' ? ' ' : ''}Example: <code className="break-all text-slate-300">{example}</code></> : null}
        </p>
      ) : field.kind === 'bool' && field.description && field.label ? (
        <p className="mt-1 pl-6 text-xs text-slate-400">{field.description}</p>
      ) : null}
    </div>
  );
}
