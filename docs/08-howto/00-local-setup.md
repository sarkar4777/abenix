# Local development setup

> From `git clone` to a running cluster on your laptop in ~10 minutes.

---

## Prerequisites

| Tool | Min version | Why |
|---|---|---|
| Docker Desktop | 24.x | Container runtime |
| Node.js | 20.x | Next.js web build |
| Python | 3.12 | Backend services |
| kubectl | 1.27 | k8s CLI |
| Helm | 3.13 | chart installs |
| minikube **or** k3d | latest | local k8s |
| jq | latest | scripts |

macOS:
```bash
brew install docker node@20 python@3.12 kubectl helm minikube jq
```

Linux:
```bash
# Use your distro's package manager + the official installers for kubectl/helm/minikube
```

Windows: WSL2 + Docker Desktop + the Linux toolchain inside WSL.

---

## Two paths

### Path A — full local k8s (recommended for backend work)

```bash
git clone https://github.com/sarkar4777/agentforge.git
cd agentforge
cp .env.example .env             # fill in LLM keys
bash scripts/deploy.sh local
```

This bootstraps minikube, builds + pushes 15 images to a local registry, helm-installs the platform + standalone apps, seeds users/agents/KBs/ML models, and runs smoke tests. ~12 minutes on a fresh machine.

When it's done, hosts wired in your `/etc/hosts`:
```
127.0.0.1   api.localhost
127.0.0.1   web.localhost
127.0.0.1   wingman.localhost
127.0.0.1   example_app.localhost
...
```

Visit `http://web.localhost` and log in as `admin@abenix.dev / Admin123456`.

### Path B — partial — frontend dev against deployed backend

For UI-only work, faster turnaround:

```bash
# In one terminal: port-forward the cloud cluster's api
kubectl -n abenix port-forward svc/abenix-api 8000:8000

# In another: run web dev server pointing at it
cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

You get Next.js hot-reload but with real platform data. Caveat: any backend change requires path A.

---

## Required env vars

`.env` at repo root:

```bash
# LLM provider keys (at least one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Tool integrations (optional — without these, related tools degrade gracefully)
TAVILY_API_KEY=tvly-...
EIA_API_KEY=...
BRAVE_SEARCH_API_KEY=...
SERPAPI_API_KEY=...
NEWS_API_KEY=...
FRED_API_KEY=...
ALPHA_VANTAGE_API_KEY=...
MEDIASTACK_API_KEY=...
ENTSOE_API_KEY=...
AISSTREAM_API_KEY=...

# Postgres (auto-populated by deploy.sh local)
JWT_SECRET=local-dev-secret-change-in-prod
```

Anything missing degrades the corresponding tool — `tavily_search` returns "tool not configured" instead of crashing.

---

## Running tests

Unit (Python):
```bash
cd apps/api && pytest
cd apps/agent-runtime && pytest
```

Unit (TS):
```bash
cd apps/web && npm run test
```

End-to-end (Playwright):
```bash
# Run the audit-fixes spec against your local deployment
USE_K8S=true BASE=http://web.localhost API=http://api.localhost \
  AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
  npx playwright test e2e/uat_audit_fixes.spec.ts
```

See [05-testing](05-testing.md) for the full test catalogue.

---

## Useful kubectl shortcuts

```bash
alias k="kubectl -n abenix"

k get all
k logs -l app=abenix-api -f
k exec -it deploy/abenix-api -- python -c "import app.main; print('ok')"
k port-forward svc/grafana 3010:3000        # then visit localhost:3010
k port-forward svc/abenix-api 8000:8000
```

---

## Resetting

```bash
# Nuke the cluster, keep the code
minikube delete && bash scripts/deploy.sh local

# Or just reset DB
k exec -it sts/postgres -- psql -U abenix -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
k exec deploy/abenix-api -- alembic upgrade head
k exec deploy/abenix-api -- python /app/packages/db/seeds/seed_agents.py
```

---

## See also

- [01-add-a-tool](01-add-a-tool.md) — first thing to try once running
- [03-add-a-page](03-add-a-page.md) — first UI change
- [04-debugging](04-debugging.md) — when things don't work
