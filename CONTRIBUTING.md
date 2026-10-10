# Contributing to Abenix

Thanks for your interest. Abenix is a young project, anything you contribute moves the needle.

## Short version

1. **Fork and clone.**
2. `cp .env.example .env`, set `ANTHROPIC_API_KEY`, then `bash scripts/dev-local.sh`. It boots the data services in Docker, migrates and seeds the database, and starts the API, the web app, the worker and the agent runtime. For a guided 30-minute path read [ONBOARDING.md](ONBOARDING.md).
3. Make your change and add a test (`tests/unit/` for backend, `e2e/` for browser flows).
4. **Before pushing**: `bash scripts/check-before-push.sh`. Don't push red.
5. Open a PR. The PR template prompts you for what reviewers need.

## Where to land, pick the smallest first PR

| You want to add | Land here |
|---|---|
| A new tool | `apps/agent-runtime/engine/tools/<your_tool>.py`, registered in `_ensure_tool_classes()` in `apps/agent-runtime/engine/agent_executor.py`. See [docs/08-howto/01-add-a-tool.md](docs/08-howto/01-add-a-tool.md) |
| A new agent | `packages/db/seeds/agents/<name>.yaml`. See [docs/08-howto/02-add-an-agent.md](docs/08-howto/02-add-an-agent.md) |
| A new LLM provider | an `LLMProvider` subclass in [apps/agent-runtime/engine/llm_router.py](apps/agent-runtime/engine/llm_router.py), with its key in `PROVIDER_CONFIG_FIELDS` in `engine/provider_credentials.py` |
| A new API endpoint | `apps/api/app/routers/<feature>.py`, registered in `apps/api/app/main.py`, returning `success()` / `error()` |
| A new capability | `CATALOG` and `ROLE_DEFAULTS` in `apps/api/app/core/capabilities.py`, checked with `require_capability("<key>")` |
| A new platform event | `CATALOG` in `apps/api/app/services/events.py`, written with `emit()` in the same transaction as the change |
| A new evaluation assertion | `TYPES` and the check in `apps/api/app/services/eval_assertions.py` |
| A new page in the web app | `apps/web/src/app/(app)/<feature>/page.tsx` with a `PageHeader`, a sidebar entry in `Sidebar.tsx` and a Help topic. See [docs/08-howto/03-add-a-page.md](docs/08-howto/03-add-a-page.md) |
| A new doc | a file under `docs/`, an entry in `docs/manifest.json`, then `bash scripts/sync-dev-docs.sh`. `python scripts/check-doc-links.py` fails on an unlisted doc or a broken link |
| A new Atlas starter ontology | a kit in `ATLAS_STARTERS` in `apps/api/app/routers/atlas.py` (FIBO, FIX and EMIR are there as models) |
| A connector preset (CMMS, HRIS, telematics and the like) | `packages/db/seeds/connector_presets/<name>.yaml`, served by `apps/api/app/routers/connectors.py` |
| A new standalone app | copy `wingman/` as the cleanest reference |

Read [How Abenix fits together](docs/00-how-abenix-fits-together.md) for what the parts are and [ARCHITECTURE.md](ARCHITECTURE.md) for the monorepo map.

## Local setup

The minimum is Docker, Node 20, Python 3.12 and an `ANTHROPIC_API_KEY`. On Windows use WSL or Git Bash, the scripts are bash.

```bash
cp .env.example .env              # set ANTHROPIC_API_KEY
bash scripts/dev-local.sh         # APPS=none to skip the standalone apps
# open http://localhost:3000      # admin@abenix.dev / Admin123456
```

`dev-local.sh` installs `requirements.txt` and the npm workspaces when they are missing. `--status`, `--stop` and `--restart` manage what it started.

For SSO testing, set the matching env vars (see [docs/09-reference/05-sso.md](docs/09-reference/05-sso.md) for per-provider setup and [ONBOARDING.md](ONBOARDING.md#optional-sso-local-test) for the local recipe).

## The contribution loop

1. Create a branch from `main`. Branch names: `feat/<short>`, `fix/<short>`, `docs/<short>`, `refactor/<short>`.
2. Make the smallest change that completes your goal. Don't bundle unrelated cleanups.
3. Add or update tests in the same PR. Backend goes in `tests/unit/`, browser flows in `e2e/uat_*.spec.ts`.
4. Run the local gate:
   ```bash
   bash scripts/check-before-push.sh
   ```
   It runs black, ruff, `pytest tests/unit/`, the agent seed lint, the README image check, the standalone app tests, pip-audit, ESLint, `tsc`, vitest, the Next build, the docs sync and the doc link check. Pass `--python` or `--web` to run one half, `--fast` to skip the Next build. If you touched tools, also run `python scripts/check-tool-config.py` and `python scripts/gen-tool-docs.py --check`, which CI runs and this script does not.
5. Open the PR. The template asks you to summarize the change and list a test plan.
6. CI runs the lint, unit and web jobs on every PR. Images are built and scanned with Trivy on pushes to `main`. Don't bypass red CI. Fix the root cause or explain why the test is wrong.

## Commit style

- One topic per commit. Bug fixes get their own commit, even if you spotted them while doing something else.
- Short subject line, imperative mood (`fix: webhook accepts empty events`), no period. A few lines of body at most, explaining the why.
- **No AI or co-author attribution** in commits, PRs, code or docs. This repo gets public-published.

## Code style

- **Python**: black (88 columns) and ruff, config in `ruff.toml`. `E402` and `E501` are ignored on purpose. Type hints on public functions.
- **TypeScript**: the repo's `.prettierrc` and `apps/web/eslint.config.mjs`. Named exports for components. Small files.
- **Comments**: terse single-line, only where the why is non-obvious. Don't narrate what the code does.
- **Markdown**: write like a developer typing notes for another developer. No AI-flourish words. No semicolons in prose.
- **Docs follow the change**: a new feature gets a user-facing Help topic (`apps/web/src/app/(app)/help/page.tsx`), a developer doc under `docs/`, and a `PageHeader` whose "How this works" steps match what the page really does.

## Tests

- `tests/unit/`, pure Python, no live services. Failing here blocks merge.
- `apps/agent-runtime/tests/`, runtime and tool tests, also run in CI.
- `e2e/uat_*.spec.ts`, Playwright. `scripts/uat.sh` runs the deploy gate against a cluster. Add a test to the spec for your surface, or a new `uat_*.spec.ts`.
- The first-use tasks and the lostness gate are a release gate. `e2e/uat_first_use_tasks.spec.ts` times a new creator, member and admin doing their first job by following only what the screen says. `e2e/uat_lostness_gate.spec.ts` opens every sidebar page as every role at phone and desktop width and fails a page with no purpose line, no next action or a raw error. A PR that adds or changes a page, the sidebar, Start here or Needs you must keep both green. `scripts/uat.sh` does not run them yet, so run them by hand, see [the wayfinding release gate](docs/08-howto/05-testing.md#the-wayfinding-release-gate).
- Don't mock the database in tests that exercise persistence. Use a real local Postgres.

More in [docs/08-howto/05-testing.md](docs/08-howto/05-testing.md).

## Reviewing other PRs

Reviewing someone else's PR is the fastest way to learn the codebase.

When you review, look for:

- Does the PR description match the diff?
- Is there at least one test that fails without this change?
- Does it introduce a feature flag or backwards-compat shim that the change doesn't actually need?
- Could a reasonable reader of just the diff understand the change a year from now?

## Security

Don't open a public issue for a security report. See [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
