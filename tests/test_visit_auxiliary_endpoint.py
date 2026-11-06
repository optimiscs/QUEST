from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
import tool_visit


def test_visit_can_use_separate_summary_server(monkeypatch):
    seen = {}
    def make_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"ok"}'))]))))
    monkeypatch.setattr(tool_visit, 'use_visit_local_prompt', lambda: True)
    monkeypatch.setattr(tool_visit, 'OpenAI', make_client)
    monkeypatch.setattr(tool_visit, 'choose_local_openai_base_url', lambda: 'http://policy/v1')
    monkeypatch.setenv('VISIT_LOCAL_API_BASE', 'http://auxiliary/v1')
    visit = tool_visit.Visit.__new__(tool_visit.Visit)
    assert visit.call_server([{'role': 'user', 'content': 'test'}]) == '{"summary":"ok"}'
    assert seen['base_url'] == 'http://auxiliary/v1'
