# QuoteIQ API — standalone FastAPI service (port 8008).
# Build from the quoteiq/ folder so the example emails can be copied in:
#   docker build -f quoteiq/api/Dockerfile quoteiq
FROM python:3.12-slim
WORKDIR /app
# The base tag's packages trail the patched builds, so upgrade before
# installing anything on top of them.
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends gcc \
  && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
COPY api/sdk/ ./sdk/
COPY api/app/ ./app/
COPY api/main.py .
# The example inbox.
COPY test-data/emails/ ./test-data/emails/
ENV PYTHONPATH=/app:/app/sdk
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8008/health').read()" || exit 1
CMD ["python", "main.py"]
