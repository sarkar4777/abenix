// the same list as SEARCH_LANGUAGES in packages/db/chunks_store.py, a unit test keeps them equal
export const SEARCH_LANGUAGES = [
  'simple', 'arabic', 'armenian', 'basque', 'catalan', 'danish', 'dutch', 'english', 'finnish', 'french',
  'german', 'greek', 'hindi', 'hungarian', 'indonesian', 'irish', 'italian', 'lithuanian', 'nepali', 'norwegian',
  'portuguese', 'romanian', 'russian', 'serbian', 'spanish', 'swedish', 'tamil', 'turkish', 'yiddish',
] as const;

export function languageLabel(language: string): string {
  if (language === 'simple') return 'Any language, exact words';
  return language.charAt(0).toUpperCase() + language.slice(1);
}

export const LANGUAGE_HELP = 'Keyword search and reranking match word forms in this language.';

export const INDEX_MODE_HELP: Record<string, string> = {
  shared: 'Documents are indexed as they arrive. Best for most collections.',
  deferred: 'Indexing waits, which makes a bulk load faster. Search stays exact and slower until you build the index.',
  building: 'The index is being built. Search keeps working meanwhile.',
  dedicated: 'This collection has its own index.',
};

export interface CognifyChoices {
  budget: string;
  selection: 'all' | 'sample' | 'salient';
  percent: string;
  maxPerDoc: string;
}

export function cognifyProblem(c: CognifyChoices): string | null {
  const budget = Number(c.budget);
  if (c.budget.trim() && (!Number.isFinite(budget) || budget < 0)) return 'The budget must be zero or more dollars.';
  const percent = Number(c.percent);
  if (c.selection !== 'all' && (!Number.isFinite(percent) || percent <= 0 || percent > 100)) {
    return 'The share of chunks must be above 0 and at most 100 percent.';
  }
  const most = Number(c.maxPerDoc);
  if (c.maxPerDoc.trim() && (!Number.isInteger(most) || most < 1)) return 'The chunks per document limit must be a whole number of 1 or more.';
  return null;
}

export function cognifyBody(c: CognifyChoices): Record<string, unknown> {
  return {
    selection: c.selection,
    ...(c.selection === 'all' ? {} : { sample_rate: Number(c.percent) / 100 }),
    ...(c.budget.trim() ? { max_cost_usd: Number(c.budget) } : {}),
    ...(c.maxPerDoc.trim() ? { max_chunks_per_doc: Number(c.maxPerDoc) } : {}),
  };
}
