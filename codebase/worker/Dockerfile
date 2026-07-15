FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker_service ./worker_service

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /var/hls \
    && chown app:app /var/hls

EXPOSE 8000
HEALTHCHECK --interval=3s --timeout=2s --start-period=15s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"
CMD ["uvicorn", "worker_service.main:app", "--host", "0.0.0.0", "--port", "8000"]