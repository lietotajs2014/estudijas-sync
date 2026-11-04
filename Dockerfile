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

# Dev versijai (DEBUG_TOOLS=1): virtuāls ekrāns + noVNC, lai RTU pieteikšanās logu redzētu pārlūkā
ARG DEBUG_TOOLS=0
RUN if [ "$DEBUG_TOOLS" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify \
      && rm -rf /var/lib/apt/lists/* && ln -sf vnc.html /usr/share/novnc/index.html; \
    fi

COPY estudijas_sync ./estudijas_sync
COPY server ./server
COPY deploy/start-web.sh /app/start-web.sh

# Nepalaižam kā root
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["sh", "/app/start-web.sh"]
