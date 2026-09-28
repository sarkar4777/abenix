# ContractIQ API — standalone FastAPI service
FROM python:3.12-slim

WORKDIR /app

# System deps
# The base tag's packages trail the patched builds, so upgrade before
# installing anything on top of them.
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY sdk/ ./sdk/
COPY main.py .

# Add SDK to path
ENV PYTHONPATH=/app:/app/sdk

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/health').read()" || exit 1

CMD ["python", "main.py"]
