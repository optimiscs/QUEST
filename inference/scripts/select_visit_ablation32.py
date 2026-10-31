"""Select a deterministic, outcome/round-stratified visit ablation cohort."""
import collections
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'workspace/strict-reproduction/browsecomp-pro6000-nvfp4-embedding-128-20261031-r1'
OUT = ROOT / 'workspace/strict-reproduction/browsecomp-visit-ablation32-20261031-r1'
BINS = [('1-20', 1, 20, 5), ('21-40', 21, 40, 5), ('41-80', 41, 80, 4), ('81-200', 81, 200, 2)]


def main():
    raw = (RUN / 'status.json').read_bytes()
    status = json.loads(raw)
    refs = json.loads((RUN / 'judge/ground-truth/references.json').read_text())
    ref_cases = {r['case'] for r in refs}
    candidates = collections.defaultdict(list)
    all_states = collections.Counter()
    problems = []
    for case, state in sorted(status['cases'].items()):
        all_states[(state.get('agent_state'), state.get('judge_state'))] += 1
        outcome = state.get('is_correct')
        if state.get('agent_state') != 'terminal' or state.get('judge_state') != 'scored' or type(outcome) is not bool:
            continue
        try:
            result_path = Path(state['result_path'])
            data = result_path.read_bytes()
            result = json.loads(data.splitlines()[-1])
            turns = result['num_rounds']
            if type(turns) is not int or case not in ref_cases:
                raise ValueError('invalid rounds or missing reference')
            log = RUN / 'logs' / f'{case}-retrieval.jsonl'
            reasons = collections.Counter(json.loads(x).get('reason') for x in log.open()) if log.is_file() else collections.Counter()
            if not reasons['selected']:
                continue
            label = next(name for name, low, high, _ in BINS if low <= turns <= high)
            start, end = state.get('agent_started_epoch'), state.get('agent_ended_epoch')
            duration = round(end-start, 2) if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start else None
            candidates[outcome, label].append({'case': case, 'baseline_correct': outcome, 'rounds': turns,
                'round_bin': label, 'selected_pages': reasons['selected'], 'short_page_bypass': reasons['short_page'],
                'baseline_agent_seconds': duration, 'result_sha256': hashlib.sha256(data).hexdigest(),
                'result_path': str(result_path), 'judge_path': str(RUN / 'checks' / f'{case}-local-judge.json')})
        except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
            problems.append({'case': case, 'reason': str(exc)})
    chosen = []
    availability = {}
    for outcome in (True, False):
        for label, _, _, count in BINS:
            pool = sorted(candidates[outcome, label], key=lambda x: (x['rounds'], x['case']))
            availability[f'{outcome}:{label}'] = len(pool)
            if len(pool) < count:
                raise RuntimeError(f'insufficient eligible cases: {outcome} {label}: {len(pool)}')
            # Midpoints of equal-sized quantile intervals, not random sampling.
            chosen.extend(pool[((2*i+1)*len(pool))//(2*count)] for i in range(count))
    assert len(chosen) == 32 and len({r['case'] for r in chosen}) == 32
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'cases.json').write_text(json.dumps([x['case'] for x in chosen], indent=2) + '\n')
    (OUT / 'selection.json').write_text(json.dumps(chosen, indent=2, ensure_ascii=False) + '\n')
    (OUT / 'configs').mkdir()
    for row in chosen:
        source = RUN / 'configs' / f"{row['case']}.jsonl"
        (OUT / 'configs' / source.name).write_bytes(source.read_bytes())
    judge_dir = OUT / 'judge' / 'ground-truth'
    judge_dir.mkdir(parents=True, mode=0o700)
    by_case = {r['case']: r for r in refs}
    (judge_dir / 'references.json').write_text(json.dumps([by_case[x['case']] for x in chosen], ensure_ascii=False, indent=2) + '\n')
    (judge_dir / 'references.json').chmod(0o600)
    with (OUT / 'selection.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(chosen[0])); w.writeheader(); w.writerows(chosen)
    summary = {'created_utc': datetime.now(timezone.utc).isoformat(), 'source_status_sha256': hashlib.sha256(raw).hexdigest(),
        'source_status_epoch': status.get('epoch'), 'source_run': str(RUN), 'status_counts': {str(k): v for k,v in all_states.items()},
        'eligible_by_group': availability, 'excluded_errors': problems,
        'method': 'terminal scored boolean, >=1 logged selected webpage, fixed 5/5/4/2 per round stratum per outcome; deterministic within-bin quantile midpoints',
        'rounds_min': min(x['rounds'] for x in chosen), 'rounds_median': statistics.median(x['rounds'] for x in chosen),
        'rounds_max': max(x['rounds'] for x in chosen), 'total_baseline_agent_hours': round(sum(x['baseline_agent_seconds'] or 0 for x in chosen)/3600,2),
        'n': len(chosen)}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
