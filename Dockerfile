# Viens image gan web lapai, gan worker (atšķiras tikai palaišanas komanda docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data ESTUDIJAS_SYNC_HOME=/data/app_home TZ=Europe/Riga \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY estudijas_sync ./estudijas_sync
COPY server ./server

# Nepalaižam kā root
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
