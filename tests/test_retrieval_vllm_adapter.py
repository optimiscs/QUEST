from fastapi.testclient import TestClient
from inference import retrieval_vllm_adapter as adapter


def test_embedding_preserves_order_and_cosine(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data': [{'index': 2, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}, {'index': 1, 'embedding': [1, 0]}]}
    def post(url, json, timeout):
        assert url.endswith('/v1/embeddings')
        assert json['input'][0].startswith('Instruct: ')
        return Response()
    monkeypatch.setattr(adapter.requests, 'post', post)
    result = TestClient(adapter.create_app('embedding', 'embed', 'http://upstream')).post('/score', json={'goal':'goal','passages':['a','b']})
    assert result.status_code == 200
    assert result.json()['scores'] == [1.0, 0.0]


def test_reranker_preserves_document_order(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data': [{'index': 1, 'score': 0.1}, {'index': 0, 'score': 0.9}]}
    def post(url, json, timeout):
        assert url.endswith('/score') and json['queries'] == ['goal']
        assert json['max_tokens_per_doc'] > 0
        return Response()
    monkeypatch.setattr(adapter.requests, 'post', post)
    result = TestClient(adapter.create_app('reranker', 'rank', 'http://upstream')).post('/score', json={'goal':'goal','passages':['a','b']})
    assert result.status_code == 200
    assert result.json()['scores'] == [0.9, 0.1]


def test_reranker_budgets_document_before_combined_truncation(monkeypatch):
    class Tokenizer:
        def encode(self, text, add_special_tokens=False): return list(text)
        def decode(self, tokens, **kwargs): return ''.join(tokens)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data': [{'index': 0, 'score': 0.9}]}
    def post(url, json, timeout):
        assert 0 < json['max_tokens_per_doc'] < 2048
        assert len(json['queries'][0]) <= 1500
        assert json['truncate_prompt_tokens'] == 2048
        return Response()
    monkeypatch.setattr(adapter.requests, 'post', post)
    client = TestClient(adapter.create_app('reranker', 'rank', 'http://upstream', Tokenizer()))
    response = client.post('/score', json={'goal': 'q' * 2000, 'passages': ['document']})
    assert response.status_code == 200
