# Decisions: business rules without code

> How to write rules that give the same answer every time, test and publish them, and call them from agents, pipelines and apps.

---

## What a decision is

A decision takes facts, such as a shipment date, a postcode and a weight, and returns outcomes, such as a surcharge, using rules people can read. It runs on the ZEN engine (GoRules, MIT), so the same facts and the same version always give the same result, with a trace of which rules applied and what values they saw.

Each version applies over a period of time. A question can be asked as of any date, and also as the rules were known on any date, so an answer given last year can be repeated exactly.

## Writing rules

Open **Decisions** from the sidebar, where admins and creators find it among the essentials, or press Ctrl+K and type decision or rules. Start blank, with **Start from JSON rules**, from the surcharge example, or with **Import a decision file**. The new decision dialog checks the key as you type and offers the next free one.

A guide at the top of every decision shows where the version is, Rules, Try it, Tests, Check, Sign-off and Publish, and says in one sentence what to do next, with a button for it. It also says when you are waiting on someone, who can approve, and once published how to call the decision from an agent, a pipeline or the SDK. Every greyed-out button says why, and every refusal says what to do about it.

The workspace has three views of the same rules:

- **Rules.** The default. One rule at a time: conditions grouped as all, any or none of, dragged to reorder or into groups, then outcomes as fixed values or calculations. Facts are picked from a list, or typed as a new path and added on the spot. Comparisons match the fact's type, so dates get before and after, numbers get more than and between, codes get one of and reference sets.
- **Table.** One row per rule and one column per fact. Type `> 50`, `>= 2026-01-01`, `a, b, c`, `in REMOTE_POSTCODES` or `between 1 and 5`. **Columns** adds the rule's description, the facts it needs, its sources and its dates, so a whole rule fits on one row. A blank cell means not set, `""` means empty text. Export to CSV.
- **Flow.** The ZEN visual editor, for multi-step decisions with switches, expressions and chained tables. Editing a draft as a flow keeps that draft as a flow.

**Paste from Excel.** A new decision with no rules shows a **Paste your rules from Excel** area. Copy the cells with a header row first, for example `rule, machine.tip_speed_ms, worker.clearance_m, action, margin_m`, and paste. Columns that are not facts or outcomes yet are listed for review, each as a fact or an outcome with its type worked out, and the rows become rules. Every new column gets a lowercase snake_case key, so a header `Tip speed` becomes `tip_speed`, and the header as typed is kept as its label. A fact is required only when every pasted row fills it. In a decision that already has rules, click a cell and paste. A paste always opens the check first, even when every column matches.

**Numbers and types.** Values keep what you type, so `0.5` typed one key at a time stays 0.5. A new fact gets a type from its name: `_ms`, `_m`, `_kg`, speed, count and pct read as numbers, names with date as dates, `is_` and `has_` as yes or no. Change it in the fact picker, beside the condition, or on **Facts and outcomes**. A text fact cannot compare amounts, and says so with a button to switch it to a number.

Problems show at the field as you type: unknown fact, wrong value type, a range the wrong way round, a formula that does not parse, rules hidden by a rule above them or giving conflicting outcomes.

**Try it** runs your unsaved changes as you edit. It shows the outcome as labelled lines, with the raw JSON one click away, which rule applied and the values it looked at, and marks the facts still needed. **Keep as test** turns the case into a golden test. Tick **Pin it to a date** only when the case is about a particular day.

A golden test matches its expected result exactly by default. Set **Match** to **Subset** on the Tests tab when only some keys matter. The test then passes when every expected key is in the result with the same value, and extra keys are ignored.

A golden test with no date runs as of the day the tests run, so it keeps testing the rules in force. Give it a date only when the case is about a particular day, for example a rule that starts on 2027-01-01.

Each outcome has a type: text, number, true or false, date, or object. A value of the wrong type shows as a problem on that rule, for example text in a number outcome. Typing `4` into a number outcome saves the number 4, and the save response lists the change under `normalized`. When a value does not fit, the problem offers a one-click fix, **Make action Text**, that changes the outcome's type. An empty value counts as not set. Outcomes saved before types existed are read as the type their values already have.

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

Nothing is deleted. A correction is a new version. **Retire** on a published version stops it applying from now on, and the confirmation says what stays in force. **Archive** hides a whole decision, **Show archived** on the list finds it again, and **Restore** brings it back. Opening a decision shows the version in force, with a pointer to the newest draft.

**Withdraw** takes a proposed version back to a draft. Its approval shows as withdrawn, not expired. Expired means nobody acted in time.

The version page shows who has to sign, who has, and who could, from `GET /api/decisions/{key}/versions/{n}/sign-off`.

### Switching a decision off at high risk

At a tier whose publish rules ask for sign-off, High and Critical by default, switching rules off needs a second person too. **Retire**, **Archive** and **Restore** each ask for a reason and raise an approval (`decision_retire`, `decision_archive` or `decision_restore`) signed under the decision's current tier. The version or decision stays as it is until the approval is granted, then the action happens and is audited with who approved it. The decision shows the request waiting as `pending_action`. Low and Medium act at once, with a reason optional. In a one-person workspace the same sole-operator sign-off applies. Retire and archive are one step there, a reason and a tick, with a button such as **Sign it myself and retire**. Restore from the archived list is two steps, the request and then the sign-off, and the second step opens straight away with the same reason. When a version is waiting for sign-off, the archive dialog says that archiving withdraws that request. An archived row with a restore waiting shows **Restore waiting for sign-off**, and no second request can be made. Asking again answers with who already asked, when, and the decision's name. After archiving, the undo reads **Undo, ask to restore it** when restoring needs sign-off. A decision that was never published has nothing in force to switch off, so archiving it, and restoring it, acts at once at any tier and says so.

Archiving closes everything still open on the decision. Every waiting approval for it, a publish, a tier change, a review after a raise or a retire, is withdrawn with the reason "The decision was archived.", the person who asked is told, and proposed or approved versions go back to drafts. Signing an approval for an archived decision answers 409 `DECISION_ARCHIVED` and withdraws it, and Approvals and Needs you never list one. Retiring a version withdraws the review after a raise and any second retire request for that version.

When a decision approval is approved, denied or returned, the person who asked gets a notification that opens the decision, and an email with the outcome and the reviewer's reason when email delivery is on. Rows on Approvals carry `requested_by_name`, the proposal's `change_note`, and `changes`, the rules added, removed or changed against the version it came from. A first version counts every rule.

### What a decision is doing now

The list and the decision page say plainly where a decision stands, from `state`: **in force** (a version applies), **retired** (it was published, nothing applies now), **draft only** (never published, only drafts) or **never published** (a version waits for sign-off or approval). `waiting` lists every version proposed or approved but not yet published, with who proposed it, so two competing proposals are visible side by side. A version that was denied carries the reason under `denial`, and `last_denial` on the decision shows the most recent one of any kind.

**Discard** removes a draft for good. Only its author, or someone who can publish decisions, can discard it, and never a proposed, approved or published version. Withdraw a proposal first.

## Changing the risk tier

The tier sets how much sign-off a new version needs, so changing it is guarded.

- **Raising** applies at once and is recorded as `decision.tier_raised`.
- **Lowering** needs a reason. If the current tier needs no sign-off it applies at once. Otherwise the tier stays and an approval is raised under the current tier's rules, with the requester unable to sign it. The decision page shows the change waiting. When it is approved the tier moves and `decision.tier_lowered` records who approved it. If it is denied nothing changes. **Withdraw** on the waiting change drops it, and raising the tier drops it too.
- **While a version waits for sign-off** the tier cannot change at all. Withdraw the version or let it finish first.
- Each proposal records the tier it was proposed under. Publishing needs the sign-off of the higher of that tier and the tier now. A version approved with no sign-off under low cannot be published after the tier goes up to high. Withdraw it and propose it again.

### Review after a raise

Raising the tier never takes live rules out of force. Instead, each version in force whose sign-off falls short of the new tier gets a review, an approval of kind `decision_reattest` signed under the new tier's rules. The decision page shows it: "Version 1 is in force but was approved under low risk. It needs a high-risk review." with a link to the approval.

- A version that was published with no sign-off, or with fewer sign-offs than the new tier asks for, needs the review. A sign-off made alone by the only person in the workspace counts for the tier it was made under, not above it.
- When the review is approved the version records `attested_under` with the new tier, and its sign-off details show who reviewed it. Denying or returning it changes nothing, and the version stays in force.
- Raising again while a review waits replaces it with one at the higher tier. Retiring the version, publishing a version that replaces it, archiving the decision or lowering the tier below the review's tier closes it as withdrawn.
- `GET /api/decisions/{key}` returns `reattest` while a review waits, otherwise null.

## Working alone

In a workspace where nobody else can approve, the requester can sign their own decision publish, tier change or review. **Approve as the only approver** appears only when no other active person holds the signing capability and `decisions.review`. It needs a written reason of at least 10 characters. The sign-off is recorded with `sole_operator: true` and the reason, the approval shows `self_approved`, the audit log gets `approval.self_approved`, and every admin is told.

### Who can approve

Approving a decision, whatever the kind, takes two things: the **Review decisions** and **Sign approvals** permissions. Admins have both. Creators and Members have neither until they are given them. Every workspace has a ready-made permission set, **Decision reviewers**, holding exactly those two, under **Admin, Permissions**. Three ways to put someone in it:

- **Can approve decisions** on the Team invite. The person joins Decision reviewers when they accept.
- **Let them approve decisions** and **Stop them approving decisions** in a member's row menu in Team turn it on or off later (`PUT /api/team/{user_id}/approver`), and a **Can approve decisions** badge shows who can. Turning off the last approver is allowed, with a warning that high-risk changes then need a sole-operator sign-off or a new approver.
- **Someone missing?** on the decision page, for admins, adds a member of the workspace in one step (`POST /api/decisions/{key}/approvers`). The people it offers come from `GET /api/decisions/{key}/approver-candidates`: active members who cannot approve yet, never the system account, an erased account or the person who proposed the waiting version.
- **Admin, Permissions, Decision reviewers, Add people.**

The person who proposed a change never counts, and neither does the platform's own system account. The sign-off panel lists everyone who can approve, by name.

As soon as someone else can approve, signing alone is refused and the message says how many people can. An admin can turn it off under **Admin, Risk and Controls** (`governance.sole_operator_signoff`, on by default). It never applies to other kinds of approval.

## Files: export and import

**Export, Full decision (rules, tests, tier)** saves the whole decision as one JSON file in the `abenix-decision-v1` format: key, name, description, tier, hit policy, tags, facts, outcomes with their types, rules and golden tests.

```json
{"format": "abenix-decision-v1", "key": "gw.safety.exclusion", "name": "...", "description": "...",
 "risk_tier": "high", "hit_policy": "first", "tags": [], "facts": [], "outcomes": [], "rules": [],
 "tests": [{"name": "...", "facts": {}, "expected": {}, "match": "exact", "as_of": null}],
 "exported_from_version": 3}
```

**Export, Rules only** saves the typed JSON rules alone.

**Import a decision file** on the list takes that file back, or the shorter `{key, name, description, risk_tier, rules, tests}` shape with typed JSON rules. A preview shows whether it creates a decision or a new draft, how many rules and tests it holds, and any problems, before anything is written. A new key creates the decision at the file's tier. A key that exists gets a new draft and its tests are added or updated by name. A file can raise an existing decision's tier but never lower it. Import under another key to keep both. Nothing is published by an import.

The preview also says where the file lands (`target`, new or existing), offers a free key such as `gw.safety.exclusion.copy` when the key is taken, warns when another decision already has the name (`name_taken`), and says when the file holds exactly the rules of the latest version (`identical_to_latest`). Importing such a file creates nothing and answers `no_changes`. `as_new_name` renames the copy. An import into an existing decision returns the new draft's number as `draft`, so the page can open it.

New decisions check the key as you type and suggest the next free one, for example `gw.safety.exclusion.2`. An archived decision still holds its key. Search matches every word you type in the name, key or description, in any case, so machine stop finds `r3-admin-machine-stop`. Ctrl+K lists matching decisions under **Decisions** from `GET /api/search`, leaving out archived ones unless `archived=1` is asked. A search that matches archived decisions says how many, from `meta.archived_matches`. **Show archived** on the list shows archived decisions, and **Restore** brings one back.

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

Managing decisions:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/decisions?archived=1` | Archived decisions instead of live ones |
| GET | `/api/decisions/check-key?key=` | `available`, `valid`, `archived` and a `suggestion` |
| PATCH | `/api/decisions/{key}` | A lowering needs `reason`. A lowering that needs sign-off answers 202 with `pending_tier_change`. A raise that leaves a version in force short of sign-off answers with `reattest`. `TIER_LOCKED` while a version is proposed |
| DELETE | `/api/decisions/{key}/tier-change` | Withdraw a lowering that waits for sign-off |
| GET | `/api/decisions/{key}/versions/{n}/sign-off` | Required sign-offs, policy in words, sign-offs so far, eligible approvers, `sole_operator_available` |
| GET | `/api/decisions/{key}/export?full=1` | The whole decision as an `abenix-decision-v1` file |
| POST | `/api/decisions/import?preview=1&as_new_key=` | Import a file, or preview it without writing |
| DELETE / POST | `/api/decisions/{key}`, `/api/decisions/{key}/restore` | Archive and restore. Body `{reason}`. At High and Critical they answer 202 with `pending` and wait for sign-off |
| POST | `/api/decisions/{key}/versions/{n}/retire` | Retire the version in force. Same sign-off rule as archive |
| DELETE | `/api/decisions/{key}/versions/{n}` | Discard a draft |
| POST | `/api/decisions/{key}/approvers` | `{user_id}`, put a person in Decision reviewers. Needs Manage permission sets |

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
