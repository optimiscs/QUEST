"""Start the local restricted Python service if it is not already running."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'workspace/strict-reproduction/sandbox-isolated'


def ready():
    try:
        with urlopen('http://127.0.0.1:8080/health', timeout=2) as response:
            return json.load(response).get('backend') == 'isolated-python'
    except Exception:
        return False


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'server.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ready():
            print('Python sandbox already running')
            return
        with (STATE / 'server.log').open('a') as log:
            process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'inference/scripts/isolated_python_service.py')],
                                       cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        (STATE / 'server.pid').write_text(str(process.pid) + '\n')
        for _ in range(50):
            if ready():
                print(f'Python sandbox started: PID {process.pid}')
                return
            if process.poll() is not None:
                raise RuntimeError(f'Python sandbox exited; check {STATE / "server.log"}')
            time.sleep(.1)
        raise RuntimeError('Python sandbox did not become ready')


if __name__ == '__main__':
    main()
