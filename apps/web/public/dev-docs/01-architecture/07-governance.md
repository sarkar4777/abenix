# Governance: risk tiers, kill switches, capabilities, audit

> What controls a tenant has over its agents, pipelines, tools and rules, how they are enforced at run time, and how the platform proves the activity log has not been touched.

---

## Risk tiers

Every agent, pipeline, tool and decision carries one of four tiers.

| Tier | Meant for |
|---|---|
| Low | Reads public or internal data and drafts text a person reads anyway |
| Medium | Writes to internal systems or produces output other teams rely on |
| High | Affects customers, money, compliance positions or regulated records |
| Critical | Irreversible or legally binding actions, filings, payments |

Where the tier comes from:

- **Agents and pipelines** set it in the builder. It is stored as `model_config.risk_tier`.
- **Tools** declare it on the class, `risk_tier = "high"`. `scripts/check-tool-config.py` fails CI when a tool class leaves it out.
- **Decisions** carry it on the decision model, `decision_models.risk_tier`. How decisions are evaluated and versioned is in [Decision service](../02-runtime/20-decision-service.md), the author view in [Decisions](../08-howto/09-decisions.md).

A run starts at its agent's or pipeline's tier, read from the database by id, so a caller cannot understate it. A nested run, such as an agent called by `agent_step`, never runs below the run that called it. When a run calls a tool above its own tier, the policy for the tool's tier decides what happens.

| Action | Effect |
|---|---|
| Allow | The call goes ahead and the run is recorded at the higher tier from then on |
| Ask a person | The run pauses on the Approvals page until someone approves or rejects the call |
| Block | The call is refused with a message telling the agent to raise its tier |

Each execution row records `risk_tier` and `risk_reasons`, the list of what raised it.

### Tier policies

**Admin -> Risk & Controls -> Tier policies** sets, per tenant and per tier:

- Sign-offs before a new version goes live, whether the author may sign, and the capability signers need, for example `approvals.sign:legal`
- What a lower-tier run does when it calls a tool at this tier
- Whether an output schema is required before an agent or pipeline at this tier goes live
- Whether an agent at this tier must pass its gating evaluation suites before it goes live, `require_eval_pass`
- After how many hours an approval nobody has acted on is escalated to admins, `escalate_after_hours`. 0 means never
- Which models are allowed. Empty means any. `claude-opus-*` allows a family

Platform defaults:

| Tier | Sign-offs | Author may sign | Lower-tier tool call | Output schema | Eval pass | Escalate after |
|---|---|---|---|---|---|---|
| Low | 0 | yes | allow | no | no | never |
| Medium | 0 | yes | allow | no | no | never |
| High | 1 | no | ask a person | yes | yes | 24 h |
| Critical | 2 | no | ask a person | yes | yes | 4 h |

With `require_eval_pass` on, publishing an agent is refused with 409 and `EVAL_GATE` unless every gating suite has a completed run against the exact configuration being published that met its threshold. Runs with a model override do not count. An agent with no gating suites is not blocked. See [evaluation suites](../02-runtime/18-evaluation-suites.md).

Those checks run when an agent is published, so a high or critical tier agent that is still a draft has not passed them. People can test such a draft from the builder and chat, signed in as themselves. Every other caller is refused with 409 `DRAFT_NOT_RELEASED` and a message to publish it first: API keys and the SDK, calls from another run (`invoke_agent` and pipeline agent steps), and triggers, which record the run as failed with that code. Low and medium tier drafts run for their owner and anyone they are shared with, as before.

Approvals raised by tiered runs carry the same sign-off rules and escalation. See [approvals](../02-runtime/05-approvals-hitl.md#tier-floor).

The admin screen stores only the settings that differ from the platform default (`PUT /api/governance/risk/{tier}`, `DELETE` to go back to defaults), so later default changes still reach the tenant. Changes apply to new runs within five seconds.

## Kill switches

**Admin -> Risk & Controls -> Kill switches** stops one of these, within five seconds, on every pod:

| Scope | Stops |
|---|---|
| Agent | New runs, and running ones at their next tool call |
| Pipeline | The pipeline and any agent it is running |
| Tool | Every call to the tool, in every agent and pipeline |
| Model | Runs that would use the model, before any tokens are spent |
| Trigger | Schedules and webhooks for the trigger. Webhook senders get 423 |
| Decision | Evaluations of the decision, target is the decision key |
| Watched source | Change detection for the source pauses, target is the source id |
| Agent improvements | Proposing and proving fixes for every agent. Releases in their watch period keep being watched |
| Everything | Every agent, pipeline and tool call in the tenant, and every check above |

Nothing is deleted. A switch needs a reason, which people who hit the stop see. Setting and resuming are written to the audit log, and setting one emits a `kill_switch.set` event. Seeing the list needs `risk.view`, setting or resuming needs `killswitch.manage`. The API is `GET` and `POST /api/governance/kill-switches` and `POST /api/governance/kill-switches/{id}/clear`. A run refused by a switch fails with `KILL_SWITCH`. A model refused by the tier's model list fails with `MODEL_NOT_ALLOWED`. Both show on `/alerts`.

How it works: [`engine/governance.py`](../../apps/agent-runtime/engine/governance.py) keeps a snapshot of tier policies, active switches and agent tiers, and its `SCOPES` are `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision`, `source` and `improvements`. Checks read the snapshot synchronously. Once the snapshot is older than five seconds, the next check starts a refresh in the background and keeps serving the old copy, so a tool call never waits on the database. Only a first load waits, or the load right after a change made through the API on that pod. Other pods pick the change up within five seconds. Switches with no tenant are platform-wide. The one wrapper every tool's `execute` passes through runs the checks, so tools need no code for it.

## Capabilities and permission sets

Roles give everyone a baseline. Capabilities add specific abilities without making someone an admin. The catalog is `CATALOG` in [`apps/api/app/core/capabilities.py`](../../apps/api/app/core/capabilities.py), and `GET /api/governance/capabilities` returns it.

| Capability | Lets you |
|---|---|
| `decisions.view` | See decision models, versions and their history |
| `decisions.evaluate` | Run a published decision from the API, an agent or a pipeline |
| `decisions.author` | Create drafts, edit rules and run tests |
| `decisions.review` | Sign off, or reject, a decision version proposed for publication |
| `decisions.publish` | Make an approved version effective |
| `approvals.sign`, `approvals.sign:<group>` | Sign approval gates, all of them or only those that ask for that group |
| `risk.view` | See tier policies, kill switches and why a run reached its tier |
| `risk.manage` | Change what each risk tier requires |
| `killswitch.manage` | Stop and resume things |
| `audit.view` | Read and export the activity log |
| `audit.verify` | Run the tamper check on the activity log |
| `sources.manage` | Add and change watched sources and their schedules |
| `evals.manage` | Create suites, cases and release gates |
| `evals.run` | Run a suite against an agent, pipeline or decision |
| `events.manage` | Subscribe endpoints and triggers to platform events |
| `permissions.manage` | Create permission sets and assign people |
| `runs.replay` | See a run's provenance and re-run it against its recorded inputs |
| `autonomy.view` | See what each agent may do alone, its track record and the action ledger |
| `autonomy.manage` | Enrol actions, set how success is judged and predicted, demote or turn off |
| `autonomy.grant` | Approve an agent moving up a level, never for an agent you built |
| `actions.review` | Answer watching reviews, record outcomes and flag harm |
| `moderation.review` | Release, redact or reject content a moderation policy held for review. Admins only by default |

Role defaults (`ROLE_DEFAULTS`):

| Role | Gets |
|---|---|
| `user` | `decisions.view`, `decisions.evaluate`, `risk.view`, `evals.run`, `runs.replay`, `autonomy.view`, `actions.review` |
| `creator` | everything a user gets, plus `decisions.author`, `evals.manage`, `sources.manage`, `events.manage`, `autonomy.manage` |
| `admin` | `*`, every capability |

A grant covers more than its exact key. `approvals.sign` covers every `approvals.sign:<group>`, and a group wildcard such as `decisions.*` covers every `decisions.` capability. **Admin -> Permissions** creates named sets, such as "Decision reviewers", and assigns them to people (`permission_sets`, `permission_assignments`). A user's capabilities are cached for ten seconds, so grants apply within that. `GET /api/me/permissions` returns the caller's role and capabilities, and the sidebar shows only what the caller can use.

## Separation of duties

An approval created under a tier policy carries the policy with it: the capability signers need and whether the requester may sign. The sign-off endpoint enforces both. Only admins hold `approvals.sign` by default, so non-admin signers on a tiered gate need it from a permission set. Signing a decision version also needs `decisions.review`. Approvals without a policy keep the older rule, where an admin or creator signs and a self-approval is recorded as such, so single-admin tenants are not locked out.

Autonomy promotions (`gate_kind = autonomy.promote`) need `autonomy.grant` and refuse the agent's author, both when requesting and when signing. The author may self-approve only the sample, or when nobody else in the tenant holds `autonomy.grant`, and the change is recorded as self-approved. Demotions never need an approval. See [Earned autonomy](../02-runtime/21-earned-autonomy.md).

## Tamper-evident audit log

Every `activity_logs` row is linked to the one before it, per tenant, by a SHA-256 hash.

- Rows are written unlinked, so logging never waits on a lock. A background job links settled rows every 30 seconds, one replica at a time.
- The database refuses updates and deletes on the table. The only write allowed is the one-time link.
- Who did something, meaning the user, address and user agent, is committed through a salted digest. GDPR erasure clears those fields and drops the salt, so the person is no longer linkable while the rest of the row still verifies.
- Archiving and retention remove only a linked prefix and leave an `audit.pruned` row naming the last hash removed. Verification starts after it.

**Admin -> Risk & Controls -> Audit integrity** walks the whole chain and reports the first entry that was changed or removed. `GET /api/governance/audit/verify` does the same, and a scheduled job verifies every tenant's chain nightly at 03:15. `GET /api/governance/audit/export` streams the linked log as JSON lines with each row's hashes, for evidence and archiving.

## Run provenance

A database trigger stamps every new execution with the agent revision, a hash of the system prompt and a snapshot of the exact configuration it ran with. Snapshots are stored once per distinct configuration, so a million runs of one agent keep one copy. `GET /api/governance/runs/{execution_id}/provenance` returns the snapshot, the run's tier and reasons, and the configuration fields that have changed since. `POST /api/governance/runs/{execution_id}/replay` runs an agent execution again on its recorded input, `pinned` to the snapshot or on the `current` agent. Pipeline runs replay from a step on the run page instead. Both need `runs.replay`.
