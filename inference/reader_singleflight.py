"""Coalesce simultaneous identical Reader calls across local worker processes."""
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def run(url, fetch):
    root = Path(os.environ.get('QUEST_READER_COORDINATION_DIR') or
                (str(Path(os.environ['QUEST_AB_GROUP_ROOT']) / 'reader-coordination')
                 if os.environ.get('QUEST_AB_GROUP_ROOT') else
                 str(Path(os.environ.get('SHARED_CACHE_DIR', tempfile.gettempdir())) / 'quest-reader-coordination')))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A URL can be reused only when Reader configuration matches.
    identity = '\0'.join((url, os.getenv('HTTPS_PROXY', ''), os.getenv('VISIT_READER_BOUNDED_RETRIES', '')))
    key = hashlib.sha256(identity.encode()).hexdigest()
    lock_path, result_path = root / (key + '.lock'), root / (key + '.json')
    arrived = time.time_ns()
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            value = json.loads(result_path.read_text(encoding='utf-8'))
            if value['completed_ns'] >= arrived and isinstance(value['result'], str):
                return value['result']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = fetch()
        # Publish atomically before releasing the lock. A crashed leader leaves
        # no completed result and the next caller retries as the new leader.
        output = json.dumps({'completed_ns': time.time_ns(), 'result': result}, ensure_ascii=False)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=key + '.', dir=root)
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as stream:
                stream.write(output)
            os.replace(tmp_name, result_path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return result
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
