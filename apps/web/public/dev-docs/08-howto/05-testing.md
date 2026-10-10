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
| `python scripts/check-doc-links.py` | A link in the README, `ONBOARDING.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md` or `docs/` points at a missing file or heading, a Help page link or a `docSlug` names a route or doc that does not exist, or `docs/manifest.json` and `docs/` disagree |
| `python scripts/check-docker-context.py` | A Dockerfile copies a path that git ignores, so it builds locally and fails on a fresh clone |
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

### The 89 `uat_*` specs, grouped

| Group | Specs |
|---|---|
| Older platform specs kept in `scripts/uat.sh` (13) | `uat_abenix_browser`, `uat_abenix_deep`, `uat_abenix_industrial`, `uat_abenix_hitl`, `uat_abenix_sdk_playground`, `uat_abenix_multi_user`, `uat_grafana_panels`, `uat_help_surfaces`, `uat_platform_surfaces`, `uat_v110_palette`, `uat_enterprise_critical`, `uat_ai_builder_deep_quality`, `uat_v2_enterprise` |
| Release gate for wayfinding (2) | `uat_lostness_gate`, `uat_first_use_tasks`, see [the wayfinding release gate](#the-wayfinding-release-gate) |
| 2.5 features (9) | `uat_rules_to_agents`, `uat_decisions`, `uat_decision_archive_restore`, `uat_governance`, `uat_evals`, `uat_source_watch`, `uat_tool_config`, `uat_wave_2_5_browser`, `uat_ux_walkthrough` |
| Autonomy and self-improvement (4) | `uat_autonomy_ui`, `uat_autonomy_complex_ui`, `uat_improvements_capture_ui`, `uat_improvements_loop_ui` |
| Screens-only walks added in 2.5.4 and 2.5.5 (12) | `uat_nav_build_run_ui`, `uat_nav_monitor_admin_ui`, `uat_platform_journeys_ui`, `uat_core_features_ui`, `uat_chat_memory_ui`, `uat_review_inbox_ui`, `uat_marketplace_ui`, `uat_meetings_ui`, `uat_cluster_view_ui`, `uat_portfolio_ui`, `uat_energy_trading_ui`, `uat_edge_builder_toggle` |
| Builder and AI builder (8) | `uat_builder_journey`, `uat_ai_build_and_heal_ui`, `uat_ai_builder_browser`, `uat_ai_builder_deep_quality`, `uat_ai_builder_jira_categorizer`, `uat_ai_builder_pipeline_azure`, `uat_models_page_builder_config`, `uat_v110_palette` |
| Platform journeys, settings and regressions (12) | `uat_critical_paths`, `uat_enterprise_critical`, `uat_enterprise_edge`, `uat_ui_journeys`, `uat_user_journey_ui`, `uat_user_journey_followups`, `uat_settings_functional`, `uat_real_functionality`, `uat_comprehensive_browser`, `uat_gaps_exploratory`, `uat_gaps_complex_flows`, `uat_audit_fixes` |
| Models, providers, MCP, ML and edge (7) | `uat_model_fallback`, `uat_model_fallback_ui`, `uat_provider_key_picker_and_fallback`, `uat_claude_subscription`, `uat_mcp_browser`, `uat_ml_models_k8s_deploy`, `uat_edge_mint` |
| Knowledge v2 (2) | `uat_v2_enterprise`, `uat_v2_real_corpus` |
| ContractIQ (6) | `uat_contractiq_advanced`, `uat_contractiq_browser`, `uat_contractiq_chat_threads`, `uat_contractiq_quickwin_deep`, `uat_contractiq_truthfulness`, `uat_contractiq_valuation_shell` |
| Wingman (7) | `uat_wingman_full`, `uat_wingman_browser_quality`, `uat_wingman_dag_and_scenarios`, `uat_wingman_mispricing`, `uat_wingman_phase15`, `uat_wingman_screenshots`, `uat_commodities_ia_collapse` |
| ClaimsIQ, Industrial IoT, ResolveAI (4) | `uat_claimsiq_journey`, `uat_claimsiq_browser_quality`, `uat_industrial_browser_quality`, `uat_resolveai_browser` |
| Cross-app (2) | `uat_apps_e2e_minikube`, `uat_demo_browser` |

`e2e/` also holds capture tools that are not tests, `capture_readme_shots.spec.ts` and `capture_audit_screenshots.spec.ts`, the CI smoke `ci_smoke.spec.ts`, shared helpers under `e2e/helpers/` and the fixtures under `e2e/fixtures/`.

The sidebar opens in Essentials, so a spec that reaches a page from the sidebar uses `e2e/helpers/sidebar.ts`. `openFromSidebar(page, href)` opens Admin or presses **Show all tools** only when the link is hidden, the way a person would.

### Running the suite

`scripts/uat.sh` runs specs one after another against a running stack, prints a table of passed, failed, skipped and not run per spec, and exits non-zero when any spec failed.

```bash
bash scripts/uat.sh                          # the platform set: core, autonomy, improvements, admin
bash scripts/uat.sh --suite core             # core|autonomy|improvements|admin|apps|all, comma separated
bash scripts/uat.sh --spec uat_evals,uat_governance
bash scripts/uat.sh --list                   # what a run would use
bash scripts/uat.sh --bail                   # stop at the first failing spec
```

It passes `BASE` (default `http://localhost:3100`), `API`, `USE_K8S` (default `true`), `AF_EMAIL` and `AF_PASSWORD`, `SECOND_EMAIL` and `SECOND_PASSWORD` and the older variable names to every spec. It warns when a deployment is mid rollout and when the Claude subscription token was revoked, since both turn into failures that say nothing about the product. Logs land in `logs/uat/`. The `apps` suite drives the standalone apps and needs their stacks running.

### Retired specs

| Spec | Why |
|---|---|
| `_record_demo.spec.ts` | Recorded a demo through the Wingman `/workbench`, which no longer exists |
| `uat_final_resweep.spec.ts` | One session's re-check list, never committed, covered by the `*_ui` specs |
| `inspect_builder.spec.ts`, `inspect_tools.spec.ts` | One-off probes that printed what they found and asserted nothing |
| `_iiot_drive.spec.ts` | One-off drive script for Industrial IoT with hard-coded ports, covered by `uat_abenix_industrial` |

### CI smoke

The `e2e-smoke` job in `.github/workflows/ci.yml` runs a real browser against a real stack on every push. `scripts/ci-e2e-stack.sh up` starts Postgres and Redis from `docker-compose.yml`, migrates and seeds, then starts the API with uvicorn and the web app with `next start`. Model calls go to a stub provider (`apps/agent-runtime/engine/llm_stub.py`) that answers `Stub reply: <your message>`. It only switches on when both `ABENIX_LLM_STUB=1` and `CI=true` are set, so no secret is needed and a stray flag cannot reach a real deployment. The job runs `e2e/ci_smoke.spec.ts` (sign in, dashboard, build and publish an agent in the builder, chat with it) and the lostness gate for the admin on six routes, using `LOSTNESS_ROUTES` and `LOSTNESS_ROLES`. To run the same thing locally:

```bash
bash scripts/ci-e2e-stack.sh up
USE_K8S=true BASE=http://localhost:3000 STUB_LLM=1 npx playwright test e2e/ci_smoke.spec.ts --project=chromium
bash scripts/ci-e2e-stack.sh down
```

### The 2.5 feature specs

All six below read `BASE` (default `http://localhost:3100`), `API` and `AF_EMAIL` / `AF_PASSWORD`, sign in as the admin, drive the screens, use the API only to read state back and clean up, and run serially with `--workers=1`.

**`uat_rules_to_agents.spec.ts`**. The whole journey from a rule to its callers, through the UI only. Creates a reference set of remote postcodes, builds a surcharge decision with a catch-all rule in the no-code builder, uses Try to hit, miss and report missing facts, keeps two golden tests, runs Check, proposes and publishes. Builds and publishes an agent with `decision_evaluate`, asks it about a remote and a London shipment in chat, and reads the tool call on the Flight Recorder. Builds a pipeline with typed inputs, a `decision_evaluate` step and an `llm_call` step, and runs it from chat. Runs both in the SDK playground and checks the generated Python carries the inputs. Finally checks a reference set in use cannot be deleted. Needs a working LLM credential, the chat and pipeline tests allow up to ten minutes.

**`uat_decisions.spec.ts`**. The decision workspace. The empty page explains itself, the surcharge rule is built with no code, Try decides live and keeps a golden test, Check, propose and publish from the lifecycle bar, a new draft takes typed JSON and a table edit, two authors editing one draft have their changes combined, and a high tier change waits for a second person who signs it on **Approvals**. That last test creates a signer with `POST /api/team/dev-create-member` and a permission set holding `approvals.sign`.

**`uat_governance.spec.ts`**. **Admin -> Risk & Controls** and **Admin -> Permissions**. All four tiers show, a tier policy is edited, validated at the field, saved and reset, a kill switch on `calculator` stops that tool inside a real run and is resumed, tool tiers are searchable, audit verification reports intact, a run records its provenance and tier, a plain user is refused until a permission set grants `killswitch.manage`, and the builder's tier picker shows what a tier requires. The kill switch test builds a one-step pipeline agent that calls the calculator, so it needs no model, and deletes it after.

**`uat_evals.spec.ts`**. A gating suite created from the sidebar blocks publishing before it has run, the assertion builder previews against a sample answer, a run executes every case and shows reasons per case, a past run is saved as a case from the execution page, and after fixing the suite a new run lets the agent publish. The first two tests are deterministic. The others run the agent for real, `EVAL_MODEL` picks the model (default `claude-haiku-4-5-20251001`), and `SKIP_LIVE_LLM=1` skips them.

**`uat_source_watch.spec.ts`**. Source Watch in the sidebar with its empty state, a private address refused while typing, a page added with a test fetch, checked to a baseline and then to no change, a JSON source that changes showing a side-by-side diff, pause with a reason and resume, and the four `source_*` tools present in `/api/tools`. Needs outbound internet from the API. `STABLE_URL` (default `https://example.com`) must not change between checks. `CHANGING_URL` (default `https://httpbin.org/uuid`) must change on every request. A local httpbin works with `SOURCE_WATCH_ALLOW_PRIVATE_TARGETS=1` on the API.

**`uat_tool_config.spec.ts`**. **Admin -> Tool Configuration**, without a hard-coded tool list. The catalogue is generated and complete, a value saved from the screen flips the source to "saved for this tenant" and the badge on `/tools` follows, a tenant value sits above a platform value, an undeclared key gets 404 and a bad URL 400, the Test button reports a rejected GitHub token, a missing required key comes back as one sentence naming the key and the screen, and a viewer gets neither the sidebar entry nor the endpoint. Its `BASE` defaults to 3000.

**`uat_abenix_sdk_playground.spec.ts`**. Part of the deploy gate. Reads `BASE` (default 3000), `API`, `AF_EMAIL` and `AF_PASSWORD`. Checks a probe agent exists (an OOB agent matching `current_time`, `hello` or `echo`, so no LLM cost), that `/sdk-playground` builds its input form from the agent's `input_variables` and `example_prompts`, and that **Run live** executes the agent and shows a status, the execution id and either output or a paused state.

### The wayfinding release gate

Two specs check that a new person never gets lost. They are a release gate: run both against the build you are about to release and do not cut the release while either fails. `scripts/uat.sh` runs both in its default set. To run them alone:

```bash
USE_K8S=true BASE=http://localhost:3000 API=http://localhost:8000   npx playwright test e2e/uat_lostness_gate.spec.ts e2e/uat_first_use_tasks.spec.ts --workers=1 --reporter=list
```

Both default `BASE` to 3100, so pass it when the web app is on 3000. Both invite their own creator and member from **Settings -> Team** and remove them afterwards.

**`uat_lostness_gate.spec.ts`** reads every non-external `href` in `NAV_GROUPS` in `apps/web/src/components/layout/Sidebar.tsx` at run time, so a page is gated the day it lands in the sidebar. It opens each one as admin, creator, member and a viewer (a member with no extra permission sets), at 390 px and 1440 px. Each page must either show a header with a purpose line and a visible primary action (`page-header`, `page-purpose`, `page-primary-action`), or plainly say there is nothing to do or that the role has no access and link onward. It also fails on raw error codes or JSON in visible text, a stack trace, sideways scroll, a purpose line that is too narrow or longer than four lines, a primary action outside the viewport, or a header overlapping the content. All failures are collected into one table under `e2e/uat_lostness_gate/`.

**`uat_first_use_tasks.spec.ts`** times three tasks done only by following what the screen says:

| Task | Limit |
|---|---|
| A new creator starts from **Start here** on the dashboard, builds an agent with a knowledge base and gets a correct answer | 10 minutes |
| A new member finds an agent, asks a follow-up in the same chat and rates an answer with the thumbs | 3 minutes |
| An admin opens **Needs you**, finds what is waiting and clears one approval | 2 minutes |

Every step looks for the on-screen guidance first (Start here steps, NextSteps cards, page primary actions, the Needs you count). If the guidance is missing, the task fails at the step where a person would have been lost. Step times go to `e2e/uat_first_use_tasks/report.json`. The creator task needs a working model credential.

A new page passes both when it uses `PageHeader` with a `purpose` and a `primaryAction` (or an empty or no-access state that links onward), and when the next step after a success is shown with `NextSteps`. See [Add a new UI page](03-add-a-page.md).

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
| A UI page | vitest, a browser spec, the wayfinding release gate | A `uat_*.spec.ts` for the user flow |
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
| `python-test` | after lint | Installs the three apps' requirements, then `check-api-requirements.py`, `pytest tests/unit/`, the agent runtime tests with `SKIP_NETWORK_TESTS=1`, `lint-agent-seeds.py`, `check-readme-images.py`, `check-doc-links.py`, `check-dockerfile-hardening.py`, `check-docker-context.py`, `check-tool-config.py` and `gen-tool-docs.py --check` |
| `web-lint-typecheck-build` | always | ESLint, `tsc --noEmit`, a full Next build, and vitest |
| `e2e-smoke` | after the three above | Boots Postgres and Redis through docker compose and installs the Playwright browsers. It runs no specs, because a full boot needs credentials and a populated tenant |
| `build-images` | push to `main` or a manual run on `main` | Builds and pushes web, api, agent-runtime and worker to ghcr.io, then runs Trivy. The Trivy steps are informational |

The browser UAT does not run in CI. Run `bash scripts/uat.sh` against a deployed cluster, then the [wayfinding release gate](#the-wayfinding-release-gate).

`bash scripts/check-before-push.sh` runs most of this locally: black, ruff, `pytest tests/unit/`, the seed lint, the README image check, the standalone app suites, pip-audit, ESLint, `tsc`, vitest, the Next build, the mermaid check, the docs mirror sync and `check-doc-links.py`. It does not run `check-tool-config.py`, `gen-tool-docs.py --check` or the agent runtime tests, so run those yourself when you touch tools. `--fast` skips the Next build, `--python` and `--web` run one half.

---

## See also

- [00-local-setup](00-local-setup.md), get a stack running first
- [04-debugging](04-debugging.md), when a test fails inexplicably
- [01-add-a-tool](01-add-a-tool.md), where tool tests go
- [10-evals](10-evals.md), testing agent behaviour inside the platform
