'use client';

import { useEffect, useId, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import type { PortfolioSchema } from './shared';

interface Props {
  schema: PortfolioSchema | null;
  usedBy: { name: string }[];
  blockedBy: string | null;
  loading: boolean;
  onClose: () => void;
  onConfirm: (opts: { force: boolean; dropTable: boolean }) => void;
}

export default function DeleteSchemaModal({ schema, usedBy, blockedBy, loading, onClose, onConfirm }: Props) {
  const [dropTable, setDropTable] = useState(false);
  const uid = useId();

  useEffect(() => { setDropTable(false); }, [schema?.id]);

  useEffect(() => {
    if (!schema) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !loading) onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [schema, loading, onClose]);

  if (!schema) return null;
  const forced = !!blockedBy || usedBy.length > 0;
  const imported = schema.source === 'spreadsheet' && !!schema.table_name;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={() => { if (!loading) onClose(); }} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
        className="relative w-full max-w-md bg-[#111827] border border-slate-700 rounded-xl p-5 space-y-4"
      >
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-500/15 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-4 h-4 text-red-400" />
          </div>
          <div className="min-w-0">
            <h2 id={`${uid}-title`} className="text-sm font-semibold text-white">
              {forced ? 'Schema is in use' : `Delete ${schema.label}?`}
            </h2>
            <p className="text-xs text-slate-300 mt-1 break-words">
              {blockedBy
                ? `${blockedBy} Deleting anyway makes the tool fail in those agents.`
                : usedBy.length
                  ? `${usedBy.length} agent${usedBy.length !== 1 ? 's' : ''} use ${schema.tool_name} (${usedBy.slice(0, 5).map(a => a.name).join(', ')}${usedBy.length > 5 ? ` +${usedBy.length - 5}` : ''}). The tool will fail in them until you remove it.`
                  : `The tool ${schema.tool_name} goes away. This can't be undone.`}
            </p>
          </div>
        </div>
        {imported && (
          <label className="flex items-start gap-2 text-xs text-slate-300 bg-slate-900/50 border border-slate-700/60 rounded-lg p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={dropTable}
              onChange={e => setDropTable(e.target.checked)}
              data-testid="ps-delete-drop-table"
              className="mt-0.5 accent-red-500"
            />
            <span>
              Also delete the table <code className="text-slate-200 break-all">{schema.table_name}</code> with every row in it,
              including rows other people uploaded. Leave this unticked to keep the data.
            </span>
          </label>
        )}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} disabled={loading} className="px-3 py-2 text-xs rounded-lg border border-slate-700 text-slate-300 hover:text-white disabled:opacity-40">
            Cancel
          </button>
          <button
            onClick={() => onConfirm({ force: forced, dropTable: imported && dropTable })}
            disabled={loading}
            data-testid="ps-delete-confirm"
            className="px-3 py-2 text-xs rounded-lg bg-red-500 text-white hover:bg-red-400 disabled:opacity-40 inline-flex items-center gap-1.5"
          >
            {loading && <Loader2 className="w-3 h-3 animate-spin" />}
            {forced ? 'Delete anyway' : dropTable ? 'Delete schema and data' : 'Delete schema'}
          </button>
        </div>
      </div>
    </div>
  );
}
