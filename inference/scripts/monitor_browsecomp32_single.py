"""Continuously compare only scored pairs against the fixed summary baseline."""
import collections
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2] / 'workspace/strict-reproduction'
OLD = ROOT / 'browsecomp-visit-summary27b-32-20261031-r1'
NEW = ROOT / 'browsecomp-v11-bf16-lora-summary32-singlemodel-20261101-r1'
old = json.loads((OLD / 'status.json').read_text())['cases']
pid = json.loads((NEW / 'checks/launcher-pid.json').read_text())['pid']


def alive():
    try:
        status = Path(f'/proc/{pid}/stat').read_text()
        return status[status.rfind(')') + 2:].split()[0] not in ('Z', 'X')
    except (FileNotFoundError, ProcessLookupError):
        return False


while True:
    state = NEW / 'status.json'
    if state.exists():
        current = json.loads(state.read_text())['cases']
        pairs = []
        for case, item in current.items():
            prior = old.get(case, {})
            if (item.get('judge_state') == prior.get('judge_state') == 'scored'
                    and type(item.get('is_correct')) is bool and type(prior.get('is_correct')) is bool):
                pairs.append({'case': case, 'baseline_correct': prior['is_correct'],
                              'finetuned_correct': item['is_correct']})
        counts = collections.Counter((x['baseline_correct'], x['finetuned_correct']) for x in pairs)
        report = {'baseline': str(OLD), 'candidate': str(NEW), 'expected_cases': 32,
                  'baseline_scored': sum(x.get('judge_state') == 'scored' for x in old.values()),
                  'candidate_scored': sum(x.get('judge_state') == 'scored' for x in current.values()),
                  'candidate_states': dict(collections.Counter(x.get('agent_state') for x in current.values())),
                  'paired_scored': len(pairs), 'baseline_correct_on_pairs': sum(x['baseline_correct'] for x in pairs),
                  'finetuned_correct_on_pairs': sum(x['finetuned_correct'] for x in pairs),
                  'transitions': {f'{int(a)}->{int(b)}': v for (a, b), v in counts.items()},
                  'cases': pairs, 'updated_epoch': time.time(),
                  'scope': 'Only pairs scored in both runs; missing/interrupted cases are not counted as wrong.',
                  'judge_caveat': 'Candidate uses the fine-tuned model itself as judge; baseline used the unmodified quantized model. Scores are not independent or judged by the same model.'}
        target = NEW / 'checks/paired-comparison.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        os.replace(temp, target)
        if all(x.get('agent_state') == 'terminal' and x.get('judge_state') not in ('pending', 'running') for x in current.values()):
            break
    if not alive():
        break
    time.sleep(15)
