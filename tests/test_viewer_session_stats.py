import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(tmp_path, usages):
    root = tmp_path / 'run'
    (root / 'logs').mkdir(parents=True)
    native = root / 'result.jsonl'
    native.write_text(json.dumps({'question': 'Q', 'prediction': 'A', 'messages': [{'content': 'A'}], 'num_rounds': len(usages)}) + '\n')
    (root / 'status.json').write_text(json.dumps({'cases': {'row0000': {'agent_state': 'terminal', 'result_path': str(native)}}}))
    events = [{'event': 'span_start', 'span_id': 'task', 'kind': 'task', 'epoch': 100}]
    for i, usage in enumerate(usages):
        events += [{'event': 'span_start', 'span_id': f'p{i}', 'kind': 'policy_model', 'epoch': 101 + i * 2},
                   {'event': 'span_end', 'span_id': f'p{i}', 'kind': 'policy_model', 'epoch': 102 + i * 2,
                    'seconds': 1, 'output': 'A', 'api_response': {'usage': usage}}]
    events += [{'event': 'span_end', 'span_id': 'task', 'kind': 'task', 'epoch': 110, 'seconds': 10}]
    (root / 'logs/row0000-agent-events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
    out = tmp_path / 'out'
    result = subprocess.run([sys.executable, str(ROOT / 'web/build_gaia.py'), '--run-root', str(root),
                             '--output-dir', str(out), '--label', 'mock', '--requested-cases', '1'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads((out / 'traces.json').read_text())['cases'][0]['sessionStats']


def test_complete_usage_is_summed_without_inventing_cache_data(tmp_path):
    stats = build(tmp_path, [{'prompt_tokens': 100, 'completion_tokens': 10, 'prompt_tokens_details': {'cached_tokens': 60}},
                             {'prompt_tokens': 80, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 50}}])
    assert stats['usage'] == {'inputTokens': 180, 'outputTokens': 30, 'totalTokens': 210,
                              'cachedInputTokens': 110, 'uncachedInputTokens': 70}
    assert stats['toolSeconds'] is None


def test_partial_usage_does_not_claim_a_total(tmp_path):
    stats = build(tmp_path, [{'prompt_tokens': 100, 'completion_tokens': 10}, None])
    assert 'usage' not in stats
