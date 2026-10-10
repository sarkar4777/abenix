# Onboarding, 30 minutes to a working local Abenix

This is the path to "I can log in, run an agent, and ship a one-line change". It assumes you have git, Docker, Node 20+ and Python 3.12 installed. On Windows use Git Bash or WSL, the scripts are bash.

## 1. Fork and clone (2 min)

```bash
git clone git@github.com:<your-username>/abenix.git
cd abenix
```

## 2. Set an LLM key (1 min)

```bash
cp .env.example .env
```

Open `.env` and set at least `ANTHROPIC_API_KEY`. The platform is multi-LLM but Anthropic is the default. `scripts/dev-local.sh` reads `.env` on every start, so the API, the agent runtime and the worker all see it.

Optional but useful:
- `OPENAI_API_KEY`, for the moderation gate, GPT models and embeddings
- `TAVILY_API_KEY`, for `tavily_search`
- `PINECONE_API_KEY`, for Pinecone-backed vector recall

Tool keys do not have to live in `.env`. Once you are signed in, an admin can paste them under **Admin -> Tool Configuration**, which lists every key a built-in tool reads, see [docs/08-howto/08-tool-configuration.md](docs/08-howto/08-tool-configuration.md). `/settings/integrations` shows the same list to everyone.

### Production-only secret: at-rest encryption KEK

When you take this to production, also set `ABENIX_DATA_KEY_KEK_BASE64`, a 32-byte base64 key that wraps the per-tenant keys for AES-256-GCM encryption of sensitive persona and memory fields and of saved tool credentials. Local dev runs fine without it. Values are then stored as entered, and nothing warns you, so set it before real data goes in. Setup is in [docs/08-howto/06-encryption-setup.md](docs/08-howto/06-encryption-setup.md).

## 3. Boot everything (10 min the first time)

```bash
bash scripts/dev-local.sh
```

It asks which standalone apps to start, then:

1. stops anything it left running, and any `kubectl port-forward` that would shadow local ports,
2. runs `docker compose up -d`: Postgres, Redis, NATS, Neo4j, TimescaleDB, MinIO, Mosquitto, pgAdmin and the three edge runtimes,
3. installs npm packages and `pip install -r requirements.txt` when they are missing,
4. runs `packages/db/bootstrap.py` and `alembic upgrade heads`, then checks the schema,
5. seeds the shipped agents, the default accounts, subject policies, portfolio schemas and sample ML models,
6. starts the API on 8000, the web app on 3000, a Celery worker, the NATS consumer for the `default` agent pool, and the apps you picked.

`APPS=none bash scripts/dev-local.sh` skips the prompt and starts the core platform only. `--status` prints what is up, `--stop` stops it all, `--restart` does both. Logs are in `.local-logs/`.

If you would rather run the whole thing on a local Kubernetes cluster, `bash scripts/deploy.sh local` is the other path, see [docs/08-howto/00-local-setup.md](docs/08-howto/00-local-setup.md).

## 4. Sign in (1 min)

Open <http://localhost:3000>. Click **Admin Demo**, or sign in with:

- **email**: `admin@abenix.dev`
- **password**: `Admin123456`

`demo@abenix.dev` / `Demo123456` is a second seeded account. You land on **Home** (`/dashboard`). Its **Start here** card is a short checklist for your role, and every tick comes from real data.

The sidebar starts in **Essentials**, a short list: Needs you, Home, Agents, AI Chat, Knowledge, Monitor. Creators and admins also get Agent Builder, Autonomy and Improvements, and admins an Admin entry. **Show all tools** at the bottom opens the full grouped list (Build, Run & Test, Monitor, Marketplace, Admin, Workspace). Ctrl+K (Cmd+K on a Mac) finds any page, agent or knowledge base. [How Abenix fits together](docs/00-how-abenix-fits-together.md) explains what each part is for.

## 5. Smoke a real flow (5 min)

1. **Agents** -> open a seeded agent and send it a message in chat. Give the answer a thumbs up or down.
2. **Monitor** (`/executions`) -> open the run to see the Flight Recorder: every model call, tool call and what the run used.
3. **Show all tools** -> **Build -> Decisions** -> start from the surcharge example, use **Try it**, and see the rule that applied.
4. **Admin -> Risk & Controls** shows the four risk tiers and the kill switches. **Run & Test -> Evaluations** and **Build -> Source Watch** sit in the same list.
5. **Autonomy** -> **Try it with the sample plant** shows an agent earning the right to act on its own. **Improvements** has a sample agent with a planted mistake to fix under control.
6. **Needs you** collects everything waiting on you: approvals, proposed fixes, watching reviews, held content and new alerts.

## 6. Run the gate (3 min)

Before you push anything:

```bash
bash scripts/check-before-push.sh
```

It runs black, ruff, `pytest tests/unit/`, the agent seed lint, the README image check, the standalone app tests, pip-audit, ESLint, `tsc`, vitest, the Next build, the docs sync and the doc link check. CI also runs `scripts/check-tool-config.py`, `scripts/gen-tool-docs.py --check`, `scripts/check-docker-context.py` and the agent runtime tests, so run those too when you touch tools or Dockerfiles.

```bash
bash scripts/check-before-push.sh --fast     # skip the Next build
bash scripts/check-before-push.sh --python   # Python half only
```

## 7. Make a tiny first change (3 min)

Pick something small to land:

- Fix a typo in a docstring or a doc.
- Add a missing test case.
- Improve an error message.

Open a PR. The template asks for a summary, a test plan and a screenshot if the change is user-visible.

## Common stumbles

| Symptom | Fix |
|---|---|
| The API exits at start with a database connection error | Postgres is not healthy yet. `docker compose ps`, then `bash scripts/dev-local.sh --restart` |
| `redis.exceptions.ConnectionError` | `docker compose up -d redis` |
| Web shows "Connection failed" on login | The API is not on `:8000`. `bash scripts/dev-local.sh --status`, then read `.local-logs/abenix-api.log` |
| Schema drift reported after migrations | An old local schema is out of sync. `docker compose down -v`, then start again |
| An agent run fails with a missing `ANTHROPIC_API_KEY` | Set it in `.env` and run `bash scripts/dev-local.sh --restart` so every process picks it up |
| A tool answers "X is not configured" | Paste the key under **Admin -> Tool Configuration** |
| A changed `NEXT_PUBLIC_*` value does nothing in the cluster | These are fixed when the web image is built, `kubectl set env` cannot change them. Set it in `.env` and rebuild the web image with the deploy script. On Azure the Grafana link is built from the ingress host of the last deploy when `NEXT_PUBLIC_GRAFANA_URL` is unset |
| Tests pass locally but CI is red | Versions differ. `check-before-push.sh` pins black 24.8.0 and ruff 0.6.9 to match CI |

## Optional: SSO local test

To test Google sign-in locally:

1. Create an OAuth client at <https://console.cloud.google.com/apis/credentials>. Authorized redirect URI: `http://localhost:8000/api/auth/oidc/google/callback`.
2. Add to `.env`:
   ```bash
   GOOGLE_OIDC_CLIENT_ID=...
   GOOGLE_OIDC_CLIENT_SECRET=...
   PUBLIC_API_BASE_URL=http://localhost:8000
   WEB_BASE_URL=http://localhost:3000
   ```
3. `bash scripts/dev-local.sh --restart`. The login page now shows a Google button.
4. GitHub and Microsoft follow the same pattern, see [docs/09-reference/05-sso.md](docs/09-reference/05-sso.md).

## What next

- [How Abenix fits together](docs/00-how-abenix-fits-together.md) for the core objects, the roles, the words the UI uses and where to start.
- [ARCHITECTURE.md](ARCHITECTURE.md) for the map of the repo.
- The in-app **Help** page (`/help`) for every screen, and `/docs` for these developer docs with search.
- The how-tos in [docs/08-howto/](docs/08-howto/): add a tool, an agent or a page, decisions, evaluation suites, governance, Source Watch and events, earned autonomy, self-improvement, marketplace, meetings, testing.
- Look at the latest merged PRs to see what conventions land.
- The maintainer is `sarkar4777`. Ping in your PR if you're blocked.
