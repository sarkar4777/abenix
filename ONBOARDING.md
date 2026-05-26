# Onboarding — 30 minutes to a working local Abenix

This is the path to "I can log in, run an agent, and ship a one-line change". It assumes you have git, docker, node 20+, and python 3.12 already installed.

## 1. Fork and clone (2 min)

```bash
git clone git@github.com:<your-username>/abenix.git
cd abenix
```

## 2. Bring up the data plane (3 min)

Postgres and Redis are the only services Abenix can't run without. Boot them with docker-compose:

```bash
docker compose up -d postgres redis
```

Verify:

```bash
docker compose ps
# postgres should be "healthy", redis "healthy"
```

## 3. Install language toolchains (5 min)

```bash
# Node toolchain (web + e2e)
npm ci

# Python toolchain (api + agent-runtime + worker)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e apps/api -e apps/agent-runtime -e apps/worker -e packages/db
pip install black ruff pytest pytest-asyncio
```

## 4. Set the one required key (1 min)

The platform is multi-LLM but Anthropic is the default. Anything you'll demo needs at least this:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # add to ~/.bashrc / ~/.zshrc to persist
```

Optional but useful:
- `OPENAI_API_KEY` — moderation gate + GPT-* models
- `TAVILY_API_KEY` — `tavily_search` tool
- `PINECONE_API_KEY` — Pinecone-backed vector recall

The full catalogue is in [the Integrations page docs](docs/integrations.md) (also visible in-product at `/settings/integrations` once logged in).

## 5. Run migrations + seed (3 min)

```bash
cd packages/db
alembic upgrade head
cd ../..

python scripts/seed-standalone-keys.sh    # provisions demo admin@abenix.dev / Admin123456
```

## 6. Boot the platform (5 min)

In separate terminals (or use the helper):

```bash
# Terminal A — API
cd apps/api && uvicorn app.main:app --reload --port 8000

# Terminal B — agent runtime (default pool)
cd apps/agent-runtime && python -m engine.consumer --pool default

# Terminal C — web
cd apps/web && npm run dev
```

Or in one shot:

```bash
bash scripts/dev-local.sh
```

## 7. Sign in (1 min)

Open <http://localhost:3000>. Click "Admin Demo" or sign in with:

- **email**: `admin@abenix.dev`
- **password**: `Admin123456`

You should land on `/dashboard` with a populated sidebar.

## 8. Smoke a real flow (5 min)

1. Sidebar → **Agents** → pick any seeded agent → **Run**.
2. Watch the live trace appear in `/executions/live`.
3. Sidebar → **Settings → DLP** → set mode to "mask" → save → reload. Value persists. (This is the JSONB regression we caught in v1.10.0.)
4. Sidebar → **Settings → Integrations** → click "Setup" on any provider. Copy the kubectl / .env snippet.

## 9. Run the gate (3 min)

Before you push anything, run:

```bash
bash scripts/check-before-push.sh
```

This runs the same checks CI will (black, ruff, pytest, eslint, tsc, web build). If it's green locally, CI will be green.

To skip the slow web build when iterating fast:

```bash
bash scripts/check-before-push.sh --fast
```

## 10. Make a tiny first change (3 min)

Pick something small to land:

- Fix a typo in a docstring or markdown file.
- Add a missing test case.
- Improve an error message.

Open a PR. The template will ask for a summary, a test plan, and a screenshot if your change is user-visible.

## Common stumbles

| Symptom | Fix |
|---|---|
| `psycopg2.OperationalError` on api startup | postgres isn't healthy yet — `docker compose ps` |
| `redis.exceptions.ConnectionError` | same — `docker compose up -d redis` |
| Web shows "Connection failed" on login | API isn't on `:8000`. Check terminal A |
| `alembic upgrade head` fails on duplicate column | a previous local schema is out of sync — `docker compose down -v` then start over |
| `ANTHROPIC_API_KEY missing` in agent run | the agent runtime needs it too — `export` before running `python -m engine.consumer` |
| Tests pass locally but CI is red | versions differ — `pip install black==24.8.0 ruff==0.6.9` to match CI |

## Optional: SSO local test

To test Google sign-in locally:

1. Create an OAuth client at <https://console.cloud.google.com/apis/credentials>. Authorized redirect URI: `http://localhost:8000/api/auth/oidc/google/callback`.
2. Export:
   ```bash
   export GOOGLE_OIDC_CLIENT_ID=...
   export GOOGLE_OIDC_CLIENT_SECRET=...
   export PUBLIC_API_BASE_URL=http://localhost:8000
   export WEB_BASE_URL=http://localhost:3000
   ```
3. Restart the API. The login page now shows a "Google" button.
4. GitHub and Microsoft follow the same pattern — see [docs/sso.md](docs/sso.md) for end-to-end provider setup.

## What next

- Browse [ARCHITECTURE.md](ARCHITECTURE.md) for the full map.
- Look at the latest 5 merged PRs to see what conventions land.
- The maintainer is `sarkar4777`. Ping in your PR if you're blocked.
