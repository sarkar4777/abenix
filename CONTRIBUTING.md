# Contributing to Abenix

Thanks for your interest. Abenix is a young project, anything you contribute moves the needle.

## TL;DR

1. **Fork and clone.**
2. `bash scripts/dev-local.sh` boots Postgres, Redis, API, web, agent-runtime locally. If you'd rather have a guided 30-minute path, read [ONBOARDING.md](ONBOARDING.md).
3. Make your change, add a test (`tests/unit/` for backend, `e2e/` for browser flows).
4. **Before pushing**: `bash scripts/check-before-push.sh` (runs the same gates CI runs). Don't push red.
5. Open a PR. The PR template will prompt you for what reviewers need.

## Where to land — pick the smallest first PR

| You want to add | Land here |
|---|---|
| A new tool | `apps/agent-runtime/engine/tools/<your_tool>.py` + register in `engine/tools/__init__.py` |
| A new LLM provider | mirror `_run_anthropic` in [apps/api/app/routers/bpm_analyzer.py](apps/api/app/routers/bpm_analyzer.py) |
| A new API endpoint | `apps/api/app/routers/<feature>.py`, register in `apps/api/app/main.py`, return `success()` / `error()` |
| A new page in the SPA | `apps/web/src/app/(app)/<feature>/page.tsx` |
| A new Atlas starter ontology | drop a kit into `ATLAS_STARTERS` in `apps/api/app/routers/atlas.py` (FIBO/FIX/EMIR are there as a model) |
| Connectors (Slack/Linear/Salesforce) | `apps/api/app/routers/triggers.py` |
| A new standalone app | copy `wingman/` as the cleanest reference |

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the monorepo map.

## Local setup

The minimum stack is Postgres + Redis + an `ANTHROPIC_API_KEY`. The full helper is `scripts/dev-local.sh`. On Windows use WSL or Git Bash, paths inside the script are POSIX.

```bash
# 1. dependencies
docker compose up -d postgres redis           # data plane
npm ci                                         # web + tooling
pip install -e apps/api -e apps/agent-runtime -e apps/worker -e packages/db

# 2. seed
ANTHROPIC_API_KEY=sk-ant-... bash scripts/dev-local.sh

# 3. open
http://localhost:3000   # admin@abenix.dev / Admin123456
```

For SSO testing, set the matching env vars (see [docs/sso.md](docs/sso.md) for per-provider setup and [ONBOARDING.md](ONBOARDING.md#optional-sso-local-test) for the local-dev recipe).

## The contribution loop

1. Create a branch from `main`. Branch names: `feat/<short>`, `fix/<short>`, `docs/<short>`, `refactor/<short>`.
2. Make the smallest change that completes your goal. Don't bundle unrelated cleanups.
3. Add or update tests in the same PR. Backend → `tests/unit/`. Browser flow → `e2e/uat_*.spec.ts`.
4. Run the local gate:
   ```bash
   bash scripts/check-before-push.sh
   ```
   This runs black, ruff, pytest, eslint, tsc, and the web build. If you only touched Python or only touched web, pass `--python` or `--web` to skip the other half.
5. Open the PR. The template will ask you to summarize the change and list a test plan.
6. CI runs the same gates plus a Trivy scan on built images. Don't bypass red CI — fix the root cause or explain why the test is wrong.

## Commit style

- One topic per commit. Bug fixes get their own commit, even if you spotted them while doing something else.
- Subject line ≤ 72 chars, imperative mood (`fix: webhook accepts empty events`), no period.
- Body explains the why, not the what — the diff shows what.
- **No AI / co-author attribution.** Don't add `Co-Authored-By: Claude` or similar. This repo gets public-published.

## Code style

- **Python**: black + ruff (config in `ruff.toml`). 88-char lines (a few exemptions in `ruff.toml`). Type hints on public functions.
- **TypeScript**: existing prettier + eslint config. Named exports for components. Small files.
- **Comments**: terse single-line, only where the why is non-obvious. Don't narrate what the code does.
- **Markdown**: write like a developer typing notes for another developer. No AI-flourish words. No semicolons in prose.

## Tests

- `tests/unit/` — pure Python, no live services. Failing here blocks merge.
- `e2e/uat_*.spec.ts` — Playwright. Three headline files cover settings, critical paths, and UI journeys. Add a test in the right file or add a new `uat_*.spec.ts` per surface.
- Don't mock the database in tests that exercise persistence. Use a real local Postgres.

## Reviewing other PRs

Reviewing someone else's PR is the fastest way to learn the codebase. We label `good-first-review` for newcomers.

When you review, look for:

- Does the PR description match the diff?
- Is there at least one test that fails without this change?
- Does it introduce a feature flag or backwards-compat shim that the change doesn't actually need?
- Could a reasonable reader of just the diff understand the change a year from now?

## Security

Don't open a public issue for a security report. See [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
