"""Pytest configuration for the platform's pure-Python unit tests.

These tests exercise the core platform primitives (pipeline executor,
moderation evaluator, failure-code classifier, response envelopes,
JWT/bcrypt security) WITHOUT any live infrastructure. They run on a
clean GitHub Actions runner with only Python + pip installed.

Path resolution: the codebase is a monorepo with three independent
Python packages (apps/api, apps/agent-runtime, packages/db). Each owns
its own `app/` or `engine/` namespace. Inserting all three roots onto
sys.path lets the tests `from app.core.foo import bar` and
`from engine.pipeline import baz` exactly the way the runtime does.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A developer's .env must not reach real providers from unit tests
for _key in (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "TAVILY_API_KEY",
    "CLAUDE_SUBSCRIPTION_TOKEN",
):
    os.environ[_key] = ""

# Order matters: app/ resolves to apps/api/app, engine/ to
# apps/agent-runtime/engine, models/ to packages/db/models, worker/
# to apps/worker/worker.
for sub in ("apps/api", "apps/agent-runtime", "packages/db", "apps/worker"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

# Settings used by app.core.security et al. read from env. Provide
# stable defaults so tests don't drift if a developer's shell has
# different values set.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_ALGORITHM", "RS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("APP_NAME", "abenix-test")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _a_model_is_configured(monkeypatch):
    # mocked databases answer in a fixed order, the no-model check must not take a turn
    # test_model_gate.py swaps the probe itself
    try:
        import app.routers.llm_models as lm
    except Exception:
        yield
        return

    async def configured(db):
        return {"anthropic": {"configured": True, "reason": None}}

    monkeypatch.setattr(lm, "_probe_providers", configured)
    yield


# Fixtures for tests that run against throwaway Neo4j and Postgres.
from atlas_live import atlas_world  # noqa: E402,F401
from kg_stack import graph, kg_conn, kg_db_url, neo4j_uri  # noqa: E402,F401

# containers start only for the tests that ask for them
from kb_pg import (  # noqa: E402,F401
    azurite_port,
    kb_conn,
    kb_db_url,
    minio_endpoint,
    neo4j_bolt,
)
