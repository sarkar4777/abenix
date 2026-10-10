# Finding your way around

A map of the repository for someone who has just cloned it. The other how-to
pages tell you how to add a thing. This one tells you where that thing lives
and which of its neighbours will notice. For what the product parts are, read
[How Abenix fits together](../00-how-abenix-fits-together.md) first.

---

## The four services

The core of the platform runs in four processes.

| Path | What it is | Runs as |
|---|---|---|
| `apps/api` | FastAPI. Auth, CRUD, SSE, every REST route | `abenix-api` |
| `apps/web` | Next.js app router. The console you look at | `abenix-web` |
| `apps/agent-runtime` | The agent loop, the pipeline executor, the tools | `abenix-agent-runtime-*` |
| `apps/worker` | Celery. Document ingest, sweepers, scheduled work | `abenix-worker` |

Two smaller pieces sit beside them. `apps/code-runner` holds the warm runners
for code assets, one Deployment per tenant and asset version, called over NATS.
`apps/edge-runtime` is the single-file pod an edge gateway runs to pull `.agent`
bundles, with C and Rust ports in `apps/edge-runtime-c` and `apps/edge-runtime-rust`.

The runtime is the interesting one. An agent run is a loop over a tool
registry, and a pipeline is a DAG whose nodes are tool calls, so most
behaviour questions end up in `apps/agent-runtime/engine/`.

## The shared packages

| Path | What it is |
|---|---|
| `packages/db` | SQLAlchemy models, alembic revisions, and every seed |
| `packages/sdk/python` | The canonical Python SDK |
| `packages/sdk/js` | `@abenix/sdk`, the JavaScript and TypeScript SDK |
| `packages/sdk/react` | `@abenix/react`, an embeddable agent chat component |
| `packages/agent-sdk` | A synced copy of the Python SDK packaged as `abenix-sdk` |
| `packages/mcp-servers` | MCP servers for BigQuery, Exasol, migration and SQL transform |
| `packages/shared` | `@abenix/shared`, types shared between web and the rest |

## The example applications

Seven of them sit at the repository root rather than under `apps/`, because
they are consumers of the platform rather than parts of it. `contractiq`,
`resolveai`, `wingman`, `industrial-iot`, `mideasttourism` and `pharmavigil`
each have their own `api/`, `web/` and `k8s/`. `claimsiq` is a Gradle build with
`app/` (backend plus `frontend/`), its own Java `sdk/` and `k8s/`.

They talk to the platform through the SDK and never by raw HTTP. If you find
yourself writing `httpx.post(f"{ABENIX_URL}/api/...")` inside one of them, the
SDK is missing a method and that is the thing to add.

---

## Where a change goes

**A new tool an agent can call.** `apps/agent-runtime/engine/tools/`, then
register it. See [Add a new tool](01-add-a-tool.md). If it needs a key,
declare the key as a `ConfigField` on the class and it shows up under
Admin -> Tool Configuration by itself, see [Tool configuration](08-tool-configuration.md).

**A new agent, or a change to one.** `packages/db/seeds/agents/*.yaml`. These
are data, not code. The seeder upserts by slug, so editing the YAML and
re-seeding is the whole workflow.

**Something an agent should be able to look up.** `packages/db/seeds/kb/*.yaml`.
The seeder chunks and embeds the documents, so a collection is searchable as
soon as the deploy finishes.

**A REST route.** `apps/api/app/routers/`. Responses go through the `success`
and `error` helpers so every payload has the same envelope.

**A page.** `apps/web/src/app/(app)/` for anything behind sign-in. The sidebar
entry and its gate go in `apps/web/src/components/layout/Sidebar.tsx`, and a new
capability goes in `apps/api/app/core/capabilities.py`. See [Add a new UI page](03-add-a-page.md)
and the [page catalogue](../05-ui/03-page-catalogue.md) for what already exists.

**Anything about how a pod is deployed.** `infra/helm/abenix/`.

**Words a user reads.** The page's own `PageHeader` purpose and steps, a topic in `apps/web/src/app/(app)/help/page.tsx`, and the plain glossary in [How Abenix fits together](../00-how-abenix-fits-together.md).

**A developer doc.** A file under `docs/`, an entry in `docs/manifest.json`, then `bash scripts/sync-dev-docs.sh` to refresh the in-app copy. `python scripts/check-doc-links.py` fails CI on a broken link or a doc missing from the manifest.

---

## Four things that surprise people

**There are two sets of Dockerfiles.** `apps/*/Dockerfile` is what CI builds,
so it is the set Trivy and the code-scanning alerts look at. `docker/Dockerfile.*`
is what `scripts/deploy.sh` and `scripts/deploy-azure.sh` build, so it is the
set that actually serves traffic. Changing one does not change the other.

This bit once already. A round of CVE patching went into the CI set, CI went
green, and every running image kept every finding. `scripts/check-dockerfile-hardening.py`
now runs in CI and compares them, so the next time they diverge on base pinning
or package upgrades it says so.

**The Python SDK is vendored seven times.** Each Python example app carries its
own copy under `api/sdk/` so it can be built without the monorepo, and
`packages/agent-sdk` holds one more. `packages/sdk/python` is canonical and
`scripts/sync-sdks.sh --check` fails if a copy has drifted. Edit the canonical
one and run the sync.

**The schema you get is not the alembic graph.** Tables come from
`Base.metadata.create_all` at API startup, plus a block of idempotent DDL
beside it in `apps/api/app/main.py`. Alembic revisions exist and are not all
reachable from one head, so a table that lives only in a revision may never
have been created. Anything the running system needs belongs in the boot path.

**An agent that declares `knowledge_search` needs a collection.** The tool is
only registered when the agent has at least one grant. Without one the model is
told in its prompt that it can search, finds no such tool, and writes out the
call it wanted to make as ordinary text. `scripts/lint-agent-seeds.py` fails
the build on that combination, and it runs in CI.

---

## Before you push

```bash
bash scripts/check-before-push.sh
```

It runs what CI runs, in the same order, with the same pinned formatter and
linter versions. Green here is green there.

For anything that touches a running system, `bash scripts/uat.sh` drives the
whole product through a browser against your cluster. It takes about fifteen
minutes and it is the gate that decides whether a deploy is good.

---

## See also

- [Local setup](00-local-setup.md) for getting a cluster up
- [Debugging](04-debugging.md) for when a run does not do what you expected
- [Testing](05-testing.md) for what to write and where it goes
- [Architecture overview](../01-architecture/00-overview.md) for how the
  pieces fit rather than where they live
