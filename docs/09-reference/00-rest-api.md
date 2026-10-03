# REST API reference

> Compact catalogue of every HTTP endpoint. For full request/response shapes, the FastAPI auto-generated OpenAPI lives at `https://api.example.com/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Auth

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/login` | Email + password → JWT pair |
| `POST` | `/api/auth/refresh` | Refresh token → new JWT |
| `POST` | `/api/auth/logout` | Revoke refresh token |
| `GET`  | `/api/auth/me` | Current user |
| `POST` | `/api/auth/signup` | New tenant + first user (marketplace flow) |
| `POST` | `/api/auth/exchange` | OAuth/OIDC exchange |
| `POST` | `/api/auth/forgot-password` / `reset-password` | Password reset |
| `GET`  | `/api/auth/invite/{token}` | Public invite lookup. Returns `{email, tenant_name, role, expired, used}` |
| `POST` | `/api/auth/accept-invite` | Body `{token, full_name, password}`. Creates the user in the inviting tenant with the invited role, returns the login token pair. 410 when the token is used or expired |

---

## Agents

| Method | Path | Purpose |
|---|---|---|
| `GET`    | `/api/agents` | List, paginated, filterable by `category`, `mode`, `status` |
| `POST`   | `/api/agents` | Create |
| `GET`    | `/api/agents/{id}` | Detail |
| `PUT`    | `/api/agents/{id}` | Update |
| `DELETE` | `/api/agents/{id}` | Soft-delete |
| `POST`   | `/api/agents/{id}/execute` | Run. body `{input, wait, client_token}` |
| `POST`   | `/api/agents/{id}/duplicate` | Clone |
| `GET`    | `/api/agents/{id}/dependents` | Pipelines, agents and triggers that use it |
| `DELETE` | `/api/agents/{id}?force=true` | Archive. Without `force`, 409 `IN_USE` with the dependents when something uses it |
| `GET`    | `/api/agents/deleted` | Archived agents the caller can restore |
| `POST`   | `/api/agents/{id}/restore` | Undo a delete, triggers switch back on |
| `POST`   | `/api/agents/{id}/revisions/{rev}/revert?which=after\|before` | Restore a saved version, or the state before it |
| `POST`   | `/api/agents/{id}/publish` | Set status=active |
| `GET`    | `/api/agents/{id}/revisions` | List version history |
| `POST`   | `/api/agents/{id}/revisions/{rev_id}/revert` | Roll back |
| `GET`    | `/api/agents/{id}/export` | Download as YAML |
| `POST`   | `/api/agents/import` | Import from YAML |
| `POST`   | `/api/agents/{id}/validate-smart` | Run AI Validator |
| `POST`   | `/api/agents/{id}/share` | Legacy share (use `/api/me/shares` instead) |

---

## Executions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/executions` | List, paginated |
| `GET` | `/api/executions/{id}` | Full detail with trace |
| `GET` | `/api/executions/{id}/events` | SSE stream |
| `POST` | `/api/executions/{id}/cancel` | Cancel running |
| `GET` | `/api/executions/{id}/wait?until=terminal` | Block until terminal |

---

## Pipelines

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/pipelines` | List |
| `POST` | `/api/pipelines/validate` | Pre-save validation |
| `POST` | `/api/pipelines/{id}/execute` | Run a pipeline |

---

## Knowledge Bases

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/knowledge-bases` | List |
| `POST` | `/api/knowledge-bases` | Create |
| `GET`  | `/api/knowledge-bases/{id}` | Detail with documents |
| `PUT`  | `/api/knowledge-bases/{id}` | Update |
| `DELETE` | `/api/knowledge-bases/{id}?force=true` | Delete. Without `force`, 409 `IN_USE` when agents or Atlas graphs use it. A confirmed delete unbinds graphs and removes agent grants |
| `GET`  | `/api/knowledge-bases/{id}/dependents` | Agents granted it and Atlas graphs bound to it |
| `POST` | `/api/knowledge-bases/{id}/upload` | Upload document |
| `GET`  | `/api/knowledge-bases/{id}/documents` | List documents |
| `DELETE` | `/api/knowledge-bases/{id}/documents/{doc_id}` | Delete doc |

---

## ML Models

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/ml-models` | List |
| `POST` | `/api/ml-models` | Upload (multipart with metadata) |
| `GET`  | `/api/ml-models/{id}` | Detail |
| `PUT`  | `/api/ml-models/{id}` | Update description + input_schema + output_schema + tags |
| `DELETE` | `/api/ml-models/{id}` | Soft-delete |
| `POST` | `/api/ml-models/{id}/deploy` | Body `{deployment_type, replicas, resource_preset}` |
| `DELETE` | `/api/ml-models/{id}/undeploy` | Undeploy |
| `POST` | `/api/ml-models/{id}/predict` | Run inference |
| `POST` | `/api/ml-models/{id}/activate` / `deactivate` | Set as active version |
| `GET`  | `/api/ml-models/{id}/download` | Download original file |
| `GET`  | `/api/ml-models/versions/{name}` | List versions by name |

---

## Code Assets

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/code-assets` | List |
| `POST` | `/api/code-assets` | Create (zip or git_url in multipart) |
| `GET`  | `/api/code-assets/{id}` | Detail |
| `PUT`  | `/api/code-assets/{id}` | Update schemas + commands |
| `DELETE` | `/api/code-assets/{id}?force=true` | Delete. Without `force`, 409 `IN_USE` with the dependents |
| `POST` | `/api/code-assets/{id}/test` | Test run. 422 `CODE_FAILED` when the code itself fails |
| `POST` | `/api/code-assets/{id}/versions` | Upload a new version, live only if it analyses cleanly |
| `POST` | `/api/code-assets/{id}/versions/{n}/restore` | Make an earlier version live again |
| `GET`  | `/api/code-assets/{id}/dependents` | Agents and pipelines that call it |
| `GET`  | `/api/code-assets/{id}/fetch` | Archive for a sandbox pod, asset-scoped token only |

---

## Approvals

Detail in [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`  | `/api/approvals` | signed in | List, filterable by status |
| `POST` | `/api/approvals` | signed in | Create (typically via the SDK from an agent). `client_token` makes it idempotent |
| `GET`  | `/api/approvals/{approval_id}` | signed in | Detail |
| `GET`  | `/api/approvals/{approval_id}/wait` | signed in | Long-poll until it leaves pending or times out |
| `POST` | `/api/approvals/{approval_id}/signoff` | admin or creator, or the tier policy's signing capability (default `approvals.sign`) | Body `{decision, reason, client_token}`. See below |
| `GET`  | `/api/approvals/webhooks` | signed in | Approval webhook config |
| `PUT`  | `/api/approvals/webhooks` | admin or owner role | Set the approval webhook URL and secret |

`decision` on signoff is one of:

- `approve` counts toward `required_signoffs`
- `deny` closes the approval as denied
- `return` sends it back to the requester as `returned`. `reason` is required, without it the call is a 400

Any other value is a 400. A second signoff by the same user is a 409, so is a signoff on an approval that is no longer pending. When the approval carries a risk tier policy, signing needs that policy's capability, and with `exclude_requester` the requester cannot approve their own request (403). On an agent's `human_approval` gate only `approve` resumes the run, `deny` and `return` both reject it.

---

## Decisions

Rules as versioned decision models. Detail in [08-howto/09-decisions](../08-howto/09-decisions.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`    | `/api/decisions` | `decisions.view` | List decisions |
| `POST`   | `/api/decisions` | `decisions.author` | Create a decision |
| `GET`    | `/api/decisions/{key}` | `decisions.view` | Detail with versions |
| `PATCH`  | `/api/decisions/{key}` | `decisions.author` | Change name, description and other metadata |
| `DELETE` | `/api/decisions/{key}` | `decisions.publish` | Archive |
| `GET`    | `/api/decisions/{key}/versions/{n}` | `decisions.view` | One version |
| `POST`   | `/api/decisions/{key}/versions` | `decisions.author` | Start a new draft |
| `PUT`    | `/api/decisions/{key}/versions/{n}` | `decisions.author` | Save a draft. `If-Match` with the etag, 409 when someone saved first or the version is no longer editable |
| `POST`   | `/api/decisions/{key}/versions/{n}/presence` | `decisions.view` | Mark yourself as editing, returns who else is |
| `POST`   | `/api/decisions/{key}/check` | `decisions.view` | Validate builder content as the author types, without saving |
| `POST`   | `/api/decisions/{key}/versions/{n}/try` | `decisions.view` | Evaluate a version, or unsaved content, against sample facts |
| `POST`   | `/api/decisions/{key}/versions/{n}/validate` | `decisions.view` | Run validation and tests on a version |
| `POST`   | `/api/decisions/{key}/versions/{n}/propose` | `decisions.author` | Send a draft for sign-off. 422 when validation fails |
| `POST`   | `/api/decisions/{key}/versions/{n}/withdraw` | `decisions.author` | Pull a proposed version back to draft |
| `GET`    | `/api/decisions/{key}/versions/{n}/publish-plan` | `decisions.view` | What publishing would do, before anyone does it |
| `POST`   | `/api/decisions/{key}/versions/{n}/publish` | `decisions.publish` | Put an approved version in force. Body `{expected_current}`. 409 `AWAITING_APPROVAL`, `REJECTED` or `NOT_APPROVED` otherwise |
| `POST`   | `/api/decisions/{key}/versions/{n}/retire` | `decisions.publish` | Take the version in force out of force |
| `POST`   | `/api/decisions/{key}/evaluate` | `decisions.evaluate` | Evaluate one set of facts. Body `{facts, as_of, known_at, version, trace, persist}` |
| `POST`   | `/api/decisions/{key}/evaluate-batch` | `decisions.evaluate` | Evaluate many items in one call |
| `POST`   | `/api/decisions/{key}/compare` | `decisions.evaluate` | Same facts against 2 to 10 targets side by side |
| `GET`    | `/api/decisions/{key}/evaluations` | `decisions.view` | Stored evaluations |
| `GET`    | `/api/decisions/{key}/tests` | `decisions.view` | Test cases |
| `POST`   | `/api/decisions/{key}/tests` | `decisions.author` | Add a test case |
| `PUT`    | `/api/decisions/{key}/tests/{test_id}` | `decisions.author` | Change a test case |
| `DELETE` | `/api/decisions/{key}/tests/{test_id}` | `decisions.author` | Delete a test case |
| `GET`    | `/api/decisions/{key}/export` | `decisions.view` | Export rules, `?version=` or the latest |
| `POST`   | `/api/decisions/{key}/import` | `decisions.author` | Import rules into a draft. `If-Match` like a save |
| `GET`    | `/api/decisions/{key}/diff?a=&b=` | `decisions.view` | Diff two versions |

Evaluate, batch and compare also accept API keys. A missing capability is a 403 that names it.

### Reference sets

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`  | `/api/decision-reference-sets` | `decisions.view` | List reference sets |
| `GET`  | `/api/decision-reference-sets/{key}` | `decisions.view` | One reference set |
| `POST` | `/api/decision-reference-sets` | `decisions.author` | Create |
| `PUT`  | `/api/decision-reference-sets/{key}` | `decisions.author` | Replace |

---

## Evaluation suites

Detail in [02-runtime/18-evaluation-suites](../02-runtime/18-evaluation-suites.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`    | `/api/evals/assertion-types` | `evals.run` | Assertion types a case can use |
| `GET`    | `/api/evals/suites` | `evals.run` | List suites |
| `POST`   | `/api/evals/suites` | `evals.manage` | Create a suite |
| `GET`    | `/api/evals/suites/{suite_id}` | `evals.run` | Suite with its cases |
| `PATCH`  | `/api/evals/suites/{suite_id}` | `evals.manage` | Change a suite |
| `DELETE` | `/api/evals/suites/{suite_id}` | `evals.manage` | Delete a suite |
| `POST`   | `/api/evals/suites/{suite_id}/cases` | `evals.manage` | Add a case |
| `POST`   | `/api/evals/suites/{suite_id}/cases/from-execution` | `evals.manage` | Turn a past run into a case with assertions that hold for it |
| `PATCH`  | `/api/evals/cases/{case_id}` | `evals.manage` | Change a case |
| `DELETE` | `/api/evals/cases/{case_id}` | `evals.manage` | Delete a case |
| `POST`   | `/api/evals/assertions/check` | `evals.run` | Validate assertions and try them on an output |
| `POST`   | `/api/evals/suites/{suite_id}/run` | `evals.run` | Start a suite run |
| `GET`    | `/api/evals/suites/{suite_id}/runs` | `evals.run` | Runs of a suite |
| `GET`    | `/api/evals/runs/{run_id}` | `evals.run` | Run detail with per-case results |
| `POST`   | `/api/evals/runs/{run_id}/cancel` | `evals.run` | Cancel a run |
| `GET`    | `/api/evals/runs/{run_id}/compare/{other_id}` | `evals.run` | Two runs side by side, `run_id` is the base |
| `GET`    | `/api/evals/gate/{agent_id}` | `evals.run` | Whether publishing the agent now would pass its gate |

---

## Source Watch

Detail in [02-runtime/17-source-watch](../02-runtime/17-source-watch.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`    | `/api/sources/settings` | signed in | Tenant settings, which credential keys are set, fetch limits |
| `PUT`    | `/api/sources/settings` | `risk.manage` | Body `{host_allowlist, pause_after_failures}` |
| `POST`   | `/api/sources/validate-url` | `sources.manage` | Whether a URL is allowed, and why not |
| `POST`   | `/api/sources/preview` | `sources.manage` | Fetch once and show what would be extracted, nothing saved |
| `GET`    | `/api/sources/changes` | signed in | Recent changes across all sources |
| `GET`    | `/api/sources/changes/{change_id}` | signed in | One change with its diff |
| `GET`    | `/api/sources/snapshots/{snapshot_id}` | signed in | One snapshot |
| `GET`    | `/api/sources/snapshots/{snapshot_id}/raw` | signed in | Raw fetched content of a snapshot |
| `GET`    | `/api/sources` | signed in | List sources |
| `POST`   | `/api/sources` | `sources.manage` | Add a source |
| `GET`    | `/api/sources/{source_id}` | signed in | Source detail |
| `PATCH`  | `/api/sources/{source_id}` | `sources.manage` | Change a source |
| `DELETE` | `/api/sources/{source_id}` | `sources.manage` | Delete a source |
| `POST`   | `/api/sources/{source_id}/pause` | `sources.manage` | Stop checking |
| `POST`   | `/api/sources/{source_id}/resume` | `sources.manage` | Start checking again |
| `POST`   | `/api/sources/{source_id}/check-now` | `sources.manage` | Check now, outside the cadence |
| `GET`    | `/api/sources/{source_id}/snapshots` | signed in | Snapshots of one source |
| `GET`    | `/api/sources/{source_id}/changes` | signed in | Changes of one source |

---

## Governance

Permission sets, risk tiers, kill switches, audit chain, replay and provenance. Detail in [01-architecture/07-governance](../01-architecture/07-governance.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`    | `/api/governance/capabilities` | signed in | Capability catalogue and the defaults per role |
| `GET`    | `/api/governance/permission-sets` | `permissions.manage` | List permission sets |
| `POST`   | `/api/governance/permission-sets` | `permissions.manage` | Create a permission set |
| `PATCH`  | `/api/governance/permission-sets/{set_id}` | `permissions.manage` | Change a permission set |
| `DELETE` | `/api/governance/permission-sets/{set_id}` | `permissions.manage` | Delete a permission set |
| `POST`   | `/api/governance/permission-sets/{set_id}/members` | `permissions.manage` | Add a member |
| `DELETE` | `/api/governance/permission-sets/{set_id}/members/{user_id}` | `permissions.manage` | Remove a member |
| `GET`    | `/api/governance/risk` | `risk.view` | Policy per tier (`low`, `medium`, `high`, `critical`) |
| `PUT`    | `/api/governance/risk/{tier}` | `risk.manage` | Set the policy for a tier |
| `DELETE` | `/api/governance/risk/{tier}` | `risk.manage` | Reset a tier to its default |
| `GET`    | `/api/governance/kill-switches` | `risk.view` | Active switches, `?include_cleared=true` for all |
| `POST`   | `/api/governance/kill-switches` | `killswitch.manage` | Set a switch. `scope` is `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision` or `source` |
| `POST`   | `/api/governance/kill-switches/{switch_id}/clear` | `killswitch.manage` | Clear a switch |
| `GET`    | `/api/governance/audit/verify` | `audit.verify` | Verify the tenant's hash-linked audit chain |
| `GET`    | `/api/governance/audit/export` | `audit.view` | Audit log as JSON lines with hashes, `?since=&until=` |
| `GET`    | `/api/governance/runs/{execution_id}/provenance` | `runs.replay` | What a run ran with |
| `POST`   | `/api/governance/runs/{execution_id}/replay` | `runs.replay` | Run it again on its recorded input. Body `{mode, model}`, `mode` is `pinned` or `current` |

---

## Atlas (Knowledge Graph)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/atlas/nodes` | Filtered list |
| `POST` | `/api/atlas/nodes` | Create |
| `PUT` / `DELETE` | `/api/atlas/nodes/{id}` | Modify |
| `GET` / `POST` / `DELETE` | `/api/atlas/edges` | Edges |
| `POST` | `/api/atlas/query` | Cypher query (admin only) |
| `GET` | `/api/atlas/suggestions` | AI-suggested extensions |

Agent-facing tools (`atlas_describe`, `atlas_query`, `atlas_traverse`, `atlas_search_grounded`, `atlas_cypher`, `atlas_as_of`) live in [`02-runtime/02-tools.md`](../02-runtime/02-tools.md#atlas-tool-cookbook).

---

## Knowledge v2 (cognify, conflicts, versioning, reembed) {#knowledge-v2}

| Method | Path | Purpose |
|---|---|---|
| `GET` / `PUT` | `/api/knowledge/cognify-config` | Per-tenant `auto_accept_threshold`, `conflict_action`, `max_parallel_docs`, `daily_budget_usd` |
| `GET` | `/api/knowledge/cognify-conflicts` | List open conflicts where two sources disagree on the same entity property |
| `POST` | `/api/knowledge/cognify-conflicts/{id}/resolve` | Body `{resolved_value}` — pick the value to keep |
| `POST` | `/api/knowledge/{kb}/documents/{doc}/replace` | Upload a new version. Old row → `is_current=false, superseded_by=<new_id>` |
| `POST` | `/api/knowledge/{kb}/reembed` | Body `{embedding_model, dry_run?}`. Enqueues kb_reembed worker, returns `job_id` + cost estimate + ETA |
| `GET` / `POST` / `DELETE` | `/api/knowledge/{kb}/documents/{doc}/grants` | Document-level ACL: `(subject_type, subject_id, permission)`. Pre-filters candidates before similarity search, cached 60 s in Redis |

### GDPR

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/gdpr/users/{user_id}/purge` | Five-store cascade: postgres, pinecone, neo4j, blob, trajectory |
| `GET`  | `/api/gdpr/users/{user_id}/receipts` | Per-store audit trail (`gdpr_purge_log` rows) — provable to a regulator |

See [`02-runtime/15-v2-knowledge-enterprise.md`](../02-runtime/15-v2-knowledge-enterprise.md) for the implementation details and [`04-data-model/03-knowledge.md`](../04-data-model/03-knowledge.md) for the data model.

---

## Team

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/team/members` | Members plus pending invites. Admins also get `invite_url` per invite |
| `POST` | `/api/team/invite` | Admin only. Body `{email, role}`. Returns the invite with `invite_url` built from `WEB_BASE_URL` or the request origin |
| `DELETE` | `/api/team/invites/{id}` | Cancel a pending invite |

---

## Triggers

| Method | Path | Purpose |
|---|---|---|
| `GET` / `POST` | `/api/triggers` | Triggers you created or on your agents, all for admins. `agent_id` narrows the list. Creating needs run access to the agent |
| `PUT` / `DELETE` | `/api/triggers/{id}` | Update or delete |
| `POST` | `/api/triggers/{id}/run` | Owner or admin. Fires the trigger once as its owner through the scheduler dispatch path. 202 with `{execution_id}` |
| `POST` | `/api/triggers/webhook/{token}` | Inbound webhook fire |

---

## Resource sharing (polymorphic)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/me/shares` | Create / update share |
| `GET`  | `/api/me/shares/of/{type}/{id}` | List shares of one resource |
| `GET`  | `/api/me/shares/received` | What's shared with me |
| `GET`  | `/api/me/shares/sent` | What I shared |
| `DELETE` | `/api/me/shares/{id}` | Revoke |

---

## Me + permissions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/me/permissions` | Permission matrix used by sidebar gating |
| `GET` | `/api/me/notifications` | Inbox |
| `GET` | `/api/me/favorites` | Saved agents |

---

## Admin

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/cluster/summary` | Cluster health (nodes, pvcs, db top tables) |
| `GET` / `POST` / `PUT` | `/api/admin/llm-pricing` | Pricing rows |
| `GET` / `PUT` | `/api/admin/llm-settings` | Provider settings |
| `GET` / `POST` | `/api/admin/archives` | Archive runs |
| `GET` / `POST` | `/api/admin/dlq` | Dead-letter queue |
| `GET` / `POST` / `PUT` / `DELETE` | `/api/connectors` | Integrations |
| `GET` / `POST` / `PUT` | `/api/admin/moderation` | Policies |

### Tool configuration

Detail in [08-howto/08-tool-configuration](../08-howto/08-tool-configuration.md).

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `GET`    | `/api/admin/tool-config` | admin role | Every declared key by provider, with where its value comes from. `?scope=tenant` (default) or `platform` |
| `PATCH`  | `/api/admin/tool-config/{key}` | admin role | Save a value in the tenant (default) or platform scope |
| `DELETE` | `/api/admin/tool-config/{key}` | admin role | Remove the saved value in one scope so the next source applies |
| `POST`   | `/api/admin/tool-config/{key}/test` | admin role | Run the declaring tool's own check, if it has one |

---

## Edge nodes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/edge/register` | Initial registration |
| `POST` | `/api/edge/heartbeat` | Periodic check-in |
| `POST` | `/api/edge/executions/bulk-upload` | Ship completed executions |
| `GET` | `/api/admin/edge` | Cloud-side node inventory |

---

## Webhooks (inbound)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/webhooks/inbound/{slug}` | Tenant-configurable webhook receiver |

## Webhooks (outbound events)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/webhooks/catalog` | Event types a subscription can match |
| `GET` | `/api/webhooks` | List subscriptions |
| `POST` | `/api/webhooks` | Create a subscription |
| `PUT` | `/api/webhooks/{webhook_id}` | Change a subscription |
| `DELETE` | `/api/webhooks/{webhook_id}` | Delete a subscription |
| `POST` | `/api/webhooks/{webhook_id}/test` | Send a test event |
| `GET` | `/api/webhooks/{webhook_id}/deliveries` | Recent deliveries |
| `POST` | `/api/webhooks/deliveries/{delivery_id}/redeliver` | Send a delivery again |

Signing, retries and the event catalogue are in [02-runtime/19-outbound-events](../02-runtime/19-outbound-events.md).

---

## A2A (agent-to-agent) protocol

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/.well-known/agent-card` | Discovery for AP-class A2A clients |
| `POST` | `/api/a2a/dispatch` | A2A dispatch endpoint |

---

## Health + telemetry

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness + DB/Redis/NATS ping |
| `GET` | `/metrics` | Prometheus scrape |
| `GET` | `/api/version` | git sha + build info |

---

## Full schema

The FastAPI app generates an OpenAPI 3.1 schema at `/openapi.json`. Use it with code generators or as the source of truth for the SDKs.

```bash
curl https://api.example.com/openapi.json > openapi.json
```

---

## See also

- [03-sdk/00-overview](../03-sdk/00-overview.md) — SDK surface (wraps these endpoints)
- [01-env-vars](01-env-vars.md) — server-side configuration
