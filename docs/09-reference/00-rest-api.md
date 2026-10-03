# REST API reference

> Every HTTP route the API serves, generated from the routers in `apps/api/app/routers/` and `main.py`. For request and response shapes, FastAPI serves Swagger UI at `/docs`, ReDoc at `/redoc` and the schema at `/openapi.json`.

## Conventions

- Base URL is the API host, for example `https://api.example.com`. Every route below is under `/api` except `/`.
- Responses use the envelope `{data, error, meta}`. Validation failures are 422 with `error_code: VALIDATION_ERROR`.
- The **Auth** column says what the route checks:
  - `public` needs nothing
  - `signed in` takes a JWT (`Authorization: Bearer ...`) or an API key (`X-API-Key: af_...`)
  - `admin role` is a signed-in user with the tenant `admin` role
  - a capability such as `decisions.view` is a signed-in user who holds it through a role default or a permission set. A missing capability is a 403 that names it
  - anything else is spelled out, for example a scoped token or a webhook secret
- Ownership checks inside a handler (owner or admin, edit access) are noted in the purpose.
- An API key with the `can_delegate` scope may send `X-Abenix-Subject` to act for an end user.

---

## Auth and SSO

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/auth/register` | public | Self-serve signup. Creates a tenant and its first user as admin. 409 when the email exists |
| `POST` | `/api/auth/login` | public | Email and password to an access and refresh token pair |
| `GET` | `/api/auth/invite/{token}` | public | Invite lookup. Returns `{email, tenant_name, role, expired, used}` |
| `POST` | `/api/auth/accept-invite` | public | Body `{token, full_name, password}`. Creates the user in the inviting tenant with the invited role and returns the token pair. 410 when the token is used or expired |
| `POST` | `/api/auth/refresh` | public | Refresh token to a new token pair |
| `POST` | `/api/auth/logout` | signed in | Revoke the refresh token |
| `GET` | `/api/auth/me` | signed in | Current user |
| `GET` | `/api/auth/oidc/providers` | public | Which SSO buttons the login page should show |
| `GET` | `/api/auth/oidc/{provider}/start` | public | Redirect to the provider to start an SSO login |
| `GET` | `/api/auth/oidc/{provider}/callback` | public | Provider callback. Finds or creates the user and issues tokens |

---

## Me, sharing and account

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/account/export` | signed in | Export your own data (GDPR Article 20) |
| `DELETE` | `/api/account` | signed in | Delete your account and data (GDPR Article 17) |
| `GET` | `/api/account/privacy` | signed in | Privacy and data processing configuration, for audits |
| `GET` | `/api/me` | signed in | Alias for `GET /api/auth/me` |
| `GET` | `/api/me/` | signed in | Same alias with a trailing slash |
| `GET` | `/api/me/permissions` | signed in | Role, per-feature flags and UI hints that drive sidebar gating |
| `POST` | `/api/me/shares` | signed in | Share any supported resource with another user in your tenant |
| `DELETE` | `/api/me/shares/{share_id}` | signed in | Revoke a share. The share's creator, the resource owner or an admin |
| `GET` | `/api/me/shares/of/{resource_type}/{resource_id}` | signed in | Active shares of one resource. Caller must own or admin it |
| `GET` | `/api/me/shares/received` | signed in | Resources shared with you |
| `GET` | `/api/me/shares/sent` | signed in | Shares you created |

---

## Settings

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/settings/builder_model` | signed in | Model the AI Builder uses to preview and validate drafts |
| `PUT` | `/api/settings/builder_model` | admin role | Set the AI Builder model |
| `GET` | `/api/settings/limits` | signed in | Execution budgets as the runtime will apply them |
| `GET` | `/api/settings/profile` | signed in | Your profile |
| `PUT` | `/api/settings/profile` | signed in | Update your profile |
| `POST` | `/api/settings/password` | signed in | Change your password |
| `GET` | `/api/settings/notifications` | signed in | Your notification preferences |
| `PUT` | `/api/settings/notifications` | signed in | Update notification preferences |
| `GET` | `/api/settings/activity` | signed in | Your recent activity |
| `GET` | `/api/settings/sessions` | signed in | Your active sessions |
| `GET` | `/api/settings/retention` | signed in | Tenant data retention settings |
| `PUT` | `/api/settings/retention` | signed in | Update tenant data retention settings |
| `GET` | `/api/settings/dlp` | signed in | Tenant DLP settings |
| `PUT` | `/api/settings/dlp` | signed in | Update DLP settings. Modes are `detect`, `mask` and `block` |
| `GET` | `/api/settings/sandbox` | signed in | Effective sandbox settings, env defaults with tenant overrides on top |
| `PUT` | `/api/settings/sandbox` | admin role | Set tenant sandbox overrides. Send `null` or omit a key to clear it |
| `GET` | `/api/settings/tenant` | signed in | Tenant settings. The Slack webhook is shown masked to admins only |
| `PUT` | `/api/settings/tenant` | admin role | Update tenant settings |

---

## API keys

Keys start with `af_` and go in `X-API-Key`. Roles and scopes are in [01-architecture/01-tenants-rbac](../01-architecture/01-tenants-rbac.md). Delegated subjects are under [Access control](#access-control-delegated-subjects).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/api-keys` | signed in | Your API keys, every key in the tenant for an admin |
| `POST` | `/api/api-keys` | signed in | Create a key. The secret is returned once. Only a platform superadmin can mint for another tenant |
| `DELETE` | `/api/api-keys/{key_id}` | signed in | Revoke a key. Your own, or any in the tenant for an admin |
| `PATCH` | `/api/api-keys/{key_id}` | signed in | Change a key's name, scopes or expiry |

---

## Notifications

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `WEBSOCKET` | `/api/ws/{user_id}` | `?token=` JWT | Live notification and execution events over WebSocket |
| `GET` | `/api/notifications` | signed in | Your notifications |
| `GET` | `/api/notifications/unread-count` | signed in | Unread count |
| `POST` | `/api/notifications/{notification_id}/read` | signed in | Mark one read |
| `POST` | `/api/notifications/read-all` | signed in | Mark all read |
| `GET` | `/api/notifications/stream` | signed in | SSE stream of new notifications. `?types=` takes a comma-separated filter |
| `POST` | `/api/admin/notification-channels/{channel}/test` | admin role | Send a test message on a notification channel |

---

## Team

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/team/members` | signed in | Members plus pending invites. Admins also get `invite_url` per invite |
| `POST` | `/api/team/dev-create-member` | admin role | Create a member in your tenant right away, without an invite |
| `POST` | `/api/team/invite` | admin role | Body `{email, role}`. Returns the invite with `invite_url` built from `WEB_BASE_URL` or the request origin |
| `PUT` | `/api/team/members/{member_id}/role` | admin role | Change a member's role |
| `DELETE` | `/api/team/members/{member_id}` | admin role | Remove a member |
| `DELETE` | `/api/team/invites/{invite_id}` | signed in | Cancel a pending invite |
| `PUT` | `/api/team/members/{member_id}/quota` | admin role | Set a member's token and cost quotas |

---

## Agents

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/agents/{agent_id}/comments` | signed in | Add a comment |
| `GET` | `/api/agents/{agent_id}/comments` | signed in | List comments |
| `PUT` | `/api/agents/{agent_id}/comments/{comment_id}` | signed in | Edit a comment |
| `POST` | `/api/agents/{agent_id}/favorite` | signed in | Favorite an agent |
| `DELETE` | `/api/agents/{agent_id}/favorite` | signed in | Unfavorite |
| `GET` | `/api/agents/favorites` | signed in | Your favorites |
| `PUT` | `/api/agents/{agent_id}/favorite` | signed in | Move a favorite to a collection. Body `{collection}` |
| `POST` | `/api/agents/{agent_id}/share` | signed in | Share an agent with a user in the same tenant. `/api/me/shares` covers every resource type |
| `GET` | `/api/agents/{agent_id}/shares` | signed in | Users the agent is shared with |
| `DELETE` | `/api/agents/{agent_id}/shares/{share_id}` | signed in | Revoke a share |
| `GET` | `/api/agents/shared-with-me` | signed in | Agents shared with you |
| `DELETE` | `/api/agents/bulk` | signed in | Archive several agents under the same rules as a single delete |
| `GET` | `/api/agents` | signed in | List agents visible to the caller. `scope=tenant` needs admin |
| `GET` | `/api/agents/deleted` | signed in | Archived agents the caller can restore, the tenant's for an admin |
| `POST` | `/api/agents/{agent_id}/restore` | signed in | Undo a delete. Owner or admin. Triggers switch back on |
| `GET` | `/api/agents/by-slug/{slug}` | signed in | Resolve an agent by slug. 404 when not found or not visible |
| `GET` | `/api/agents/{agent_id}/export` | signed in | Export as a JSON template |
| `POST` | `/api/agents/import` | signed in | Import from an exported JSON template |
| `GET` | `/api/agents/{agent_id}` | signed in | Detail |
| `GET` | `/api/agents/{agent_id}/self-check` | signed in | Check the stored config for structural issues |
| `POST` | `/api/agents` | signed in | Create. Only admins can create `oob` agents |
| `PUT` | `/api/agents/{agent_id}` | signed in | Update. Creator, admin or a user with edit access. Only admins edit `oob` agents |
| `GET` | `/api/agents/{agent_id}/revisions` | signed in | Version history |
| `POST` | `/api/agents/{agent_id}/revisions/{revision_id}/revert` | signed in | Restore a saved version, or the state before it with `?which=before`. Owner or admin |
| `GET` | `/api/agents/{agent_id}/dependents` | signed in | Pipelines, agents and triggers that use it |
| `DELETE` | `/api/agents/{agent_id}` | signed in | Archive. Creator or admin. Without `?force=true`, 409 `IN_USE` with the dependents when something uses it |
| `POST` | `/api/agents/{agent_id}/duplicate` | signed in | Clone |
| `POST` | `/api/agents/{agent_id}/publish` | signed in | Body `{visibility, marketplace_price, category}`. `tenant` makes it active, `public` sends it to admin review. 400 when the risk tier setup is incomplete, 409 `EVAL_GATE` with `details.suites` when the evaluation gate fails |
| `POST` | `/api/agents/{agent_id}/review` | admin role | Approve or reject an agent submitted for review |
| `POST` | `/api/agents/{agent_id}/validate-smart` | signed in | Run the layered AI Validate stack on a saved agent |
| `GET` | `/api/agents/{agent_id}/preview-validation` | signed in | Which model the agent would run on right now |
| `POST` | `/api/agents/{agent_id_or_slug}/execute` | signed in | Run by id or slug. Body `{message, context, stream, wait, wait_mode, wait_timeout_seconds}`. For a pipeline agent, declared `input_variables` defaults fill in under the caller's `context`. An `Idempotency-Key` header dedupes non-streaming calls. 429 `BUDGET_EXCEEDED` when the agent is over `daily_cost_limit` or `daily_budget_usd` |
| `GET` | `/api/agents/{agent_id}/memories` | signed in | Stored memories of an agent |
| `DELETE` | `/api/agents/{agent_id}/memories/{memory_id}` | signed in | Delete one memory |
| `DELETE` | `/api/agents/{agent_id}/memories` | signed in | Delete all memories of an agent |
| `POST` | `/api/agents/{agent_id}/reviews` | signed in | Leave a rating and review |
| `GET` | `/api/agents/{agent_id}/reviews` | signed in | List reviews |

---

## AI Builder and playgrounds

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/ai/build-agent` | signed in | Generate an agent or pipeline config from a plain-language description |
| `POST` | `/api/ai/generate-tool` | signed in | Generate a custom tool from a description, with an adversarial review |
| `POST` | `/api/ai/build-iterative` | signed in | SSE. Generate, validate and judge in a loop |
| `POST` | `/api/ai/simulate-meeting` | signed in | Run a meeting agent against a synthetic transcript, no real room |
| `POST` | `/api/load-playground/generate` | signed in | Generate a Python load-test script for an agent or pipeline |
| `POST` | `/api/load-playground/execute` | signed in | Run a generated load-test script with a one-hour API key. Streams stdout over SSE |
| `GET` | `/api/sdk-playground/asset-context/{asset_type}/{asset_id}` | signed in | Resolve an asset to the details the playground needs |
| `POST` | `/api/sdk-playground/generate` | signed in | Generate SDK code with the LLM, using the SDK source as context |
| `POST` | `/api/sdk-playground/execute` | signed in | Run Python with the SDK available, in a sandbox |
| `GET` | `/api/sdk-playground/use-cases` | public | Use case templates |

---

## Executions

Replay on the original input, pinned or current, is under [Governance](#governance). `GET /api/executions/{id}/replay` here only returns the trace for step-through viewing.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/batch/execute` | signed in | Run one agent over many inputs. Needs execute access, checks the daily caps before queueing (429 `BUDGET_EXCEEDED`), and records every input as its own execution row whose id is in the batch result. Runs get the agent's knowledge base grants, MCP tools and the tenant moderation gate, the same as execute. Pipeline agents are refused |
| `GET` | `/api/batch/{batch_id}` | signed in | Batch status |
| `GET` | `/api/executions/live` | signed in | Running executions in the tenant |
| `GET` | `/api/executions/live/stream` | signed in | SSE of execution state changes, every 2 seconds |
| `GET` | `/api/executions/live/{execution_id}` | signed in | Live state of one execution |
| `GET` | `/api/executions/tree/{execution_id}` | signed in | Parent plus every child execution |
| `GET` | `/api/executions/approvals` | signed in | Pending human-approval gates in the tenant |
| `POST` | `/api/executions/{execution_id}/approve` | signed in | Approve or reject a gate. `?gate_id=` names it |
| `GET` | `/api/executions/{execution_id}/stream` | signed in | SSE of the run's events, replayed from the start then live |
| `GET` | `/api/executions/{execution_id}/watch` | Bearer header or `?token=` | Live DAG snapshot stream for one execution. The query token is for browser EventSource |
| `GET` | `/api/executions/{execution_id}` | signed in | Full record with trace |
| `GET` | `/api/executions` | signed in | Past executions with filters, paginated |
| `DELETE` | `/api/executions/{execution_id}` | signed in | Delete. Owner or admin |
| `GET` | `/api/executions/{execution_id}/replay` | signed in | Full trace for step-through replay |
| `GET` | `/api/executions/{execution_id}/children` | signed in | Child executions spawned by this run |

---

## Pipelines

A pipeline is an agent with `model_config.mode = "pipeline"`, so `{agent_id}` and `{pipeline_id}` are agent ids. Running one through `POST /api/agents/{id}/execute` (stream or not) fills in its declared `input_variables` defaults under whatever `context` the caller sent.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/pipelines/{pipeline_id}/diffs` | signed in | Recent failure diffs, newest first |
| `GET` | `/api/pipelines/{pipeline_id}/patches` | signed in | Drafted patches, filter by status |
| `POST` | `/api/pipelines/{pipeline_id}/diagnose` | signed in | Run the Pipeline Surgeon on the latest or a named failure. Owner or admin |
| `POST` | `/api/pipelines/{pipeline_id}/patches/{patch_id}/apply` | signed in | Apply a pending patch to the live DSL. Owner or admin |
| `POST` | `/api/pipelines/{pipeline_id}/patches/{patch_id}/reject` | signed in | Reject a patch. Owner or admin |
| `POST` | `/api/pipelines/{pipeline_id}/patches/{patch_id}/rollback` | signed in | Restore the snapshot an applied patch took. Owner, admin or the approver |
| `POST` | `/api/pipelines/{agent_id}/execute` | signed in | Run a pipeline DSL sent in the body against the agent's tools. The execute routes answer 429 `BUDGET_EXCEEDED` when the agent is over a daily cap, and stop at the next node once `per_execution_cost_limit` is spent |
| `GET` | `/api/pipelines/{agent_id}/config` | signed in | Saved `pipeline_config` of the agent |
| `POST` | `/api/pipelines/{agent_id}/execute-saved` | signed in | Run the agent's saved pipeline |
| `POST` | `/api/pipelines/{agent_id}/execute-stream` | signed in | Run with SSE node progress |
| `GET` | `/api/pipelines/{agent_id}/state` | signed in | Persistent key-value state of a pipeline |
| `PUT` | `/api/pipelines/{agent_id}/state` | signed in | Update state keys. Body is a dict |
| `POST` | `/api/pipelines/{agent_id}/replay` | signed in | Replay from one node using cached outputs of an earlier run |
| `POST` | `/api/pipelines/validate` | signed in | Validate a pipeline definition without running it |
| `POST` | `/api/pipelines/validate-smart` | signed in | Run the layered AI Validate stack on a pipeline config |
| `POST` | `/api/pipelines/{agent_id}/validate` | signed in | Dry-run validate against the agent's config, no side effects |
| `GET` | `/api/workflow-shell/grammar` | signed in | Verb registry, used for autocomplete |
| `POST` | `/api/workflow-shell/{pipeline_id}` | signed in | Run a shell command against a pipeline. Changes need owner or admin |

---

## Conversations

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/conversations` | signed in | Threads visible to you or the acting subject |
| `POST` | `/api/conversations` | signed in | New chat thread |
| `GET` | `/api/conversations/{conversation_id}` | signed in | Thread with messages |
| `POST` | `/api/conversations/{conversation_id}/turn` | signed in | Add a user message, run the agent with the history, save both |
| `PUT` | `/api/conversations/{conversation_id}` | signed in | Update a thread |
| `DELETE` | `/api/conversations/{conversation_id}` | signed in | Delete a thread |
| `POST` | `/api/conversations/{conversation_id}/messages` | signed in | Save a message without running the agent |
| `POST` | `/api/conversations/{conversation_id}/share` | signed in | Create a share link |
| `DELETE` | `/api/conversations/{conversation_id}/share` | signed in | Remove the share link |
| `GET` | `/api/conversations/shared/{share_token}` | public | Read a shared thread |

---

## Triggers

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/triggers` | signed in | Create a webhook or schedule trigger. Needs run access to the agent |
| `GET` | `/api/triggers` | signed in | Triggers you created or on your agents, all for an admin. `agent_id` narrows the list |
| `DELETE` | `/api/triggers/{trigger_id}` | signed in | Delete |
| `PUT` | `/api/triggers/{trigger_id}` | signed in | Update |
| `POST` | `/api/triggers/webhook/{token}` | webhook token | Inbound event from an external system, runs the agent. 429 `BUDGET_EXCEEDED` when the agent is over a daily cap, with the failed run's id |
| `POST` | `/api/triggers/{trigger_id}/run` | signed in | Fire once as the trigger's owner, through the scheduler path. Trigger owner, agent owner or admin. 202 with `{execution_id}`, or 429 `BUDGET_EXCEEDED` |

---

## Approvals

Detail in [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/approvals` | signed in | Create, usually from an agent through the SDK. `client_token` makes it idempotent |
| `GET` | `/api/approvals` | signed in | List, filterable by status |
| `GET` | `/api/approvals/webhooks` | signed in | Approval webhook config |
| `PUT` | `/api/approvals/webhooks` | admin or owner role | Set the approval webhook URL and secret |
| `GET` | `/api/approvals/{approval_id}` | signed in | Detail |
| `GET` | `/api/approvals/{approval_id}/wait` | signed in | Long-poll until it leaves pending or times out |
| `POST` | `/api/approvals/{approval_id}/signoff` | signed in, plus the tier's signing capability when set | Body `{decision, reason, client_token}`. See below |

`decision` on signoff is one of:

- `approve` counts toward `required_signoffs`
- `deny` closes the approval as denied
- `return` sends it back to the requester as `returned`. `reason` is required, without it the call is a 400

Any other value is a 400. A second signoff by the same user is a 409, so is a signoff on an approval that is no longer pending. When the approval carries a risk tier policy, signing needs that policy's capability (default `approvals.sign`), and with `exclude_requester` the requester cannot approve their own request (403). On an agent's `human_approval` gate only `approve` resumes the run, `deny` and `return` both reject it.

A tiered approval also carries the tier's `escalate_after_hours`. When it stays pending that long, the tenant's admins get one notification. There is no escalation endpoint, the scheduler does it.

---

## Decisions

Rules as versioned decision models. Detail in [08-howto/09-decisions](../08-howto/09-decisions.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/decisions` | `decisions.view` | List decisions |
| `POST` | `/api/decisions` | `decisions.author` | Create a decision |
| `GET` | `/api/decisions/{key}` | `decisions.view` | Detail with versions |
| `PATCH` | `/api/decisions/{key}` | `decisions.author` | Change name, description and other metadata |
| `DELETE` | `/api/decisions/{key}` | `decisions.publish` | Archive |
| `GET` | `/api/decisions/{key}/versions/{n}` | `decisions.view` | One version |
| `POST` | `/api/decisions/{key}/versions` | `decisions.author` | Start a new draft |
| `PUT` | `/api/decisions/{key}/versions/{n}` | `decisions.author` | Save a draft. `If-Match` with the etag, 409 when someone saved first or the version is no longer editable |
| `POST` | `/api/decisions/{key}/versions/{n}/presence` | `decisions.view` | Mark yourself as editing, returns who else is |
| `POST` | `/api/decisions/{key}/check` | `decisions.view` | Validate builder content as the author types, without saving |
| `POST` | `/api/decisions/{key}/versions/{n}/try` | `decisions.view` | Evaluate a version, or unsaved content, against sample facts |
| `POST` | `/api/decisions/{key}/versions/{n}/validate` | `decisions.view` | Run validation and tests on a version |
| `POST` | `/api/decisions/{key}/versions/{n}/propose` | `decisions.author` | Send a draft for sign-off. 422 when validation fails |
| `POST` | `/api/decisions/{key}/versions/{n}/withdraw` | `decisions.author` | Pull a proposed version back to draft |
| `POST` | `/api/decisions/{key}/versions/{n}/publish` | `decisions.publish` | Put an approved version in force. Body `{expected_current}`. 409 `AWAITING_APPROVAL`, `REJECTED` or `NOT_APPROVED` otherwise |
| `GET` | `/api/decisions/{key}/versions/{n}/publish-plan` | `decisions.view` | What publishing would do, before anyone does it |
| `POST` | `/api/decisions/{key}/versions/{n}/retire` | `decisions.publish` | Take the version in force out of force |
| `POST` | `/api/decisions/{key}/evaluate` | `decisions.evaluate` | Evaluate one set of facts. Body `{facts, as_of, known_at, version, trace, persist, idempotency_key}` |
| `POST` | `/api/decisions/{key}/evaluate-batch` | `decisions.evaluate` | Evaluate many items in one call |
| `POST` | `/api/decisions/{key}/compare` | `decisions.evaluate` | Same facts against 2 to 10 targets side by side |
| `GET` | `/api/decisions/{key}/evaluations` | `decisions.view` | Stored evaluations |
| `GET` | `/api/decisions/{key}/tests` | `decisions.view` | Test cases |
| `POST` | `/api/decisions/{key}/tests` | `decisions.author` | Add a test case |
| `PUT` | `/api/decisions/{key}/tests/{test_id}` | `decisions.author` | Change a test case |
| `DELETE` | `/api/decisions/{key}/tests/{test_id}` | `decisions.author` | Delete a test case |
| `GET` | `/api/decisions/{key}/export` | `decisions.view` | Export rules, `?version=` or the latest |
| `POST` | `/api/decisions/{key}/import` | `decisions.author` | Import rules into a draft. `If-Match` like a save |
| `GET` | `/api/decisions/{key}/diff` | `decisions.view` | Diff two versions, `?a=&b=` |

Evaluate, batch and compare also accept API keys. A missing capability is a 403 that names it.

### Reference sets

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/decision-reference-sets` | `decisions.view` | List reference sets |
| `GET` | `/api/decision-reference-sets/{key}` | `decisions.view` | One reference set |
| `POST` | `/api/decision-reference-sets` | `decisions.author` | Create |
| `PUT` | `/api/decision-reference-sets/{key}` | `decisions.author` | Replace |
| `DELETE` | `/api/decision-reference-sets/{key}` | `decisions.author` | Delete |

---

## Evaluation suites

Detail in [02-runtime/18-evaluation-suites](../02-runtime/18-evaluation-suites.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/evals/assertion-types` | `evals.run` | Assertion types a case can use |
| `GET` | `/api/evals/suites` | `evals.run` | List suites |
| `POST` | `/api/evals/suites` | `evals.manage` | Create a suite |
| `GET` | `/api/evals/suites/{suite_id}` | `evals.run` | Suite with its cases |
| `PATCH` | `/api/evals/suites/{suite_id}` | `evals.manage` | Change a suite |
| `DELETE` | `/api/evals/suites/{suite_id}` | `evals.manage` | Delete a suite |
| `POST` | `/api/evals/suites/{suite_id}/cases` | `evals.manage` | Add a case |
| `POST` | `/api/evals/suites/{suite_id}/cases/from-execution` | `evals.manage` | Turn a past run into a case with assertions that hold for it |
| `PATCH` | `/api/evals/cases/{case_id}` | `evals.manage` | Change a case |
| `DELETE` | `/api/evals/cases/{case_id}` | `evals.manage` | Delete a case |
| `POST` | `/api/evals/assertions/check` | `evals.run` | Validate assertions and try them on an output |
| `POST` | `/api/evals/suites/{suite_id}/run` | `evals.run` | Start a suite run |
| `GET` | `/api/evals/suites/{suite_id}/runs` | `evals.run` | Runs of a suite |
| `GET` | `/api/evals/runs/{run_id}` | `evals.run` | Run detail with per-case results |
| `POST` | `/api/evals/runs/{run_id}/cancel` | `evals.run` | Cancel a run |
| `GET` | `/api/evals/runs/{run_id}/compare/{other_id}` | `evals.run` | Two runs side by side, `run_id` is the base |
| `GET` | `/api/evals/gate/{agent_id}` | `evals.run` | Whether publishing the agent now would pass its gate |

---

## Source Watch

Detail in [02-runtime/17-source-watch](../02-runtime/17-source-watch.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/sources/settings` | signed in | Tenant settings, which credential keys are set, fetch limits |
| `PUT` | `/api/sources/settings` | `risk.manage` | Body `{host_allowlist, pause_after_failures}` |
| `POST` | `/api/sources/validate-url` | `sources.manage` | Whether a URL is allowed, and why not |
| `POST` | `/api/sources/preview` | `sources.manage` | Fetch once and show what would be extracted, nothing saved |
| `GET` | `/api/sources/changes` | signed in | Recent changes across all sources |
| `GET` | `/api/sources/changes/{change_id}` | signed in | One change with its diff |
| `GET` | `/api/sources/snapshots/{snapshot_id}` | signed in | One snapshot |
| `GET` | `/api/sources/snapshots/{snapshot_id}/raw` | signed in | Raw fetched content of a snapshot |
| `GET` | `/api/sources` | signed in | List sources |
| `POST` | `/api/sources` | `sources.manage` | Add a source |
| `GET` | `/api/sources/{source_id}` | signed in | Source detail |
| `PATCH` | `/api/sources/{source_id}` | `sources.manage` | Change a source |
| `DELETE` | `/api/sources/{source_id}` | `sources.manage` | Delete a source |
| `POST` | `/api/sources/{source_id}/pause` | `sources.manage` | Stop checking |
| `POST` | `/api/sources/{source_id}/resume` | `sources.manage` | Start checking again |
| `POST` | `/api/sources/{source_id}/check-now` | `sources.manage` | Check now, outside the cadence |
| `GET` | `/api/sources/{source_id}/snapshots` | signed in | Snapshots of one source |
| `GET` | `/api/sources/{source_id}/changes` | signed in | Changes of one source |

---

## Governance

Permission sets, risk tiers, kill switches, audit chain, replay and provenance. Detail in [01-architecture/07-governance](../01-architecture/07-governance.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/governance/capabilities` | signed in | Capability catalogue and the defaults per role |
| `GET` | `/api/governance/permission-sets` | `permissions.manage` | List permission sets |
| `POST` | `/api/governance/permission-sets` | `permissions.manage` | Create a permission set |
| `PATCH` | `/api/governance/permission-sets/{set_id}` | `permissions.manage` | Change a permission set |
| `DELETE` | `/api/governance/permission-sets/{set_id}` | `permissions.manage` | Delete a permission set |
| `POST` | `/api/governance/permission-sets/{set_id}/members` | `permissions.manage` | Add a member |
| `DELETE` | `/api/governance/permission-sets/{set_id}/members/{user_id}` | `permissions.manage` | Remove a member |
| `GET` | `/api/governance/risk` | `risk.view` | Policy per tier (`low`, `medium`, `high`, `critical`) |
| `PUT` | `/api/governance/risk/{tier}` | `risk.manage` | Set the policy for a tier |
| `DELETE` | `/api/governance/risk/{tier}` | `risk.manage` | Reset a tier to its default |
| `GET` | `/api/governance/kill-switches` | `risk.view` | Active switches, `?include_cleared=true` for all |
| `POST` | `/api/governance/kill-switches` | `killswitch.manage` | Set a switch. `scope` is `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision` or `source` |
| `POST` | `/api/governance/kill-switches/{switch_id}/clear` | `killswitch.manage` | Clear a switch |
| `GET` | `/api/governance/audit/verify` | `audit.verify` | Verify the tenant's hash-linked audit chain |
| `GET` | `/api/governance/runs/{execution_id}/provenance` | `runs.replay` | What a run ran with |
| `GET` | `/api/governance/audit/export` | `audit.view` | Audit log as JSON lines with hashes, `?since=&until=` |
| `POST` | `/api/governance/runs/{execution_id}/replay` | `runs.replay` | Run it again on its recorded input. Body `{mode, model}`, `mode` is `pinned` or `current` |

---

## Outbound events

Subscriptions to platform events. Signing, retries and the event catalogue are in [02-runtime/19-outbound-events](../02-runtime/19-outbound-events.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/webhooks/catalog` | signed in | Event types a subscription can match |
| `GET` | `/api/webhooks` | signed in | List subscriptions |
| `POST` | `/api/webhooks` | `events.manage` | Create a subscription. `target_type` is `webhook`, `agent` or `pipeline`. A webhook target gets a `signing_secret`, shown once |
| `DELETE` | `/api/webhooks/{webhook_id}` | `events.manage` | Delete a subscription |
| `PUT` | `/api/webhooks/{webhook_id}` | `events.manage` | Change a subscription. Turning it back on resets the failure counters |
| `POST` | `/api/webhooks/{webhook_id}/test` | `events.manage` | Queue a sample event for this subscription only |
| `POST` | `/api/webhooks/deliveries/{delivery_id}/redeliver` | `events.manage` | Send a delivery again with a fresh retry budget |
| `GET` | `/api/webhooks/{webhook_id}/deliveries` | signed in | Delivery history, newest first |

---

## Knowledge bases

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge-bases` | signed in | List |
| `POST` | `/api/knowledge-bases` | signed in | Create |
| `GET` | `/api/knowledge-bases/{kb_id}` | signed in | Detail with documents |
| `PUT` | `/api/knowledge-bases/{kb_id}` | signed in | Update |
| `GET` | `/api/knowledge-bases/{kb_id}/dependents` | signed in | Agents granted it and Atlas graphs bound to it |
| `DELETE` | `/api/knowledge-bases/{kb_id}` | signed in | Delete. Without `?force=true`, 409 `IN_USE` when agents or Atlas graphs use it. A confirmed delete unbinds graphs and removes agent grants |
| `POST` | `/api/knowledge-bases/{kb_id}/upload` | signed in | Upload a document |
| `GET` | `/api/knowledge-bases/{kb_id}/documents` | signed in | List documents. Documents restricted by grants the caller cannot see are left out, `meta.hidden` counts them |
| `DELETE` | `/api/knowledge-bases/{kb_id}/documents/{doc_id}` | signed in | Delete a document |

---

## Knowledge v2 (cognify, conflicts, versioning, reembed, document grants) {#knowledge-v2}

See [02-runtime/15-v2-knowledge-enterprise](../02-runtime/15-v2-knowledge-enterprise.md) for the implementation and [04-data-model/03-knowledge](../04-data-model/03-knowledge.md) for the data model. Document grants pre-filter candidates before similarity search and are cached 60 s in Redis.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge/{kb_id}/documents/{doc_id}/grants` | signed in | Document-level grants `(subject_type, subject_id, permission)`. `subject_type` is `user` or `agent` |
| `POST` | `/api/knowledge/{kb_id}/documents/{doc_id}/grants` | collection editor | Add a document grant. The first grant restricts the document to its grantees, admins, the collection creator and WRITE or ADMIN holders |
| `DELETE` | `/api/knowledge/{kb_id}/documents/{doc_id}/grants/{grant_id}` | collection editor | Remove a document grant |
| `POST` | `/api/knowledge/{kb_id}/documents/{doc_id}/replace` | signed in | Upload a new version. The old row gets `is_current=false, superseded_by=<new_id>` |
| `GET` | `/api/knowledge/{kb_id}/reembed` | can read the collection | Current `embedding_model`, `supported_models` and the latest job's progress |
| `POST` | `/api/knowledge/{kb_id}/reembed` | admin role | Body `{embedding_model, dry_run}`. With `dry_run` returns chunk count, cost estimate and ETA. Otherwise queues the job and answers 202 with `job_id`. 400 for an unknown model, 409 while a job is queued or running |
| `GET` | `/api/knowledge/cognify-config` | signed in | Tenant `auto_accept_threshold`, `conflict_action`, `max_parallel_docs`, `daily_budget_usd` |
| `PUT` | `/api/knowledge/cognify-config` | admin role | Set the cognify config |
| `GET` | `/api/knowledge/cognify-conflicts` | signed in | Open conflicts where two sources disagree on an entity's type |
| `POST` | `/api/knowledge/cognify-conflicts/{conflict_id}/resolve` | admin role | Body `{resolved_value}`, one of the two values the sources gave. Writes that type to the graph |

---

## Knowledge engine

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge-engines/cognify/active` | signed in | Cognify jobs running or finished in the last hour |
| `POST` | `/api/knowledge-engines/{kb_id}/cognify` | signed in | Build the knowledge graph from the documents |
| `GET` | `/api/knowledge-engines/{kb_id}/graph-stats` | signed in | Graph statistics |
| `GET` | `/api/knowledge-engines/{kb_id}/graph` | signed in | Subgraph for visualization |
| `POST` | `/api/knowledge-engines/{kb_id}/search` | signed in | Hybrid search across graph and vectors. Restricted documents the caller cannot read are dropped before ranking, `hidden_documents` counts them. Chunk hits carry `metadata.citation` |
| `POST` | `/api/knowledge-engines/{kb_id}/feedback` | signed in | Feedback on search results |
| `GET` | `/api/knowledge-engines/{kb_id}/cognify-jobs` | signed in | Cognify job history, with `entities_held_back`, `relationships_held_back` and `conflicts_recorded` per job |

---

## Knowledge projects and collections

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge-collections/{collection_id}/agents` | signed in | Agents granted this collection |
| `POST` | `/api/knowledge-collections/{collection_id}/agents` | ADMIN on the collection | Grant an agent access |
| `DELETE` | `/api/knowledge-collections/{collection_id}/agents/{agent_id}` | ADMIN on the collection | Revoke an agent's access |
| `GET` | `/api/knowledge-collections/{collection_id}/users` | signed in | Users granted this collection |
| `POST` | `/api/knowledge-collections/{collection_id}/users` | ADMIN on the collection | Grant a user access |
| `DELETE` | `/api/knowledge-collections/{collection_id}/users/{user_id}` | ADMIN on the collection | Revoke a user's access |
| `POST` | `/api/knowledge-projects/bootstrap` | signed in | Find or create a project and its collections in one call |
| `POST` | `/api/knowledge-projects/{slug}/subject-collections/ensure` | signed in | Find or create a subject's collection in a project |
| `GET` | `/api/knowledge-projects` | signed in | Projects you can see |
| `POST` | `/api/knowledge-projects` | signed in | Create a project |
| `GET` | `/api/knowledge-projects/{project_id}` | signed in | Project detail |
| `PATCH` | `/api/knowledge-projects/{project_id}` | signed in | Update. Creator or admin |
| `DELETE` | `/api/knowledge-projects/{project_id}` | signed in | Delete. Creator or admin |
| `GET` | `/api/knowledge-projects/{project_id}/collections` | signed in | Collections in a project |
| `GET` | `/api/knowledge-projects/{project_id}/ontology-schemas` | signed in | Ontology schemas of a project |
| `GET` | `/api/knowledge-projects/{project_id}/ontology-schemas/active` | signed in | Active schema |
| `POST` | `/api/knowledge-projects/{project_id}/ontology-schemas` | signed in | Create a schema |
| `POST` | `/api/knowledge-projects/{project_id}/ontology-schemas/{schema_id}/activate` | signed in | Make a schema active |
| `GET` | `/api/knowledge-projects/{project_id}/correlations` | signed in | Top entity correlations across the project's collections |
| `GET` | `/api/knowledge-projects/{project_id}/correlations/{entity_name}` | signed in | Entities that co-occur with one entity |
| `GET` | `/api/knowledge-projects/{project_id}/members` | signed in | Project members |
| `POST` | `/api/knowledge-projects/{project_id}/members` | signed in | Add a member. Tenant admin or project ADMIN |
| `DELETE` | `/api/knowledge-projects/{project_id}/members/{user_id}` | signed in | Remove a member. Tenant admin or project ADMIN. The last ADMIN cannot be removed |

---

## GDPR

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/gdpr/users/{user_id}/purge` | admin role or the user | Five-store cascade: postgres, pinecone, neo4j, blob, trajectory. The user must be in the caller's tenant, otherwise 404 |
| `GET` | `/api/gdpr/users/{user_id}/receipts` | admin role or the user | Per-store audit trail from `gdpr_purge_log`, with `affected`, how many rows or vectors each step removed |

---

## Atlas (knowledge graph)

Agent-facing tools (`atlas_describe`, `atlas_query`, `atlas_traverse`, `atlas_search_grounded`, `atlas_as_of`) are in [02-runtime/02-tools](../02-runtime/02-tools.md#atlas-tool-cookbook).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/atlas/graphs` | signed in | Own, shared and platform graphs, the whole tenant for admins |
| `POST` | `/api/atlas/graphs` | signed in | Create. Body `{name, description, kb_id}` |
| `GET` | `/api/atlas/graphs/{graph_id}` | signed in | Full graph, meta plus every node and edge |
| `PATCH` | `/api/atlas/graphs/{graph_id}` | signed in | Update graph meta |
| `DELETE` | `/api/atlas/graphs/{graph_id}` | signed in | Delete a graph |
| `POST` | `/api/atlas/graphs/{graph_id}/nodes` | signed in | Add a node |
| `PATCH` | `/api/atlas/graphs/{graph_id}/nodes/{node_id}` | signed in | Change a node |
| `DELETE` | `/api/atlas/graphs/{graph_id}/nodes/{node_id}` | signed in | Delete a node |
| `POST` | `/api/atlas/graphs/{graph_id}/edges` | signed in | Add an edge |
| `PATCH` | `/api/atlas/graphs/{graph_id}/edges/{edge_id}` | signed in | Change an edge |
| `DELETE` | `/api/atlas/graphs/{graph_id}/edges/{edge_id}` | signed in | Delete an edge |
| `POST` | `/api/atlas/graphs/{graph_id}/parse-nl` | signed in | Turn a sentence into a list of graph ops |
| `POST` | `/api/atlas/graphs/{graph_id}/extract` | signed in | Proposed nodes and edges from an uploaded document, image, audio, video or text |
| `POST` | `/api/atlas/graphs/{graph_id}/apply` | signed in | Apply ops returned by parse-nl or extract |
| `GET` | `/api/atlas/graphs/{graph_id}/suggestions` | signed in | Duplicates, missing inverses and orphans |
| `GET` | `/api/atlas/graphs/{graph_id}/snapshots` | signed in | Snapshots |
| `POST` | `/api/atlas/graphs/{graph_id}/snapshots` | signed in | Take a labelled snapshot |
| `POST` | `/api/atlas/graphs/{graph_id}/snapshots/{snapshot_id}/restore` | signed in | Replace live nodes and edges with a snapshot |
| `GET` | `/api/atlas/graphs/{graph_id}/export` | signed in | Export as JSON-LD or plain JSON |
| `POST` | `/api/atlas/graphs/{graph_id}/bind-kb` | signed in | Bind or unbind a knowledge collection |
| `POST` | `/api/atlas/graphs/{graph_id}/sync-kb` | signed in | Add the bound collection's documents to the canvas |
| `POST` | `/api/atlas/graphs/{graph_id}/query` | signed in | Match a small graph pattern |
| `PATCH` | `/api/atlas/graphs/{graph_id}/nodes/{node_id}/binding` | signed in | Bind a node to a live data source |
| `GET` | `/api/atlas/graphs/{graph_id}/nodes/{node_id}/instances` | signed in | Live instances of a bound node |
| `GET` | `/api/atlas/starters` | signed in | Starter ontologies |
| `POST` | `/api/atlas/graphs/{graph_id}/import-starter` | signed in | Import a starter ontology |
| `POST` | `/api/atlas/graphs/{graph_id}/relayout` | signed in | Reposition every node |
| `POST` | `/api/atlas/graphs/{graph_id}/persist-to-kb` | signed in | Write a dropped file into the bound collection |

---

## ML models

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/ml-models` | signed in | Upload a model file with metadata (multipart) |
| `GET` | `/api/ml-models` | signed in | List models visible to the caller. `scope=tenant` needs admin |
| `GET` | `/api/ml-models/{model_id}` | signed in | Detail with deployments |
| `PUT` | `/api/ml-models/{model_id}` | signed in | Update description, `input_schema`, `output_schema` and tags |
| `DELETE` | `/api/ml-models/{model_id}` | signed in | Delete a model and its file |
| `POST` | `/api/ml-models/{model_id}/deploy` | signed in | Deploy in-process or as a k8s pod. Body `{deployment_type, replicas, resource_preset}`. A k8s deploy needs the admin or owner role |
| `POST` | `/api/ml-models/{model_id}/predict` | signed in | Run inference |
| `DELETE` | `/api/ml-models/{model_id}/undeploy` | signed in | Tear down the deployment |
| `GET` | `/api/ml-models/{model_id}/fetch` | model-scoped token | Model file for a runtime pod that does not share the API's volume |
| `GET` | `/api/ml-models/{model_id}/download` | signed in | Download the model file |
| `GET` | `/api/ml-models/versions/{model_name}` | signed in | Versions by name |
| `POST` | `/api/ml-models/{model_id}/activate` | signed in | Make this the active version |
| `POST` | `/api/ml-models/{model_id}/deactivate` | signed in | Deactivate this version |
| `GET` | `/api/ml-models/check/{model_name}` | signed in | Whether a model is ready and deployed, used by pipeline validation |

---

## Code assets

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/code-assets/{asset_id}/versions` | signed in | Upload a new version, live only if it analyses cleanly. Owner, admin or edit access |
| `POST` | `/api/code-assets/{asset_id}/versions/{version}/restore` | signed in | Make an earlier version live again, as a new version number |
| `POST` | `/api/code-assets` | signed in | Create from an uploaded zip or `metadata.git_url` (multipart) |
| `GET` | `/api/code-assets` | signed in | List assets visible to the caller. `scope=tenant` needs admin |
| `GET` | `/api/code-assets/{asset_id}` | signed in | Detail |
| `PUT` | `/api/code-assets/{asset_id}` | signed in | Update schemas and commands. Needs edit access |
| `POST` | `/api/code-assets/{asset_id}/test` | signed in | Test run with sample input. 422 `CODE_FAILED` when the code itself fails |
| `GET` | `/api/code-assets/{asset_id}/download` | signed in | Download the zip. Sandbox pods call it with a short-lived JWT |
| `GET` | `/api/code-assets/{asset_id}/fetch` | asset-scoped token | Archive for a sandbox pod |
| `GET` | `/api/code-assets/{asset_id}/dependents` | signed in | Agents and pipelines that call it |
| `DELETE` | `/api/code-assets/{asset_id}` | signed in | Delete. Owner or admin. Without `?force=true`, 409 `IN_USE` with the dependents |

---

## Invocation logs

Call history for code assets, ML models and knowledge collections.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/code-assets/{asset_id}/invocations` | signed in | Recent runs of an asset |
| `GET` | `/api/code-assets/{asset_id}/invocations/stream` | signed in | SSE of runs as they happen |
| `GET` | `/api/code-assets/{asset_id}/stats` | signed in | Call counts and latency |
| `GET` | `/api/ml-models/invocations` | signed in | Recent predictions across all models |
| `GET` | `/api/ml-models/{model_id}/invocations` | signed in | Recent predictions of one model |
| `GET` | `/api/ml-models/{model_id}/invocations/stream` | signed in | SSE of predictions as they happen |
| `GET` | `/api/ml-models/{model_id}/stats` | signed in | Call counts and latency |
| `GET` | `/api/knowledge-collections/{collection_id}/queries` | signed in | Recent queries against a collection |
| `GET` | `/api/knowledge-collections/{collection_id}/queries/stream` | signed in | SSE of queries as they happen |

---

## Tools

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/integrations/status` | signed in | Which integrations are configured |
| `GET` | `/api/integrations/tools` | signed in | Every credential a tool declares, with its status and never its value |
| `POST` | `/api/tools/save` | signed in | Save an AI-generated tool to the library, pending approval |
| `GET` | `/api/tools/library` | signed in | Saved tools |
| `GET` | `/api/tools/library/{tool_id}` | signed in | Tool detail with code |
| `POST` | `/api/tools/library/{tool_id}/approve` | admin role | Approve a pending tool so agents can use it |
| `POST` | `/api/tools/library/{tool_id}/reject` | admin role | Reject a pending tool with a reason |
| `DELETE` | `/api/tools/library/{tool_id}` | signed in | Delete a saved tool |
| `GET` | `/api/tool-presets` | signed in | Saved tool presets |
| `GET` | `/api/tool-presets/{preset_slug}` | signed in | One preset |
| `POST` | `/api/tool-presets` | signed in | Create or replace a preset |
| `DELETE` | `/api/tool-presets/{preset_slug}` | signed in | Delete a preset |
| `POST` | `/api/tool-presets/{preset_slug}/run` | signed in | Run a preset, caller args merged over its defaults |
| `GET` | `/api/tools` | signed in | Built-in tools with metadata |
| `POST` | `/api/tools/{tool_slug}/execute` | signed in | Run one tool directly, outside the agent loop |
| `GET` | `/api/tools/invocations` | signed in | Recent direct tool calls |

---

## MCP

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/mcp/connections` | signed in | MCP server connections |
| `POST` | `/api/mcp/connections` | signed in | Add a connection |
| `GET` | `/api/mcp/connections/{connection_id}` | signed in | One connection |
| `PUT` | `/api/mcp/connections/{connection_id}` | signed in | Update a connection |
| `DELETE` | `/api/mcp/connections/{connection_id}` | signed in | Delete a connection |
| `POST` | `/api/mcp/connections/{connection_id}/discover` | signed in | List the server's tools |
| `POST` | `/api/mcp/discover` | signed in | Probe a URL without saving a connection |
| `POST` | `/api/mcp/connections/{connection_id}/health` | signed in | Health check |
| `GET` | `/api/mcp/connections/{connection_id}/resources` | signed in | Server resources |
| `POST` | `/api/mcp/connections/{connection_id}/resources/read` | signed in | Read a resource |
| `GET` | `/api/mcp/connections/{connection_id}/prompts` | signed in | Server prompts |
| `POST` | `/api/mcp/connections/{connection_id}/prompts/get` | signed in | Get a prompt |
| `POST` | `/api/mcp/oauth2/start` | signed in | Start an OAuth2 PKCE flow, returns the auth URL |
| `POST` | `/api/mcp/oauth2/callback` | signed in | Finish OAuth2 PKCE and store the tokens encrypted |
| `GET` | `/api/mcp/agents/{agent_id}/tools` | signed in | MCP tools attached to an agent |
| `POST` | `/api/mcp/agents/{agent_id}/tools` | signed in | Attach an MCP tool |
| `DELETE` | `/api/mcp/agents/{agent_id}/tools` | signed in | Detach an MCP tool |
| `GET` | `/api/mcp/registry` | signed in | Browse the MCP server registry |
| `POST` | `/api/mcp/registry/install` | signed in | Install a registry server as a connection |
| `POST` | `/api/mcp/registry/sync` | signed in | Seed or sync the registry with curated servers |

---

## Connectors

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/connectors/presets` | signed in | Connector presets for the create form |
| `POST` | `/api/connectors` | signed in | Create a connector |
| `GET` | `/api/connectors` | signed in | List connectors |
| `GET` | `/api/connectors/{connector_id}` | signed in | One connector |
| `PUT` | `/api/connectors/{connector_id}` | signed in | Update |
| `DELETE` | `/api/connectors/{connector_id}` | signed in | Delete |
| `POST` | `/api/connectors/{connector_id}/test` | signed in | Call the base URL with the connector's auth and time it |

---

## Moderation

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/moderation/vet` | signed in | Check content against the tenant's active moderation policy |
| `GET` | `/api/moderation/policies` | signed in | Policies |
| `POST` | `/api/moderation/policies` | admin role | Create a policy |
| `GET` | `/api/moderation/policies/{policy_id}` | signed in | One policy |
| `PATCH` | `/api/moderation/policies/{policy_id}` | admin role | Change a policy |
| `DELETE` | `/api/moderation/policies/{policy_id}` | admin role | Delete a policy |
| `GET` | `/api/moderation/events` | signed in | Moderation events |

---

## Meetings and persona

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/meetings` | signed in | Create a meeting |
| `GET` | `/api/meetings` | signed in | List meetings |
| `GET` | `/api/meetings/livekit-token` | signed in | Token for a person to join the same LiveKit room as the bot |
| `GET` | `/api/meetings/{meeting_id}` | signed in | Meeting detail |
| `PUT` | `/api/meetings/{meeting_id}/authorize` | signed in | Set what the bot may answer. Body `{scope_allow, scope_defer, persona_scopes}` |
| `POST` | `/api/meetings/{meeting_id}/start` | signed in | Run the Meeting Representative agent for this meeting |
| `POST` | `/api/meetings/{meeting_id}/redispatch` | signed in | Respawn the bot for a meeting that is already live |
| `POST` | `/api/meetings/{meeting_id}/inject-turn` | signed in | Add a synthetic utterance to the live transcript |
| `POST` | `/api/meetings/{meeting_id}/kill` | signed in | Stop the bot |
| `GET` | `/api/meetings/{meeting_id}/stream` | signed in | SSE of the live transcript and decisions |
| `GET` | `/api/meetings/{meeting_id}/deferrals` | signed in | Questions the bot deferred to you |
| `POST` | `/api/meetings/{meeting_id}/deferrals/{deferral_id}/answer` | signed in | Answer a deferred question |
| `GET` | `/api/persona/items` | signed in | Your persona items |
| `GET` | `/api/persona/scopes` | signed in | Persona scopes |
| `DELETE` | `/api/persona/items/{item_id}` | signed in | Delete an item |
| `POST` | `/api/persona/notes` | signed in | Add a note |
| `POST` | `/api/persona/upload` | signed in | Upload a file to your persona |
| `GET` | `/api/persona/voice` | signed in | Your voice clone state |
| `POST` | `/api/persona/voice/consent` | signed in | Record voice clone consent, separate from the upload |
| `POST` | `/api/persona/voice/revoke` | signed in | Revoke consent and delete the voice at the provider |
| `POST` | `/api/persona/voice/upload` | signed in | Upload a 30 to 120 second reference clip to clone |
| `POST` | `/api/persona/meeting-context` | signed in | Add context for one upcoming meeting |

---

## Edge

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/edge/signing-key` | public | Public verify key for gateways |
| `GET` | `/api/edge/runtime/download` | public | Edge runtime variants with image, Helm and Docker instructions |
| `POST` | `/api/edge/tokens/mint` | signed in | Mint an API key for the edge runtime's `PLATFORM_TOKEN` |
| `POST` | `/api/edge/gateways/register` | signed in | Register a gateway. Idempotent on `gateway_id` |
| `GET` | `/api/edge/gateways` | signed in | Registered gateways |
| `POST` | `/api/edge/gateways/{gateway_pk}/deploy` | signed in | Compile, sign and push a `.agent` bundle to a gateway |
| `GET` | `/api/edge/gateways/{gateway_pk}/agents` | signed in | Agents on a gateway, proxied from it |
| `DELETE` | `/api/edge/gateways/{gateway_pk}` | signed in | Forget a gateway. It registers again on its next start |
| `POST` | `/api/edge/agents/{agent_id}/compile` | signed in | Compile an agent into a `.agent` bundle |

---

## A2A (agent-to-agent)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/a2a/discover` | public | Published agents on this instance |
| `GET` | `/api/a2a/agents/{agent_id}/card` | public | A2A agent card with capabilities and input schema |
| `POST` | `/api/a2a/agents/{agent_id}/invoke` | `X-API-Key` | Run a published agent, or one the key's user can execute, from an external platform. Checks the daily caps, records an execution row, and applies knowledge base grants, MCP tools and the moderation gate like execute. Pipeline agents answer 400 |

Invoke runs a published agent, or one the key's user may execute, and answers 404 for anything else. Each call writes an execution row like any other run, with status, cost, tokens, `failure_code` and provenance, and the response carries its `execution_id`. The agent's daily caps are checked first and a refusal is 429 `BUDGET_EXCEEDED`. An optional `cost_limit` in the body tightens the per-run limit.

---

## Analytics and search

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/analytics/overview` | signed in | Dashboard totals |
| `GET` | `/api/analytics/executions` | signed in | Executions over time |
| `GET` | `/api/analytics/tokens` | signed in | Token use by model |
| `GET` | `/api/analytics/costs` | signed in | Cost breakdown |
| `GET` | `/api/analytics/live-stats` | signed in | Live counters |
| `GET` | `/api/analytics/failures` | signed in | Recent failures grouped by `failure_code` |
| `GET` | `/api/analytics/drift-alerts/config` | signed in | Tenant drift detection toggle |
| `PUT` | `/api/analytics/drift-alerts/config` | admin role | Turn drift detection on or off for the tenant |
| `GET` | `/api/analytics/drift-alerts` | signed in | Drift alerts |
| `POST` | `/api/analytics/drift-alerts/{alert_id}/acknowledge` | signed in | Acknowledge a drift alert |
| `GET` | `/api/analytics/per-user` | signed in | Tokens and cost per user. Admins see everyone, others themselves |
| `GET` | `/api/search` | signed in | Global search across pages, agents, pipelines, executions, knowledge bases, ML models and code assets |

---

## Files

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/files/download` | signed in | Download a file by storage URI |
| `GET` | `/api/files/export/{filename}` | signed in | Download an agent-generated export |
| `GET` | `/api/files/list` | signed in | Files of the tenant |

---

## LLM models

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/llm-models` | signed in | Models for every model dropdown |
| `GET` | `/api/llm/available-providers` | signed in | Which providers are configured, and why not |
| `GET` | `/api/llm-models/resolve` | signed in | Which model the resolver would pick for `model` right now |
| `POST` | `/api/llm-models/ping-now` | admin role | Probe model availability now |
| `POST` | `/api/llm-models/clear-stale` | admin role | Clear sticky unavailable markers so the next request probes again |
| `GET` | `/api/use-cases` | public | Use case links, with hosts resolved on the server |

---

## Billing, marketplace and creators

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/billing/plans` | signed in | Plans |
| `POST` | `/api/billing/checkout` | signed in | Start a Stripe checkout |
| `POST` | `/api/billing/portal` | signed in | Open the Stripe billing portal |
| `GET` | `/api/billing/usage` | signed in | Usage for the billing period |
| `POST` | `/api/billing/webhook` | Stripe signature | Stripe webhook receiver |
| `POST` | `/api/creator/onboard` | signed in | Start Stripe Connect onboarding as a creator |
| `GET` | `/api/creator/status` | signed in | Creator onboarding status |
| `GET` | `/api/creator/dashboard` | creator or admin role | Earnings and payouts. `?period=` is `7d`, `30d` or `90d` |
| `GET` | `/api/creator/login-link` | signed in | Link to the Stripe Express dashboard |
| `GET` | `/api/marketplace` | signed in | Browse published agents |
| `GET` | `/api/marketplace/{agent_id}` | signed in | Marketplace agent detail |
| `POST` | `/api/marketplace/subscribe/{agent_id}` | signed in | Subscribe to an agent |

---

## Workspaces

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/workspaces` | signed in | Workspaces |
| `POST` | `/api/workspaces` | signed in | Create a workspace |
| `GET` | `/api/workspaces/{workspace_id}` | signed in | One workspace |
| `PUT` | `/api/workspaces/{workspace_id}` | signed in | Update |
| `DELETE` | `/api/workspaces/{workspace_id}` | signed in | Delete |

---

## Portfolio schemas

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/portfolio-schemas` | signed in | Portfolio schemas of the tenant |
| `POST` | `/api/portfolio-schemas` | signed in | Create a schema |
| `GET` | `/api/portfolio-schemas/{schema_id}` | signed in | One schema |
| `PUT` | `/api/portfolio-schemas/{schema_id}` | signed in | Update |
| `DELETE` | `/api/portfolio-schemas/{schema_id}` | signed in | Delete |
| `GET` | `/api/portfolio-schemas/templates/list` | public | Starter schema templates |

---

## Access control (delegated subjects)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/access-control/policies` | signed in | Subject policies under your API keys |
| `POST` | `/api/access-control/policies` | signed in | Create a subject policy |
| `GET` | `/api/access-control/policies/{policy_id}` | signed in | One policy |
| `PUT` | `/api/access-control/policies/{policy_id}` | signed in | Update |
| `DELETE` | `/api/access-control/policies/{policy_id}` | signed in | Delete |
| `GET` | `/api/access-control/api-keys` | signed in | API keys with delegation turned on |
| `GET` | `/api/access-control/templates` | public | Policy templates |
| `POST` | `/api/access-control/test` | signed in | Simulate what a subject can and cannot reach |

---

## OracleNet

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/oraclenet/analyze` | signed in | Submit a decision for OracleNet analysis. SSE of agent progress |
| `GET` | `/api/oraclenet/sessions` | signed in | Past analyses |
| `GET` | `/api/oraclenet/sessions/{execution_id}` | signed in | One Decision Brief |
| `POST` | `/api/oraclenet/export` | signed in | Export a brief sent in the body as PDF or DOCX |
| `GET` | `/api/oraclenet/sessions/{execution_id}/export/{fmt}` | signed in | Export a brief as PDF, DOCX or Markdown |

---

## BPM Analyzer

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/bpm-analyzer/models` | signed in | Vision-capable models for the picker |
| `POST` | `/api/bpm-analyzer/upload` | signed in | Upload a process artifact and start the analysis |
| `POST` | `/api/bpm-analyzer/chat/{thread_id}/turn` | signed in | Follow-up question on a thread |
| `GET` | `/api/bpm-analyzer/threads` | signed in | Threads |
| `GET` | `/api/bpm-analyzer/threads/{thread_id}` | signed in | One thread |
| `POST` | `/api/bpm-analyzer/threads/{thread_id}/suggest-agents` | signed in | Structured list of agent specs from the analysis |
| `POST` | `/api/bpm-analyzer/threads/{thread_id}/build-and-test` | signed in | Build and test one suggested agent |
| `POST` | `/api/bpm-analyzer/threads/{thread_id}/create-agent` | signed in | Create one suggested agent from its spec |
| `POST` | `/api/bpm-analyzer/threads/{thread_id}/export-pdf` | signed in | Thread as a PDF |
| `DELETE` | `/api/bpm-analyzer/threads/{thread_id}` | signed in | Delete a thread |

---

## Admin: settings and tool configuration

Tool configuration detail in [08-howto/08-tool-configuration](../08-howto/08-tool-configuration.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/settings` | admin role | Every known setting with its value or default, by category |
| `GET` | `/api/admin/settings/models` | admin role | Platform model list |
| `GET` | `/api/admin/settings/models/public` | signed in | Same model list for any signed-in user |
| `PATCH` | `/api/admin/settings/{key}` | admin role | Set one setting |
| `GET` | `/api/admin/settings/subscription` | admin role | Whether subscription mode is on, and what it serves |
| `POST` | `/api/admin/settings/subscription/verify` | admin role | One minimal real call with the stored token |
| `POST` | `/api/admin/settings/reset` | admin role | Reset settings to defaults |
| `GET` | `/api/admin/tool-config` | admin role | Every declared key by provider, with where its value comes from. `?scope=tenant` (default) or `platform` |
| `PATCH` | `/api/admin/tool-config/{key}` | admin role | Save a value in the tenant (default) or platform scope |
| `DELETE` | `/api/admin/tool-config/{key}` | admin role | Remove the saved value in one scope so the next source applies |
| `POST` | `/api/admin/tool-config/{key}/test` | admin role | Run the declaring tool's own check, if it has one |
| `GET` | `/api/admin/tool-runtime` | admin | One row per tool with 24h call counts and last latency |
| `GET` | `/api/admin/tool-runtime/{slug}` | admin | Runtime config of one tool |
| `POST` | `/api/admin/tool-runtime` | admin | Create or update a tool's runtime config |

---

## Admin: models and pricing

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/model-availability` | admin role | Availability per model |
| `POST` | `/api/admin/model-availability/force-status` | admin role | Force a model's status |
| `POST` | `/api/admin/model-availability/ping/{model}` | admin role | Probe one model now |
| `GET` | `/api/admin/llm-pricing` | admin role | Pricing rows |
| `POST` | `/api/admin/llm-pricing` | admin role | Add a pricing row |
| `PATCH` | `/api/admin/llm-pricing/{row_id}` | admin role | Change a row |
| `DELETE` | `/api/admin/llm-pricing/{row_id}` | admin role | Delete a row |
| `POST` | `/api/admin/llm-pricing/seed` | admin role | Re-seed pricing, capabilities and fallback chains from the baseline |

---

## Admin: scaling

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/scaling/pools` | admin role | Pools with agent counts and recent usage |
| `GET` | `/api/admin/scaling/agents` | admin role | Agents with their scaling settings, filter by pool |
| `PATCH` | `/api/admin/scaling/agents/{agent_id}` | admin role | Change an agent's scaling settings |
| `POST` | `/api/admin/scaling/agents/{agent_id}/pause` | admin role | Pause an agent, the runtime refuses new runs |
| `POST` | `/api/admin/scaling/agents/{agent_id}/resume` | admin role | Resume a paused agent |
| `POST` | `/api/admin/scaling/agents/{agent_id}/dedicated-mode` | admin role | Turn per-agent dedicated pod scaling on or off |
| `GET` | `/api/admin/scaling/agents/{agent_id}/cost-projection` | admin role | Hourly, daily and monthly cost projection |
| `GET` | `/api/admin/scaling/tenants/{tenant_id}/spend` | admin role | Tenant spend today and this month against `daily_budget_usd` |
| `GET` | `/api/admin/scaling/pipelines` | admin | Pipeline agents with their node DAG resolved to scaling routes |

---

## Admin: archives, DLQ, cluster and alerts

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/alerts` | admin role | Current alerts from Alertmanager, or Prometheus when it is not reachable |
| `GET` | `/api/admin/alerts/rules` | admin role | Loaded Prometheus rules |
| `POST` | `/api/admin/alerts/webhook` | webhook token | Alertmanager webhook. Sends each alert to admins and Slack |
| `GET` | `/api/admin/cluster/summary` | admin role | Cluster health: nodes, pods, PVCs, DB size |
| `GET` | `/api/admin/dlq` | admin role | Dead-letter queue |
| `POST` | `/api/admin/dlq/{dlq_id}/replay` | admin role | Run a dead-lettered execution again from its original input |
| `GET` | `/api/admin/archives` | admin role | Archive runs |
| `POST` | `/api/admin/archives/trigger` | admin role | Start an archive run |
| `GET` | `/api/admin/archives/retention-policies` | admin role | Retention policy per table |
| `PUT` | `/api/admin/archives/retention-policies/{table}` | admin role | Set a table's retention policy |
| `GET` | `/api/admin/archives/{run_id}/download` | admin role | Download an archive file |
| `POST` | `/api/admin/archives/{run_id}/restore` | admin role | Restore an archive run |

---

## Health and telemetry

Defined in `main.py`, not a router.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | public | Liveness. Always `{"status": "ok"}` |
| `GET` | `/api/health/ready` | public | Readiness. Checks postgres, redis, neo4j and that an LLM key is set. `status` is `ok` or `degraded` |
| `GET` | `/api/metrics` | public | Prometheus scrape, multiprocess aware |
| `GET` | `/` | public | API banner |

---

## Full schema

The FastAPI app generates an OpenAPI 3.1 schema at `/openapi.json`. Use it with code generators or as the source of truth for the SDKs.

```bash
curl https://api.example.com/openapi.json > openapi.json
```

To rebuild the route list from code, read every `@router.<method>(...)` decorator in `apps/api/app/routers/*.py` and prefix it with that file's `APIRouter(prefix=...)`. `main.py` mounts every router with no extra prefix.

---

## See also

- [03-sdk/00-overview](../03-sdk/00-overview.md) for the SDKs that wrap these routes
- [01-env-vars](01-env-vars.md) for server-side configuration
