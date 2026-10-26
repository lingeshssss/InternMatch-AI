"""Run local services; propagate shutdown to all children. Never logs env values."""
import argparse, os, signal, subprocess, sys, time
from pathlib import Path
from dotenv import dotenv_values
root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument('--production',action='store_true');args=parser.parse_args()
env={**{k:v for k,v in dotenv_values(root/'.env').items() if v is not None},**os.environ,'NEXT_TELEMETRY_DISABLED':'1'}
python=str(root/'.venv/bin/python')
commands=[([python,'-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000','--no-proxy-headers'],root/'backend'),([python,'-m','app.worker'],root/'backend'),(['npm','run','start' if args.production else 'dev'],root/'frontend')]
children=[]
def stop(*_):
    for p in children:
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    for p in children:
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:(stop(),sys.exit(0)))
try:
    for cmd,cwd in commands:children.append(subprocess.Popen(cmd,cwd=cwd,env=env,start_new_session=True))
    while all(p.poll() is None for p in children):time.sleep(1)
    code=next((p.returncode for p in children if p.returncode is not None),1)
finally:stop()
sys.exit(code or 1)
