# Platform settings

Runtime knobs an admin changes from **Admin -> Model Selection** and **Admin -> Tool Configuration** without a redeploy.
They live in the `platform_settings` table, are declared in
[`apps/api/app/core/platform_settings.py`](../../apps/api/app/core/platform_settings.py),
and are read through `get_setting()` or `get_int_setting()`.

Values are cached for 30 seconds per process, in the API and in the
agent-runtime consumer alike, so a change takes effect within half a minute. A
key that has never been written falls back to the default declared in
`DEFAULTS`, which is what the UI shows as "Platform default".

There are 16 keys in `DEFAULTS`, listed below. `PATCH /api/admin/settings/{key}`
refuses any key that is not one of them.

---

## Setting kinds

| Kind | Rendered as | Validation |
|---|---|---|
| `model` (default) | Model picker | Must be in the model catalogue |
| `int` | Number input with the declared bounds | Must be a whole number inside `min`/`max` |

Validation happens on the API, not only in the browser, because these values are
read on the execution hot path and a bad one would otherwise surface as a
failed run rather than a rejected save.

---

## Execution limits

These were hardcoded in the engine until 2.4.x. A seven-node LLM pipeline does
not fit in the old 120-second budget, which is how ClaimsIQ's adjudication kept
dying with `Pipeline timeout exceeded` on its last two nodes while the earlier
nodes succeeded.

| Key | Default | Range | What it controls |
|---|---|---|---|
| `pipeline.timeout_seconds` | 300 | 60-3600 | Wall-clock budget for a whole pipeline run. Raise it for pipelines with many LLM nodes. A node cut off by this limit reports `Pipeline timeout exceeded` and the run ends `failed` with `failure_code=SANDBOX_TIMEOUT`. |
| `agent.max_iterations` | 10 | 1-50 | Default tool-calling loop cap. An agent can request more in its own `model_config.max_iterations`. |
| `sandbox.timeout_seconds` | 300 | 30-1800 | Wall-clock budget for one sandboxed code execution. |

`PIPELINE_TIMEOUT_SECONDS` and `SANDBOX_TIMEOUT_SECONDS` in the environment
are only the engine's fallback for when the settings table cannot be read. A
stored value or the `DEFAULTS` entry wins over them.

**Sizing the pipeline budget.** Count the LLM nodes and allow roughly 20 to 40
seconds each, more if a node does web research or multimodal work. OracleNet's
deep mode sets its own 600 in code because seven research agents genuinely need
it. If runs are being cut off, the execution row names which nodes ran out of
time in `error_message`.

### Clients that wait on a run

`GET /api/settings/limits` returns the current budgets to any authenticated
caller, API keys included:

```json
{"pipeline_timeout_seconds": 900, "agent_max_iterations": 10,
 "sandbox_timeout_seconds": 300}
```

A client that blocks on a synchronous run should size its own wait from this
rather than carrying a second number. ClaimsIQ used to hold an independent 240s
against a 300s platform budget, so a slow adjudication returned 504 to the app
while the pipeline carried on and finished. It now reads this endpoint, caches
for a minute, and waits the platform budget plus 30 seconds, so the server times
the run out first and reports which nodes ran over.

---

## Model selection

One setting per surface, so a cheaper model can be used for the high-volume
paths without touching the ones that need the strongest reasoning.

| Key | Used by |
|---|---|
| `ai_builder.model` | Generating agents and pipelines from a description |
| `ai_builder.critic.model` | The builder's critic and adversarial-safety gates |
| `ai_builder.validation.model` | Tier-3 pipeline critique behind AI Validate |
| `moderation.model` | The moderation gate's provider model |
| `knowledge_engine.summarizer.model` | Cognify document summarisation |
| `sdk_playground.default.model` | Pre-selected model in the SDK Playground |
| `triggers.default.model` | Cron-triggered agent runs |
| `pipeline_surgeon.model` | Pipeline Surgeon's diagnose and patch |
| `workflow_shell.model` | The workflow shell REPL |

Under an exclusive Claude subscription these are all overridden at request time,
see below.

---

## Claude subscription

| Key | Default | Notes |
|---|---|---|
| `llm.subscription.enabled` | `false` | Turns subscription mode on. Refuses to enable without a stored token. |
| `llm.subscription.token` | empty | Secret. Masked in every response and never returned to the browser. |
| `llm.subscription.default_model` | `claude-haiku-4-5` | The model the subscription serves. Haiku by default for rate-limit headroom, because exclusive mode pins every request and one pipeline can fan out to a dozen sub-agents. |
| `llm.subscription.exclusive` | `true` | Pins every request to `default_model`, including ones that already name a Claude model. |

The token rotates. When agent runs start failing with
`OAuth access token has been revoked`, run
`bash scripts/sync-claude-subscription.sh` rather than debugging the platform,
and confirm with `POST /api/admin/settings/subscription/verify`.

---

## Tool credentials

Keys saved on **Admin -> Tool Configuration** with the scope on "Platform" live in the same table under the `tool.credential.` prefix, one row per key, for example `tool.credential.TAVILY_API_KEY`. They are not in `DEFAULTS`. The set of keys is generated from the tools' `config_fields`, so this file never lists them.

Keys saved with the scope on "This tenant" live in `tenant_tool_credentials`, one row per `(tenant_id, key)`, encrypted the same way. A tenant row wins over the platform row for that tenant only.

| Behaviour | Detail |
|---|---|
| Who writes | `PATCH /api/admin/tool-config/{KEY}` with `scope=tenant` (default) or `scope=platform`, admin only. The generic settings endpoints never return these rows. Platform writes are audited on the `abenix.audit.tool_config` logger with the scope and the caller's tenant. |
| Masking | Every `tool.credential.*` key is treated as a secret by `is_secret()`. The tool-config endpoints mask by declared kind and show the last four characters of a secret. |
| At rest | AES-GCM under `ABENIX_DATA_KEY_KEK_BASE64` when set, otherwise stored as entered. The screen says which. Both tables use one scope, so the runtime decodes them the same way. |
| Reset | `POST /api/admin/settings/reset` clears only the settings listed on this page. Tool credentials, connector secrets and the marketplace and monetization switches stay as they are. |
| Propagation | 30 seconds. The agent-runtime reads both tables over `DATABASE_URL` with asyncpg, single-flight, serving the previous snapshot while a refresh runs. |
| Precedence | The tenant row wins over the platform row, which wins over the environment, which wins over `tool_defaults.yaml`, which wins over the tool's declared default. |
| Which tenant | The executor sets the tenant at the start of a run and the queue consumer sets it before building an executor. `GET /api/tools` resolves for the caller's tenant. |

How a tool declares a key, and how the screen is generated from that: [08-howto/08-tool-configuration](../08-howto/08-tool-configuration.md).

---

## Endpoints

| Method | Path | Who | What |
|---|---|---|---|
| `GET` | `/api/admin/settings` | admin | Every key with its stored value or default, grouped by category. Secrets masked |
| `PATCH` | `/api/admin/settings/{key}` | admin | Body `{"value": "..."}`. Model keys must be in the catalogue, int keys inside their bounds. Enabling subscription mode needs a stored or environment token |
| `POST` | `/api/admin/settings/reset` | admin | Clears the stored values of the settings on this page, nothing else |
| `GET` | `/api/admin/settings/models` | admin | The model catalogue the pickers offer |
| `GET` | `/api/admin/settings/models/public` | signed in | Same catalogue for non-admin pickers |
| `GET` | `/api/admin/settings/subscription` | admin | Subscription state, token masked |
| `POST` | `/api/admin/settings/subscription/verify` | admin | Makes one call with the token and reports the result |
| `GET` | `/api/settings/builder_model` | signed in | Current `ai_builder.validation.model` |
| `PUT` | `/api/settings/builder_model` | admin | Writes `ai_builder.validation.model` |
| `GET` | `/api/settings/limits` | signed in | The three execution budgets, see above |

The model picker's provider check also reads rows named
`provider.<name>.api_key` or in category `secrets`. Nothing in the platform
writes such rows today, so in practice that check sees only the environment.

---

## Tenant-scoped settings

These are not in `platform_settings`. They live per tenant and a tenant admin
changes them, so they are listed here only so you know where to look.

| Setting | Stored in | Endpoint |
|---|---|---|
| Data retention days for executions, messages and audit log | `tenants.settings.retention` | `GET`/`PUT /api/settings/retention`. Floors 7, 30 and 365 days |
| DLP mode `detect`, `mask` or `block` | `tenants.settings.dlp` | `GET`/`PUT /api/settings/dlp` |
| Sandboxed job overrides `enabled`, `allow_network`, `allowed_images` | Redis hash per tenant | `GET`/`PUT /api/settings/sandbox`. Unset falls back to the `SANDBOXED_JOB_*` variables |
| Tenant Slack webhook | `tenants.slack_webhook_url`, encrypted | `GET`/`PUT /api/settings/tenant` |
| Approval webhook URL and secret | `tenants.settings.approval_webhook_url` and `approval_webhook_secret`, secret encrypted | `GET`/`PUT /api/approvals/webhooks` |
| Source Watch host allow-list and pause threshold | `tenants.settings.source_watch` | `GET`/`PUT /api/sources/settings`, see [17-source-watch](../02-runtime/17-source-watch.md) |
| Drift detection on or off | Redis key `drift:config:enabled:<tenant>` | `GET`/`PUT /api/analytics/drift-alerts/config` |
| Tool credentials for one tenant | `tenant_tool_credentials` | Admin -> Tool Configuration, see above |

---

## Adding a setting

1. Add an entry to `DEFAULTS` in `platform_settings.py` with a `category`, a
   `description` that reads as a sentence, and for a numeric knob
   `"kind": "int"` plus `min` and `max`.
2. Add the category to `CATEGORY_META` in
   [`admin/llm-settings/page.tsx`](../../apps/web/src/app/(app)/admin/llm-settings/page.tsx)
   if it is a new one. Existing categories need no UI change.
3. Read it with `await get_setting(key)` or `await get_int_setting(key, fallback)`.
   Always pass a fallback. These are read on the execution path and settings I/O
   must never take a run down.
4. If a secret, add the key to `SECRET_KEYS` so it is masked.

A value a tool needs is not a platform setting. Declare it on the tool as a `ConfigField` instead, and it appears under Tool Configuration with no change here.

---

## See also

- [01-env-vars](01-env-vars.md) — deploy-time configuration, which needs a restart
- [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md) — subscription mode in the router
- [02-runtime/13-moderation-gate](../02-runtime/13-moderation-gate.md) — the moderation policy, configured per tenant rather than here
