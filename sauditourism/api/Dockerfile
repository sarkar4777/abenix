FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    # weasyprint native deps for PDF rendering
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Build context is sauditourism/ (the parent of api/) — see scripts/deploy-azure.sh.
# This lets us COPY test-data/ alongside the api/ source tree.
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app/ ./app/
COPY api/sdk/ ./sdk/
COPY api/main.py .
# Bake the demo CSVs/TXTs into the image so POST /api/st/datasets/seed
# can read them at /app/test-data/. Without this the seed endpoint
# returns {"seeded": []} because the path on disk doesn't exist.
COPY test-data/ /app/test-data/

ENV PYTHONPATH=/app:/app/sdk
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/api/health')"

CMD ["python", "main.py"]
