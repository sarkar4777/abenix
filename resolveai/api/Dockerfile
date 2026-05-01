# ResolveAI API — standalone FastAPI service (port 8004).
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
  && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sdk/ ./sdk/
COPY app/ ./app/
COPY main.py .
ENV PYTHONPATH=/app:/app/sdk
EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/health').read()" || exit 1
CMD ["python", "main.py"]
