"""Opt-in credential rotation at HTTP boundary; upstream sources stay unchanged."""
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

if os.environ.get('QUEST_KEY_ROTATION') == '1' and os.environ.get('QUEST_KEY_ROTATION_ACTIVE_PID') != str(os.getpid()):
    os.environ['QUEST_KEY_ROTATION_ACTIVE_PID'] = str(os.getpid())
    import fcntl
    import http.client
    import requests

    repo = Path(__file__).resolve().parents[2]
    workspace = repo / 'workspace'
    project = Path(os.environ.get('QUEST_PROJECT_ROOT', str(workspace if (workspace / 'strict-reproduction').is_dir() else repo.parent)))
    root = project / 'strict-reproduction'
    secret = Path(os.environ.get('QUEST_KEY_POOL_DIR', str(root / '.secrets')))
    pool_file = Path(os.environ.get('QUEST_KEY_POOL_FILE', str(secret / 'api_key_pool.json')))
    state_file = Path(os.environ.get('QUEST_KEY_STATE_FILE', str(secret / 'key_rotation_state.json')))
    lock_file = Path(os.environ.get('QUEST_KEY_LOCK_FILE', str(secret / 'key_rotation.lock')))
    log_dir = Path(os.environ.get('QUEST_KEY_AUDIT_DIR', str(project / 'logs/key-rotation')))
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    events = log_dir / 'events.jsonl'

    def locked(fn):
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            pool = json.loads(pool_file.read_text())
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            result = fn(pool, state)
            tmp = state_file.with_name(state_file.name + '.' + str(os.getpid()) + '.tmp')
            out = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(out, 'w') as f: json.dump(state, f)
            os.replace(tmp, state_file)
            return result
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def record(service, event, index, status):
        line = json.dumps({'epoch': time.time(), 'pid': os.getpid(), 'service': service,
                           'event': event, 'key_index': index + 1, 'status': status}) + '\n'
        fd = os.open(events, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try: os.write(fd, line.encode())
        finally: os.close(fd)

    def choose(service, attempted):
        def select(pool, state):
            s = state.setdefault(service, {'current': 0, 'exhausted': []})
            for i in range(len(pool[service])):
                index = (s['current'] + i) % len(pool[service])
                if index not in s['exhausted'] and index not in attempted:
                    s['current'] = index
                    return index, pool[service][index]
            return None
        return locked(select)

    def exhaust(service, index, status):
        def update(pool, state):
            s = state.setdefault(service, {'current': 0, 'exhausted': []})
            if index not in s['exhausted']: s['exhausted'].append(index)
            if s['current'] == index: s['current'] = (index + 1) % len(pool[service])
        locked(update)
        record(service, 'exhausted_or_invalid', index, status)

    def switchable(status, body):
        if status in (401, 402): return True
        if status not in (403, 429): return False
        text = body.lower()[:10000]
        return bool(re.search(r'(insufficient|not enough|exhausted|exceeded|no remaining|zero).{0,40}(quota|credit|balance)|(?:quota|credit|balance).{0,40}(insufficient|exhausted|exceeded|not enough|depleted)', text))

    # Official Jina calls and QUEST visit both use requests. Only Jina is affected.
    original_request = requests.sessions.Session.request
    def jina_request(self, method, url, **kwargs):
        if urlsplit(str(url)).hostname != 'r.jina.ai':
            return original_request(self, method, url, **kwargs)
        attempted = set()
        last = None
        while True:
            selection = choose('jina', attempted)
            if selection is None:
                if last is not None: return last
                raise requests.exceptions.RequestException('All Jina keys are exhausted or invalid')
            index, key = selection
            headers = dict(kwargs.get('headers') or {})
            headers = {k: v for k, v in headers.items() if k.lower() != 'authorization'}
            headers['Authorization'] = key if key.lower().startswith('bearer ') else 'Bearer ' + key
            opts = dict(kwargs, headers=headers)
            response = original_request(self, method, url, **opts)
            record('jina', 'response', index, response.status_code)
            if not switchable(response.status_code, response.text): return response
            attempted.add(index)
            exhaust('jina', index, response.status_code)
            if last is not None: last.close()
            last = response

    requests.sessions.Session.request = jina_request

    # QUEST's Serper search uses http.client, not requests. Retry only the same
    # POST after explicit credential/quota failure; leave all other hosts alone.
    original_https_request = http.client.HTTPSConnection.request
    original_getresponse = http.client.HTTPSConnection.getresponse
    class BufferedResponse:
        def __init__(self, original, data): self.original, self.buf = original, io.BytesIO(data)
        def read(self, amount=None): return self.buf.read(-1 if amount is None else amount)
        def __getattr__(self, name): return getattr(self.original, name)

    def serper_request(conn, method, url, body=None, headers=None, *, encode_chunked=False):
        if conn.host != 'google.serper.dev':
            return original_https_request(conn, method, url, body, headers or {}, encode_chunked=encode_chunked)
        selected = choose('serper', set())
        if selected is None: raise RuntimeError('All Serper keys are exhausted or invalid')
        index, key = selected
        clean = {k: v for k, v in (headers or {}).items() if k.lower() != 'x-api-key'}
        conn._quest_serper = (method, url, body, clean, encode_chunked, index, {index})
        return original_https_request(conn, method, url, body, dict(clean, **{'X-API-KEY': key}), encode_chunked=encode_chunked)

    def serper_response(conn):
        response = original_getresponse(conn)
        saved = getattr(conn, '_quest_serper', None)
        if conn.host != 'google.serper.dev' or saved is None: return response
        method, url, body, clean, chunked, index, attempted = saved
        while True:
            record('serper', 'response', index, response.status)
            if response.status not in (401, 402, 403, 429): return response
            data = response.read()
            if not switchable(response.status, data.decode('utf-8', errors='replace')):
                return BufferedResponse(response, data)
            exhaust('serper', index, response.status)
            selected = choose('serper', attempted)
            if selected is None: return BufferedResponse(response, data)
            index, key = selected
            attempted.add(index)
            conn.close()
            original_https_request(conn, method, url, body, dict(clean, **{'X-API-KEY': key}), encode_chunked=chunked)
            response = original_getresponse(conn)
    http.client.HTTPSConnection.request = serper_request
    http.client.HTTPSConnection.getresponse = serper_response
