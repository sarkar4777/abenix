# Testing: unit, lint, integration, browser UAT

> What tests exist, where they live, what CI runs, and how to run the browser specs against a local or deployed stack.

---

## Layer 1. Unit tests

### Python

| Location | What | Run |
|---|---|---|
| `tests/unit/` | The CI gate. Pure Python, no live services. `conftest.py` puts `apps/api`, `apps/agent-runtime`, `packages/db` and `apps/worker` on the path. Decisions, evals, events, governance, source watch and tool configuration all have suites here (`test_decisions.py`, `test_eval_assertions.py`, `test_evals_api.py`, `test_events.py`, `test_governance.py`, `test_source_watch.py`, `test_sources_api.py`, `test_tool_config_service.py`, `test_tool_config_scope.py`, `test_tool_contract.py`). Spend caps, queue leases, the GDPR purge, document grants, re-embedding, network policies and admin-only routes have theirs too (`test_agent_budget.py`, `test_decision_review_and_lease_sweep.py`, `test_gdpr_purge.py`, `test_document_grants.py`, `test_kb_reembed_and_vacuum.py`, `test_network_policies.py`, `test_admin_routes_gated.py`, `test_dependency_health.py`) | `pytest tests/unit/ -v` |
| `apps/agent-runtime/tests/` | Runtime and tool tests, named `test_<tool>_tool.py` for tools. `test_queue_delivery.py` covers at-least-once delivery and the lease, `test_knowledge_stack.py` the search ACL, reranking, per-collection embedding models, Cognify conflicts and extractors, `test_atlas_as_of.py` the as-of tool. Redis and LiveKit tests skip when the service is absent | `SKIP_NETWORK_TESTS=1 python -m pytest -q apps/agent-runtime/tests` |
| `apps/api/tests/` | Older route tests through the ASGI app. They need a reachable Postgres at the configured `DATABASE_URL` | `cd apps/api && pytest -v` |
| `apps/code-runner/tests/` | The warm runner gateway. Has its own `pytest.ini` | `cd apps/code-runner && pytest` |
| `apps/edge-runtime/tests/` | The Python edge runtime | `pytest apps/edge-runtime/tests` |
| `apps/edge-runtime-c/tests/`, `apps/edge-runtime-rust/tests/` | The C and Rust edge runtimes | their own `Makefile` and `cargo test` |
| `<app>/api/tests/` | Standalone app suites, today `resolveai` and `pharmavigil` | `check-before-push.sh` runs every one it finds |

`apps/worker/tests/` and `packages/agent-sdk/tests/` hold only an `__init__.py`.

### TypeScript

```bash
npm test                      # turbo, runs vitest in apps/web
cd apps/web && npx vitest run # the same, directly
```

The web suites live in `apps/web/src/__tests__/`. `toastsAndSignIn.test.tsx` covers app-wide toasts and the return to the page after a session expires, `settingsEventsGate.test.tsx` the Events tab gate.

---

## Layer 2. Lint and contract checks

These are cheap and catch whole classes of bug. CI runs all of them.

| Script | Fails when |
|---|---|
| `python scripts/lint-agent-seeds.py` | An agent YAML breaks `AgentSeedSchema`, lists `knowledge_search` with no collection granted, or uses a tool with a required key not in `requires_credentials` |
| `python scripts/check-tool-config.py` | A tool reads `os.environ` for a non-infrastructure name, reads an undeclared key, declares a key nothing reads, is not in the registry, or has no valid `risk_tier`. `--report` lists every read |
| `python scripts/gen-tool-docs.py --check` | The generated tool docs in the web app are stale. `--write` regenerates them |
| `python scripts/check-api-requirements.py` | `apps/api/requirements.txt` and the API's `pyproject.toml` disagree |
| `python scripts/check-readme-images.py` | The README links an image that is missing or untracked |
| `python scripts/check-dockerfile-hardening.py` | A Dockerfile in `apps/*/` (built by CI) or `docker/` (built by the deploy scripts) breaks the base image patching rules, such as a base pinned to a patch level |
| `bash scripts/verify-alembic-graph.sh` | Two migrations share a revision id, or the graph has more than one head |
| `bash scripts/sync-sdks.sh --check` | A vendored copy of the Python SDK drifted from `packages/sdk/python/abenix_sdk/` |
| `node scripts/validate-mermaid.mjs` | A mermaid block in the docs does not parse |

Formatting is `black` 24.8.0 and `ruff` 0.6.9 over `apps/api apps/agent-runtime apps/worker packages/db`. ESLint and `tsc --noEmit` cover the web app.

---

## Layer 3. Integration tests

`tests/integration/` fires real HTTP at a running API, `http://localhost:8000` by default or `ABENIX_API_URL`. It is skipped unless `ABENIX_INTEGRATION=1`, except `test_seed_loader.py`, which only validates YAML and always runs.

```bash
ABENIX_INTEGRATION=1 pytest tests/integration -v
```

`tests/load/locustfile.py` and `scripts/load/` (including `decision_load.py` and `code_runner_bench.py`) drive load. See [06-deployment/load-test-baseline](../06-deployment/load-test-baseline.md).

---

## Layer 4. Browser UAT (Playwright)

Real browser, real API, real database. `playwright.config.ts` sets `testDir: './e2e'`, one worker, and starts `npm run dev --workspace=apps/web` itself unless `USE_K8S` is set. Set `USE_K8S=true` when the web app is already running, in a cluster or under `dev-local.sh`.

### How the specs are configured

Most specs read the same variables:

| Variable | Default | Meaning |
|---|---|---|
| `BASE` | `http://localhost:3000`, or `http://localhost:3100` in the 2.5 specs | The Abenix web app |
| `API` | `http://localhost:8000` | The Abenix API |
| `AF_EMAIL` / `AF_PASSWORD` | `admin@abenix.dev` / `Admin123456` | The admin they sign in as |

Some read their own names. `uat_apps_full` reads `BASE_AB` and `AB_API` plus per-app URLs (`BASE_WM`, `BASE_IOT`, `BASE_CIQ`, `BASE_ST`, `BASE_RA`). The ContractIQ specs read `CIQ_EMAIL` and `CIQ_PASSWORD`. `uat_claimsiq_deep` reads `BASE_URL` and `API_URL`. `uat_model_fallback` reads `API_URL`, `ADMIN_EMAIL` and `ADMIN_PASSWORD`. `uat_grafana_panels` reads `GRAFANA`, `GRAFANA_USER` and `GRAFANA_PASSWORD`. Read the top of a spec before running it.

Pass `BASE` explicitly when your web app is on 3000 and the spec defaults to 3100:

```bash
USE_K8S=true BASE=http://localhost:3000 API=http://localhost:8000 \
  npx playwright test e2e/uat_decisions.spec.ts --workers=1 --reporter=list
```

Against AKS, open the forwards with `bash scripts/portforward-azure.sh` first and point `BASE` and `API` at them.

### The 69 `uat_*` specs, grouped

| Group | Specs |
|---|---|
| Deploy gate, run by `scripts/uat.sh` (13) | `uat_abenix_browser`, `uat_abenix_deep`, `uat_abenix_industrial`, `uat_abenix_hitl`, `uat_abenix_sdk_playground`, `uat_apps_full`, `uat_wingman`, `uat_abenix_multi_user`, `uat_claimsiq_deep`, `uat_grafana_panels`, `uat_pharmavigil`, `uat_help_surfaces`, `uat_platform_surfaces` |
| 2.5 features (8) | `uat_rules_to_agents`, `uat_decisions`, `uat_governance`, `uat_evals`, `uat_source_watch`, `uat_tool_config`, `uat_wave_2_5_browser`, `uat_ux_walkthrough` |
| Builder and AI builder (7) | `uat_builder_journey`, `uat_ai_builder_browser`, `uat_ai_builder_deep_quality`, `uat_ai_builder_jira_categorizer`, `uat_ai_builder_pipeline_azure`, `uat_models_page_builder_config`, `uat_v110_palette` |
| Platform journeys, settings and regressions (13) | `uat_critical_paths`, `uat_enterprise_critical`, `uat_enterprise_edge`, `uat_ui_journeys`, `uat_user_journey_ui`, `uat_user_journey_followups`, `uat_settings_functional`, `uat_real_functionality`, `uat_comprehensive_browser`, `uat_gaps_exploratory`, `uat_gaps_complex_flows`, `uat_audit_fixes`, `uat_final_resweep` |
| Models, providers, MCP, ML and edge (7) | `uat_model_fallback`, `uat_model_fallback_ui`, `uat_provider_key_picker_and_fallback`, `uat_claude_subscription`, `uat_mcp_browser`, `uat_ml_models_k8s_deploy`, `uat_edge_mint` |
| Knowledge v2 (2) | `uat_v2_enterprise`, `uat_v2_real_corpus` |
| ContractIQ (6) | `uat_contractiq_advanced`, `uat_contractiq_browser`, `uat_contractiq_chat_threads`, `uat_contractiq_quickwin_deep`, `uat_contractiq_truthfulness`, `uat_contractiq_valuation_shell` |
| Wingman (7) | `uat_wingman_full`, `uat_wingman_browser_quality`, `uat_wingman_dag_and_scenarios`, `uat_wingman_mispricing`, `uat_wingman_phase15`, `uat_wingman_screenshots`, `uat_commodities_ia_collapse` |
| ClaimsIQ, Industrial IoT, ResolveAI (4) | `uat_claimsiq_journey`, `uat_claimsiq_browser_quality`, `uat_industrial_browser_quality`, `uat_resolveai_browser` |
| Cross-app (2) | `uat_apps_e2e_minikube`, `uat_demo_browser` |

`e2e/` also holds helper specs that are not UAT, such as `capture_readme_shots.spec.ts`, `feature-shots.spec.ts` and `inspect_tools.spec.ts`, and the fixtures under `e2e/fixtures/`.

### The 2.5 feature specs

All six below read `BASE` (default `http://localhost:3100`), `API` and `AF_EMAIL` / `AF_PASSWORD`, sign in as the admin, drive the screens, use the API only to read state back and clean up, and run serially with `--workers=1`.

**`uat_rules_to_agents.spec.ts`**. The whole journey from a rule to its callers, through the UI only. Creates a reference set of remote postcodes, builds a surcharge decision with a catch-all rule in the no-code builder, uses Try to hit, miss and report missing facts, keeps two golden tests, runs Check, proposes and publishes. Builds and publishes an agent with `decision_evaluate`, asks it about a remote and a London shipment in chat, and reads the tool call on the Flight Recorder. Builds a pipeline with typed inputs, a `decision_evaluate` step and an `llm_call` step, and runs it from chat. Runs both in the SDK playground and checks the generated Python carries the inputs. Finally checks a reference set in use cannot be deleted. Needs a working LLM credential, the chat and pipeline tests allow up to ten minutes.

**`uat_decisions.spec.ts`**. The decision workspace. The empty page explains itself, the surcharge rule is built with no code, Try decides live and keeps a golden test, Check, propose and publish from the lifecycle bar, a new draft takes typed JSON and a table edit, two authors editing one draft have their changes combined, and a high tier change waits for a second person who signs it on **Approvals**. That last test creates a signer with `POST /api/team/dev-create-member` and a permission set holding `approvals.sign`.

**`uat_governance.spec.ts`**. **Admin -> Risk & Controls** and **Admin -> Permissions**. All four tiers show, a tier policy is edited, validated at the field, saved and reset, a kill switch on `calculator` stops that tool inside a real run and is resumed, tool tiers are searchable, audit verification reports intact, a run records its provenance and tier, a plain user is refused until a permission set grants `killswitch.manage`, and the builder's tier picker shows what a tier requires. The kill switch test runs an agent that has the calculator tool and skips when none exists.

**`uat_evals.spec.ts`**. A gating suite created from the sidebar blocks publishing before it has run, the assertion builder previews against a sample answer, a run executes every case and shows reasons per case, a past run is saved as a case from the execution page, and after fixing the suite a new run lets the agent publish. The first two tests are deterministic. The others run the agent for real, `EVAL_MODEL` picks the model (default `claude-haiku-4-5-20251001`), and `SKIP_LIVE_LLM=1` skips them.

**`uat_source_watch.spec.ts`**. Source Watch in the sidebar with its empty state, a private address refused while typing, a page added with a test fetch, checked to a baseline and then to no change, a JSON source that changes showing a side-by-side diff, pause with a reason and resume, and the four `source_*` tools present in `/api/tools`. Needs outbound internet from the API. `STABLE_URL` (default `https://example.com`) must not change between checks. `CHANGING_URL` (default `https://httpbin.org/uuid`) must change on every request. A local httpbin works with `SOURCE_WATCH_ALLOW_PRIVATE_TARGETS=1` on the API.

**`uat_tool_config.spec.ts`**. **Admin -> Tool Configuration**, without a hard-coded tool list. The catalogue is generated and complete, a value saved from the screen flips the source to "saved for this tenant" and the badge on `/tools` follows, a tenant value sits above a platform value, an undeclared key gets 404 and a bad URL 400, the Test button reports a rejected GitHub token, a missing required key comes back as one sentence naming the key and the screen, and a viewer gets neither the sidebar entry nor the endpoint. Its `BASE` defaults to 3000.

**`uat_abenix_sdk_playground.spec.ts`**. Part of the deploy gate. Reads `BASE` (default 3000), `API`, `AF_EMAIL` and `AF_PASSWORD`. Checks a probe agent exists (an OOB agent matching `current_time`, `hello` or `echo`, so no LLM cost), that `/sdk-playground` builds its input form from the agent's `input_variables` and `example_prompts`, and that **Run live** executes the agent and shows a status, the execution id and either output or a paused state.

### `scripts/uat.sh`, the deploy gate

```bash
bash scripts/uat.sh               # everything below
bash scripts/uat.sh --seed-only   # prepare the cluster and stop before the specs
```

Before it runs anything it needs port forwards on 3000 (web) and 8000 (API), a `kubectl` context on the cluster, and the MCP fixture manifests in `e2e/fixtures/mcp_server/`.

In order, it

1. exports `BASE` (`http://localhost:3000`), `API` (`http://localhost:8000`), `BASE_AB` and `AB_API` (same as those two), `AF_EMAIL`, `AF_PASSWORD`, `AF_VIEWER_EMAIL` (`viewer@abenix.dev`), `AF_VIEWER_PASSWORD` (`Viewer123456`), `GRAFANA` (`http://localhost:3030`), and `GRAFANA_USER` and `GRAFANA_PASSWORD` read off the Grafana deployment. Any of them can be overridden,
2. runs `python e2e/fixtures/build.py` when the PDF, zip or pickle fixtures are missing,
3. checks `$API/api/health` and `$BASE/` answer, exit 2 if not,
4. creates the viewer user in the admin's tenant through `POST /api/team/dev-create-member`, a 409 counts as already there,
5. applies the `uat-mcp` and `custom-mcp` fixture deployments, building their images into minikube when the context is minikube, and waits for them,
6. checks both MCP hosts are in `MCP_ALLOWED_HOSTS` on the `abenix-config` configmap, exit 1 if not,
7. runs the 13 gate specs one after another with `--reporter=list --workers=1 --timeout=300000`, in the order of the first table row above. `uat_claimsiq_deep` gets `BASE_URL=${CLAIMSIQ_BASE:-http://localhost:3005}`.

The first failing spec stops the run with a non-zero exit. The HTML report goes to `playwright-report/`.

### Writing a spec

- Create what you need through the API, namespace it with a timestamp (`Date.now().toString(36)`), and delete it in `finally` or `afterAll`, so the spec runs on a fresh cluster.
- Look elements up by `data-testid`, named `<feature>-<action>` or `<feature>-<state>`, for example `decision-new`, `kill-switch-submit`, `validation-chip-error`. Keep them stable, specs depend on them.
- Wrap API calls in one retry. A reused keep-alive socket can close under the request, which shows up as `socket hang up`.

---

## When to write what

| You're changing | Run | Add |
|---|---|---|
| A tool | `tests/unit/`, `scripts/check-tool-config.py` | A unit test for the happy path and each error path |
| An agent seed | `scripts/lint-agent-seeds.py` | An evaluation case, see [10-evals](10-evals.md) |
| A REST endpoint | `tests/unit/` | A unit test through the router, or an integration test against a running API |
| A UI page | vitest, a browser spec | A `uat_*.spec.ts` for the user flow |
| An agent's prompt | Its evaluation suite | Cases for what the change fixes |
| The SDK | `sync-sdks.sh --check`, the SDK playground spec | A unit test |
| Deploy or build scripts | `deploy.sh local`, `scripts/uat.sh` | A gate spec if it guards a release |

Prompt and agent quality is tested with evaluation suites, which run inside the platform. See [10-evals](10-evals.md).

---

## CI

`.github/workflows/ci.yml` runs on push and pull request to `main`, and by hand through `workflow_dispatch`. All jobs run on `ubuntu-latest`.

| Job | Runs | What it does |
|---|---|---|
| `python-lint` | always | `black --check`, `ruff`, then `pip-audit` on `apps/api/requirements.txt` with `.pip-audit-ignore` applied. A CVE without an ignore entry fails the build |
| `python-test` | after lint | Installs the three apps' requirements, then `check-api-requirements.py`, `pytest tests/unit/`, the agent runtime tests with `SKIP_NETWORK_TESTS=1`, `lint-agent-seeds.py`, `check-readme-images.py`, `check-dockerfile-hardening.py`, `check-tool-config.py` and `gen-tool-docs.py --check` |
| `web-lint-typecheck-build` | always | ESLint, `tsc --noEmit`, a full Next build, and vitest |
| `e2e-smoke` | after the three above | Boots Postgres and Redis through docker compose and installs the Playwright browsers. It runs no specs, because a full boot needs credentials and a populated tenant |
| `build-images` | push to `main` or a manual run on `main` | Builds and pushes web, api, agent-runtime and worker to ghcr.io, then runs Trivy. The Trivy steps are informational |

The browser UAT does not run in CI. Run `bash scripts/uat.sh` against a deployed cluster.

`bash scripts/check-before-push.sh` runs most of this locally: black, ruff, `pytest tests/unit/`, the seed lint, the README image check, the standalone app suites, pip-audit, ESLint, `tsc`, vitest, the Next build, the mermaid check and the docs mirror check. It does not run `check-tool-config.py`, `gen-tool-docs.py --check` or the agent runtime tests, so run those yourself when you touch tools. `--fast` skips the Next build, `--python` and `--web` run one half.

---

## See also

- [00-local-setup](00-local-setup.md), get a stack running first
- [04-debugging](04-debugging.md), when a test fails inexplicably
- [01-add-a-tool](01-add-a-tool.md), where tool tests go
- [10-evals](10-evals.md), testing agent behaviour inside the platform
