"""Pause this trial if all Jina credentials are exhausted or invalid."""
import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SECRET = REPO / 'workspace/strict-reproduction/.secrets'
RUN = REPO / 'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'


def exhausted(secret=SECRET):
    with (secret/'key_rotation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        pool = json.loads((secret/'api_key_pool.json').read_text())['jina']
        state = json.loads((secret/'key_rotation_state.json').read_text()).get('jina', {})
        return bool(pool) and set(range(len(pool))).issubset(set(state.get('exhausted', [])))


def pause_trial(pid):
    proc = Path('/proc')/str(pid)
    if b'inference/scripts/run_gaia_retrieval_ab.py' not in (proc/'cmdline').read_bytes():
        raise RuntimeError('controller PID does not match the expected trial')
    os.kill(pid, signal.SIGSTOP)
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            status = dict(line.split(':', 1) for line in (path/'status').read_text().splitlines() if ':' in line)
            if int(status['PPid'].strip()) == pid and not status['State'].strip().startswith('Z'):
                os.kill(int(path.name), signal.SIGSTOP)
        except (OSError, KeyError, ValueError):
            continue
    inventory = RUN/'adopt-active.json'
    if inventory.exists():
        for item in json.loads(inventory.read_text()):
            try:
                process = Path('/proc')/str(item['pid'])
                values = dict(x.split('=', 1) for x in process.joinpath('environ').read_bytes().decode(errors='replace').split('\0') if '=' in x)
                if values.get('QUEST_AUDIT_CASE') == item['case'] and Path(values.get('QUEST_AB_GROUP_ROOT', '')).name == item['group']:
                    os.kill(item['pid'], signal.SIGSTOP)
            except (OSError, KeyError, ValueError):
                continue
    target = RUN/'runtime-status.json'
    tmp = target.with_suffix('.tmp')
    try:
        runtime = json.loads(target.read_text())
    except (OSError, ValueError):
        runtime = {}
    runtime.update(state='paused', reason='Jina Reader 密钥池不可用，等待恢复', time=time.time())
    tmp.write_text(json.dumps(runtime, ensure_ascii=False))
    tmp.replace(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--controller-pid', type=int, required=True)
    args = parser.parse_args()
    while (Path('/proc')/str(args.controller_pid)).exists():
        if exhausted():
            pause_trial(args.controller_pid)
            print('Jina pool exhausted; trial paused.', flush=True)
            break
        time.sleep(5)
