import importlib.util
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'inference/scripts/retrieval_ab_metrics.py'
spec = importlib.util.spec_from_file_location('retrieval_ab_metrics', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_pairing_excludes_missing_and_unscored():
    base = {'a': {'judge_state': 'scored', 'is_correct': True},
            'b': {'judge_state': 'scored', 'is_correct': False},
            'c': {'judge_state': 'unavailable', 'is_correct': None}}
    other = {'a': {'judge_state': 'scored', 'is_correct': False},
             'b': {'judge_state': 'scored', 'is_correct': True},
             'c': {'judge_state': 'scored', 'is_correct': True}}
    result = module.paired_comparison(base, other)
    assert result['paired_scored'] == 2
    assert result['baseline_only_correct'] == result['treatment_only_correct'] == 1
    assert result['mcnemar_exact_p'] == 1


def test_pairing_identical_has_no_test_statistic():
    rows = {'a': {'judge_state': 'scored', 'is_correct': True}}
    assert module.paired_comparison(rows, rows)['mcnemar_exact_p'] is None


def test_service_timeout_excludes_score_until_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RUN', tmp_path)
    group = tmp_path / 'hybrid-direct'
    (group / 'logs').mkdir(parents=True)
    (group / 'status.json').write_text(json.dumps({'cases': {'row0000': {
        'agent_state': 'terminal', 'judge_state': 'scored', 'is_correct': True}}}))
    (group / 'logs/row0000-agent.stdout.log').write_text(
        'Summary Content [visit] Error: Unexpected error: HTTPConnectionPool(host=127.0.0.1): Read timed out\n')
    result = module.calculate()['groups']['hybrid-direct']['cases']['row0000']
    assert result['judge_state'] == 'needs_retry'
    assert result['is_correct'] is None
    (group / 'logs/row0000-agent.stdout.log').write_text(
        '[visit] Error: Network error: All Jina keys are exhausted or invalid\n')
    result = module.calculate()['groups']['hybrid-direct']['cases']['row0000']
    assert result['judge_state'] == 'needs_retry'
    assert result['is_correct'] is None


def test_running_retry_does_not_expose_stale_score(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RUN', tmp_path)
    group = tmp_path/'hybrid-direct'
    (group/'logs').mkdir(parents=True)
    (tmp_path/'checks').mkdir()
    (group/'status.json').write_text(json.dumps({'cases': {'row0000': {'agent_state':'terminal','judge_state':'scored','is_correct':True}}}))
    (tmp_path/'checks/retry-required.json').write_text(json.dumps({'cases':[{'group':'hybrid-direct','case':'row0000','status':'running_retry'}]}))
    result = module.calculate()['groups']['hybrid-direct']['cases']['row0000']
    assert result['agent_state'] == 'running'
    assert result['judge_state'] == 'needs_retry'
    assert result['is_correct'] is None
