"""Verify a restored Jina pool and resume the deliberately suspended trial.

No credentials are printed. A non-200 probe does not clear an exhausted key.
Invoke only after replenishing the pool; this script is never run by the
background controller or the website.
"""
import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
SECRETS = REPO / 'workspace/strict-reproduction/.secrets'
RUN = REPO / 'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'


def check_keys(keys, get=requests.get):
    usable = []
    statuses = []
    for index, key in enumerate(keys):
        try:
            token = key if key.lower().startswith('bearer ') else 'Bearer ' + key
            response = get('https://r.jina.ai/https://example.com',
                           headers={'Authorization': token}, timeout=(10, 30))
            status = response.status_code
            response.close()
        except requests.RequestException:
            status = None
        statuses.append(status)
        if status == 200:
            usable.append(index)
    return usable, statuses


def restore_pool(secret_dir, get=requests.get):
    secret_dir = Path(secret_dir)
    lock_path = secret_dir / 'key_rotation.lock'
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pool = json.loads((secret_dir / 'api_key_pool.json').read_text())
        keys = pool['jina']
        fcntl.flock(lock, fcntl.LOCK_UN)
        usable, statuses = check_keys(keys, get)
        if not usable:
            return statuses, False
        fcntl.flock(lock, fcntl.LOCK_EX)
        if json.loads((secret_dir / 'api_key_pool.json').read_text())['jina'] != keys:
            raise RuntimeError('Jina pool changed during verification; no rotation state updated')
        state_path = secret_dir / 'key_rotation_state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        jina = state.setdefault('jina', {})
        jina['exhausted'] = [i for i in jina.get('exhausted', []) if i not in usable]
        jina['current'] = usable[0]
        temp = state_path.with_name(state_path.name + '.restore.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(state, handle)
        os.replace(temp, state_path)
        return statuses, True


def resume_processes(pid):
    proc = Path('/proc') / str(pid)
    command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ')
    state = (proc / 'status').read_text()
    if b'inference/scripts/run_gaia_retrieval_ab.py' not in command or '\nState:\tT' not in state:
        raise RuntimeError('expected suspended experiment controller not found')
    children = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            status = (path / 'status').read_text()
            fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
            if int(fields['PPid'].strip()) == pid and fields['State'].strip().startswith('T'):
                children.append(int(path.name))
        except (OSError, KeyError, ValueError):
            continue
    for child in children:
        try:
            os.kill(child, signal.SIGCONT)
        except ProcessLookupError:
            pass
    inventory = RUN/'adopt-active.json'
    if inventory.exists():
        for item in json.loads(inventory.read_text()):
            try:
                process = Path('/proc')/str(item['pid'])
                values = dict(x.split('=', 1) for x in process.joinpath('environ').read_bytes().decode(errors='replace').split('\0') if '=' in x)
                if values.get('QUEST_AUDIT_CASE') == item['case'] and Path(values.get('QUEST_AB_GROUP_ROOT', '')).name == item['group']:
                    os.kill(item['pid'], signal.SIGCONT)
            except (OSError, KeyError, ValueError):
                continue
    os.kill(pid, signal.SIGCONT)
    return len(children)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--controller-pid', required=True, type=int)
    args = parser.parse_args()
    # Verify the controller before changing rotation state or making a request.
    proc = Path('/proc') / str(args.controller_pid)
    if not proc.exists() or b'inference/scripts/run_gaia_retrieval_ab.py' not in (proc / 'cmdline').read_bytes() or '\nState:\tT' not in (proc / 'status').read_text():
        raise SystemExit('Suspended controller is unavailable; no state changed.')
    statuses, restored = restore_pool(SECRETS)
    print('Jina probe HTTP statuses by key index:', statuses, flush=True)
    if not restored:
        raise SystemExit('No usable Jina key; experiment remains paused.')
    count = resume_processes(args.controller_pid)
    status_path = RUN / 'runtime-status.json'
    temp = status_path.with_suffix('.tmp')
    try:
        runtime = json.loads(status_path.read_text())
    except (OSError, ValueError):
        runtime = {}
    runtime.update(state='running', time=time.time())
    runtime.pop('reason', None)
    temp.write_text(json.dumps(runtime, ensure_ascii=False))
    temp.replace(status_path)
    print('Resumed controller and', count, 'suspended child processes.', flush=True)
