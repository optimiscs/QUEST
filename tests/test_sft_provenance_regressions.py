"""Regression cases for known open-ended SFT provenance gaps.

These verify relationships between the candidate, trajectory, and scoring evidence.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'contrib' / 'deepseek_data'


def write_jsonl(path, value):
    path.write_text(json.dumps(value) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(script, **paths):
    args = [sys.executable, str(SCRIPTS / script)]
    for name, value in paths.items():
        args.extend(['--' + name.replace('_', '-'), str(value)])
    return subprocess.run(args, text=True, capture_output=True)


@pytest.fixture
def evidence(tmp_path):
    candidate = tmp_path / 'candidate.jsonl'
    reference = tmp_path / 'reference.jsonl'
    sessions = tmp_path / 'sessions.jsonl'
    score = tmp_path / 'score.jsonl'
    status = tmp_path / 'score.status.json'
    ledger = tmp_path / 'ledger.jsonl'
    write_jsonl(candidate, {'question': 'Question A', 'iter': 1, 'prediction': 'A' * 120})
    write_jsonl(reference, {'question': 'Question A', 'prediction': 'R' * 120, 'termination': 'answer'})
    write_jsonl(sessions, {'question': 'Question A', 'iter': 1, 'task_id': 'task-1', 'is_final': True,
                           'messages': [{'role': 'user', 'content': 'Question A'},
                                        {'role': 'assistant', 'content': 'A' * 120}]})
    write_jsonl(score, {'id': 'task-1', 'iter': 1, 'query': 'Question A', 'final_score': 0.8})
    status.write_text(json.dumps({'complete': True, 'exit_code': 0, 'result_rows': 1,
                                  'valid_scores': 1, 'output_sha256': digest(score),
                                  'input_sha256': {'candidate': digest(candidate), 'reference': digest(reference)}}))
    return dict(candidate=candidate, reference=reference, sessions=sessions, score=score,
                status=status, ledger=ledger, tmp=tmp_path)


def build(e):
    return invoke('build_openended_ledger.py', score=e['score'], candidate=e['candidate'],
                  reference=e['reference'], sessions=e['sessions'], reference_kind='independent_agent',
                  out=e['ledger'])


def export(e):
    return invoke('export_sft.py', ledger=e['ledger'], output=e['tmp'] / 'output.json',
                  manifest=e['tmp'] / 'manifest.json')


def test_rejects_trajectory_for_a_different_question(evidence):
    write_jsonl(evidence['sessions'], {'question': 'Question B', 'iter': 1, 'task_id': 'task-1', 'is_final': True,
                                      'messages': [{'role': 'user', 'content': 'Question B'},
                                                   {'role': 'assistant', 'content': 'unrelated'}]})
    result = build(evidence)
    assert result.returncode != 0, 'an unrelated trajectory must not be accepted'
    assert not evidence['ledger'].exists()


def test_rejects_ledger_score_that_disagrees_with_evidence(evidence):
    result = build(evidence)
    assert result.returncode == 0, result.stderr
    row = json.loads(evidence['ledger'].read_text())
    row['score'] = 1.0
    write_jsonl(evidence['ledger'], row)
    result = export(evidence)
    assert result.returncode != 0, 'a changed ledger score must not authorize export'
    assert not (evidence['tmp'] / 'output.json').exists()


@pytest.mark.parametrize('change', ['iteration', 'answer', 'missing_iteration', 'multiple_final'])
def test_rejects_unbound_or_ambiguous_trajectory(evidence, change):
    row = json.loads(evidence['sessions'].read_text())
    if change == 'iteration':
        row['iter'] = 2
    elif change == 'answer':
        row['messages'][-1]['content'] = 'different answer'
    elif change == 'missing_iteration':
        del row['iter']
    write_jsonl(evidence['sessions'], row)
    if change == 'multiple_final':
        with evidence['sessions'].open('a') as stream:
            stream.write(json.dumps(row) + '\n')
    result = build(evidence)
    assert result.returncode != 0
    assert not evidence['ledger'].exists()


def test_rejects_provisional_reference_relabelled_in_ledger(evidence):
    ref = json.loads(evidence['reference'].read_text())
    ref.update(reference_kind='provisional_continuation', termination='continuation_after_tool_limit')
    write_jsonl(evidence['reference'], ref)
    status = json.loads(evidence['status'].read_text())
    status['input_sha256']['reference'] = digest(evidence['reference'])
    evidence['status'].write_text(json.dumps(status))
    result = invoke('build_openended_ledger.py', score=evidence['score'], candidate=evidence['candidate'],
                    reference=evidence['reference'], sessions=evidence['sessions'],
                    reference_kind='provisional_generator', out=evidence['ledger'])
    assert result.returncode == 0, result.stderr
    row = json.loads(evidence['ledger'].read_text())
    row.update(reference_kind='independent_agent', score_status='scored')
    write_jsonl(evidence['ledger'], row)
    result = export(evidence)
    assert result.returncode != 0
    assert not (evidence['tmp'] / 'output.json').exists()


def test_rejects_changed_score_status(evidence):
    result = build(evidence)
    assert result.returncode == 0, result.stderr
    evidence['status'].write_text('{}')
    result = export(evidence)
    assert result.returncode != 0
    assert not (evidence['tmp'] / 'output.json').exists()


def test_rejects_same_path_for_output_and_manifest(evidence):
    result = build(evidence)
    assert result.returncode == 0, result.stderr
    destination = evidence['tmp'] / 'same.json'
    result = invoke('export_sft.py', ledger=evidence['ledger'], output=destination, manifest=destination)
    assert result.returncode != 0
    assert not destination.exists()


def test_trajectory_task_id_must_match_score(evidence):
    row = json.loads(evidence['sessions'].read_text())
    row['task_id'] = 'different-task'
    write_jsonl(evidence['sessions'], row)
    result = build(evidence)
    assert result.returncode != 0
    assert not evidence['ledger'].exists()


def test_export_module_import_has_no_cli_side_effect():
    import importlib.util
    import contextlib
    import io
    spec = importlib.util.spec_from_file_location('contrib.deepseek_data.export_sft', SCRIPTS / 'export_sft.py')
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        spec.loader.exec_module(module)
    assert callable(module.main)
    assert not out.getvalue()
