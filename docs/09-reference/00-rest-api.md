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

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/approvals` | List, filterable by status |
| `POST` | `/api/approvals` | Create (typically via the SDK from an agent) |
| `GET`  | `/api/approvals/{id}` | Detail |
| `GET`  | `/api/approvals/{id}/wait` | Block until terminal |
| `POST` | `/api/approvals/{id}/signoff` | Body `{decision, reason}` |
| `GET`  | `/api/approvals/webhooks` / `PUT` | Webhook config |

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

The platform also exposes outbound webhooks — see `/api/webhook-config` for the configuration surface.

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
