"""Reconcile retries after an already-running direct-phase controller exits."""
import fcntl
import concurrent.futures
import json
import os
import queue
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from inference.retry_manifest import complete_retry
RUN = REPO / 'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'
DIRECT = {'baseline', 'bm25-direct', 'embedding-direct', 'bm25-reranker-direct',
          'hybrid-direct', 'hybrid-reranker-direct'}

with (RUN / 'controller.lock').open('r') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    state = json.loads((RUN / 'controller-state.json').read_text())['groups']
    complete = set(state) == DIRECT and all(
        len(rows) == 32 and all(row.get('agent_state') == 'terminal' for row in rows.values())
        for rows in state.values())
    fcntl.flock(lock, fcntl.LOCK_UN)

if complete:
    retry_lock = (RUN/'checks/retry-runner.lock').open('a+')
    fcntl.flock(retry_lock, fcntl.LOCK_EX)
    retry_path = RUN / 'checks/retry-required.json'
    retries = json.loads(retry_path.read_text()) if retry_path.exists() else {'cases': []}
    timeout = re.compile(r'Summary Content \[visit\] Error:.*127\.0\.0\.1.*Read timed out|All Jina keys are exhausted or invalid')
    flagged = []
    for group in sorted(DIRECT - {'baseline', 'bm25-direct'}):
        for log in sorted((RUN / group / 'logs').glob('row*-agent.stdout.log')):
            if timeout.search(log.read_text(errors='replace')):
                case = log.name.split('-')[0]
                if not any(x.get('group') == group and x.get('case') == case for x in retries['cases']):
                    retries['cases'].append({'group': group, 'case': case, 'status': 'pending_retry',
                                             'reason': 'retrieval_or_reader_unavailable'})
                flagged.append((group, case))
        for case, row in state[group].items():
            if row.get('judge_state') != 'scored' and (group, case) not in flagged:
                if not any(x.get('group') == group and x.get('case') == case for x in retries['cases']):
                    retries['cases'].append({'group': group, 'case': case, 'status': 'pending_retry',
                                             'reason': 'missing_official_score'})
                flagged.append((group, case))
    for item in retries['cases']:
        pair = (item.get('group'), item.get('case'))
        if item.get('status') == 'pending_retry' and pair[0] in DIRECT and pair not in flagged:
            flagged.append(pair)
    tmp = retry_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(retries, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(retry_path)
    pending = [(group, case) for group, case in flagged
               if next(x for x in retries['cases'] if x.get('group') == group and x.get('case') == case).get('status') != 'completed']
    gpu_slots = queue.Queue()
    for port in (18210, 18201, 18202):
        for _ in range(8):
            gpu_slots.put(port)
    def run_retry(item):
        group, case = item
        port = gpu_slots.get()
        try:
            secret = REPO/'workspace/strict-reproduction/.secrets'
            with (secret/'key_rotation.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                pool = json.loads((secret/'api_key_pool.json').read_text())['jina']
                rotation = json.loads((secret/'key_rotation_state.json').read_text()).get('jina', {})
                if not pool or set(range(len(pool))).issubset(set(rotation.get('exhausted', []))):
                    print('Reader pool unavailable; leaving retry pending:', group, case, flush=True)
                    return 1
            print('Retrying affected case:', group, case, flush=True)
            result = subprocess.call([sys.executable, '-u', str(REPO / 'inference/scripts/retry_gaia_retrieval_case.py'), group, case],
                                     env=dict(os.environ, QUEST_RETRY_PORT=str(port)))
            if result:
                complete_retry(retry_path, group, case, {'status':'pending_retry'})
            return result
        finally:
            gpu_slots.put(port)
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        results = list(executor.map(run_retry, pending))
    if any(results):
        print('One or more retries failed; leaving decision pending.', flush=True)
        sys.exit(1)
    print('Direct phase finished; reconciling corrected scores and conditional Flash decision.', flush=True)
    sys.exit(subprocess.call([sys.executable, '-u', str(REPO / 'inference/scripts/run_gaia_retrieval_ab.py'), '--resume-direct-complete']))
print('No reconciliation started: direct phase incomplete or summary phase already exists.', flush=True)
