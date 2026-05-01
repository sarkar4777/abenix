FROM python:3.12-slim AS deps
COPY apps/worker/pyproject.toml /tmp/worker.toml
COPY packages/db/pyproject.toml /tmp/db.toml
COPY apps/agent-runtime/pyproject.toml /tmp/runtime.toml
RUN python3 -c "\
import tomllib; \
a=tomllib.load(open('/tmp/worker.toml','rb'))['project']['dependencies']; \
b=tomllib.load(open('/tmp/db.toml','rb'))['project']['dependencies']; \
c=tomllib.load(open('/tmp/runtime.toml','rb'))['project']['dependencies']; \
f=open('/tmp/req.txt','w'); \
[f.write(d+chr(10)) for d in sorted(set(a+b+c))]" && \
    pip install --no-cache-dir -r /tmp/req.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# procps: pgrep for readiness probes. netcat-openbsd: `nc` for the
# wait-for-postgres / wait-for-redis init containers. python:3.12-slim
# has neither by default → without these the init loop errors
# "nc: not found" and the pod stays in Init:0/N forever.
RUN apt-get update && apt-get install -y --no-install-recommends procps netcat-openbsd && rm -rf /var/lib/apt/lists/*
RUN adduser --system --uid 1001 appuser
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY apps/worker/ ./apps/worker/
COPY packages/db/ ./packages/db/
COPY apps/agent-runtime/ ./apps/agent-runtime/
USER appuser
WORKDIR /app/apps/worker
# Concurrency + queues are env-configurable so the same image can run a
# small minikube deploy (CELERY_CONCURRENCY=2) and a scaled production
# deployment (CELERY_CONCURRENCY=12+). Hardcoding concurrency=2 was the
# #1 throughput bottleneck at >10 parallel workflows. Default raised to
# 8 — a prefork worker with 8 children still fits in ~512MB RAM per pod.
ENV CELERY_CONCURRENCY=8 \
    CELERY_QUEUES=documents,agents \
    CELERY_LOGLEVEL=info
# NB: cognify is intentionally NOT in the general worker's queue
# list — the dedicated abenix-cognify-worker pod consumes that
# queue. Including it here lets the general worker steal cognify
# tasks and crash on first DB call (since the general worker image
# bundle uses a different concurrency / preStop). Override via
# CELERY_QUEUES at runtime if you really want both pools to share.
CMD celery -A worker.celery_app worker \
    --loglevel=${CELERY_LOGLEVEL} \
    --concurrency=${CELERY_CONCURRENCY} \
    -Q ${CELERY_QUEUES}
