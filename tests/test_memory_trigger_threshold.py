"""Full-context triggers must not be cancelled by the older-history threshold."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
from tool_memory import Memory


def test_full_context_trigger_summarizes_small_older_subset(monkeypatch):
    monkeypatch.delenv('MEMORY_INPUT_TOKEN_BUDGET', raising=False)
    tool = object.__new__(Memory)
    tool.tokenizer = object()
    tool.token_threshold = 40000
    tool.count_tokens = lambda text: 12000
    calls = []
    def summarize(messages):
        calls.append(messages)
        return '{"version":"dr_state","information_state":{}}'
    tool.call_api_with_litellm = summarize
    params = {'events': [{'role': 'user', 'content': 'Older supported evidence'}]}
    assert 'below threshold' in tool.call(params)
    assert not calls
    assert 'dr_state' in tool.call(params, _context_threshold_triggered=True)
    assert len(calls) == 1


def test_context_trigger_keeps_input_budget_guard(monkeypatch):
    monkeypatch.setenv('MEMORY_INPUT_TOKEN_BUDGET', '1')
    tool = object.__new__(Memory)
    tool.tokenizer = object()
    tool.token_threshold = 40000
    tool.count_tokens = len
    def unexpected(messages):
        raise AssertionError('The input budget must still prevent an oversized call')
    tool.call_api_with_litellm = unexpected
    result = tool.call({'events': [{'role': 'user', 'content': 'Evidence'}]},
                       _context_threshold_triggered=True)
    assert 'Input budget cannot fit' in result
