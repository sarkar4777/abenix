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
    pip install --no-cache-dir -r /tmp/runtime-req.txt -r /tmp/extra-req.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN adduser --system --uid 1001 appuser
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY apps/agent-runtime/ ./apps/agent-runtime/
COPY packages/db/ ./packages/db/
USER appuser
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1
WORKDIR /app/apps/agent-runtime
CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
