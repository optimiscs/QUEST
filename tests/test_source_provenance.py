import pytest
from inference.source_ids import SourceRegistry


def test_assistant_cannot_register_or_resolve_an_invented_source(tmp_path):
    r = SourceRegistry(tmp_path)
    r.render('Title: Evidence\nLink: https://real.test/a\nSnipptes: 42')
    before = r._read()
    for value in ('https://invented.test/b', 'S99'):
        with pytest.raises(ValueError): r.assistant(value)
    assert r._read() == before
    with pytest.raises(ValueError): r.resolve(['S1', 'https://invented.test/b'])
    context = r.context({'messages': [{'role': 'assistant', 'content': 'See https://invented.test/b or S99'}]}, 'policy')
    assert 'unregistered' in context['messages'][0]['content']
    assert r._read() == before
    assert r.validate_final('42 [S1]') == '42 [S1]'


def test_user_seed_is_visitable_but_is_not_evidence(tmp_path):
    r = SourceRegistry(tmp_path)
    r.context({'role': 'user', 'content': 'Check https://seed.test'}, 'user')
    assert r.resolve('S1') == 'https://seed.test'
    with pytest.raises(ValueError, match='no_tool_observation'): r.validate_final('Fact [S1]')
    r.compact('Page says fact.', exact_urls=['https://seed.test'], origin='page_observation')
    assert r.validate_final('Fact [S1]') == 'Fact [S1]'


def test_legacy_mapping_and_memory_do_not_certify_sources(tmp_path):
    r = SourceRegistry(tmp_path)
    r.compact('https://old.test')
    with pytest.raises(ValueError, match='no_tool_observation'): r.validate_final('[S1]')
    r.context([{'role': 'user', 'content': 'events: https://new.test'}], 'memory')
    assert len(r._read()) == 1
