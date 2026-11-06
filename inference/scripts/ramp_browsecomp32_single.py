"""Slowly adjust agent concurrency based on both vLLM servers' pressure."""
import json
import math
import os
from pathlib import Path
import re
import time
import requests

RUN = Path(__file__).resolve().parents[2] / 'workspace/strict-reproduction/browsecomp-v11-bf16-lora-summary32-singlemodel-20261101-r1'
FLOOR, CEILING, INTERVAL, STABLE_SECONDS = 4, 32, 10, 120
pid = json.loads((RUN / 'checks/launcher-pid.json').read_text())['pid']
previous = {}
last_change = None
stable_since = None
waiting_streak = high_kv_streak = 0


def alive():
    try:
        s = Path(f'/proc/{pid}/stat').read_text()
        return s[s.rfind(')')+2:].split()[0] not in ('Z', 'X')
    except (FileNotFoundError, ProcessLookupError): return False


def metrics(port):
    text = requests.get(f'http://127.0.0.1:{port}/metrics', timeout=5).text
    found = {}
    for key in ('kv_cache_usage_perc', 'num_requests_running', 'num_requests_waiting', 'num_preemptions_total'):
        values = []
        for line in text.splitlines():
            if re.match(r'^vllm:' + key + r'(?:\{|\s)', line):
                value = float(line.split()[-1])
                if math.isfinite(value): values.append(value)
        if not values: raise ValueError('Missing metric: ' + key)
        found[key] = max(values) if key == 'kv_cache_usage_perc' else sum(values)
    return found


def log(data):
    with (RUN / 'checks/concurrency-decisions.jsonl').open('a') as f:
        f.write(json.dumps(dict(epoch=time.time(), **data), ensure_ascii=False) + '\n')


while alive():
    state_path = RUN / 'status.json'
    if not state_path.exists():
        time.sleep(INTERVAL)
        continue
    state = json.loads(state_path.read_text())['cases']
    if last_change is None:
        # Loading servers can take minutes; start the stability window only
        # once agents actually become eligible to run.
        last_change = time.monotonic()
    if all(x.get('agent_state') == 'terminal' and x.get('judge_state') not in ('pending', 'running') for x in state.values()):
        log({'event': 'complete'})
        break
    try:
        current = {port: metrics(port) for port in (19320,)}
        new_preemptions = sum(max(0, m['num_preemptions_total'] - previous.get(port, m)['num_preemptions_total'])
                              for port, m in current.items())
        previous = current
        waiting = any(m['num_requests_waiting'] > 0 for m in current.values())
        max_kv = max(m['kv_cache_usage_perc'] for m in current.values())
        waiting_streak = waiting_streak + 1 if waiting else 0
        high_kv_streak = high_kv_streak + 1 if max_kv >= .90 else 0
        limit_path = RUN / 'agent-concurrency-limit'
        limit = int(limit_path.read_text())
        now = time.monotonic()
        if waiting or max_kv >= .70 or new_preemptions:
            stable_since = None
        elif stable_since is None:
            stable_since = now
        reason = None
        if new_preemptions or high_kv_streak >= 2 or waiting_streak >= 3:
            desired = max(FLOOR, limit - 2)
            if desired != limit:
                reason = 'preemption' if new_preemptions else 'high_kv' if high_kv_streak >= 2 else 'persistent_queue'
        elif (stable_since is not None and now - stable_since >= STABLE_SECONDS
              and now - last_change >= STABLE_SECONDS
              and any(x.get('agent_state') == 'pending' for x in state.values())):
            desired = min(CEILING, limit + 2)
            if desired != limit: reason = 'stable_low_pressure'
        else:
            desired = limit
        if reason:
            temp = limit_path.with_suffix('.tmp')
            temp.write_text(f'{desired}\n')
            os.replace(temp, limit_path)
            last_change = now
            stable_since = None
            waiting_streak = high_kv_streak = 0
        log({'event': 'adjust' if reason else 'observe', 'reason': reason, 'before': limit, 'after': desired,
             'new_preemptions': new_preemptions, 'servers': current})
    except Exception as exc:
        stable_since = None
        log({'event': 'metrics_unavailable_hold', 'error': type(exc).__name__ + ': ' + str(exc)})
    time.sleep(INTERVAL)
