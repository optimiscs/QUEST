"""Use QUEST's shared Jina rotation pool without exposing credentials."""
import fcntl
import json
import os
import time
from pathlib import Path


class JinaPool:
    def __init__(self):
        project = Path(os.environ.get('QUEST_PROJECT_ROOT', str(Path(__file__).resolve().parents[5] / 'workspace')))
        secret = Path(os.environ.get('QUEST_KEY_POOL_DIR', str(project / 'strict-reproduction/.secrets')))
        self.pool = Path(os.environ.get('QUEST_KEY_POOL_FILE', str(secret / 'api_key_pool.json')))
        self.state = Path(os.environ.get('QUEST_KEY_STATE_FILE', str(secret / 'key_rotation_state.json')))
        self.lock = Path(os.environ.get('QUEST_KEY_LOCK_FILE', str(secret / 'key_rotation.lock')))
        self.events = Path(os.environ.get('QUEST_KEY_AUDIT_DIR', str(project / 'logs/key-rotation'))) / 'events.jsonl'

    def _locked(self, callback):
        self.lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            pool = json.loads(self.pool.read_text())
            state = json.loads(self.state.read_text()) if self.state.exists() else {}
            keys = pool['jina']
            if not isinstance(keys, list) or not all(isinstance(k, str) and k.strip() for k in keys):
                raise ValueError('invalid Jina key pool')
            result = callback(keys, state)
            tmp = self.state.with_name(self.state.name + '.' + str(os.getpid()) + '.tmp')
            out = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(out, 'w') as f:
                json.dump(state, f)
            os.replace(tmp, self.state)
            return result
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def choose(self, attempted):
        def select(keys, state):
            s = state.setdefault('jina', {'current': 0, 'exhausted': []})
            for i in range(len(keys)):
                index = (s['current'] + i) % len(keys)
                normalized = keys[index].strip()
                if normalized.lower().startswith('bearer '):
                    normalized = normalized[7:].strip()
                if index not in s['exhausted'] and normalized not in attempted:
                    s['current'] = index
                    return index, keys[index].strip()
            return None
        return self._locked(select)

    def reject(self, index):
        def update(keys, state):
            s = state.setdefault('jina', {'current': 0, 'exhausted': []})
            if index not in s['exhausted']:
                s['exhausted'].append(index)
            if keys and s['current'] == index:
                s['current'] = (index + 1) % len(keys)
        self._locked(update)
        self.events.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.events, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (json.dumps({'epoch': time.time(), 'pid': os.getpid(), 'service': 'jina', 'event': 'exhausted_or_invalid', 'key_index': index + 1, 'status': 402}) + '\n').encode())
        finally:
            os.close(fd)
