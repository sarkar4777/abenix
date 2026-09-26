# Testing — unit, integration, E2E, UAT

> Four layers. Each catches different bugs. CI runs them in order. you only need to run the ones relevant to your change.

---

## Layer 1 — Unit tests (pytest + vitest)

Per-file, mocked dependencies. The fastest layer.

### Python (backend + tools)

```bash
cd apps/api && pytest -v
cd apps/agent-runtime && pytest -v
cd apps/worker && pytest -v
```

Per-tool example: see `apps/agent-runtime/tests/tools/test_*.py`. Each tool gets:
- Happy path test
- Each error path
- Boundary inputs (empty, too long, wrong type)

### TypeScript (web)

```bash
cd apps/web && npm test
```

Vitest + Testing Library. Run individual components in isolation.

---

## Layer 2 — Integration tests (pytest against a real DB)

A real Postgres in a Docker container. Tests the SQL + ORM layer + auth + RBAC.

```bash
# Spin up the test DB
docker compose -f apps/api/tests/docker-compose.test.yml up -d

# Run integration tests
cd apps/api && pytest tests/integration/ -v

# Teardown
docker compose -f apps/api/tests/docker-compose.test.yml down -v
```

These tests are 2-10x slower than unit but catch:
- Migration order bugs
- N+1 queries (we measure query counts)
- Tenant-filter bugs (does this query leak to another tenant?)
- Index gaps (slow queries fail a latency budget)

---

## Layer 3 — E2E tests (Playwright)

Real browser, real backend, real DB. The most expensive layer. reserve for user-facing flows.

```bash
# Locally — assumes deploy.sh local is running
npx playwright test e2e/uat_audit_fixes.spec.ts --reporter=list

# Against the deployed cluster (with port-forwards on :3000 and :8000)
USE_K8S=true BASE=http://localhost:3000 API=http://localhost:8000 \
  AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
  npx playwright test e2e/uat_audit_fixes.spec.ts
```

### Self-fixturing pattern

The well-written specs create + tear down their own fixtures via the API, so they run on a fresh cluster without seeding. Example from `uat_audit_fixes.spec.ts`:

```ts
test('KB dropzone advertises multi-file (self-fixturing)', async ({ page }) => {
  const token = await getToken();
  const kb = await apiPost<{ id: string }>('/api/knowledge-bases', {
    name: `e2e-kb-${Date.now()}`, description: 'fixture',
    chunk_size: 1000, chunk_overlap: 200,
  }, token);
  try {
    await login(page);
    await page.goto(`${BASE}/knowledge?id=${kb.id}`);
    await expect(page.getByTestId('kb-dropzone-input')).toHaveAttribute('multiple', '');
  } finally {
    await apiDelete(`/api/knowledge-bases/${kb.id}`, token);
  }
});
```

Pattern: create → test → finally-delete. Fixtures are namespaced with timestamps to avoid collisions.

### data-testid convention

UI elements that tests look up have a `data-testid` attribute. Naming:
- `<feature>-<action>` — e.g. `ml-use-in-agent`, `code-share`, `kb-dropzone-input`.
- `<feature>-<state>` — e.g. `validation-chip-error`, `approval-expiry`.

Keep them stable across releases. tests grep by these strings.

---

## Layer 4 — UAT (canonical user-acceptance suite)

The deploy gate. 111 tests in three buckets:

| Bucket | Tests | Runs against | Time |
|---|---|---|---|
| sanity | 61 | local minikube via deploy.sh | ~3 min |
| deep | 31 | local minikube via deploy.sh | ~8 min |
| industrial | 19 | industrial-iot specifically | ~5 min |

Run:
```bash
bash scripts/uat.sh sanity              # block deploy on failure
bash scripts/uat.sh deep                # nightly
bash scripts/uat.sh industrial          # nightly when Industrial-IoT changes
bash scripts/uat.sh all                 # everything
```

Each test is one curl + assertion or one Playwright spec. The suite covers:
- Login + auth + RBAC
- CRUD for every resource
- Agent execution for every shipped agent
- Pipeline execution for every shipped pipeline
- KB upload + retrieval
- ML model upload + deploy + predict
- Cross-app actAs delegation
- Approval flow

The `scripts/uat.sh` runner uses an in-cluster MCP fixture (see [02-runtime/03-mcp](../02-runtime/03-mcp.md#built-in-mcp-server-fixtures)) so MCP-dependent tests can run without external services.

---

## When to write what test

| You're changing | Run | Add |
|---|---|---|
| A tool's logic | Unit (Python) | Unit + integration if it touches DB |
| A REST endpoint | Integration | Integration covering the new path |
| A UI component | TS unit | TS unit + E2E if user-facing |
| An agent's prompt | Manual via `/agents → Test` | An eval — see "Evals" below |
| Deploy/build script | Manual via `deploy.sh local` | Add to UAT sanity if it gates a release |
| A pipeline node type | Unit + integration | E2E for the builder UI |
| The SDK | Unit | Run the entire UAT suite — SDK changes ripple |

---

## Evals (LLM correctness over time)

Different beast from unit tests — LLM behaviour drifts. `evals/` directory has YAML cases:

```yaml
# evals/wingman/mispricing.yaml
agent: wingman-mispricing-extractor
cases:
  - name: "USGC-NWE Q1 2026 closed arb"
    input: {corridor: {id: "USGC-NWE", ...}}
    assertions:
      - "$.output.observed_spread_usd_mt | should be_between(-100, -20)"
      - "$.output.verdict | should be 'dislocated'"
```

> **Not built yet.** There is no `evals/` directory and no `scripts/evals.sh`
> in the tree. The shape above is the intended design, kept here so whoever
> picks it up does not have to reinvent it. Today, prompt changes are checked by
> hand through `/agents -> Test` and by the UAT specs.

---

## CI matrix

`.github/workflows/ci.yml` triggers on push and pull request against `main`.
All jobs run on GitHub-hosted `ubuntu-latest`.

| Job | Runs | What it does |
|---|---|---|
| `python-lint` | always | `black --check`, `ruff`, then `pip-audit` against `apps/api/requirements.txt` with `.pip-audit-ignore` applied. A CVE without a whitelist entry fails the build. |
| `python-test` | after lint | `pytest tests/unit/` with the three apps' requirement files installed. |
| `web-lint-typecheck-build` | always | ESLint, `tsc --noEmit`, and a full Next build. |
| `e2e-smoke` | after the three above | Boots Postgres and Redis through docker-compose and installs the Playwright browsers. The API and web are deliberately not booted, because a full boot needs credentials and a populated tenant. |
| `build-images` | push to `main` only | Builds and pushes the four service images to ghcr.io, then runs Trivy. Both Trivy steps are informational and do not fail the build. |

There is no nightly or weekly schedule, and the browser UAT does not run in CI.
Run it yourself against a deployed cluster with `bash scripts/uat.sh`.

Before pushing, `bash scripts/check-before-push.sh` runs the same gates locally.
It is considerably faster than waiting for CI to go red.

---

## Performance benchmarks

> **Not built yet.** There is no `bench/` directory. Load behaviour is
> currently exercised through the Load Playground page and the numbers recorded
> in [06-deployment/load-test-baseline](../06-deployment/load-test-baseline.md).

---

## See also

- [00-local-setup](00-local-setup.md) — get a local stack running first
- [04-debugging](04-debugging.md) — when a test fails inexplicably
- [01-add-a-tool](01-add-a-tool.md) — example of where tests go
