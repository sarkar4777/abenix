# How to let an agent earn autonomy

> Declare what a tool changes, enrol an agent's action, watch it, review it and promote it as its record grows. The runtime reference is [02-runtime/21-earned-autonomy](../02-runtime/21-earned-autonomy.md).

---

## Before you start

| You want to | You need |
|---|---|
| See the Autonomy pages | `autonomy.view` (every role) |
| Enrol, configure, demote, run the sample | `autonomy.manage` (creator, admin) |
| Approve a promotion | `autonomy.grant` (admin), and you did not build the agent |
| Answer watching reviews, record outcomes, flag harm | `actions.review` (every role) |

Admins can hand these out as permission sets under **Admin -> Permissions**.

---

## 1. Try the sample plant first

The fastest way to see the whole ladder. Nothing external is needed.

1. Open **Monitor -> Autonomy**. On an empty tenant choose **Try it with the sample plant**. This creates the agent "Plant operator (sample)", the action type `sample_plant.set_setpoint`, the limits decision `sample_plant_limits` (setpoint between 2 and 6 bar) and a grant at Watching, all through the public API.
2. On the grant page press **Run the sample agent** with 1, 3 or 5. Each run reads the simulated plant and, when pressure is outside 4.0 to 5.0 bar, proposes a new setpoint with an intent and a prediction.
3. Open **Approvals -> Watching reviews**. Answer with the keyboard: `A` agree, `D` I did something else (then type what), `N` not sure.
4. After 5 reviews with enough agreement the grant shows **Ready to move to Asks first**. Press **Promote**. Because this is the sample, the author may approve it, so the grant page shows the reason and an **Approve now** button. The change is recorded as self-approved. On a real action type a second user with `autonomy.grant` signs it in **Approvals**.
5. Run it again. Each setpoint now waits in **Approvals** as an action card. Approve, Edit and approve, or Reject.
6. 30 seconds after each approved setpoint the scheduler reads the plant and scores the prediction. After 8 scored actions the grant is ready for Acts within limits.
7. Flag harm on any executed action from its card. The grant drops to Asks first at once and the owners get a notification.

The sample's thresholds are low on purpose. Real action types use the defaults in the runtime doc.

If the limits decision needs sign-off under your tenant's decision policy, the grant page says so. The sample still runs, without limits, until the decision is published.

---

## 2. Declare `effect` on a tool

Every tool that changes something declares it on the class, next to `risk_tier`.

```python
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult


class ValveTool(BaseTool):
    name = "valve_control"
    risk_tier = "medium"
    effect = Effect(
        kind="control",            # write | send | publish | control | trade | delete | external
        label="Move a valve",      # verb phrase, shown on cards and in the agent's description
        target_param="valve_id",   # argument naming what is acted on
        magnitude_param="opening_pct",
        reversible=True,
    )

    @classmethod
    def effect_for(cls, arguments: dict) -> Effect | None:
        # reads are not actions
        return READ_ONLY if arguments.get("operation") == "status" else cls.effect
```

Rules:

- A tool that only reads sets `effect = READ_ONLY`.
- When some operations write and others read, override `effect_for` as above. `http_client` does this by method, `sample_plant` by operation.
- `python scripts/check-tool-config.py` fails when a tool at `medium` tier or above declares neither an effect nor `READ_ONLY`.
- Nothing else changes. Until an agent's action is enrolled, the call runs as before and is recorded in the ledger as `unmanaged`. The Autonomy page lists unmanaged actions with an **Enrol** button.

See also [01-add-a-tool](01-add-a-tool.md#declare-what-the-tool-changes).

---

## 3. Enrol an agent's action from the UI

From **Autonomy -> Enrol an action**, from the agent's **Actions** panel on its info page, or from an unmanaged row:

1. **Pick an agent.** Search every agent you can see.
2. **Pick an action.** Only tools on the agent with an effect show. Each tool lists the actions it is already enrolled on, with an Open link, and the existing actions other agents use. **Use it** joins an existing action with its settings, which suits a pipeline and an agent sending the same command. **New action** starts from the tool's defaults.
3. **How we judge success.** The outcome probe. Prefilled with a manual outcome after one hour. **Which calls it covers** takes an argument and a value or pattern, for example `topic` and `controls.battery.*`. It becomes the action's `match` and keeps it apart from other uses of the same tool. Empty means every call.
4. **How we predict.** The world model. Prefilled with "the agent states it" and a maximum band width of 50 percent.
5. **Hard limits.** Pick a published decision model, or none.

**Start watching** creates the action type (or reuses one with the same key) and a grant at Watching. Each step has a **Test** button later on the grant page, which runs that part against the last real action.

The same over REST is `POST /api/autonomy/enrol`:

```json
{
  "agent_id": "…",
  "tool_name": "mqtt_publish",
  "action_type": {
    "label": "Publish a reset command",
    "match": {"param": "topic", "glob": "controls.*"},
    "world_model": {"kind": "agent_stated", "metric": "fault_cleared"},
    "outcome_probe": {"kind": "api", "after_s": 900},
    "limits_decision_key": "bedrocc_reset_limits",
    "max_band_width": 0.5
  },
  "scope": {"param": "site", "equals": "plant-a"}
}
```

`match` picks which calls of the tool the action type covers. Its key becomes `mqtt_publish:controls`. `scope` narrows the grant, so an agent can act alone on one site and ask first everywhere else.

---

## 4. Write a limits decision model

A limit is an ordinary decision model, so it gets versions, golden tests and publish approval. Build it under **Build -> Decisions** with the rule builder.

- **Facts** are the tool's arguments by name, plus `target`. A dotted path reads nested arguments.
- **Outputs** must include `ok` (true or false) and should include `reason`, a sentence shown to the agent and the reviewer. `allowed` works in place of `ok`, `breach: true` also blocks, and a list in `reasons` is shown as is.
- **Write the breaches.** When no rule matches, the action counts as inside the limits, on the runtime and the SDK path alike. A rule per breach with `ok: false` and a `reason` is enough.
- A missing required fact blocks the action and names the fact.

The sample plant's model, as builder JSON:

```json
{
  "kind": "rules",
  "hit_policy": "first",
  "facts": [{"path": "setpoint_bar", "type": "number", "label": "Setpoint (bar)", "required": true}],
  "outputs": [{"field": "ok", "label": "Inside the limits"}, {"field": "reason", "label": "Reason"}],
  "rules": [
    {"key": "below_minimum", "when": {"all": [{"fact": "setpoint_bar", "op": "lt", "value": 2}]},
     "then": {"ok": {"value": false}, "reason": {"value": "The setpoint is below the 2 bar minimum"}}},
    {"key": "above_maximum", "when": {"all": [{"fact": "setpoint_bar", "op": "gt", "value": 6}]},
     "then": {"ok": {"value": false}, "reason": {"value": "The setpoint is above the 6 bar maximum"}}},
    {"key": "inside_limits", "when": {"all": [{"fact": "setpoint_bar", "op": "between", "values": [2, 6]}]},
     "then": {"ok": {"value": true}, "reason": {"value": ""}}}
  ]
}
```

Add golden tests for inside, below and above, propose, publish, then set the key on the action type (**Hard limits** card or `PATCH /api/autonomy/action-types/{id}` with `limits_decision_key`). Only a published key is accepted. Limits apply at every level, Watching included.

See [09-decisions](09-decisions.md) for the builder.

---

## 5. Configure the world model

`world_model` on the action type. Change it on the **How we predict** card or with `PATCH /api/autonomy/action-types/{id}`. A change never demotes, it puts a marker on the track record chart.

| Kind | Fields | Prediction comes from |
|---|---|---|
| `agent_stated` | `metric` | The agent's `_prediction` argument. The tool's description tells it to pass one |
| `decision` | `ref` (decision key), `metric`, `inputs`, optional `band` | The decision's result. `value` (or the metric's field), plus `low` and `high`, or `value ± band` |
| `ml_model` | `ref` (model name), `metric`, `inputs`, optional `band` | `ml_model` predict on `inputs` |
| `none` | | No prediction. Level 3 always falls back to asking first |

`inputs` are templates over the call: `{"flow": "{{args.flow_lpm}}", "site": "{{target}}"}`. `timeout_s` defaults to 10, at most 120. A failure or timeout leaves the action without a prediction and the card says why.

`max_band_width` on the action type is the widest honest band, relative to the value. With 0.2, a prediction of 4.5 may span at most 0.9. A wider band counts as no prediction when scoring and at level 3.

---

## 6. Configure the outcome probe

`outcome_probe` on the action type, the **How we judge success** card.

| Kind | Fields | How the outcome arrives |
|---|---|---|
| `tool` | `tool`, `arguments`, `path`, `metric`, `after_s` | The scheduler calls the tool `after_s` seconds after the action, as the agent's creator, and reads `path` from the result. Retries every 30 s, unknown after 3 misses |
| `api` | `after_s`, `metric` | Your app calls `report_outcome` (SDK) or `POST /api/autonomy/actions/{id}/outcome` |
| `manual` | `after_s`, `metric` | A person enters it on the action card |
| `none` | | Not scored. The grant can never pass the accuracy requirements |

```json
{"kind": "tool", "after_s": 30, "tool": "sample_plant",
 "arguments": {"operation": "read"}, "path": "pressure_bar", "metric": "pressure_bar"}
```

`arguments` take the same templates as world model inputs. `path` reads `a.b[0].c` or `$.a.b`. An outcome that never arrives within 24 h of being due is `unknown`. Above 20 percent unknown blocks promotion and the checklist links to this card.

---

## 7. Tune the ladder per action type

`policy` on the action type overrides any default threshold, key by key:

```json
{
  "to_asks_first": {"min_reviews": 10},
  "to_within_limits": {"min_executed": 30, "harm_free_days": 14},
  "window": 30,
  "approval_expires_s": 3600
}
```

On the grant page, **How fast it moves up** shows the thresholds in force and **Change thresholds** edits the common ones: reviews and agreement for Asks first, scored actions, accuracy, approved without edits, rejects, missing outcomes, days without harm and days at the level for Acts within limits. Saving writes a "Thresholds changed" line on the history of every grant on the action. Every move up still needs a person who did not build the agent.

Ceilings only go down through the API: `PATCH /api/autonomy/action-types/{id}` or `PATCH /api/autonomy/grants/{id}` with a lower `ceiling`. A grant above the new ceiling is demoted at once.

---

## 8. Drive it from a standalone app

An app that acts itself (a trade, an ERP posting, a refund) asks the platform first, then reports what ran and what happened. The action type must exist (enrol it once from the UI against the agent the app speaks for). `agent_id` is optional when only one agent holds a grant on the type.

The decision is one of:

| `decision` | Do |
|---|---|
| `run` | Act now |
| `wait` | A person has to approve. Call `wait`, then act on the returned `arguments` if it says `run` |
| `watching` | Do not act. A person will review what you would have done |
| `blocked` | Do not act. `message` says why |

### Python

```python
from abenix_sdk import Abenix

async with Abenix(api_key=KEY, base_url=URL) as forge:
    d = await forge.actions.propose(
        "trade.execute",
        {"symbol": "TTF", "side": "buy", "lots": 5},
        target="TTF-Q1",
        intent="Spread is two sigma under fair value",
        prediction={"metric": "pnl_eur", "value": 12000, "low": 4000, "high": 20000},
    )
    args = {"symbol": "TTF", "side": "buy", "lots": 5}
    if d["decision"] == "wait":
        d = await forge.actions.wait(d["action_id"], timeout_seconds=1800)
        args = d.get("arguments") or args
    if d["decision"] == "run":
        fill = await place_order(**args)
        await forge.actions.executed(d["action_id"], True, result_preview=str(fill))
        # later, when the result is known
        await forge.actions.report_outcome(d["action_id"], 9800)
```

### TypeScript

```ts
import { Abenix } from '@abenix/sdk';

const forge = new Abenix({ apiKey: KEY, baseUrl: URL });
let d = await forge.actions.propose('trade.execute', { symbol: 'TTF', side: 'buy', lots: 5 }, {
  target: 'TTF-Q1',
  intent: 'Spread is two sigma under fair value',
  prediction: { metric: 'pnl_eur', value: 12000, low: 4000, high: 20000 },
});
let args: Record<string, unknown> = { symbol: 'TTF', side: 'buy', lots: 5 };
if (d.decision === 'wait') {
  const w = await forge.actions.wait(d.action_id, { timeoutSeconds: 1800 });
  args = w.arguments ?? args;
  d = { ...d, decision: w.decision };
}
if (d.decision === 'run') {
  const fill = await placeOrder(args);
  await forge.actions.executed(d.action_id, true, { resultPreview: JSON.stringify(fill) });
  await forge.actions.reportOutcome(d.action_id, 9800);
}
```

### Java

```java
Abenix forge = Abenix.builder().baseUrl(url).apiKey(key).build();
ActionDecision d = forge.actions().propose(
    ActionsClient.ProposeRequest.of("trade.execute")
        .arguments(Map.of("symbol", "TTF", "side", "buy", "lots", 5))
        .target("TTF-Q1")
        .intent("Spread is two sigma under fair value")
        .prediction(Map.of("metric", "pnl_eur", "value", 12000, "low", 4000, "high", 20000)));
if (d.isWaiting()) d = forge.actions().waitFor(d.actionId(), 1800);
if (d.shouldRun()) {
    Map<String, Object> args = d.arguments() != null ? d.arguments() : Map.of("symbol", "TTF", "side", "buy", "lots", 5);
    String fill = placeOrder(args);
    forge.actions().executed(d.actionId(), true, fill);
    forge.actions().reportOutcome(d.actionId(), 9800, null);
}
```

`flag_harm` / `flagHarm` drops the grant to Asks first. `forge.autonomy.overview()` and `grant(id)` read levels and checklists for your own UI.

---

## Common problems

| Symptom | Cause |
|---|---|
| The agent says it changed something but nothing ran | It ignored the watching result. The sample prompt shows the wording that fixes it: never claim the change unless the tool confirms it |
| Promote is greyed out | Hover it. The tooltip lists every unmet line, each with a link to fix it |
| "You built this agent, so someone else has to approve its promotion" | Separation of duties. Ask another user with `autonomy.grant`. The author may only self-approve the sample, or when nobody else in the workspace holds `autonomy.grant`, and that is checked again at signing |
| Level shows lower than granted | The agent's prompt, model or tools changed, the grant is paused, or the call was outside the grant's scope. The card's fallback reason says which |
| Outcomes stay pending | The probe tool needs a value the probe user (the agent's creator) cannot read, or `path` does not match the result. Use **Test** on the How we judge success card |
| Enrol says the action "already covers these calls with different" settings | An action with the same key exists with other limits, prediction or outcome settings. Pick it under the existing actions to use its settings, or narrow Which calls so a new action is made |
| The limits block an MQTT command although the numbers are fine | Name nested facts by path, for example `payload.mw`. A payload sent as JSON text is read as an object |
| Everything is blocked by the limits | A rule returns `ok: false` for these arguments, a required fact is missing, or the check timed out (5 s). Try the arguments under Decisions to see which rule fires |
