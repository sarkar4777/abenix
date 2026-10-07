export interface PortfolioSchema {
  id: string;
  domain_name: string;
  label: string;
  description: string | null;
  record_noun: string;
  record_noun_plural: string;
  schema_json: any;
  is_active: boolean;
  tool_name: string;
  source?: 'spreadsheet' | 'manual';
  table_name?: string | null;
  my_rows?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ImportCapabilities {
  formats: string[];
  max_rows: number;
  max_bytes: number;
  max_columns: number;
}

export type ColumnType = 'text' | 'number' | 'date' | 'boolean';

export interface PreviewColumn {
  index: number;
  source: string;
  name: string;
  label: string;
  type: ColumnType;
  empty: number;
  samples: string[];
  note: string | null;
}

export interface ImportPreview {
  filename: string;
  columns: PreviewColumn[];
  rows: string[][];
  total_rows: number;
  skipped_on_read: { row: number; reason: string }[];
  skipped_on_read_count: number;
  warnings: string[];
  suggested_title_column: string | null;
  existing_columns: { name: string; type: ColumnType }[] | null;
}

export interface ImportResult {
  schema: PortfolioSchema;
  table: string;
  mode: 'create' | 'replace' | 'append';
  rows_imported: number;
  rows_replaced: number;
  rows_skipped: number;
  skipped: { row: number; reason: string }[];
  notes: string[];
  sample?: boolean;
}

export const DEFAULT_CAPS: ImportCapabilities = {
  formats: ['csv'],
  max_rows: 50000,
  max_bytes: 20 * 1024 * 1024,
  max_columns: 100,
};

// mirrors portfolio_import.snake_case so the preview shows the name the server will use
export function snakeCase(raw: string, fallback = 'column', limit = 59): string {
  let s = (raw || '').normalize('NFKD').replace(/[^\x00-\x7f]/g, '');
  s = s.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
  s = s.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  if (!s) s = fallback;
  if (/^\d/.test(s)) s = `c_${s}`;
  return s.slice(0, limit).replace(/_+$/, '');
}

export function agentHref(s: PortfolioSchema): string {
  const plural = s.record_noun_plural || 'records';
  const noun = s.record_noun || 'record';
  const prompt =
    `You answer questions about my ${s.label} (${plural}). Use the ${s.tool_name} tool. ` +
    `list_records with limit 50 returns up to 50 ${plural} with all their columns, search finds ${plural} by text, ` +
    `get_summary gives the count plus totals and averages of the number columns, get_record shows one ${noun} in full. ` +
    `When a question needs a filtered total, list the records, keep the ones that match, add them up and show which rows you used. ` +
    `Only use numbers that come from the tool.`;
  const q = new URLSearchParams({ tool: s.tool_name, name: `${s.label} assistant`, prompt });
  return `/builder?${q.toString()}`;
}

export function exampleQuestions(s: PortfolioSchema): string[] {
  const main = s.schema_json?.main_table || {};
  const cols: Record<string, { type?: string; label?: string }> = main.columns || {};
  const plural = s.record_noun_plural || 'records';
  const num = Object.entries(cols).find(([, c]) => c?.type === 'number');
  const text = Object.entries(cols).find(([n, c]) => c?.type === 'string' && n !== main.title_column);
  const out = [`How many ${plural} do I have?`];
  if (num) out.push(`What is the total ${num[1].label || num[0]} across my ${plural}?`);
  if (num && text) out.push(`Break down ${num[1].label || num[0]} by ${(text[1].label || text[0]).toLowerCase()}.`);
  out.push(num ? `Which 5 ${plural} have the highest ${num[1].label || num[0]}?` : `List my ${plural}.`);
  return out;
}

export function fmtBytes(n: number): string {
  return `${(n / (1024 * 1024)).toFixed(0)} MB`;
}
