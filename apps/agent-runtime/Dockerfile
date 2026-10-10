FROM python:3.12-slim AS deps
# Install the full runtime dep set from requirements.txt (which is
# the canonical superset — pyproject.toml has the minimum project
# metadata but requirements.txt is what the API + consumer actually
# need at runtime, incl. redisvl, langfuse, ML deps, etc.)
COPY apps/agent-runtime/requirements.txt /tmp/runtime-req.txt
COPY apps/agent-runtime/pyproject.toml /tmp/runtime.toml
COPY packages/db/pyproject.toml /tmp/db.toml
RUN python3 -c "\
import tomllib; \
a=tomllib.load(open('/tmp/runtime.toml','rb'))['project']['dependencies']; \
b=tomllib.load(open('/tmp/db.toml','rb'))['project']['dependencies']; \
f=open('/tmp/extra-req.txt','w'); \
[f.write(d+chr(10)) for d in sorted(set(a+b))]" && \
    pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir -r /tmp/runtime-req.txt -r /tmp/extra-req.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# The base tag's Debian packages trail the patched builds, so upgrade them
# rather than wait for a new python:3.12-slim to be cut. pip is upgraded in the
# deps stage instead of here, because this stage's site-packages is wiped
# and replaced by the deps stage's copy below.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN adduser --system --uid 1001 appuser
WORKDIR /app
# COPY merges into the destination rather than replacing it, so the base
# image's own dist-info directories survive next to the ones copied in and
# Trivy reports the stale versions. Clear the directory first so what lands
# here is exactly what the deps stage resolved.
RUN rm -rf /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY apps/agent-runtime/ ./apps/agent-runtime/
COPY packages/db/ ./packages/db/
# consumer.py imports app.core.execution_state to share the canonical
# Redis primitives (pub/sub log + per-execution tool_calls list +
# live state hash) with the platform API. Without this, the pool
# couldn't update the live snapshot the SSE producer reads — and the
# DAG drawer would never tick during pool-mode runs. We only ship the
# `core/` and `__init__.py` shim, NOT the full app, to keep the image
# small.
COPY apps/api/app/__init__.py ./apps/api/app/__init__.py
COPY apps/api/app/core/ ./apps/api/app/core/
# the consumer writes failed runs to the dead-letter queue through this service
COPY apps/api/app/services/__init__.py ./apps/api/app/services/__init__.py
COPY apps/api/app/services/dlq.py ./apps/api/app/services/dlq.py
COPY apps/api/app/services/execution_hooks.py ./apps/api/app/services/execution_hooks.py
# App-owned post-processor modules. The engine itself stays
# commodity-agnostic; each app drops a runtime/post_processors/ tree
# here and points POST_PROCESSOR_MODULES at it.
COPY contractiq/runtime/ ./contractiq/runtime/
COPY contractiq/__init__.py ./contractiq/__init__.py
# Standalone-app code assets shipped with the repo — seed_code_assets.py
# discovers each agentforge.yaml at boot and the code_asset tool executes
# them here. Without these copies, agents like contractiq_correlations and
# contractiq_risk_calculator return "Code asset not found".
COPY contractiq/code-assets/ ./contractiq/code-assets/
COPY wingman/code-assets/ ./wingman/code-assets/
USER appuser
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1
WORKDIR /app/apps/agent-runtime
CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
