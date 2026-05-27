# E&C-Copilot — contract intelligence

> Upload contracts, extract clauses, classify risk, benchmark against the corpus, run valuation. Heavy use of the KB + Atlas + ML model registry.

---

## Domain

E&C-Copilot ingests contracts (PDF, DOCX) and produces:
- A typed clause inventory (NDA, IP, indemnity, change-of-control, etc.).
- Risk flags + severity.
- Valuation deltas under different counterparty scenarios.
- Benchmark vs. the tenant's corpus + market norms.

Customers: legal ops at corporates, deal teams at PE/VC, contract operations at SaaS.

---

## Pages

| Route | Purpose |
|---|---|
| `/` Home | Quick stats: contracts ingested, clauses flagged, benchmark coverage |
| `/contracts` | Inbox of uploaded contracts + status |
| `/contracts/{id}` | Detail — clause-by-clause review, side-by-side counterparty data |
| `/clauses` | Cross-corpus clause search (KB-backed) |
| `/atlas` | Counterparty + clause + obligation graph |
| `/valuation` | What-if valuation simulator |
| `/benchmark` | Compare a clause against the corpus + market |
| `/insights` | Wave 1 insights — risk dashboard, expiry pipeline |

---

## Agents

`packages/db/seeds/agents/contractiq_*.yaml`:

| Slug | Purpose |
|---|---|
| `contractiq-ingest` | PDF/DOCX → text + structured chunks → KB |
| `contractiq-clause-extractor` | LLM-based clause typing |
| `contractiq-risk-flagger` | Per-clause risk + severity |
| `contractiq-valuation` | What-if valuation modelling |
| `contractiq-benchmark` | Compare clause vs corpus/market norms |
| `contractiq-counterparty-extractor` | Pull parties + roles into the atlas graph |
| `contractiq-obligation-extractor` | Pull obligations + deadlines |
| `contractiq-summarizer` | One-paragraph deal summary |
| `contractiq-redline-assistant` | Suggest redlines based on policy |

The ingest agent is a pipeline (extract → counterparty → clause → risk in parallel → atlas-update). The others are single-LLM agents that the pipeline orchestrates.

---

## ML models

`contractiq/aimodels/`:

| Model | Type | Purpose |
|---|---|---|
| `contractiq-clause-classifier` | sklearn pipeline | Coarse-grained clause typing (faster than LLM for triage) |
| `contractiq-valuation-model` | XGBoost | Valuation delta given a clause-risk feature vector |
| `contractiq-redline-policy` | sklearn | Policy-fit score for a redline suggestion |

---

## KB usage

E&C-Copilot is the heaviest KB user. Per tenant:
- One "Master Corpus" KB — every ingested contract chunked + embedded.
- Per-deal KBs — temporary, for negotiation rooms.
- A shared "Policy" KB — house counsel's preferred language for each clause type.

The clause-extractor + benchmark agents use `kb_search` heavily. the redline-assistant uses `atlas_query` to walk obligation chains.

---

## Atlas (graph)

The atlas surfaces:
- Counterparties → companies → ultimate-parent links
- Clauses → governing law jurisdictions
- Obligations → owners + deadlines + escalation chains

The `/atlas` page lets a deal lead query across multiple contracts: "show all change-of-control clauses where the counterparty is owned by a sanctioned entity."

---

## actAs pattern

E&C-Copilot has its own user table (`contractiq.users`). Each request to the platform carries:
```
X-Abenix-Subject: contractiq:<user_id>
```

The platform's audit log records every clause extraction, valuation, and benchmark run with the right actor.

---

## Where to look

- App: [`contractiq/`](../../contractiq/)
- Agent yamls: [`packages/db/seeds/agents/contractiq_*.yaml`](../../packages/db/seeds/agents/)
- Mock data + corpus: [`contractiq/aimodels/`](../../contractiq/aimodels/) and `contractiq/api/data/`
- E2E: [`e2e/uat_ciq_*.spec.ts`](../../e2e/)

---

## See also

- [00-pattern](00-pattern.md) — the thin-app contract
- [04-data-model/03-knowledge](../04-data-model/03-knowledge.md) — KB schema (E&C-Copilot is the canonical heavy user)
