# Tools, models, integrations, archives

The tables behind tool configuration, code assets, ML models, MCP, connectors, the LLM catalogue and the archiver.

Migrations: [`d6e7f8a9b0c1_tenant_tool_credentials`](../../packages/db/alembic/versions/d6e7f8a9b0c1_tenant_tool_credentials.py), [`b1c2d3e4f5a6_code_asset_versions`](../../packages/db/alembic/versions/b1c2d3e4f5a6_code_asset_versions.py), [`f8a9b0c1d2e3_mcp_tool_orphaned`](../../packages/db/alembic/versions/f8a9b0c1d2e3_mcp_tool_orphaned.py), [`a3c4d5e6f7a8_archive_tenant_scope`](../../packages/db/alembic/versions/a3c4d5e6f7a8_archive_tenant_scope.py), [`e7f8a9b0c1d2_archive_storage_key`](../../packages/db/alembic/versions/e7f8a9b0c1d2_archive_storage_key.py), [`a8b9c0d1e2f3_model_availability`](../../packages/db/alembic/versions/a8b9c0d1e2f3_model_availability.py)

---

## Tool configuration

### `tenant_tool_credentials`

One row per tenant and key. Source: [`tenant_tool_credential.py`](../../packages/db/models/tenant_tool_credential.py).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | Primary key part. `ON DELETE CASCADE`. |
| `key` | varchar(128) | Primary key part. The environment-style name a tool declares in `config_fields`, for example `TAVILY_API_KEY`. |
| `value` | text | Encrypted with the cluster KEK when `ABENIX_DATA_KEY_KEK_BASE64` is set, stored as is otherwise. |
| `updated_at` / `updated_by` | | |

### `platform_settings`

Admin-only key/value table (`key` primary key, `value`, `description`, `category`, `updated_at`, `updated_by`). Created by raw SQL in the API startup hook as well as the model. Platform-wide tool credentials live here as `tool.credential.<KEY>` rows, encrypted the same way. See [09-reference/04-platform-settings](../09-reference/04-platform-settings.md).

The resolver in [`engine/credentials.py`](../../apps/agent-runtime/engine/credentials.py) reads a value in this order: test override, `tenant_tool_credentials` row for the current tenant, `platform_settings` row, process environment, `packages/db/seeds/tool_defaults.yaml`, the tool's declared default, empty. LLM provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` and others) go through the same path, declared in [`engine/provider_credentials.py`](../../apps/agent-runtime/engine/provider_credentials.py). See [08-howto/08-tool-configuration](../08-howto/08-tool-configuration.md).

### `tool_runtime_config`

One row per tool slug, platform-wide. `slug` primary key, `enabled`, `pool`, `max_inflight_global`, `max_inflight_per_tenant`, `rate_limit_qps_global`, `rate_limit_qps_per_tenant`, `cache_ttl_seconds`, `cache_scope`, circuit breaker threshold, window and cooldown, `timeout_seconds`, `daily_budget_calls_per_tenant`.

### `tool_presets` and `saved_tools`

| Table | Key columns | Notes |
|---|---|---|
| `tool_presets` | `slug`, `label`, `tool_slug`, `default_args`, `config`, `category`, `ui_group`, `asset_class`, `enabled`, `is_system` | A labelled tool plus default arguments per tenant |
| `saved_tools` | `name`, `code`, `input_schema`, `created_by`, `approved_by`, `status`, `is_public`, `usage_count`, `review_score`, `permissions` | AI-generated tools that need admin approval before use |

---

## Code assets

`code_assets` holds an uploaded zip or git repo and what the analyser found: `source_type`, `source_git_url`, `source_ref`, `storage_uri`, `detected_language`, `detected_version`, `detected_package_manager`, `detected_entrypoint`, suggested image and commands, `input_schema`, `output_schema`, `status`, and the last test input, output and result.

Versions are columns, not a table. `b1c2d3e4f5a6` added:

| Column | Notes |
|---|---|
| `version` | int, `server_default 1`. Bumped on every new upload. |
| `version_history` | jsonb list of earlier versions with their `storage_uri`, so one can be restored. Capped by `CODE_ASSET_MAX_VERSIONS` (default 20). Archives no version uses any more are deleted. |

Warm code runners are Kubernetes Deployments keyed by tenant and asset version. They have no table. See [02-runtime/16-warm-code-runners](../02-runtime/16-warm-code-runners.md).

---

## ML models

| Table | Key columns | Notes |
|---|---|---|
| `ml_models` | `name`, `version`, `framework`, `file_uri`, `original_filename`, `input_schema`, `output_schema`, `status`, `training_metrics`, `tags`, `is_active`, `created_by` | The registry. A model that failed its load check has `status=error`, `is_active=false` and the reason in `training_metrics.validation_error` |
| `ml_model_deployments` | `model_id`, `deployment_type`, `endpoint_url`, `replicas`, `status`, `pod_name`, `service_name`, `k8s_namespace`, `config` | In-process or a Kubernetes pod |

See [02-runtime/12-ml-models](../02-runtime/12-ml-models.md).

---

## MCP and connectors

| Table | Key columns | Notes |
|---|---|---|
| `user_mcp_connections` | `user_id`, `server_name`, `server_url`, `transport_type`, `auth_type`, `auth_config`, `discovered_tools`, `health_status`, `is_enabled`, OAuth2 client, URLs and encrypted token columns | OAuth2 columns added by `d4e5f6a7b8c9` |
| `agent_mcp_tools` | `agent_id`, `mcp_connection_id`, `tool_name`, `tool_config`, `approval_required`, `max_calls_per_execution`, `is_orphaned`, `orphaned_at` | A tool attached to an agent |
| `mcp_registry_cache` | `registry_id`, `name`, `server_url`, `auth_type`, `categories`, `tools_count`, `popularity_score`, `verified` | Cached public registry |
| `connectors` | `name`, `kind`, `preset_key`, `base_url`, `auth_type`, `secret_ref`, `config`, `is_active`, `last_test_ok` | External systems, added by `1100_a_connectors` |
| `edge_gateways` | `gateway_id`, `name`, `endpoint_url`, `status`, `deployed_agents`, `registered_at`, `last_seen_at` | Remote edge pods, added by `1100_e_edge` |

`is_orphaned` replaced deletion. When a connection is refreshed and the server no longer offers a tool, the row is flagged with `orphaned_at` instead of removed. The runtime leaves orphaned tools out of the agent's tool list. If the server offers the tool again the flag clears.

---

## LLM catalogue

| Table | Key columns | Notes |
|---|---|---|
| `llm_model_pricing` | `model`, `provider`, `input_per_m`, `output_per_m`, `cached_input_per_m`, batch prices, `capabilities`, `fallback_to`, `provider_endpoint`, `display_name`, `is_deprecated`, `deprecated_at`, `migration_hint`, `effective_from`, `is_active` | Source of truth for run cost and fallback chains. Added by `s9t0u1v2w3x4`, extended by `a8b9c0d1e2f3` |
| `model_availability` | `model`, `provider`, `status`, `last_checked_at`, `last_ok_at`, `last_error`, `consecutive_failures`, `latency_ms`, `status_since` | Health per model |
| `model_availability_events` | `model`, `from_status`, `to_status`, `error` | Status transitions. Created by migration `a8b9c0d1e2f3` and written with raw SQL, no ORM model |

---

## Portfolio schemas

`portfolio_schemas` holds tenant-defined record schemas for the portfolio tool: `domain_name`, `label`, `record_noun`, `record_noun_plural`, `schema_json`, `is_active`.

Create and update run `schema_json` through [`portfolio_schema_check.py`](../../apps/api/app/core/portfolio_schema_check.py) before saving:

- `domain` needs `label`, `record_noun` and `record_noun_plural`. Missing ones are filled from the request fields. `domain.name` is always set to `domain_name`.
- `main_table` needs `name`, `user_scope_column`, `title_column`, a non-empty `list_columns` and a non-empty `columns` object. `created_at_column`, `search_columns`, `type_column` and `summary_aggregations` are optional.
- Each entry in `related_tables` needs `name`, a unique `label`, `foreign_key` and `columns`. `order_by` is a column with an optional `ASC` or `DESC`. A key-value table (`is_kv_store`) also needs `key_column` and `value_column`.
- Every table and column name must match `^[a-z_][a-z0-9_]*$` and must not be a reserved SQL word such as `order` or `user`, because the tool puts names into queries unquoted. Aggregation `sql` must be one `count`, `sum`, `avg`, `min` or `max` over a single column, or `count(*)`.
- Every referenced table and column must exist in the platform database (checked against `information_schema`). The main table also needs `id`, and `created_at` unless `created_at_column` names another column.

Problems come back as a 422 with `error.details.problems`, one line each.

### Spreadsheet import (`pf_` tables)

A schema only works against a table that exists, so the page can also make the table. [`portfolio_import.py`](../../apps/api/app/core/portfolio_import.py) reads an uploaded CSV (and `.xlsx` when `openpyxl` is installed, which the API image does not do today, so the cluster takes CSV only and says so), and the router creates:

- a table `pf_<first 8 hex of tenant id>_<domain>`, at most 63 characters (a long domain is cut and gets an 8 character hash)
- columns `id uuid` primary key with `gen_random_uuid()`, `owner_id uuid not null`, `created_at timestamptz default now()`, then one column per kept spreadsheet column
- an index on `owner_id` and the table comment `abenix:portfolio-import:<tenant id>`, which marks it as made by this feature for that tenant

Column names are snake_case of the header. `id`, `owner_id` and `created_at` become `source_<name>`, reserved SQL words get `_value`, duplicates get `_2`, `_3`. Types are inferred from every non-empty value: number (`double precision`, thousands commas allowed, leading zeros stay text), date (`date`, or `timestamptz` when any value has a time, ISO or day/month/year or month/day/year when the values settle it), boolean (yes/no, true/false, y/n) and otherwise text. A row whose value does not fit its column is skipped and reported with the row number and the reason. Limits are 50,000 rows, 20 MB and 100 columns.

The generated `schema_json` uses `owner_id` as `user_scope_column`, lists every column, searches the text columns, and adds `count(*)` plus `sum` and `avg` for up to ten number columns. It carries `"source": {"kind": "spreadsheet", "table": ...}` and goes through the same validator as a hand-written schema. Rows belong to the uploader, so each person and the agents acting for them see only their own rows.

Uploading again to the same domain either replaces the uploader's rows or appends. Other people's rows are never touched. New columns are added to the table and to the schema, existing columns keep their stored type.

Deleting a schema keeps its table unless `drop_table=true`. The table is dropped only when its name is the `pf_` name for that tenant and domain, it carries the marker comment and no other schema in the tenant reads it.

"Try with a sample" imports [`energy_trades_sample.csv`](../../apps/api/app/core/portfolio_templates/energy_trades_sample.csv) (40 power and gas trades) as `energy_trading_book`, owned by the person who clicked. Clicking again refreshes that person's sample rows.

These tables are made at runtime, so they are not in the SQLAlchemy models or alembic. Leave `pf_*` alone if you ever autogenerate a migration.

The starter templates (`real_estate`, `ma_documents`, `energy_contracts`) are examples. Their tables do not ship with the platform, so they save only once pointed at real tables. The energy contracts template lives in [`apps/api/app/core/portfolio_templates/energy_contracts.json`](../../apps/api/app/core/portfolio_templates/energy_contracts.json) and `seed_portfolio_schemas.py` reads it from there.

---

## Archives

Source: [`archive.py`](../../packages/db/models/archive.py). Both tables were first created by `create_all`. `a3c4d5e6f7a8` creates them when absent and adds tenant scope, because without it any tenant admin could archive, delete and download every tenant's rows.

### `archive_runs`

| Column | Notes |
|---|---|
| `tenant_id` | Added by `a3c4d5e6f7a8`. `ON DELETE CASCADE`. |
| `source_table` | One of `executions`, `messages`, `activity_logs`, `code_asset_invocations`, `ml_model_invocations`, `kb_query_invocations`. |
| `triggered_by` / `is_manual` / `status` | `status` is `pending`, `running`, `completed` or `failed`. |
| `started_at` / `completed_at` / `cutoff_at` | |
| `rows_archived` / `rows_deleted` | |
| `file_uri` / `file_size_bytes` / `file_sha256` | The dump. |
| `storage_key` / `storage_backend` | Added by `e7f8a9b0c1d2`. Object key `archives/{tenant}/{run}.jsonl.gz` and the backend it went to (`local`, `s3` or `azure`, from `STORAGE_BACKEND`). |
| `restored_at` / `restored_rows` / `restore_error` | Added by `e7f8a9b0c1d2`. The last `POST /api/admin/archives/{id}/restore`. |
| `oldest_row_at` / `newest_row_at` / `error_message` / `notes` | |

### `retention_policies`

Primary key `(tenant_id, source_table)` since `a3c4d5e6f7a8`. Columns `retention_days`, `enabled`, `description`, `updated_by`. Defaults when no row exists: 30 days for the three invocation tables, 60 for `executions` and `messages`, 90 for `activity_logs`.

Archiving `activity_logs` follows the audit chain rules in [05-governance-decisions](05-governance-decisions.md#audit-chain-on-activity_logs).

---

## See also

- [02-runtime/02-tools](../02-runtime/02-tools.md) — the tool framework
- [02-runtime/03-mcp](../02-runtime/03-mcp.md) — MCP integration
- [06-deployment/02-helm](../06-deployment/02-helm.md) — where the KEK and storage backend are set
