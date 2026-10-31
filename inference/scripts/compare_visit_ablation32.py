"""Paired, completed-case comparison of the visit 32-case experiment."""
import collections
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'workspace/strict-reproduction'
BASE = ROOT / 'browsecomp-pro6000-nvfp4-embedding-128-20261031-r1'
SUMMARY = ROOT / 'browsecomp-visit-summary27b-32-20261031-r1'
KINDS = ('policy_model', 'summary', 'memory_api')


def measure(root, case, state):
    result = json.loads(Path(state['result_path']).read_text().splitlines()[-1])
    kinds = {k: collections.Counter() for k in KINDS}
    for line in (root / 'logs' / f'{case}-agent-events.jsonl').open():
        e = json.loads(line)
        if e.get('event') != 'span_end' or e.get('kind') not in KINDS:
            continue
        c = kinds[e['kind']]; c['calls'] += 1; c['seconds'] += e.get('seconds', 0)
        response = e.get('api_response')
        usage = response.get('usage') if isinstance(response, dict) else None
        if isinstance(usage, dict) and type(usage.get('prompt_tokens')) is int and type(usage.get('completion_tokens')) is int:
            c['measured'] += 1; c['input'] += usage['prompt_tokens']; c['output'] += usage['completion_tokens']
            detail = usage.get('prompt_tokens_details') or {}
            if isinstance(detail, dict) and type(detail.get('cached_tokens')) is int:
                c['cache_measured'] += 1; c['cache'] += detail['cached_tokens']
    return {'correct': state['is_correct'], 'rounds': result['num_rounds'],
            'agent_seconds': state['agent_ended_epoch']-state['agent_started_epoch'],
            'kinds': {k: dict(v) for k,v in kinds.items()}}


def aggregate(rows):
    out = {'n': len(rows), 'correct': sum(x['correct'] for x in rows),
           'rounds_mean': statistics.mean(x['rounds'] for x in rows),
           'rounds_median': statistics.median(x['rounds'] for x in rows),
           'seconds_mean': statistics.mean(x['agent_seconds'] for x in rows),
           'seconds_median': statistics.median(x['agent_seconds'] for x in rows)}
    for kind in KINDS:
        values = [x['kinds'][kind] for x in rows]
        total = {key: sum(v.get(key, 0) for v in values) for key in ('calls','measured','input','output','cache_measured','cache','seconds')}
        out[kind] = total
    return out


def main():
    a = json.loads((BASE/'status.json').read_text()); b = json.loads((SUMMARY/'status.json').read_text())
    paired = []
    for case, state in b['cases'].items():
        baseline = a['cases'].get(case, {})
        if state.get('agent_state') == 'terminal' and state.get('judge_state') == 'scored' and type(state.get('is_correct')) is bool and baseline.get('judge_state') == 'scored' and type(baseline.get('is_correct')) is bool:
            paired.append({'case': case, 'baseline': measure(BASE, case, baseline), 'summary': measure(SUMMARY, case, state)})
    if not paired: raise SystemExit('No paired scored cases')
    out = {'status_epoch': b['epoch'], 'n': len(paired), 'status_counts': dict(collections.Counter(x['agent_state'] for x in b['cases'].values())),
           'baseline': aggregate([x['baseline'] for x in paired]), 'summary': aggregate([x['summary'] for x in paired]),
           'transitions': dict(collections.Counter(f"{int(x['baseline']['correct'])}->{int(x['summary']['correct'])}" for x in paired)),
           'cases': paired}
    target = SUMMARY/'checks/paired-comparison-latest.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k != 'cases'}, ensure_ascii=False, indent=2))
    print('case outcomes:')
    for x in paired:
        print(x['case'], int(x['baseline']['correct']), int(x['summary']['correct']), x['baseline']['rounds'], x['summary']['rounds'], round(x['baseline']['agent_seconds']/60,1), round(x['summary']['agent_seconds']/60,1))


if __name__ == '__main__': main()
