# Contributing to Abenix

Thanks for your interest. Abenix is a young project — anything you contribute moves the needle.

## Quick start

1. Fork and clone the repo.
2. `bash scripts/dev-local.sh` — boots Postgres, Redis, the API, the web app, and an agent runtime locally.
3. Open http://localhost:3000 and sign in with `admin@abenix.dev` / `Admin123456`.
4. Make your change, add tests, run `bash scripts/run-e2e.sh` to verify nothing regressed.
5. Open a PR.

## What we'd love help with

- **New tools** — a tool is a single Python file under `apps/agent-runtime/engine/tools/`. See existing tools for the contract; one-line examples land in the registry automatically.
- **Atlas starter ontologies** — drop a new kit into `ATLAS_STARTERS` in `apps/api/app/routers/atlas.py` (FIBO/FIX/EMIR are there as a model).
- **Provider integrations** — add a new LLM provider by mirroring `_run_anthropic` / `_run_gemini` / `_run_openai` in `bpm_analyzer.py`.
- **Connectors** — Slack, Linear, Salesforce, etc. — see `apps/api/app/routers/triggers.py`.
- **Docs and screenshots** — drop captures into `docs/screenshots/` matching the manifest there.

## Code style

- Python: black + ruff (configured in `pyproject.toml`). 88-char lines.
- TypeScript: the existing prettier config; small files, named exports.
- Tests: pytest (backend) and Playwright (e2e). Add at least one happy-path test for any new endpoint.

## Reviewing other PRs

The fastest way to learn the codebase is to review someone else's PR. We tag good-first-review issues for newcomers.

## Code of Conduct

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security issues

Don't open a public issue. See [SECURITY.md](SECURITY.md).
