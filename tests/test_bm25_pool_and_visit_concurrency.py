import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'inference'))
os.environ.setdefault('VISIT_CACHE_ENABLED','false')
os.environ.setdefault('CACHE_DIR','/tmp/quest-test-import')
import retrieval_experiment as retrieval
import tool_visit
from inference.bm25_pool_service import create_app, prepare_page


def test_prepare_matches_original_chunking_and_ranking():
    text = ('red fox crosses the river. ' * 800) + '\n\n' + ('blue whale lives in oceans. ' * 800)
    result = prepare_page(text,'blue whale',True)
    chunks = retrieval.split_chunks(text)
    assert result['chunks'] == [x.text for x in chunks]
    assert result['lexical'] == retrieval.bm25_rank(chunks,'blue whale')


def test_shared_process_pool_matches_inline_top8(monkeypatch):
    text = ('red fox crosses the river. ' * 800) + '\n\n' + ('blue whale lives in oceans. ' * 800)
    with patch.dict(os.environ,{},clear=False):
        os.environ.pop('VISIT_BM25_POOL_URL',None)
        expected, audit = retrieval.select(text,'blue whale','bm25')
    with TestClient(create_app(workers=2,queue_limit=4)) as client:
        class Response:
            def __init__(self,r): self.response=r
            def raise_for_status(self): self.response.raise_for_status()
            def json(self): return self.response.json()
        def post(url,json,timeout): return Response(client.post('/prepare',json=json))
        monkeypatch.setattr(retrieval.requests,'post',post)
        with patch.dict(os.environ,{'VISIT_BM25_POOL_URL':'http://pool'}):
            actual, other = retrieval.select(text,'blue whale','bm25')
    assert actual == expected
    assert other['selected_indices'] == audit['selected_indices']


def test_invalid_pool_ranking_is_not_silently_accepted(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'input_tokens':3000, 'short_page':False, 'chunks':['a'], 'lexical':[5]}
    monkeypatch.setattr(retrieval.requests,'post',lambda *args,**kwargs:Response())
    with patch.dict(os.environ,{'VISIT_BM25_POOL_URL':'http://pool'}):
        with pytest.raises(ValueError,match='invalid BM25 pool ranking'):
            retrieval.select('text','goal','bm25')


def test_pool_applies_bounded_admission(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from inference import bm25_pool_service as service
    entered, release = threading.Event(), threading.Event()
    app = service.create_app(workers=1,queue_limit=0,admission_timeout=0.05)
    with TestClient(app) as client:
        app.state.pool.shutdown(wait=True)
        app.state.pool = ThreadPoolExecutor(max_workers=1)
        def slow(text, goal, need):
            entered.set()
            assert release.wait(5)
            return {'input_tokens':1,'short_page':True,'chunks':[],'lexical':[]}
        monkeypatch.setattr(service,'prepare_page',slow)
        with ThreadPoolExecutor(max_workers=1) as caller:
            first=caller.submit(client.post,'/prepare',json={'text':'one','goal':'q'})
            assert entered.wait(5)
            second=client.post('/prepare',json={'text':'two','goal':'q'})
            assert second.status_code == 503
            release.set()
            assert first.result(timeout=5).status_code == 200


def test_multi_url_concurrency_preserves_order_and_reports_errors():
    visit = tool_visit.Visit.__new__(tool_visit.Visit)
    visit.cache = None
    barrier = threading.Barrier(3, timeout=5)
    def read(url, goal):
        barrier.wait()
        if url.endswith('/bad'): raise RuntimeError('example')
        time.sleep(0.01)
        return url + ':' + goal
    visit.readpage_jina = read
    urls=['https://a.test/1','https://a.test/bad','https://a.test/3']
    with patch.dict(os.environ,{'VISIT_PAGE_CONCURRENCY':'3'}):
        out=visit.call({'url':urls,'goal':'goal'})
    parts=out.split('\n=======\n')
    assert parts == ['https://a.test/1:goal','[visit] Error: Unexpected error: example','https://a.test/3:goal']


def test_cache_initializes_once_across_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_visit,'VISIT_CACHE_SHARD_DIR',str(tmp_path))
    monkeypatch.setattr(tool_visit,'VISIT_CACHE_AUTO_MERGE',False)
    cache=tool_visit.VisitCache(cache_file=str(tmp_path/'visit.db'),resume=False,shards=2)
    barrier=threading.Barrier(8,timeout=5)
    def get():
        barrier.wait()
        return cache._get_conn(0)
    with __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=8) as pool:
        connections=list(pool.map(lambda _: get(),range(8)))
    assert len({id(x) for x in connections}) == 1
    cache.close()
