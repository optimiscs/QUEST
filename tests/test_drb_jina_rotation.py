import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('QUEST_KEY_POOL_DIR', str(tmp_path))
    monkeypatch.setenv('QUEST_KEY_AUDIT_DIR', str(tmp_path))
    path = Path(__file__).resolve().parents[1] / 'evaluation/drbench/eval/deep_research_bench/utils/api.py'
    sys.path.insert(0, str(path.parents[1]))
    spec = importlib.util.spec_from_file_location('utils.api', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, status): self.status_code = status
    def json(self):
        return {'data': {'url': 'https://example.com', 'title': 'title', 'description': 'desc', 'content': 'body'}}


def test_402_rotates_and_remembers_next_key(api, monkeypatch):
    monkeypatch.setenv('JINA_API_KEYS', 'first,second,third')
    calls = []
    def get(url, headers, timeout):
        auth=headers['Authorization'];calls.append(auth)
        return Response(402 if auth == 'Bearer first' else 200)
    monkeypatch.setattr(api.requests, 'get', get)
    assert api.scrape_url('https://example.com')['content'] == 'body'
    assert api.scrape_url('https://example.com')['content'] == 'body'
    assert calls == ['Bearer first', 'Bearer second', 'Bearer second']


def test_all_402_returns_error_without_secrets(api, monkeypatch):
    monkeypatch.setenv('JINA_API_KEYS', 'first,second')
    calls=[]
    def get(url, headers, timeout):
        calls.append(headers['Authorization']); return Response(402)
    monkeypatch.setattr(api.requests,'get',get)
    result=api.scrape_url('https://example.com')
    assert result['status_code']==402 and len(calls)==2
    assert all(key not in str(result) for key in ('first','second'))


def test_other_errors_do_not_rotate(api, monkeypatch):
    monkeypatch.setenv('JINA_API_KEYS','first,second')
    calls=[]
    def get(url, headers, timeout):
        calls.append(headers['Authorization']);return Response(403)
    monkeypatch.setattr(api.requests,'get',get)
    result=api.scrape_url('https://example.com')
    assert result['status_code']==403 and calls==['Bearer first']


def test_parallel_requests_use_available_key(api, monkeypatch):
    monkeypatch.setenv('JINA_API_KEYS','first,second')
    lock=Lock();calls=[]
    def get(url, headers, timeout):
        auth=headers['Authorization']
        with lock:calls.append(auth)
        return Response(402 if auth=='Bearer first' else 200)
    monkeypatch.setattr(api.requests,'get',get)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(api.scrape_url,['https://example.com']*10))
    assert all(x['content']=='body' for x in results)
    assert 'Bearer second' in calls


def test_singular_key_and_explicit_override(api, monkeypatch):
    monkeypatch.delenv('JINA_API_KEYS',raising=False)
    monkeypatch.setenv('JINA_API_KEY','Bearer legacy')
    calls=[]
    def get(url,headers,timeout):calls.append(headers['Authorization']);return Response(200)
    monkeypatch.setattr(api.requests,'get',get)
    api.scrape_url('https://example.com')
    api.WebScrapingJinaTool('explicit')('https://example.com')
    assert calls == ['Bearer legacy','Bearer explicit']


def test_402_falls_back_to_shared_pool_and_persists(api, monkeypatch, tmp_path):
    import json
    monkeypatch.setenv('JINA_API_KEYS', 'primary')
    (tmp_path/'api_key_pool.json').write_text(json.dumps({'jina':['pool0','pool1','pool2'], 'serper':['serper-secret']}))
    (tmp_path/'key_rotation_state.json').write_text(json.dumps({'jina':{'current':0,'exhausted':[0]}, 'serper':{'current':0,'exhausted':[]}}))
    calls=[]
    def get(url, headers, timeout):
        auth=headers['Authorization'];calls.append(auth)
        return Response(402 if auth in ('Bearer primary','Bearer pool1') else 200)
    monkeypatch.setattr(api.requests,'get',get)
    assert api.scrape_url('https://example.com')['content']=='body'
    assert calls == ['Bearer primary','Bearer pool1','Bearer pool2']
    state=json.loads((tmp_path/'key_rotation_state.json').read_text())
    assert state['jina']=={'current':2,'exhausted':[0,1]}
    assert state['serper']=={'current':0,'exhausted':[]}
    assert 'pool1' not in (tmp_path/'events.jsonl').read_text()


def test_pool_only_and_all_exhausted(api, monkeypatch, tmp_path):
    import json
    monkeypatch.delenv('JINA_API_KEYS',raising=False)
    monkeypatch.delenv('JINA_API_KEY',raising=False)
    (tmp_path/'api_key_pool.json').write_text(json.dumps({'jina':['pool1','pool2']}))
    calls=[]
    def get(url,headers,timeout):calls.append(headers['Authorization']);return Response(402)
    monkeypatch.setattr(api.requests,'get',get)
    result=api.scrape_url('https://example.com')
    assert result['status_code']==402
    assert calls==['Bearer pool1','Bearer pool2']
    assert json.loads((tmp_path/'key_rotation_state.json').read_text())['jina']['exhausted']==[0,1]
    assert api.scrape_url('https://example.com')['status_code']==402
    assert len(calls)==2
