"""Start both API and Streamlit. Dependencies: pip install -r requirements.txt."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import shutil

root = Path(__file__).resolve().parent
if not (root / '.env').exists():
    shutil.copyfile(root / '.env.example', root / '.env')
env = os.environ.copy()
env['PYTHONPATH'] = str(root / 'backend') + os.pathsep + env.get('PYTHONPATH','')
processes = []
try:
    api = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000'], cwd=root, env=env)
    processes.append(api)
    for _ in range(80):
        if api.poll() is not None:
            raise SystemExit('API failed to start; check the output above and port 8000.')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1):
                break
        except OSError:
            time.sleep(.25)
    else:
        raise SystemExit('API startup timed out.')
    ui = subprocess.Popen([sys.executable,'-m','streamlit','run','streamlit_app.py','--server.address','127.0.0.1',
                           '--server.port','8501','--browser.gatherUsageStats','false'],cwd=root,env=env)
    processes.append(ui)
    print('Open http://localhost:8501 | API docs: http://localhost:8000/docs', flush=True)
    while all(p.poll() is None for p in processes):
        time.sleep(.5)
except KeyboardInterrupt:
    pass
finally:
    for p in processes:
        if p.poll() is None:
            p.terminate()
    for p in processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
