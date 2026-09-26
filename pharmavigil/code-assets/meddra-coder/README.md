# meddra-coder

Maps verbatim reaction terms from a safety report onto the MedDRA hierarchy.

```bash
echo '{"terms": ["heart attack", "naseua"]}' | python main.py
```

## How it decides

Three passes, most trusted first.

| Pass | What it catches | Score |
|---|---|---|
| `exact` | The verbatim string is an LLT after normalisation | 1.0 |
| `synonym` | A known reporter phrasing — "heart attack", "yellow eyes" | 0.95 |
| `synonym_contained` | That phrasing inside a longer sentence | 0.90 |
| `fuzzy` | Token overlap and edit distance across the LLT index | computed |

A term is flagged `needs_review` when the best score is under 0.80, or when
two candidates sit within 0.05 of each other. The second rule matters more
than the first: a confident-looking score means nothing if a second term
scored just as well, and that is exactly the case a dictionary cannot settle.

The calling agent adjudicates every flagged term and may override an unflagged
one. Anything it cannot code lands in `uncoded` with a reason rather than
being forced onto a near-miss.

## The dictionary

The table in `main.py` is a demonstration subset of about 45 LLTs, chosen to
cover the common reactions plus the Important Medical Event terms that change
a seriousness assessment. MedDRA itself is licensed and cannot ship here.

Point `MEDDRA_DICT_PATH` at a JSON export shaped
`{llt: [pt, hlt, soc, code, is_ime]}` to use a real one. The matching logic
does not change — only the index it searches.

## Why this is code and not a prompt

Dictionary lookup, normalisation and edit distance are deterministic, cheap
and auditable. Asking a model to do them costs tokens, varies between runs and
cannot be diffed. What a model is genuinely better at is the adjudication:
reading "dark urine and muscle pain" and recognising rhabdomyolysis when the
dictionary offers two mediocre candidates. The split follows that line.
