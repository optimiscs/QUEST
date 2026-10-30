"""Publish measurements from experiment event logs without changing scores."""
import json
import math
import re
import subprocess
import time
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from evaluation.gaia_retrieval_decision import reconcile
RUN = REPO / 'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'
DEST = REPO / 'web/trace-viewer/datasets/gaia-retrieval-ab-metrics.json'


def percentile(values, p):
    if not values: return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * p) - 1], 3)


def paired_comparison(baseline, treatment):
    """Compare only cases scored in both groups; preserve missingness."""
    both = [(base, treatment[case]) for case, base in baseline.items()
            if case in treatment and base.get('judge_state') == 'scored'
            and treatment[case].get('judge_state') == 'scored'
            and isinstance(base.get('is_correct'), bool)
            and isinstance(treatment[case].get('is_correct'), bool)]
    better = sum(not base['is_correct'] and other['is_correct'] for base, other in both)
    worse = sum(base['is_correct'] and not other['is_correct'] for base, other in both)
    n = better + worse
    # Exact two-sided McNemar p-value; small samples are reported, not declared equivalent.
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(better, worse) + 1)) / (2 ** n)) if n else None
    return {'paired_scored': len(both), 'treatment_only_correct': better,
            'baseline_only_correct': worse, 'both_correct': sum(a['is_correct'] and b['is_correct'] for a,b in both),
            'both_wrong': sum(not a['is_correct'] and not b['is_correct'] for a,b in both), 'mcnemar_exact_p': p}


def calculate():
    groups = {}
    retry_path = RUN / 'checks/retry-required.json'
    retry_cases = set()
    running_retry_cases = set()
    completed_retries = {}
    if retry_path.exists():
        retries = json.loads(retry_path.read_text()).get('cases', [])
        retry_cases = {(x['group'], x['case']) for x in retries if x.get('status') in ('pending_retry', 'running_retry')}
        running_retry_cases = {(x['group'], x['case']) for x in retries if x.get('status') == 'running_retry'}
        completed_retries = {(x['group'],x['case']): x for x in retries if x.get('status') == 'completed' and isinstance(x.get('is_correct'),bool)}
    for root in RUN.iterdir():
        if not (root / 'status.json').exists(): continue
        unavailable_reader = re.compile(r'Summary Content \[visit\] Error:.*127\.0\.0\.1.*Read timed out|All Jina keys are exhausted or invalid')
        for path in (root/'logs').glob('row*-agent.stdout.log'):
            case = path.name.split('-')[0]
            if (root.name, case) not in completed_retries and unavailable_reader.search(path.read_text(errors='replace')):
                retry_cases.add((root.name, case))
        events = []; retrieval = []
        retry_root = RUN/'retries'/root.name
        event_paths = list((root/'logs').glob('row*-agent-events.jsonl')) + list(retry_root.rglob('row*-agent-events.jsonl'))
        for path in event_paths:
            for line in path.open():
                try: events.append(json.loads(line))
                except ValueError: continue
        retrieval_paths = list((root/'logs').glob('row*-retrieval.jsonl')) + list(retry_root.rglob('row*-retrieval.jsonl'))
        for path in retrieval_paths:
            for line in path.open():
                try: retrieval.append(json.loads(line))
                except ValueError: continue
        status = json.loads((root/'status.json').read_text())
        result = {'cases': {case: {'agent_state': 'running' if (root.name, case) in running_retry_cases else row.get('agent_state'),
                                   'judge_state': 'needs_retry' if (root.name, case) in retry_cases else row.get('judge_state'),
                                   'is_correct': None if (root.name, case) in retry_cases else row.get('is_correct')}
                            for case, row in status.get('cases', {}).items()}}
        for (group, case), retry in completed_retries.items():
            if group == root.name and case in result['cases']:
                result['cases'][case].update(agent_state='terminal',judge_state='scored',is_correct=retry['is_correct'],retry=True)
        for role in ('task', 'summary', 'policy_model', 'memory_api'):
            ends = [e for e in events if e.get('event') == 'span_end' and e.get('kind') == role]
            usage = [(e.get('api_response') or {}).get('usage') or {} for e in ends]
            times = [e['seconds'] for e in ends if isinstance(e.get('seconds'), (int,float))]
            result[role] = {'calls': len(ends), 'latency_p50_s': percentile(times,.5), 'latency_p95_s': percentile(times,.95),
                            'prompt_tokens': sum(x.get('prompt_tokens') or 0 for x in usage),
                            'completion_tokens': sum(x.get('completion_tokens') or 0 for x in usage),
                            'cached_tokens': sum((x.get('prompt_tokens_details') or {}).get('cached_tokens') or 0 for x in usage),
                            'reasoning_tokens': sum((x.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0 for x in usage),
                            'cached_reported_calls': sum((x.get('prompt_tokens_details') or {}).get('cached_tokens') is not None for x in usage),
                            'reasoning_reported_calls': sum((x.get('completion_tokens_details') or {}).get('reasoning_tokens') is not None for x in usage),
                            'usage_reported_calls': sum(bool(x) for x in usage)}
        elapsed = [x['total_seconds'] for x in retrieval if isinstance(x.get('total_seconds'), (int,float))]
        result['retrieval'] = {'requests': len(retrieval), 'latency_p50_s': percentile(elapsed,.5), 'latency_p95_s': percentile(elapsed,.95),
                               'input_tokens': sum(x.get('input_tokens') or 0 for x in retrieval),
                               'output_tokens': sum(x.get('output_tokens') or 0 for x in retrieval)}
        groups[root.name] = result
    baseline = groups.get('baseline', {}).get('cases', {})
    pairs = {group: paired_comparison(baseline, value.get('cases', {})) for group,value in groups.items() if group != 'baseline'}
    try: decision = reconcile(RUN)
    except (OSError,ValueError,KeyError): decision = {'decision':'pending','reason':'state_unavailable'}
    models = {}
    for name in ('Qwen3-Embedding-8B', 'Qwen3-Reranker-8B'):
        root = REPO/'workspace/models'/name
        try:
            shards = set(json.loads((root/'model.safetensors.index.json').read_text())['weight_map'].values())
            models[name] = {'ready_shards':sum((root/shard).is_file() for shard in shards), 'total_shards':len(shards)}
        except (OSError, ValueError, KeyError):
            models[name] = {'ready_shards':0,'total_shards':None}
    try: runtime = json.loads((RUN/'runtime-status.json').read_text())
    except (OSError, ValueError): runtime = {'state': 'running'}
    return {'updated': time.time(), 'groups': groups, 'paired': pairs, 'decision': decision, 'models':models, 'runtime': runtime}


if __name__ == '__main__':
    while True:
        data = calculate()
        tmp = DEST.with_suffix('.tmp'); tmp.write_text(json.dumps(data, ensure_ascii=False)); tmp.replace(DEST)
        try:
            manifest = json.loads((RUN/'checks/retry-required.json').read_text())
            groups = {x.get('group') for x in manifest.get('cases', []) if x.get('status') == 'running_retry'}
            for group in sorted(groups & {'baseline','bm25-direct','embedding-direct','bm25-reranker-direct','hybrid-direct','hybrid-reranker-direct'}):
                subprocess.run([sys.executable, str(REPO/'web/build_gaia.py'), '--run-root', str(RUN/group),
                                '--output-dir', str(REPO/'web/trace-viewer/datasets'/('gaia-retrieval-ab-20261029-'+group)),
                                '--label', 'GAIA32 '+group, '--include-running', '--replace-existing'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(30)
