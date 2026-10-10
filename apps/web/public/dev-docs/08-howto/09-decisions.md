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

A golden test matches its expected result exactly by default. Set **Match** to **Subset** on the Tests tab when only some keys matter. The test then passes when every expected key is in the result with the same value, and extra keys are ignored.

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

Every caller goes through the same evaluator and gets the same answer for the same facts, version and dates. Pick the caller that fits.

### From an agent

Add the tools to the agent. In the builder, search the palette for `decision_evaluate`. In a seed YAML, list them under `model_config.tools`:

```yaml
model_config:
  model: claude-sonnet-4-5-20250929
  tools:
    - decision_list
    - decision_evaluate
system_prompt: |
  For every shipment, call decision_evaluate with decision "freight.remote.surcharge",
  facts {"shipment": {"date": "<YYYY-MM-DD>", "postcode": "<postcode>", "weightKg": <number>}}
  and as_of set to the shipment date. Never decide yourself. If the tool reports
  missing facts, ask the user for them.
```

| Tool | Tier | Arguments | Does |
|---|---|---|---|
| `decision_list` | low | optional `query` | The published decisions, with the facts each needs and their types |
| `decision_evaluate` | low | `decision`, `facts`, optional `as_of`, `known_at`, `record` | Evaluates facts. On `missing_facts` or `invalid_facts` it adds a `next_step` telling the model what to gather |
| `decision_compare` | low | `decision`, `facts`, `targets` (2 to 10, each with `label`, `version`, `as_of` or `known_at`) | The same facts under several dates or versions, and what changes |
| `decision_explain` | low | same as `decision_evaluate` | Why the result came out as it did, with the sources cited per rule |
| `decision_test` | low | `decision`, optional `version` | Runs a decision's golden tests |
| `decision_propose` | medium | `decision`, `rules` (typed JSON), `note` | Saves the rules as a new version and proposes it. If a golden test fails it stays a draft. Agents cannot publish |

Inside an agent or pipeline run every evaluation is kept as an auditable record unless the call passes `record: false`. Outside a run, `record: true` keeps one. The tool result is the same JSON the REST call returns, with the outcome, `result` and `applied_rules`. A kill switch on the decision makes the tool answer with an error naming the switch.

### From a pipeline

A decision is a tool step. In the builder's pipeline mode add a `decision_evaluate` step. Its argument form lists the published decisions and shows the facts the chosen one needs. In YAML:

```yaml
mode: pipeline
model_config:
  tools: [decision_evaluate, llm_call]
input_variables:
  - {name: ship_date, type: string, required: true}
  - {name: postcode, type: string, required: true}
  - {name: weight_kg, type: number, required: true}
pipeline_config:
  nodes:
    - id: decide
      tool_name: decision_evaluate
      arguments:
        decision: freight.remote.surcharge
        facts:
          shipment:
            date: "{{input.ship_date}}"
            postcode: "{{input.postcode}}"
            weightKg: "{{input.weight_kg}}"
        as_of: "{{input.ship_date}}"
    - id: explain
      tool_name: llm_call
      depends_on: [decide]
      arguments:
        prompt: >-
          Tell the shipper in one sentence which surcharge applies and why.
          Decision: {{decide.result}} Rules applied: {{decide.applied_rules}}
```

Downstream steps read the evaluation's fields, `{{decide.outcome}}`, `{{decide.result.surcharge}}`, `{{decide.applied_rules}}`, `{{decide.trace_hash}}`. A weight sent as the string `"120"` is normalised to a number before the rules run. Gate later steps on the outcome with a node `condition` (`source_node: decide`, `field: outcome`, `operator: eq`, `value: decided`) so a `missing_facts` answer does not flow on as if it were a result.

### Seeing the decision a run made

Open the run at `/executions/{id}`. Each `decision_evaluate` call, in an agent or a pipeline step, shows as a decision card with the outcome, outputs, rules that applied and their citations, the version, the trace hash and a button that reopens the same facts in Try. The decision's **Evaluations** tab lists every kept evaluation with a link back to its run. See [the decision service](../02-runtime/20-decision-service.md#in-the-run-record-and-the-flight-recorder) for what is stored.

### From an app, with the SDK

```python
import os
from abenix_sdk import Abenix, AbenixDecisionError

forge = Abenix(api_key=os.environ["ABENIX_API_KEY"], base_url="http://localhost:8000")
try:
    r = await forge.decisions.evaluate(
        "freight.remote.surcharge",
        {"shipment": {"date": "2026-03-01", "postcode": "IV27", "weightKg": 120}},
        as_of="2026-03-01",
        persist=True,
    )
except AbenixDecisionError as e:
    print(e.status, e.code, e)      # a mistyped key comes back with the closest matches
else:
    if r["outcome"] == "decided":
        print(r["result"], r["applied_rules"], r["trace_hash"])
```

```ts
import { Abenix, AbenixDecisionError } from '@abenix/sdk';

const abenix = new Abenix({ apiKey: process.env.ABENIX_API_KEY!, baseUrl: 'http://localhost:8000' });
const r = await abenix.decisions.evaluate('freight.remote.surcharge', facts, { asOf: '2026-03-01' });
```

The Python `DecisionsClient` also has `list`, `get`, `create`, `evaluate_batch`, `compare`, `versions`, `version`, `export`, `propose_rules`, `validate`, `publish`, `update`, `new_draft`, `save_draft`, `import_rules`, `propose`, `withdraw`, `publish_plan`, `retire`, `diff`, `tests`, `add_test`, `evaluations`, `reference_sets`, `reference_set` and `put_reference_set`. The TypeScript client covers the core of that in camelCase, `evaluateBatch`, `proposeRules`, `newDraft`, `saveDraft`, `importRules`, `publishPlan` and the rest. `propose_rules` opens a draft from the version in force, imports the rules into it and proposes it in one call.

Errors raise `AbenixDecisionError` with the platform's message, `status` and `code`:

| Code | Status | Meaning |
|---|---|---|
| `NOT_FOUND` | 404 | No decision with that key, or no such version. The message names the closest keys |
| `NO_VERSION_IN_FORCE` | 404 | Nothing published applies on `as_of`, as known on `known_at` |
| `KILL_SWITCH` | 423 | A kill switch stops this decision |
| `IDEMPOTENCY_CONFLICT` | 409 | The idempotency key was already used for a different evaluation |

### Over REST

| Method | Path | Body |
|---|---|---|
| POST | `/api/decisions/{key}/evaluate` | `facts`, `as_of`, `known_at`, `version`, `trace` (default true), `persist`, `idempotency_key` |
| POST | `/api/decisions/{key}/evaluate-batch` | `items` (up to 1,000, each `{facts, as_of, known_at}` or bare facts), `as_of`, `known_at`, `version` |
| POST | `/api/decisions/{key}/compare` | `facts`, `targets` (2 to 10) |

These three accept a bearer token or an `X-API-Key` and need `decisions.evaluate`, which every role has by default. Facts are capped at 256 KB. Pass `persist: true` or an `idempotency_key` to keep an auditable record. The decision's `log_mode` (`none`, `sampled` or `all`, set with `PATCH /api/decisions/{key}`) records evaluations without the caller asking.

## Who can do what

| Capability | Held by default by | Allows |
|---|---|---|
| `decisions.view` | user, creator, admin | Read decisions, versions, tests and evaluations |
| `decisions.evaluate` | user, creator, admin | The evaluate, batch and compare endpoints |
| `decisions.author` | creator, admin | Create, edit, import, check, propose and withdraw drafts. Manage reference sets |
| `decisions.publish` | admin | Publish, retire and archive |
| `decisions.review` | admin | Sign off, or reject, a version proposed for publication |
| `approvals.sign` | admin | Sign the approval a proposal waits on, together with `decisions.review`. The proposer cannot sign when the tier sets `exclude_author` |

Anything beyond the role defaults comes from a permission set, see [11-governance](11-governance.md).

## Events

A proposal sent through the API, a publish and a retire write `decision.proposed`, `decision.published` and `decision.retired` to the event outbox. Send them to a webhook or start an agent on them, see [12-source-watch-and-events](12-source-watch-and-events.md). Filter on `decision_key` to follow one decision.

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
