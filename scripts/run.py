"""Start the whole local stack behind one URL: PostgreSQL, migrations, API, worker, Next.js and Caddy.

Usage:  .venv/bin/python scripts/run.py [--production] [--migrate-only] [--port 8080]
Never prints environment values. Ctrl+C stops every child process group.
"""
import argparse, os, platform, shutil, signal, subprocess, sys, time, urllib.request, json
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--production', action='store_true', help='serve the built Next.js app (run npm --prefix frontend run build first)')
parser.add_argument('--migrate-only', action='store_true', help='start PostgreSQL if needed, apply migrations, then exit')
parser.add_argument('--port', type=int, default=8080, help='public port served by Caddy')
parser.add_argument('--api-port', type=int, default=8000)
parser.add_argument('--web-port', type=int, default=3000)
parser.add_argument('--no-ollama-start', action='store_true', help='do not try to launch Ollama if it is not running')
args = parser.parse_args()

env = {**{k: v for k, v in dotenv_values(root / '.env').items() if v is not None}, **os.environ, 'NEXT_TELEMETRY_DISABLED': '1'}
python = str(root / '.venv/bin/python')
children: list[subprocess.Popen] = []
started_postgres = False

def say(msg): print(f'[internmatch] {msg}', flush=True)
def fail(msg): say('ERROR: ' + msg); stop(); sys.exit(1)

def local_postgres():
    """Return (pg_bin, data_dir) when DATABASE_URL targets the project-local cluster."""
    url = urlsplit(env.get('DATABASE_URL', '').replace('postgresql+psycopg', 'postgresql'))
    data = root / '.local/postgres'
    if url.hostname in ('127.0.0.1', 'localhost') and url.port == 55432 and (data / 'PG_VERSION').exists():
        pg_bin = Path(env.get('PG_BIN') or '')
        if not (pg_bin / 'pg_ctl').exists(): fail('PG_BIN in .env does not point to PostgreSQL binaries')
        return pg_bin, data
    return None

def start_postgres():
    global started_postgres
    found = local_postgres()
    if not found: return
    pg_bin, data = found
    if subprocess.run([pg_bin / 'pg_ctl', 'status', '-D', data], capture_output=True).returncode == 0: return
    say('Starting PostgreSQL on 127.0.0.1:55432')
    r = subprocess.run([pg_bin / 'pg_ctl', 'start', '-w', '-D', data, '-l', root / '.local/postgres.log'], capture_output=True, text=True)
    if r.returncode: fail('PostgreSQL failed to start; see .local/postgres.log')
    started_postgres = True

def stop_postgres():
    found = local_postgres() if started_postgres else None
    if found: subprocess.run([found[0] / 'pg_ctl', 'stop', '-m', 'fast', '-D', found[1]], capture_output=True)

def migrate():
    url = env.get('DATABASE_URL', '')
    if not url: fail('DATABASE_URL is not set')
    # Create the application database on the local cluster if it does not exist yet.
    if local_postgres():
        code = ('import psycopg,os,urllib.parse as u;p=u.urlsplit(os.environ["DATABASE_URL"].replace("+psycopg",""));'
                'c=psycopg.connect(host=p.hostname,port=p.port,user=p.username,password=u.unquote(p.password or ""),dbname="postgres",autocommit=True);'
                'n=p.path.lstrip("/");c.execute("SELECT 1 FROM pg_database WHERE datname=%s",(n,)).fetchone() or c.execute("CREATE DATABASE "+n)')
        if subprocess.run([python, '-c', code], env=env).returncode: fail('Could not create the local database')
    say('Applying database migrations')
    if subprocess.run([python, '-m', 'alembic', 'upgrade', 'head'], cwd=root / 'backend', env=env).returncode: fail('Migration failed')

def check_ai():
    if env.get('AI_PROVIDER', 'disabled') != 'ollama':
        say(f"AI provider: {env.get('AI_PROVIDER', 'disabled')}"); return
    base = env.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    def tags():
        with urllib.request.urlopen(base + '/api/tags', timeout=3) as r: return {m['name'] for m in json.load(r)['models']}
    try: names = tags()
    except Exception:
        if not args.no_ollama_start and platform.system() == 'Darwin' and Path('/Applications/Ollama.app').exists():
            say('Ollama is not running; launching Ollama.app'); subprocess.run(['open', '-a', 'Ollama'])
            for _ in range(30):
                time.sleep(1)
                try: names = tags(); break
                except Exception: names = None
        else: names = None
    if names is None:
        say(f'WARNING: Ollama is not reachable at {base}. The app runs, but extraction stays unavailable and postings remain Unverified.'); return
    for key, default in (('OLLAMA_MODEL', 'qwen3.5:9b'), ('OLLAMA_EMBEDDING_MODEL', 'qwen3-embedding:0.6b')):
        model = env.get(key, default)
        if model not in names and model + ':latest' not in names: say(f'WARNING: {key}={model} is not installed. Run: ollama pull {model}')
    say(f"Local AI ready check done ({env.get('OLLAMA_MODEL', 'qwen3.5:9b')} / {env.get('OLLAMA_EMBEDDING_MODEL', 'qwen3-embedding:0.6b')})")

def stop(*_):
    for p in children:
        try: os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError: pass
    for p in children:
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    children.clear()
    stop_postgres()

def port_free(port):
    import socket
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0

def main():
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: (say('Stopping'), stop(), sys.exit(0)))
    if not env.get('DATA_ENCRYPTION_KEY'): fail('DATA_ENCRYPTION_KEY is missing from .env. Restore it from backup, or run scripts/install.sh for a new install')
    start_postgres()
    migrate()
    if args.migrate_only: stop(); return 0
    for port in (args.port, args.api_port, args.web_port):
        if not port_free(port): fail(f'Port {port} is already in use. Stop the other process (lsof -nP -iTCP:{port} -sTCP:LISTEN)')
    if not shutil.which('caddy'): fail('caddy not found (brew install caddy)')
    standalone = root / 'frontend/.next/standalone'
    if args.production:
        if not (standalone / 'server.js').exists(): fail('Run npm --prefix frontend run build before --production')
        # The standalone server does not include static assets; copy them as the container image does.
        shutil.copytree(root / 'frontend/.next/static', standalone / '.next/static', dirs_exist_ok=True)
        if (root / 'frontend/public').exists(): shutil.copytree(root / 'frontend/public', standalone / 'public', dirs_exist_ok=True)
    check_ai()
    origin = f'http://localhost:{args.port}'
    origins = f'{origin},http://127.0.0.1:{args.port}'
    if args.port != 8080 or not env.get('APP_ORIGINS'): env['APP_ORIGINS'] = origins
    proc_env = {**env, 'SITE_ADDRESS': f':{args.port}', 'API_UPSTREAM': f'127.0.0.1:{args.api_port}', 'WEB_UPSTREAM': f'127.0.0.1:{args.web_port}',
                'PORT': str(args.web_port), 'HOSTNAME': '127.0.0.1'}
    commands = [
        ([python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(args.api_port), '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'], root / 'backend'),
        ([python, '-m', 'app.worker'], root / 'backend'),
        ((['node', 'server.js'], standalone) if args.production else (['npm', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', str(args.web_port)], root / 'frontend')),
        (['caddy', 'run', '--config', str(root / 'deploy/Caddyfile'), '--adapter', 'caddyfile'], root),
    ]
    for cmd, cwd in commands: children.append(subprocess.Popen(cmd, cwd=cwd, env=proc_env, start_new_session=True))
    for _ in range(120):
        if any(p.poll() is not None for p in children): break
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health', timeout=2) as r:
                if r.status == 200: say(f'InternMatch AI is running at {origin}  (Ctrl+C to stop)'); break
        except Exception: time.sleep(1)
    while all(p.poll() is None for p in children): time.sleep(1)
    code = next((p.returncode for p in children if p.returncode is not None), 1)
    say(f'A service exited (code {code}); stopping the others')
    stop()
    return code or 1

if __name__ == '__main__':
    try: sys.exit(main())
    finally: stop()
