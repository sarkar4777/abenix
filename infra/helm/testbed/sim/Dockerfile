FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /sim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sim.py .
RUN adduser --system --uid 1001 sim
USER sim
ENTRYPOINT ["python", "/sim/sim.py"]
