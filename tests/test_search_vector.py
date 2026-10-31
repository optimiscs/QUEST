from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from inference.search_vector_client import parse_search_results, scope_for
from inference import search_vector_client, evidence_archive
from inference import search_vector_service


def test_parse_keeps_distinct_snippets_and_query():
    text = ("A Google search for 'first query' found 2 results:\n\n"
            'Title: A\nLink: https://example.com/a\nSnipptes: first fact\n\n'
            'Title: A\nLink: https://example.com/a\nSnipptes: different fact\n\n'
            "A Google search for 'second query' found 1 results:\n\n"
            'Title: B\nLink: https://example.com/b\nSnipptes: 2020')
    got = parse_search_results(text)
    assert [x['snippet'] for x in got] == ['first fact', 'different fact', '2020']
    assert [x['query'] for x in got] == ['first query', 'first query', 'second query']


def test_realtime_index_idempotent_and_scope_isolated(monkeypatch, tmp_path):
    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {'data': [{'index': i, 'embedding': [1., 0., 0.] if 'apple' in t else [0., 1., 0.]}
                                 for i, t in enumerate(json['input'])]}
        return Response()
    monkeypatch.setattr(search_vector_service.requests, 'post', fake_post)
    db = QdrantClient(':memory:')
    client = TestClient(search_vector_service.create_app(None, 'http://embedding', 'fake-model', 3, db))
    s1, s2 = scope_for(tmp_path / 'one'), scope_for(tmp_path / 'two')
    request = {'scope': s1, 'evidence_id': 'E' + 'a' * 64,
               'entries': [{'title': 'apple', 'url': 'https://a', 'snippet': 'fruit', 'query': 'fruit'}]}
    assert client.post('/index', json=request).json()['indexed'] == 1
    assert client.post('/index', json=request).json()['indexed'] == 1
    hits = client.post('/search', json={'scope': s1, 'query': 'apple'}).json()['hits']
    assert len(hits) == 1 and hits[0]['url'] == 'https://a'
    assert len(client.post('/search', json={'scope': s1, 'query': 'apple', 'evidence_id': request['evidence_id'], 'source_query': 'fruit'}).json()['hits']) == 1
    assert client.post('/search', json={'scope': s1, 'query': 'apple', 'evidence_id': request['evidence_id'], 'source_query': 'other'}).json()['hits'] == []
    assert client.post('/search', json={'scope': s2, 'query': 'apple'}).json()['hits'] == []


def test_qdrant_local_persists_across_reopen(monkeypatch, tmp_path):
    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'data': [{'index': i, 'embedding': [1., 0., 0.]} for i, _ in enumerate(json['input'])]}
        return Response()
    monkeypatch.setattr(search_vector_service.requests, 'post', fake_post)
    path = str(tmp_path / 'db'); scope = scope_for(tmp_path / 'trace')
    db = QdrantClient(path=path)
    client = TestClient(search_vector_service.create_app(None, 'http://embedding', 'fake-model', 3, db))
    assert client.post('/index', json={'scope': scope, 'evidence_id': 'E' + 'b' * 64,
                                      'entries': [{'title': 'source', 'snippet': 'fact'}]}).status_code == 200
    client.close(); db.close()
    reopened = QdrantClient(path=path)
    client2 = TestClient(search_vector_service.create_app(None, 'http://embedding', 'fake-model', 3, reopened))
    assert len(client2.post('/search', json={'scope': scope, 'query': 'fact'}).json()['hits']) == 1
    client2.close(); reopened.close()


def test_index_failure_remains_in_outbox_for_retry(monkeypatch, tmp_path):
    content = "A Google search for 'q' found 1 results:\n\nTitle: A\nLink: https://a\nSnipptes: fact"
    eid = evidence_archive.store(tmp_path, 'search', {'query': ['q']}, content)
    pending = search_vector_client.enqueue(tmp_path, eid)
    monkeypatch.setattr(search_vector_client, 'index', lambda *a: (_ for _ in ()).throw(OSError('unavailable')))
    try:
        search_vector_client.retry_pending('http://vector', tmp_path)
    except OSError:
        pass
    assert pending.exists() and evidence_archive.load(tmp_path, eid)['content'] == content
    monkeypatch.setattr(search_vector_client, 'index', lambda *a: 1)
    assert search_vector_client.retry_pending('http://vector', tmp_path) == 1
    assert not pending.exists()
