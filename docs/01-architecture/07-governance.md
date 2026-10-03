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
- **Decisions** carry it on the decision model.

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

Approvals raised by tiered runs carry the same sign-off rules and escalation. See [approvals](../02-runtime/05-approvals-hitl.md#tier-floor).

Only the settings that differ from the platform default are stored, so later default changes still reach the tenant. Changes apply to new runs within five seconds.

## Kill switches

**Admin -> Risk & Controls -> Kill switches** stops one of these, within five seconds, on every pod:

| Scope | Stops |
|---|---|
| Agent | New runs, and running ones at their next tool call |
| Pipeline | The pipeline and any agent it is running |
| Tool | Every call to the tool, in every agent and pipeline |
| Model | Runs that would use the model, before any tokens are spent |
| Trigger | Schedules and webhooks for the trigger. Webhook senders get 423 |
| Decision | Evaluations of the decision |
| Everything | Every agent, pipeline and tool call in the tenant |

Nothing is deleted. A switch needs a reason, which people who hit the stop see. Setting and resuming are written to the audit log. A run refused by a switch fails with `KILL_SWITCH`. A model refused by the tier's model list fails with `MODEL_NOT_ALLOWED`. Both show on `/alerts`.

How it works: `engine/governance.py` keeps a snapshot of tier policies, active switches and agent tiers. Checks read the snapshot synchronously, and a background task refreshes it every five seconds, so a tool call never waits on the database. The one wrapper every tool's `execute` passes through runs the checks, so tools need no code for it.

## Capabilities and permission sets

Roles give everyone a baseline. Capabilities add specific abilities without making someone an admin.

| Capability | Lets you |
|---|---|
| `decisions.view`, `decisions.evaluate` | See and run decisions |
| `decisions.author` | Create drafts, edit rules, run tests, propose |
| `decisions.publish` | Make an approved version effective |
| `approvals.sign`, `approvals.sign:<group>` | Sign approval gates, all of them or only a group's |
| `risk.view`, `risk.manage` | See or change tier policies |
| `killswitch.manage` | Stop and resume things |
| `audit.view`, `audit.verify` | Read or verify the activity log |
| `permissions.manage` | Create permission sets and assign people |

Users get view, evaluate and replay. Creators add authoring. Admins hold everything. **Admin -> Permissions** creates named sets, such as "Decision reviewers", and assigns them to people. Grants apply within ten seconds. `GET /api/me/permissions` returns the caller's capabilities, and the sidebar shows only what the caller can use.

## Separation of duties

An approval created under a tier policy carries the policy with it: the capability signers need and whether the requester may sign. The sign-off endpoint enforces both. Approvals without a policy keep the older rule, where an admin or creator signs and a self-approval is recorded as such, so single-admin tenants are not locked out.

## Tamper-evident audit log

Every `activity_logs` row is linked to the one before it, per tenant, by a SHA-256 hash.

- Rows are written unlinked, so logging never waits on a lock. A background job links settled rows every 30 seconds, one replica at a time.
- The database refuses updates and deletes on the table. The only write allowed is the one-time link.
- Who did something, meaning the user, address and user agent, is committed through a salted digest. GDPR erasure clears those fields and drops the salt, so the person is no longer linkable while the rest of the row still verifies.
- Archiving and retention remove only a linked prefix and leave an `audit.pruned` row naming the last hash removed. Verification starts after it.

**Admin -> Risk & Controls -> Audit integrity** walks the whole chain and reports the first entry that was changed or removed. `GET /api/governance/audit/verify` does the same.

## Run provenance

A database trigger stamps every new execution with the agent revision, a hash of the system prompt and a snapshot of the exact configuration it ran with. Snapshots are stored once per distinct configuration, so a million runs of one agent keep one copy. `GET /api/governance/runs/{execution_id}/provenance` returns the snapshot and the configuration fields that have changed since.
