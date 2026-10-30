"""Reconcile the conditional Flash decision using reruns and missing scores."""
import json
from pathlib import Path

DIRECT = ('bm25-direct', 'embedding-direct', 'bm25-reranker-direct', 'hybrid-direct', 'hybrid-reranker-direct')


def decide(groups, retries, threshold=3):
    names = ('baseline',) + DIRECT
    if any(name not in groups or len(groups[name]) != 32 for name in names):
        return {'decision': 'pending', 'reason': 'missing_groups_or_cases'}
    if any(set(groups[name]) != set(groups['baseline']) for name in DIRECT):
        return {'decision': 'inconclusive', 'reason': 'case_sets_differ'}
    if any(row.get('agent_state') != 'terminal' for name in names for row in groups[name].values()):
        return {'decision': 'pending', 'reason': 'direct_phase_running'}
    updated = {name: {case: dict(row) for case,row in groups[name].items()} for name in names}
    for item in retries:
        name,case = item.get('group'),item.get('case')
        if name not in updated or case not in updated[name]: continue
        if item.get('status') != 'completed' or not isinstance(item.get('is_correct'),bool):
            return {'decision': 'pending', 'reason': 'retry_incomplete', 'group': name, 'case': case}
        updated[name][case].update(judge_state='scored',is_correct=item['is_correct'])
    missing = [(name,case) for name in names for case,row in updated[name].items()
               if row.get('judge_state') != 'scored' or not isinstance(row.get('is_correct'),bool)]
    if missing:
        return {'decision':'inconclusive','reason':'missing_scores','missing':missing}
    counts = {name:sum(row['is_correct'] for row in updated[name].values()) for name in names}
    rank = sorted(DIRECT,key=lambda name:(-counts[name],name))
    gap = counts['baseline'] - counts[rank[0]]
    return {'decision':'run_flash' if gap >= threshold else 'skip_flash', 'counts': counts,
            'baseline_minus_best':gap, 'threshold_tasks':threshold,
            'selected':rank[:3] if gap >= threshold else [], 'ranking':rank}


def reconcile(root):
    root = Path(root)
    state = json.loads((root/'controller-state.json').read_text())['groups']
    path = root/'checks/retry-required.json'
    retries = json.loads(path.read_text()).get('cases',[]) if path.exists() else []
    return decide(state,retries)


if __name__ == '__main__':
    import sys
    print(json.dumps(reconcile(sys.argv[1]),ensure_ascii=False,indent=2))
