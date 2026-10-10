# How to set risk tiers, kill switches and permission sets

> Give an agent a risk tier, decide what each tier requires, stop a tool or an agent in seconds, and hand people capabilities beyond their role.

---

## The pieces

| Piece | What it is | Where |
|---|---|---|
| Risk tier | `low`, `medium`, `high` or `critical`, on agents, pipelines, tools, decisions and sources | The builder's tier picker, `model_config.risk_tier`, a tool's `risk_tier` class attribute |
| Tier policy | What a tier requires, per tenant. Defaults apply until an admin changes them | **Admin -> Risk & Controls**, `/api/governance/risk` |
| Kill switch | Stops everything in a scope, or one target, until someone resumes it | **Admin -> Risk & Controls -> Kill switches**, `/api/governance/kill-switches` |
| Capability | A permission such as `killswitch.manage`. Roles carry defaults | `/api/governance/capabilities` |
| Permission set | A named bundle of capabilities assigned to people | **Admin -> Permissions**, `/api/governance/permission-sets` |

Every change here is written to the audit log. Tier policy changes carry the old and new value.

---

## Step 1. Give the agent a tier

In the builder, pick the tier on the agent panel. The picker lists what the tenant's policy for that tier requires and warns about tools on the canvas that sit above it. In YAML or over the API the tier lives in `model_config`:

```yaml
model_config:
  model: claude-sonnet-4-5-20250929
  risk_tier: high
  output_schema: {type: object, required: [surcharge], properties: {surcharge: {type: string}}}
  tools: [decision_evaluate, email_sender]
```

`PUT /api/agents/{id}` replaces `model_config` whole, so send the full object with the tier in it.

A run starts at the higher of the agent's stored tier and the tier of the run that called it, so a nested agent never runs below its caller. When the run calls a tool whose tier is above the run's, the policy's `tool_call_action` decides what happens:

| `tool_call_action` | The call |
|---|---|
| `allow` | Goes ahead and the run's tier rises to the tool's |
| `approval` | Waits on a human approval gate on **Approvals**. Approved, it goes ahead and the tier rises. Otherwise the tool answers with an error |
| `block` | Is refused with a message telling the model the agent's tier is too low for the tool |

The tier and the reasons it rose are kept on the execution. `GET /api/governance/runs/{execution_id}/provenance` (`runs.replay`) returns them with the config hash, the snapshot of the prompt and `model_config` the run used, and which fields have changed on the agent since.

A tool declares its tier on the class (`risk_tier = "medium"`). `scripts/check-tool-config.py` fails on a tool that does not. **Admin -> Risk & Controls -> Tool tiers** lists every tool with its tier.

---

## Step 2. Set what each tier requires

Defaults, before a tenant changes anything:

| Setting | low | medium | high | critical |
|---|---|---|---|---|
| `publish_approvals.min_approvers` | 0 | 0 | 1 | 2 |
| `publish_approvals.exclude_author` | false | false | true | true |
| `publish_approvals.capability` | `approvals.sign` | `approvals.sign` | `approvals.sign` | `approvals.sign` |
| `publish_approvals.escalate_after_hours` | 0 | 0 | 24 | 4 |
| `tool_call_action` | allow | allow | approval | approval |
| `allowed_models` | any | any | any | any |
| `require_output_schema` | false | false | true | true |
| `require_eval_pass` | false | false | true | true |

What each does:

- `publish_approvals` sets how many sign-offs a decision version at that tier needs before it can be published, and an approval request tied to a run at that tier gets the same floor. `exclude_author` keeps the proposer from signing. `capability` can be narrowed with a suffix, `approvals.sign:legal` limits signing to people holding that. After `escalate_after_hours` with no action, the tenant's admins get a notification. The check runs every 15 minutes.
- `tool_call_action` is described in step 1.
- `allowed_models` is a list of model ids, a trailing `*` matches a prefix. Empty means any. An agent on a model outside the list cannot be set active, and a run at that tier on such a model is refused with `MODEL_NOT_ALLOWED`.
- `require_output_schema` refuses to set an agent active at that tier without an output schema.
- `require_eval_pass` makes publishing wait on the agent's gating evaluation suites, see [10-evals](10-evals.md).

Change a tier by sending the fields you want to override. The body replaces that tier's stored overrides as a whole, so anything you leave out goes back to its default, including fields an earlier call changed:

```bash
curl -s -X PUT "$API/api/governance/risk/high" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tool_call_action": "block", "allowed_models": ["claude-sonnet-4-5*"], "publish_approvals": {"min_approvers": 2}}'
```

A decision's own tier is guarded the same way. Raising it applies at once, lowering it needs a reason and the current tier's sign-off, and neither is allowed while a version waits for sign-off. See [09-decisions](09-decisions.md#changing-the-risk-tier).

A change to a permission set, its members, or someone's role takes effect at once in every API worker, each one drops its cached view of that person when told over Redis.

**Decision reviewers.** Every workspace has this permission set ready, holding Review decisions and Sign approvals, the two a person needs to approve any decision approval. Admins can add people to it under Admin, Permissions, from **Someone missing?** on a decision, or by ticking **Can approve decisions** on a Team invite. It is a normal set, so it can be renamed or changed, and it is created again if deleted. Team shows a **Can approve decisions** badge on each member who can, and an admin turns it on or off from the row menu with **Let them approve decisions** or **Stop them approving decisions**. Archiving a decision that was never published needs no sign-off at any tier, because nothing was ever in force.

**Sole-operator sign-off.** In a workspace where nobody else can approve, the person who proposed a decision version or a tier change can sign it alone with a written reason. It is recorded as a self-approval and every admin is told. It is on by default. Turn it off with `PUT /api/governance/settings` and `{"sole_operator_signoff": false}`, admins only. `GET /api/governance/settings` and `GET /api/governance/risk` (under `settings`) show the current value. See [Working alone](../02-runtime/05-approvals-hitl.md#working-alone).

An unknown key or a bad value is refused with 400 naming it. The policy also accepts an `autonomy` object, the thresholds for earned autonomy at that tier, see [02-runtime/21-earned-autonomy](../02-runtime/21-earned-autonomy.md). `GET /api/governance/risk` returns each tier's guide text, default, overrides and the effective policy, plus every tool's tier. `DELETE /api/governance/risk/{tier}` goes back to the default. Reading needs `risk.view`, writing `risk.manage`. Runtime pods pick a change up within five seconds.

---

## Step 3. Stop something with a kill switch

| Scope | Target | Checked |
|---|---|---|
| `all` | always `*` | Every run and tool call in the tenant |
| `agent` | agent id, or `*` | When an agent run starts, and at each tool call of a run already going |
| `pipeline` | pipeline (agent) id, or `*` | When a pipeline starts |
| `tool` | tool name, such as `web_search`, or `*` | At each call of that tool |
| `model` | model id, or `*` | When an agent run starts |
| `trigger` | trigger id, or `*` | When the trigger fires |
| `decision` | decision key, or `*` | Every evaluation, from the API, an agent or a pipeline |
| `source` | source id, or `*` | Every check of a watched source |
| `improvements` | always `*` | Proposing and proving agent improvements in the tenant |

```bash
curl -s -X POST "$API/api/governance/kill-switches" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"scope": "tool", "target": "calculator", "reason": "wrong rounding, fix in progress"}'
```

`reason` is required, at least three characters, and is what users and the model see. Setting a switch that is already on returns the existing one. Pods pick it up within five seconds. A stopped tool answers the model with `The tool calculator is stopped by a kill switch. Reason given: ... An admin can resume it under Admin, Risk and Controls.` as an error result of the call. A stopped decision returns 423 with code `KILL_SWITCH`, a stopped source check returns 409 with the same code.

Resume with `POST /api/governance/kill-switches/{id}/clear`. `GET /api/governance/kill-switches` lists the active ones, add `?include_cleared=true` for history. Setting and clearing need `killswitch.manage`, listing needs `risk.view`. Both write `kill_switch.set` and `kill_switch.cleared` events, so an on-call channel can hear about them through a webhook.

---

## Step 4. Grant capabilities with a permission set

Each role carries defaults. A permission set adds to them, it never takes away.

Pages show a person only what they can do. A Member opening Team, Decisions, a decision, Approvals or Risk and Controls sees the page view only, with a line saying who can act and how to get the right, and no control that would be refused after the click. Ctrl+K lists Team as view only for them and leaves Permissions out. An invite started from a decision's approver list arrives with **Can approve decisions** already ticked and a way back to the decision, and pending invites say when the person will be able to approve.

| Capability | user | creator | admin |
|---|---|---|---|
| `decisions.view`, `decisions.evaluate` | yes | yes | yes |
| `decisions.author` | | yes | yes |
| `decisions.review`, `decisions.publish` | | | yes |
| `approvals.sign` | | | yes |
| `risk.view` | yes | yes | yes |
| `risk.manage`, `killswitch.manage` | | | yes |
| `audit.view`, `audit.verify` | | | yes |
| `sources.manage` | | yes | yes |
| `evals.run` | yes | yes | yes |
| `evals.manage` | | yes | yes |
| `events.manage` | | yes | yes |
| `permissions.manage` | | | yes |
| `runs.replay` | yes | yes | yes |
| `autonomy.view`, `actions.review` | yes | yes | yes |
| `autonomy.manage` | | yes | yes |
| `autonomy.grant` | | | yes |
| `improvements.view`, `improvements.propose` | | yes | yes |
| `improvements.approve` | | | yes |
| `feedback.give` | yes | yes | yes |
| `moderation.review` | | | yes |

Admins hold `*`. A grant of `evals.*` covers every `evals.` capability, and `approvals.sign` covers `approvals.sign:legal`.

```bash
# a set for risk officers
SET=$(curl -s -X POST "$API/api/governance/permission-sets" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Risk officers", "description": "On-call stop and resume", "capabilities": ["killswitch.manage", "risk.manage", "approvals.sign"]}' \
  | python -c 'import sys,json; print(json.load(sys.stdin)["data"]["id"])')

# add a person by email, they must be in your tenant
curl -s -X POST "$API/api/governance/permission-sets/$SET/members" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"email": "ops@example.com"}'
```

An unknown capability is refused with 400. `PATCH /api/governance/permission-sets/{id}` replaces name, description and capabilities. `DELETE /api/governance/permission-sets/{id}` deletes a set. `DELETE /api/governance/permission-sets/{id}/members/{user_id}` removes a person. All of these need `permissions.manage`. Capabilities are cached per user for ten seconds, so a new grant works on the next request after that.

A request without the capability gets 403 with `This needs the <capability> capability. An admin can grant it under Admin, Permissions.` `GET /api/governance/capabilities` returns the catalogue, the role defaults and the caller's own capabilities as `mine`. The SDKs read the same through `permissions()`, which calls `GET /api/me/permissions`.

---

## Audit

- `GET /api/governance/audit/verify` (`audit.verify`) walks the tenant's hash-chained activity log and reports whether it is intact. A nightly job does the same for every tenant.
- `GET /api/governance/audit/export?since=2026-01-01&until=2026-02-01` (`audit.view`) streams the linked log as JSON lines with each row's hashes.
- `POST /api/governance/runs/{execution_id}/replay` (`runs.replay`) runs a past agent execution again on its recorded input, with `{"mode": "pinned"}` for the configuration it ran with or `{"mode": "current"}` for the agent as it is now. An optional `model` runs it on another model.

---

## See also

- [01-architecture/07-governance](../01-architecture/07-governance.md), how the pieces fit together
- [10-evals](10-evals.md), the `require_eval_pass` gate
- [09-decisions](09-decisions.md), sign-off on decision versions
- [05-testing](05-testing.md), `e2e/uat_governance.spec.ts` drives this page's flows through the UI

---

## Source map

| What | Where |
|---|---|
| Endpoints | [`apps/api/app/routers/governance.py`](../../apps/api/app/routers/governance.py), prefix `/api/governance` |
| Capability catalogue and role defaults | [`apps/api/app/core/capabilities.py`](../../apps/api/app/core/capabilities.py) |
| Tiers and default policies | [`apps/agent-runtime/engine/risk.py`](../../apps/agent-runtime/engine/risk.py) |
| Kill switch and policy cache, run tier | [`apps/agent-runtime/engine/governance.py`](../../apps/agent-runtime/engine/governance.py) |
| Tool call check | `_govern` in [`apps/agent-runtime/engine/tools/base.py`](../../apps/agent-runtime/engine/tools/base.py) |
| Unit tests | `tests/unit/test_governance.py` |
