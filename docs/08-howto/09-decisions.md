# Decisions: business rules without code

> How to write rules that give the same answer every time, test and publish them, and call them from agents, pipelines and apps.

---

## What a decision is

A decision takes facts, such as a shipment date, a postcode and a weight, and returns outcomes, such as a surcharge, using rules people can read. It runs on the ZEN engine (GoRules, MIT), so the same facts and the same version always give the same result, with a trace of which rules applied and what values they saw.

Each version applies over a period of time. A question can be asked as of any date, and also as the rules were known on any date, so an answer given last year can be repeated exactly.

## Writing rules

Open **Build -> Decisions** and start blank, from typed JSON rules, or from the surcharge example. The workspace has three views of the same rules:

- **Rules.** The default. One rule at a time: conditions grouped as all, any or none of, dragged to reorder or into groups, then outcomes as fixed values or calculations. Facts are picked from a list, or typed as a new path and added on the spot. Comparisons match the fact's type, so dates get before and after, numbers get more than and between, codes get one of and reference sets.
- **Table.** One row per rule and one column per fact. Type `> 50`, `>= 2026-01-01`, `a, b, c`, `in REMOTE_POSTCODES` or `between 1 and 5`. Paste rows from Excel, with or without a header row. Export to CSV.
- **Flow.** The ZEN visual editor, for multi-step decisions with switches, expressions and chained tables. Editing a draft as a flow keeps that draft as a flow.

Problems show at the field as you type: unknown fact, wrong value type, a range the wrong way round, a formula that does not parse, rules hidden by a rule above them or giving conflicting outcomes.

**Try it** runs your unsaved changes as you edit. It shows the outcome, which rule applied and the values it looked at. **Keep as test** turns the case into a golden test.

Drafts save themselves. Two people can edit the same draft. Each sees the other on the page, and if one saves first the other's changes are combined rule by rule, with a choice offered only where both changed the same rule.

## Outcomes

| Outcome | Meaning |
|---|---|
| decided | A rule applied. `result` holds the outcomes and `applied_rules` the rule keys |
| no_match | No rule applied, so nothing is required by this decision |
| missing_facts | A required fact is absent. `missing_facts` lists them. Nothing is guessed |
| invalid_facts | A fact has the wrong type, for example text where a number belongs |

Facts are normalised before the rules run. A code sent as a number is read as text, a weight sent as `"120"` is read as 120, and the response says so. The trace hash covers the facts, the version and the result, so two evaluations can be compared without storing either.

## From draft to published

1. **Check** runs validation, the golden tests, and a comparison with the published version over the golden tests and recent recorded evaluations. Every result that would change is listed.
2. **Propose** checks again and sends the version for sign-off under the decision's risk tier. Low and medium tiers need no sign-off by default. High needs one person who did not author it. Critical needs two.
3. Approvers see it on **Approvals** with a link to the rules and what changes.
4. **Publish** shows what it will do before it does it: which versions it replaces, and which versions end on the new version's start date. A version whose period would be split in two is refused, with the fix.

Nothing is deleted. A correction is a new version. Retiring a version stops it applying from now on.

## Calling a decision

From an agent or pipeline, add the tools:

| Tool | Does |
|---|---|
| `decision_list` | The published decisions, with the facts each needs and their types |
| `decision_evaluate` | Evaluates facts. Says which facts to gather when some are missing |
| `decision_compare` | The same facts under several dates or versions, and what changes |
| `decision_explain` | Why the result came out as it did, with the sources cited per rule |
| `decision_test` | Runs a decision's golden tests |
| `decision_propose` | Proposes rule changes for people to approve. Agents cannot publish |

From an app, use the SDK:

```python
result = await forge.decisions.evaluate(
    "freight.remote.surcharge",
    {"shipment": {"date": "2026-03-01", "postcode": "IV27", "weightKg": 120}},
    as_of="2026-03-01",
)
```

```ts
const r = await abenix.decisions.evaluate('freight.remote.surcharge', facts, { asOf: '2026-03-01' });
```

Errors raise `AbenixDecisionError` with the platform's message and code. A mistyped key comes back with the closest matches.

REST: `POST /api/decisions/{key}/evaluate`, `/evaluate-batch` (up to 1,000 items), `/compare`. Pass `persist: true` or an `idempotency_key` to keep an auditable record. The same key with different facts is refused.

## Typed JSON rules

Rules import and export in this shape, losslessly:

```json
{
  "ruleKey": "freight.remote.surcharge",
  "validFrom": "2026-01-01",
  "requiresFacts": ["shipment.date", "shipment.postcode", "shipment.weightKg"],
  "when": {"all": [
    {"gte": [{"fact": "shipment.date"}, "2026-01-01"]},
    {"inReferenceSet": [{"fact": "shipment.postcode"}, "REMOTE_POSTCODES"]},
    {"gt": [{"fact": "shipment.weightKg"}, 50]}
  ]},
  "then": {"surcharge": "REMOTE_AREA_SURCHARGE"},
  "provenance": {"citations": ["Carrier tariff 2026, section 4.2"]}
}
```

Operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `notIn`, `inReferenceSet`, `notInReferenceSet`, `contains`, `startsWith`, `endsWith`, `isSet`, `isNotSet`, `isTrue`, `isFalse`, grouped by `all`, `any` and `not`. Any other key on a rule is kept and exported back.

## Reference sets

**Decisions -> Reference sets** holds named lists such as remote postcode areas. Paste one value per line. Each change is a new version. A published decision keeps the values it was compiled with. A new draft picks up the latest.

## Scale

- Evaluation is stateless and runs in every API pod. Compiled decisions are cached per process by content hash, and publishing tells every pod over Redis.
- The evaluate endpoints authenticate from a short-lived cache and touch the database only on a cache miss, so they scale by adding API replicas.
- `scripts/load/decision_load.py` drives concurrent evaluations and can publish a new version mid-run. It reports latency percentiles, errors, the versions seen and any case whose trace hash differed.
