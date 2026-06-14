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
| `DELETE` | `/api/knowledge-bases/{id}` | Delete |
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
| `DELETE` | `/api/code-assets/{id}` | Delete |
| `POST` | `/api/code-assets/{id}/test` | Test run |

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
| `GET` / `POST` / `DELETE` | `/api/knowledge/{kb}/documents/{doc}/grants` | Document-level ACL: `(subject_type, subject_id, permission)`. Pre-filters candidates before similarity search; cached 60 s in Redis |

### GDPR

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/gdpr/users/{user_id}/purge` | Five-store cascade: postgres, pinecone, neo4j, blob, trajectory |
| `GET`  | `/api/gdpr/users/{user_id}/receipts` | Per-store audit trail (`gdpr_purge_log` rows) — provable to a regulator |

See [`02-runtime/15-v2-knowledge-enterprise.md`](../02-runtime/15-v2-knowledge-enterprise.md) for the implementation details and [`04-data-model/03-knowledge.md`](../04-data-model/03-knowledge.md) for the data model.

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
| `POST` | `/api/admin/notification-channels/{channel}/test` | Send a synthetic test event through Slack or email so admins can prove delivery without waiting for a real incident. `channel` is `slack` or `email`. Admin only. |

---

## Notifications

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/notifications` | List for the current user |
| `GET` | `/api/notifications/unread-count` | Badge counter |
| `POST` | `/api/notifications/{id}/read` | Mark one read |
| `POST` | `/api/notifications/read-all` | Mark all read |
| `GET` | `/api/notifications/stream` | SSE feed, filtered by `?types=` |
| `WS` | `/api/ws/{user_id}` | WebSocket variant of the SSE feed |

---

## ML model invocations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/ml-models/invocations` | Cross-model aggregate for the caller's tenant, paginated. Use this for the dashboard widget instead of looping over each model. |
| `GET` | `/api/ml-models/{id}/invocations` | Per-model history |
| `GET` | `/api/ml-models/{id}/invocations/stream` | SSE feed of new invocations |
| `GET` | `/api/ml-models/{id}/stats` | 24h rollups |

---

## MCP

| Method | Path | Purpose |
|---|---|---|
| `GET` / `POST` | `/api/mcp/connections` | List or create. `auth_config` secrets are encrypted with the per-tenant DEK on write and redacted on read. Server URL is checked against the SSRF allowlist before the connection is stored. |
| `GET` / `PUT` / `DELETE` | `/api/mcp/connections/{id}` | Detail, update, delete |
| `POST` | `/api/mcp/connections/{id}/discover` | Refresh tool catalogue from the remote server |
| `POST` | `/api/mcp/discover` | One-shot discover for a candidate URL without saving. SSRF allowlist applies. |
| `POST` | `/api/mcp/connections/{id}/health` | Liveness check |
| `GET` / `POST` | `/api/mcp/connections/{id}/resources` | List or read |
| `POST` | `/api/mcp/connections/{id}/tools/{tool}/invoke` | Invoke a tool against the remote server |
| `GET` | `/api/mcp/connections/{id}/oauth/authorize` | Start the OAuth2 dance |

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
