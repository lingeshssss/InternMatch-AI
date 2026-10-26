"""Container entrypoint: validate configuration, migrate, then supervise API, worker, Next.js and Caddy.

If any process exits, all are stopped and the container exits non-zero so the platform restarts it.
Never prints secret values.
"""
import os, signal, subprocess, sys, time
from urllib.parse import urlsplit

REQUIRED = ('DATABASE_URL', 'DATA_ENCRYPTION_KEY', 'APP_ORIGINS')
children = []

def log(msg): print(f'[start] {msg}', flush=True)

def check_config():
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing: log('Missing required environment variables: ' + ', '.join(missing)); sys.exit(2)
    if os.environ.get('APP_ENV') != 'production': log('APP_ENV must be production in the container'); sys.exit(2)
    local_ok = os.environ.get('ALLOW_INSECURE_LOCAL_ORIGIN') == 'true'
    for origin in os.environ['APP_ORIGINS'].split(','):
        u = urlsplit(origin.strip().strip('"\'').strip())
        # Plain HTTP is accepted only for a container tested on this machine (docker compose), never a public host.
        if u.scheme != 'https' and not (local_ok and u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1')):
            # Origins are public URLs, so showing the rejected value is safe and saves guesswork.
            log(f'APP_ORIGINS must list https:// origins only; got {origin!r}. Example: https://your-app.onrender.com'); sys.exit(2)
    db = urlsplit(os.environ['DATABASE_URL'])
    if db.hostname in ('localhost', '127.0.0.1', '::1'):
        # Inside a container, localhost is the container itself; a laptop's local .env value cannot work here.
        log(f'DATABASE_URL points at {db.hostname}:{db.port}, which inside this container is the container itself. '
            'Use the managed database URL (e.g. Neon: postgresql://...neon.tech/...?sslmode=require).'); sys.exit(2)
    try:
        from cryptography.fernet import Fernet
        Fernet(os.environ['DATA_ENCRYPTION_KEY'].encode())
    except Exception:
        log('DATA_ENCRYPTION_KEY is not a valid Fernet key'); sys.exit(2)
    if os.environ.get('AI_PROVIDER') == 'ollama':
        log('AI_PROVIDER=ollama: the container can only reach an Ollama endpoint it has a route to (see docs/LOCAL_AI.md).')

def stop(*_):
    for p in children:
        try: p.send_signal(signal.SIGTERM)
        except ProcessLookupError: pass
    deadline = time.monotonic() + 20
    for p in children:
        try: p.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired: p.kill()

def main():
    check_config()
    if os.environ.get('RUN_MIGRATIONS', 'true') == 'true':
        log('Applying migrations')
        if subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd='/app/backend').returncode: log('Migration failed'); sys.exit(1)
    port = os.environ.get('PORT', '8080')
    env = {**os.environ, 'SITE_ADDRESS': f':{port}', 'CADDY_BIND': os.environ.get('CADDY_BIND', '0.0.0.0'), 'HOSTNAME': '127.0.0.1', 'PORT': '3000', 'NEXT_TELEMETRY_DISABLED': '1'}
    commands = [
        ([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1',
          '--timeout-graceful-shutdown', '15'], '/app/backend'),
        ([sys.executable, '-m', 'app.worker'], '/app/backend'),
        (['node', 'server.js'], '/app/web'),
        (['caddy', 'run', '--config', '/app/deploy/Caddyfile', '--adapter', 'caddyfile'], '/app'),
    ]
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: (log('Shutting down'), stop(), sys.exit(0)))
    for cmd, cwd in commands: children.append(subprocess.Popen(cmd, cwd=cwd, env=env))
    log(f'Serving on port {port}')
    while all(p.poll() is None for p in children): time.sleep(1)
    failed = next(p for p in children if p.poll() is not None)
    log(f'Process {failed.args[0]} exited with {failed.returncode}; stopping container')
    stop(); sys.exit(1)

if __name__ == '__main__': main()
