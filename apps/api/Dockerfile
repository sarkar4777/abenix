FROM python:3.12-slim AS deps
COPY apps/api/pyproject.toml /tmp/api.toml
COPY packages/db/pyproject.toml /tmp/db.toml
COPY apps/agent-runtime/requirements.txt /tmp/runtime.txt
RUN python3 -c "\
import tomllib; \
a=tomllib.load(open('/tmp/api.toml','rb'))['project']['dependencies']; \
b=tomllib.load(open('/tmp/db.toml','rb'))['project']['dependencies']; \
c=[l.strip() for l in open('/tmp/runtime.txt') if l.strip() and not l.startswith('#')]; \
f=open('/tmp/req.txt','w'); \
[f.write(d+chr(10)) for d in sorted(set(a+b+c))]" && \
    pip install --no-cache-dir -r /tmp/req.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/agent-runtime:/app/packages/db:/app/packages/sdk/python
# The base tag's Debian packages trail the patched builds, and pip ships its
# own advisories. Both are fixed in place rather than by waiting for a new
# python:3.12-slim to be cut.
RUN apt-get update \n && apt-get upgrade -y --no-install-recommends \n && rm -rf /var/lib/apt/lists/* \n && pip install --no-cache-dir --upgrade pip
RUN adduser --system --uid 1001 appuser
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY apps/api/ ./apps/api/
COPY packages/db/ ./packages/db/
COPY packages/sdk/python/ ./packages/sdk/python/
COPY apps/agent-runtime/engine/ ./apps/agent-runtime/engine/
# The Use Cases screen reads this catalogue at runtime. docker/Dockerfile.api
# carries it and this one did not, so the image CI publishes answered "No use
# cases available" while a locally built one worked.
COPY infra/use_cases_catalog.json ./infra/use_cases_catalog.json
# Standalone-app code assets need to be in the image so seed_code_assets.py
# discovers each agentforge.yaml at boot. Without this, agents that reference
# a code_asset_id from these folders return "Code asset not found".
COPY contractiq/code-assets/ ./contractiq/code-assets/
COPY pharmavigil/aimodels/ ./pharmavigil/aimodels/
COPY pharmavigil/code-assets/ ./pharmavigil/code-assets/
COPY wingman/code-assets/ ./wingman/code-assets/
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
WORKDIR /app/apps/api
# Prometheus multi-process mode aggregates metrics across the 4 uvicorn
# workers. Without it, a Counter incremented in worker 2 is invisible
# to a /metrics scrape that lands on worker 1 — partially-populated
# Grafana panels were tracked back to this. The dir lives in /tmp so
# a pod restart wipes counters; that's fine for cumulative dashboards
# (rate() handles resets) and avoids needing a writable PVC.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc
CMD sh -c 'mkdir -p $PROMETHEUS_MULTIPROC_DIR && rm -f $PROMETHEUS_MULTIPROC_DIR/* && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4'
