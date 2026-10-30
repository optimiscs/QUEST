import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import http.client
import requests

class FakeResponse:
    def __init__(self, status, text): self.status_code, self.status, self.text = status, status, text
    def read(self): return self.text.encode()
    def close(self): pass

with tempfile.TemporaryDirectory() as directory:
    p = Path(directory)
    (p/'api_key_pool.json').write_text(json.dumps({'jina':['SECRET_J1','SECRET_J2'],'serper':['SECRET_S1','SECRET_S2']}))
    os.environ.update(QUEST_KEY_ROTATION='1', QUEST_KEY_POOL_DIR=directory, QUEST_KEY_AUDIT_DIR=directory)
    os.environ.pop('QUEST_KEY_ROTATION_ACTIVE_PID', None)
    calls = []
    def fake_request(self, method, url, **kwargs):
        key = kwargs['headers']['Authorization']; calls.append(key)
        return FakeResponse(402, 'account balance exhausted') if key.endswith('J1') else FakeResponse(200, 'OK')
    requests.sessions.Session.request = fake_request
    sent = []
    def fake_http_request(conn, method, url, body=None, headers=None, *, encode_chunked=False): sent.append(headers['X-API-KEY'])
    mode = 'quota'
    def fake_http_response(conn):
        if sent[-1] != 'SECRET_S1': return FakeResponse(200, '{"organic": []}')
        return FakeResponse(400, 'Not enough credits') if mode == 'quota' else FakeResponse(429, 'Rate limit exceeded: requests per second')
    http.client.HTTPSConnection.request = fake_http_request
    http.client.HTTPSConnection.getresponse = fake_http_response
    module_path = Path(__file__).with_name('sitecustomize.py')
    spec = importlib.util.spec_from_file_location('rotation_test', module_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = requests.Session().get('https://r.jina.ai/https://example.com')
    assert result.status_code == 200 and calls == ['Bearer SECRET_J1', 'Bearer SECRET_J2']
    conn = http.client.HTTPSConnection('google.serper.dev')
    conn.request('POST', '/search', '{}', {})
    result = conn.getresponse()
    assert result.status == 200 and sent == ['SECRET_S1', 'SECRET_S2']
    assert json.loads((p/'key_rotation_state.json').read_text())['jina']['exhausted'] == [0]
    logs = (p/'events.jsonl').read_text()
    assert 'SECRET_' not in logs
    assert module.switchable(400, 'Not enough credits')
    assert not module.switchable(400, 'invalid request')
    assert not module.switchable(429, 'requests per minute exceeded')
    assert module.switchable(429, 'credit balance exhausted')
    # A temporary 429 may try the next key without exhausting either key.
    state=json.loads((p/'key_rotation_state.json').read_text())
    state['serper']={'current':0,'exhausted':[]}
    (p/'key_rotation_state.json').write_text(json.dumps(state))
    os.environ['QUEST_SERPER_RATE_LIMIT_ROTATE']='1';mode='rate';sent.clear()
    conn=http.client.HTTPSConnection('google.serper.dev')
    conn.request('POST','/search','{}',{}); result=conn.getresponse()
    assert result.status==200 and sent==['SECRET_S1','SECRET_S2']
    assert json.loads((p/'key_rotation_state.json').read_text())['serper']['exhausted']==[]
    print('PASS: Jina and Serper quota rotation, persistent state, rate-limit distinction, secret-free logs')
