FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && find /usr/local/lib/python3.12 -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.12 -name '*.pyc' -delete

COPY runtime.py /app/runtime.py

RUN useradd -u 1001 -m edge \
    && mkdir -p /var/edge/agents /etc/edge \
    && chown -R edge:edge /var/edge /etc/edge

USER edge

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200 else 1)"

CMD ["python", "/app/runtime.py"]
