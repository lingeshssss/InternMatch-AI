# Single-container deployment: Caddy (public port) -> Next.js standalone + FastAPI + worker.
# PostgreSQL is external (managed). Build: docker build -t internmatch .

FROM node:24.22.0-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build && cp -r .next/static .next/standalone/.next/static && (test ! -d public || cp -r public .next/standalone/public)

FROM caddy:2.11.7-alpine AS caddy
# The upstream binary carries a cap_net_bind_service file capability. Hosts that run containers with
# no-new-privileges (e.g. Render) refuse to exec it as a non-root user. Port 8080 needs no capability,
# so copy it without extended attributes.
RUN cp /usr/bin/caddy /caddy

FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production PORT=8080
WORKDIR /app
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock && useradd --uid 10001 --create-home internmatch
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=caddy /caddy /usr/bin/caddy
COPY --from=web --chown=internmatch /web/.next/standalone /app/web
COPY backend/app backend/app
COPY backend/migrations backend/migrations
COPY backend/alembic.ini backend/alembic.ini
COPY deploy deploy
USER internmatch
ENV XDG_DATA_HOME=/tmp/caddy XDG_CONFIG_HOME=/tmp/caddy
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health/live',timeout=4)"
CMD ["python", "/app/deploy/start.py"]
