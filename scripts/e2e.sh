#!/usr/bin/env bash
# Browser end-to-end tests against disposable same-origin stacks. The development database is never touched.
#   stack "live"    http://localhost:8090  database internmatch_e2e       real local AI runtime
#   stack "ai-down" http://localhost:8091  database internmatch_e2e_down  AI runtime deliberately unreachable
# Usage: scripts/e2e.sh [playwright args, e.g. --project same-origin]
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
set -a; source .env; set +a
PGDATA="$ROOT/.local/postgres"
LOGDIR="$ROOT/.local/e2e"; mkdir -p "$LOGDIR"
BASE_URL="${DATABASE_URL%/*}"
started_pg=0; pids=()

cleanup() {
  for pid in "${pids[@]:-}"; do [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]:-}"; do [ -n "$pid" ] && wait "$pid" 2>/dev/null || true; done
  for db in internmatch_e2e internmatch_e2e_down; do
    .venv/bin/python - "$db" <<'PY' || true
import os, sys, psycopg, urllib.parse as u
p = u.urlsplit(os.environ['DATABASE_URL'].replace('+psycopg', ''))
c = psycopg.connect(host=p.hostname, port=p.port, user=p.username, password=u.unquote(p.password or ''), dbname='postgres', autocommit=True)
c.execute('DROP DATABASE IF EXISTS ' + sys.argv[1] + ' WITH (FORCE)')
PY
  done
  [ "$started_pg" = 1 ] && "$PG_BIN/pg_ctl" stop -D "$PGDATA" -m fast >/dev/null || true
}
trap cleanup EXIT

if ! "$PG_BIN/pg_ctl" status -D "$PGDATA" >/dev/null 2>&1; then
  "$PG_BIN/pg_ctl" start -w -D "$PGDATA" -l "$ROOT/.local/postgres.log" >/dev/null; started_pg=1
fi
npm --prefix frontend run build >"$LOGDIR/build.log" 2>&1 || { tail -30 "$LOGDIR/build.log"; exit 1; }
(cd frontend && npx playwright install chromium >/dev/null)

DATABASE_URL="$BASE_URL/internmatch_e2e" .venv/bin/python scripts/run.py --production --port 8090 --api-port 8001 --web-port 3001 >"$LOGDIR/live.log" 2>&1 &
pids+=($!)
DATABASE_URL="$BASE_URL/internmatch_e2e_down" OLLAMA_BASE_URL="http://127.0.0.1:9" .venv/bin/python scripts/run.py --production --no-ollama-start \
  --port 8091 --api-port 8002 --web-port 3002 >"$LOGDIR/ai-down.log" 2>&1 &
pids+=($!)
for url in http://localhost:8090 http://localhost:8091; do
  for _ in $(seq 1 90); do curl -sf "$url/api/health" >/dev/null && break; sleep 1; done
  curl -sf "$url/api/health" >/dev/null || { echo "Stack at $url did not become healthy"; tail -40 "$LOGDIR"/*.log; exit 1; }
done
(cd backend && DATABASE_URL="$BASE_URL/internmatch_e2e" ../.venv/bin/python -m tests.e2e_seed)
(cd frontend && E2E_URL=http://localhost:8090 E2E_AI_DOWN_URL=http://localhost:8091 npx playwright test "$@")
