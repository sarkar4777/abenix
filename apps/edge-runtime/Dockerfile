# Abenix Edge: collectors with store-and-forward, plus the agent bundle runtime.
# Multi-arch: docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/abenix/edge-runtime:<tag> --push apps/edge-runtime
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ABENIX_EDGE_DATA=/var/lib/abenix-edge

# The base tag's packages trail the patched builds, so upgrade before
# installing anything on top of them.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && find /usr/local/lib/python3.12 -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.12 -name '*.pyc' -delete

COPY runtime.py entrypoint.py /app/
COPY abenix_edge /app/abenix_edge

# dialout opens serial ports for Modbus RTU and GPS
RUN useradd -u 1001 -m -G dialout edge \
    && mkdir -p /var/edge/agents /etc/edge /var/lib/abenix-edge \
    && chown -R edge:edge /var/edge /etc/edge /var/lib/abenix-edge

USER 1001
VOLUME ["/var/lib/abenix-edge"]

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200 else 1)"

CMD ["python", "/app/entrypoint.py"]
