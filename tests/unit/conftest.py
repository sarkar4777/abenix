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

# Order matters: app/ resolves to apps/api/app, engine/ to
# apps/agent-runtime/engine, models/ to packages/db/models.
for sub in ("apps/api", "apps/agent-runtime", "packages/db"):
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
