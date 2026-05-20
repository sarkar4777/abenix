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

Run nightly via `bash scripts/evals.sh`. Failures don't block deploys (LLM drift is real). they file a GitHub issue.

---

## CI matrix

GitHub Actions runs:

| On | Jobs |
|---|---|
| every push | unit (py + ts) — < 3 min |
| every PR | + integration — < 8 min |
| merge to main | + UAT sanity + image build — < 15 min |
| nightly | + UAT deep + evals — ~30 min |
| weekly | + UAT industrial + perf benchmarks — ~60 min |

The CI runners are GitHub-hosted x86 large for unit. self-hosted (an AKS namespace) for UAT.

---

## Performance benchmarks

`bench/` has scripts that exercise:
- 100 concurrent agent executions
- 500 KB document uploads
- 10k pipeline-step throughput

Reported metrics: p50/p95/p99 latency, sustained rps, peak memory. Compared to the prior release. regressions > 20% file an issue.

---

## See also

- [00-local-setup](00-local-setup.md) — get a local stack running first
- [04-debugging](04-debugging.md) — when a test fails inexplicably
- [01-add-a-tool](01-add-a-tool.md) — example of where tests go
