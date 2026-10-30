"""Use spare 4B task slots for flagged retries while the direct phase drains."""
import fcntl
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from inference.retry_manifest import complete_retry
RUN = REPO/'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'
SECRET = REPO/'workspace/strict-reproduction/.secrets'
PORTS = (18210,18201,18202)


def reader_available():
    with (SECRET/'key_rotation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        pool = json.loads((SECRET/'api_key_pool.json').read_text())['jina']
        state = json.loads((SECRET/'key_rotation_state.json').read_text()).get('jina', {})
        return bool(pool) and not set(range(len(pool))).issubset(set(state.get('exhausted', [])))


def original_load():
    state = json.loads((RUN/'controller-state.json').read_text())['groups']
    load = Counter()
    for group, rows in state.items():
        for case, row in rows.items():
            if row.get('agent_state') == 'pending':
                raise RuntimeError('early retries require no pending original cases')
            if row.get('agent_state') == 'running':
                lines = (RUN/group/'configs'/f'{case}-server_endpoints.conf').read_text().splitlines()
                port = int(next(line.split('=',1)[1] for line in lines if line.startswith('PORTS=')))
                if port not in PORTS: raise RuntimeError('unexpected 4B port')
                load[port] += 1
    return load


def main():
    with (RUN/'checks/retry-runner.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        running = {}
        attempted = set()
        while True:
            for pair, (proc, port, output) in list(running.items()):
                rc = proc.poll()
                if rc is None: continue
                output.close()
                del running[pair]
                if rc:
                    complete_retry(RUN/'checks/retry-required.json', pair[0], pair[1], {'status':'pending_retry'})
                print('retry finished', pair[0], pair[1], 'exit', rc, flush=True)
            rows = json.loads((RUN/'checks/retry-required.json').read_text())['cases']
            pending = [(x['group'],x['case']) for x in rows if x.get('status') == 'pending_retry' and (x['group'],x['case']) not in attempted]
            if not pending and not running:
                print('Early retry queue drained.', flush=True)
                return
            if reader_available():
                load = original_load()
                load.update(port for _, port, _ in running.values())
                for group, case in pending:
                    available = [port for port in PORTS if load[port] < 8]
                    if not available: break
                    port = min(available, key=lambda p: (load[p],PORTS.index(p)))
                    output = (RUN/'checks'/f'early-retry-{group}-{case}.log').open('w')
                    proc = subprocess.Popen([sys.executable,'-u',str(REPO/'inference/scripts/retry_gaia_retrieval_case.py'),group,case],
                                            env=dict(os.environ,QUEST_RETRY_PORT=str(port)),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                    running[group,case] = proc,port,output
                    attempted.add((group,case)); load[port] += 1
                    print('started retry',group,case,'port',port,flush=True)
            elif not running:
                print('Reader pool unavailable; pending retries remain for recovery.', flush=True)
                return
            time.sleep(5)


if __name__ == '__main__':
    main()
