#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR=/workspace/.cache/uv
export npm_config_cache=/workspace/.cache/npm
uv venv --allow-existing .venv
uv pip sync --python .venv/bin/python backend/requirements.lock
npm --prefix frontend ci --no-audit --no-fund
# Local development only. Production uses managed services and externally provided keys.
.venv/bin/python - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
p=Path('.env')
if not p.exists():
    p.write_text('DATA_ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\n')
    p.chmod(0o600)
PY
docker compose up -d --wait
(cd backend && ../.venv/bin/alembic upgrade head)
