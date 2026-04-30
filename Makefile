.PHONY: dev build test test-cov lint docker-up docker-down install clean \
       deploy-local deploy-local-runtime deploy-cloud deploy-status deploy-destroy \
       rollback load-test type-check audit-deps migrate help

# ── Development ──────────────────────────────────────────────────
dev:
	bash scripts/dev-local.sh

dev-make:
	$(MAKE) docker-up
	@echo "Starting API and Web dev servers..."
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 & \
	cd apps/web && npm run dev & \
	wait

build:
	npx turbo run build

install:
	npm install
	cd apps/api && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd apps/agent-runtime && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd apps/worker && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# ── Testing ──────────────────────────────────────────────────────
test:
	cd apps/api && .venv/bin/python -m pytest tests/ -v
	npx turbo run test

test-cov:
	cd apps/api && .venv/bin/python -m pytest tests/ -v --cov=app --cov-report=html --cov-fail-under=60
	npx turbo run test -- --coverage

test-e2e:
	npx playwright test --headed

test-e2e-k8s:
	USE_K8S=true npx playwright test

test-agents:
	python scripts/test_all_agents.py

load-test:
	@echo "Starting load test (open http://localhost:8089)..."
	pip install locust 2>/dev/null || true
	locust -f tests/load/locustfile.py --host=http://localhost:8000

# ── Code Quality ─────────────────────────────────────────────────
lint:
	npx turbo run lint
	black --check apps/api apps/agent-runtime apps/worker packages/db
	ruff check apps/api apps/agent-runtime apps/worker packages/db

type-check:
	mypy apps/api/app/core/ --ignore-missing-imports

audit-deps:
	pip-audit || echo "Install: pip install pip-audit"
	npm audit || true

# ── Database ─────────────────────────────────────────────────────
migrate:
	cd packages/db && PYTHONPATH=. python -m alembic upgrade head

migrate-new:
	@read -p "Migration message: " msg && \
	cd packages/db && PYTHONPATH=. python -m alembic revision --autogenerate -m "$$msg"

# ── Docker ───────────────────────────────────────────────────────
docker-up:
	docker compose -f infra/docker/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker/docker-compose.yml down

# ── Kubernetes ───────────────────────────────────────────────────
deploy-local:
	bash scripts/deploy.sh local

deploy-local-runtime:
	bash scripts/deploy.sh local-runtime

deploy-cloud:
	bash scripts/deploy.sh cloud

deploy-status:
	bash scripts/deploy.sh status

deploy-destroy:
	bash scripts/deploy.sh destroy

rollback:
	helm rollback abenix -n abenix
	@echo "Rolled back to previous Helm release. Run 'make deploy-status' to verify."

# ── Cleanup ──────────────────────────────────────────────────────
clean:
	docker compose -f infra/docker/docker-compose.yml down -v
	rm -rf node_modules apps/*/node_modules packages/*/node_modules
	rm -rf apps/web/.next
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

# ── Help ─────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Abenix — Development Commands"
	@echo "  ──────────────────────────────────────────────"
	@echo ""
	@echo "  Development:"
	@echo "    make dev                  Start full dev environment (Docker + API + Web + Workers)"
	@echo "    make build                Build all apps"
	@echo "    make install              Install all dependencies"
	@echo ""
	@echo "  Testing:"
	@echo "    make test                 Run unit tests"
	@echo "    make test-cov             Run tests with coverage (fails if < 60%)"
	@echo "    make test-e2e             Run Playwright E2E tests (local)"
	@echo "    make test-e2e-k8s         Run Playwright E2E tests (against K8s)"
	@echo "    make test-agents          Smoke-test all 42 OOB agents"
	@echo "    make load-test            Start Locust load test (http://localhost:8089)"
	@echo ""
	@echo "  Code Quality:"
	@echo "    make lint                 Lint all code (ESLint + black + ruff)"
	@echo "    make type-check           Run mypy type checking on core modules"
	@echo "    make audit-deps           Audit Python + Node dependencies for vulnerabilities"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate              Run all pending Alembic migrations"
	@echo "    make migrate-new          Create a new Alembic migration"
	@echo ""
	@echo "  Kubernetes:"
	@echo "    make deploy-local         Deploy to minikube (embedded mode)"
	@echo "    make deploy-local-runtime Deploy to minikube (production-like, runtime pod)"
	@echo "    make deploy-cloud         Deploy to cloud Kubernetes"
	@echo "    make deploy-status        Check deployment health"
	@echo "    make deploy-destroy       Tear down Kubernetes deployment"
	@echo "    make rollback             Rollback to previous Helm release"
	@echo ""
	@echo "  Privacy & Compliance (GDPR):"
	@echo "    POST /api/account/export  Export all user data (Article 20)"
	@echo "    DELETE /api/account        Delete account (Article 17)"
	@echo "    GET  /api/account/privacy  View data processing info"
	@echo "    PUT  /api/settings/retention  Configure data retention"
	@echo "    UI:  /settings/privacy     Privacy & data management dashboard"
	@echo ""
	@echo "  Observability:"
	@echo "    GET  /api/health           Liveness check"
	@echo "    GET  /api/health/ready     Readiness (Postgres, Redis, Neo4j, LLM)"
	@echo "    GET  /api/metrics          Prometheus metrics"
	@echo "    UI:  /settings/observability  System health dashboard"
	@echo ""
	@echo "  Other:"
	@echo "    make docker-up            Start Docker infrastructure only"
	@echo "    make docker-down          Stop Docker infrastructure"
	@echo "    make clean                Remove all build artifacts and volumes"
	@echo ""
