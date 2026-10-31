import json
from inference import evidence_archive


def test_archive_roundtrip_pages_and_hash_validation(tmp_path):
    original = 'abcd' * 5000
    key = evidence_archive.store(tmp_path, 'visit', {'goal': 'a'}, original)
    first = evidence_archive.read(tmp_path, key)
    second = evidence_archive.read(tmp_path, key, first['next_offset'])
    assert first['content'] + second['content'] == original
    assert second['next_offset'] is None
    assert first['arguments'] == {'goal': 'a'}
    (tmp_path / 'evidence' / (key + '.json')).write_text('{}')
    try:
        evidence_archive.read(tmp_path, key)
        assert False, 'corrupt archive must be rejected'
    except OSError:
        pass


def test_search_compaction_retains_distinct_snippets():
    text = ('Title: A\nLink: https://example.com\nSnipptes: 1998\n\n'
            'Title: A\nLink: https://example.com\nSnipptes: 1998\n\n'
            'Title: A\nLink: https://example.com\nSnipptes: 2001')
    result = evidence_archive.compact('search', text, 'E' + 'a' * 64)
    assert result.count('1998') == 1
    assert '2001' in result
