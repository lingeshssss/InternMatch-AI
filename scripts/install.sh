#!/usr/bin/env bash
# Local setup for macOS/Linux. Idempotent: never overwrites existing .env values or encryption keys.
# Requires: uv, Node 24 + npm, PostgreSQL 16+ server binaries (initdb/pg_ctl), Caddy 2.
#   macOS: brew install uv postgresql@17 caddy node
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1 ($2)" >&2; exit 1; }; }
need uv "brew install uv"
need npm "install Node 24"
need caddy "brew install caddy"
PG_BIN="${PG_BIN:-}"
if [ -z "$PG_BIN" ]; then
  for candidate in /opt/homebrew/opt/postgresql@17/bin /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@17/bin /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
    [ -x "$candidate/initdb" ] && PG_BIN="$candidate" && break
  done
fi
[ -n "$PG_BIN" ] && [ -x "$PG_BIN/initdb" ] || { echo "PostgreSQL server binaries not found. brew install postgresql@17, or set PG_BIN" >&2; exit 1; }

uv venv --python 3.12 --allow-existing .venv
uv pip sync --python .venv/bin/python backend/requirements.lock
npm --prefix frontend ci --no-audit --no-fund

# .env: add only missing keys. Existing values (especially DATA_ENCRYPTION_KEY) are preserved.
.venv/bin/python - "$PG_BIN" <<'PY'
import secrets, sys
from pathlib import Path
from cryptography.fernet import Fernet
p = Path('.env')
lines = p.read_text().splitlines() if p.exists() else []
present = {l.split('=', 1)[0].strip() for l in lines if '=' in l and not l.lstrip().startswith('#')}
existing = dict(l.split('=', 1) for l in lines if '=' in l and not l.lstrip().startswith('#'))
pg_password = existing.get('POSTGRES_PASSWORD') or secrets.token_urlsafe(24)
defaults = {
    'APP_ENV': 'development',
    'APP_ORIGINS': 'http://localhost:8080,http://127.0.0.1:8080',
    'POSTGRES_PASSWORD': pg_password,
    'DATABASE_URL': f'postgresql+psycopg://internmatch:{pg_password}@127.0.0.1:55432/internmatch',
    'PG_BIN': sys.argv[1],
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'AI_PROVIDER': 'ollama',
    'OLLAMA_BASE_URL': 'http://127.0.0.1:11434',
    'OLLAMA_MODEL': 'qwen3.5:9b',
    'OLLAMA_EMBEDDING_MODEL': 'qwen3-embedding:0.6b',
    'AI_ALLOW_HOSTED_FALLBACK': 'false',
}
if 'DATA_ENCRYPTION_KEY' in present and not existing.get('DATA_ENCRYPTION_KEY', '').strip():
    sys.exit('.env has an empty DATA_ENCRYPTION_KEY. Restore the original key from your backup; refusing to generate one over it.')
added = [f'{k}={v}' for k, v in defaults.items() if k not in present]
if added:
    p.write_text('\n'.join(lines + ['# Added by scripts/install.sh'] + added) + '\n')
p.chmod(0o600)
print('.env: added', ', '.join(a.split('=')[0] for a in added) if added else 'nothing (all keys present)')
PY

# Project-local PostgreSQL cluster, bound to 127.0.0.1 only.
PGDATA="$ROOT/.local/postgres"
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  mkdir -p "$ROOT/.local"
  PWFILE="$(mktemp)"; trap 'rm -f "$PWFILE"' EXIT
  grep '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2- > "$PWFILE"
  "$PG_BIN/initdb" -D "$PGDATA" -U internmatch --pwfile="$PWFILE" --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8 >/dev/null
  printf "listen_addresses = '127.0.0.1'\nport = 55432\nunix_socket_directories = '%s'\n" "$PGDATA" >> "$PGDATA/postgresql.conf"
fi
.venv/bin/python scripts/run.py --migrate-only
echo "Install complete. Start everything with: .venv/bin/python scripts/run.py"
