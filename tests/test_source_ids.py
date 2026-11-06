import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from inference.source_ids import SourceRegistry


def test_markdown_table_and_adjacent_links_preserve_boundaries(tmp_path):
    registry = SourceRegistry(tmp_path)
    raw = ('Basketball[[115]](https://example.org/MSG#note-115)| Years | Capacity |\n'
           '[[27]](https://example.org/Tour#Variety_(September_2025)-30)'
           '[[28]](https://example.org/Tour#note-31)| next')
    assert registry.compact(raw, origin='page_observation') == (
        'Basketball[[115]](S1)| Years | Capacity |\n[[27]](S2)[[28]](S3)| next')
    assert registry._read() == {
        'S1': 'https://example.org/MSG#note-115',
        'S2': 'https://example.org/Tour#Variety_(September_2025)-30',
        'S3': 'https://example.org/Tour#note-31'}
    assert registry.assistant('[source](https://example.org/MSG#note-115)|') == '[source](S1)|'


def test_structured_url_preserves_literal_delimiters(tmp_path):
    registry = SourceRegistry(tmp_path)
    url = 'https://example.org/a|b)'
    assert registry.render('Title: X\nLink: ' + url) == 'Title: X\nLink: S1'
    assert registry.resolve('S1') == url


def test_url_free_task_has_an_explicit_empty_source_map(tmp_path):
    registry = SourceRegistry(tmp_path)
    assert registry.context({'role': 'user', 'content': 'Who?'}, 'user')['content'] == 'Who?'
    assert json.loads(registry.path.read_text()) == {}


def test_persistent_exact_urls_and_evidence_preserved(tmp_path):
    text = ('Title: A\nLink: https://example.com/a?x=1&y=2\n'
            'Date published: 2020\nSnipptes: See https://example.com/evidence\n'
            'Sitelinks:\n- B: https://example.com/b\n\n')
    r = SourceRegistry(tmp_path)
    rendered = r.render(text)
    assert rendered == text.replace('https://example.com/a?x=1&y=2', 'S1').replace('https://example.com/evidence', 'S3').replace('https://example.com/b', 'S2')
    reopened = SourceRegistry(tmp_path)
    assert reopened.resolve(['S1', '[S2]']) == [
        'https://example.com/a?x=1&y=2', 'https://example.com/b']
    with pytest.raises(ValueError): reopened.resolve('https://other.test')
    assert reopened.render(text) == rendered
    assert SourceRegistry(tmp_path / 'other').render('Title: X\nLink: https://other.test') .endswith('S1')


def test_concurrent_registration_has_no_collisions(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: SourceRegistry(tmp_path).render(f'Title: A\nLink: https://example.com/{i % 10}'), range(40)))
    saved = json.loads((tmp_path / 'sources.json').read_text())
    assert len(saved) == len(set(saved.values())) == 10


def test_all_context_layers_and_memory_retry_are_url_free(monkeypatch, tmp_path):
    from inference import source_ids
    monkeypatch.setenv('QUEST_SOURCE_IDS', 'true')
    source_ids.bind_task(tmp_path)
    r = SourceRegistry(tmp_path)
    messages = [{'role': 'system', 'content': 'Read https://system.test/docs.'},
                {'role': 'user', 'content': 'See [page](https://user.test/a_(b)) and www.example.org.'},
                {'role': 'assistant', 'tool_calls': [{'function': {'name': 'visit',
                  'arguments': json.dumps({'url': ['https://page.test/?a=1&b=2'], 'goal': 'find'})}}]},
                {'role': 'tool', 'content': 'Evidence: https://evidence.test/a'},
                {'role': 'assistant', 'content': '{"evidence":"https:\\/\\/retry.test\\/path"}'}]
    visible = r.context({'messages': messages, 'tools': [{'description': 'https://schema.test'}]}, 'policy')
    assert not source_ids.URL_PATTERN.search(json.dumps(visible))
    assert '[unregistered URL]' in visible['messages'][2]['tool_calls'][0]['function']['arguments']
    assert 'https://user.test/a_(b)' in r._read().values()
    assert 'https://retry.test/path' not in r._read().values()
    r.compact("[author](https://example.com/O'Brien) and [help](https://example.com/a\\_b)")
    assert "https://example.com/O'Brien" in r._read().values()
    assert 'https://example.com/a_b' in r._read().values()
    # Memory input embeds serialized events inside a prose prompt.
    memory = source_ids.compact_memory([{'role': 'user', 'content': 'events:\n' + json.dumps(messages)}])
    assert not source_ids.URL_PATTERN.search(json.dumps(memory))
    assert r.context(visible, 'policy') == visible
    assert 'https://' in messages[0]['content']  # originals remain auditable


@pytest.mark.parametrize('url', [
    'https://example.com/a!?x=(y)',
    "https://www.researchgate.net/publication/315411496_Preschoolers'_Social-Emotional",
    "https://www.findagrave.com/cemetery/2738399/st.-stephen's-cemetery",
])
def test_exact_search_url_with_punctuation_round_trips(tmp_path, url):
    r = SourceRegistry(tmp_path)
    rendered = r.render('Title: A\nLink: ' + url + '\nSnipptes: fact')
    assert rendered == 'Title: A\nLink: S1\nSnipptes: fact'
    assert r.resolve('S1') == url


def test_persistence_failure_never_returns_uncommitted_ids(monkeypatch, tmp_path):
    from inference import source_ids
    r = SourceRegistry(tmp_path)
    r.render('Title: A\nLink: https://example.com/a')
    def fail(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr(source_ids.os, 'replace', fail)
    with pytest.raises(OSError):
        r.render('Title: B\nLink: https://example.com/b')
    assert r._read() == {'S1': 'https://example.com/a'}
    assert not list(tmp_path.glob('*.tmp'))


def test_memory_api_sanitizes_actual_messages(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
    import tool_memory
    from inference import source_ids
    monkeypatch.setenv('QUEST_SOURCE_IDS', 'true')
    monkeypatch.setenv('MEMORY_MODEL_NAME', 'openai/test')
    monkeypatch.setenv('MEMORY_API_BASE', 'http://127.0.0.1:19251/v1')
    monkeypatch.setattr(tool_memory, 'use_memory_local_prompt', lambda: False)
    monkeypatch.setattr(tool_memory, 'MEMORY_SYSTEM_PROMPT', 'Read https://system.test/docs')
    source_ids.bind_task(tmp_path)
    seen = []
    def completion(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    monkeypatch.setattr(tool_memory, 'completion', completion)
    memory = tool_memory.Memory.__new__(tool_memory.Memory)
    memory.tokenizer = None
    memory.call_api_with_litellm([{'role': 'user', 'content': 'https://evidence.test/page'}])
    assert not source_ids.URL_PATTERN.search(json.dumps(seen[0]['messages']))
    assert seen[0]['api_base'] == 'http://127.0.0.1:19251/v1'


def test_executor_resolves_before_visit_and_rejects_entire_invalid_batch(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
    import react_agent
    import native_tools
    monkeypatch.setenv('QUEST_SOURCE_IDS', 'true')
    monkeypatch.setenv('QUEST_SEARCH_VECTOR_URL', '')
    calls = []
    search = SimpleNamespace(call=lambda *a, **k: 'Title: A\nLink: https://example.com/a?q=1\nSnipptes: fact')
    visit = SimpleNamespace(call=lambda args, **k: calls.append(args['url']) or 'fetched')
    monkeypatch.setitem(react_agent.TOOL_MAP, 'search', search)
    monkeypatch.setitem(react_agent.TOOL_MAP, 'visit', visit)
    agent = SimpleNamespace(_get_thread_state=lambda: SimpleNamespace(task_log_dir=str(tmp_path)))
    execute = lambda name, args: react_agent.MultiTurnReactAgent.custom_call_tool(agent, name, args)
    assert 'Link: S1' in execute('search', {'query': ['q']})
    args = {'url': ['S1'], 'goal': 'fact'}
    before = copy.deepcopy(args)
    assert execute('visit', args) == 'fetched'
    assert args == before and calls == [['https://example.com/a?q=1']]
    assert 'Unknown source ID' in execute('visit', {'url': ['S1', 'S999'], 'goal': 'fact'})
    assert len(calls) == 1
    monkeypatch.setenv('QUEST_SOURCE_IDS', 'false')
    assert 'Link: https://' in execute('search', {'query': ['q']})
    assert 'persistent source IDs' not in native_tools.system_prompt('test')
