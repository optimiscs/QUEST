"""Atomically update a retry receipt shared by concurrent workers."""
import fcntl
import json
import os
from pathlib import Path


def complete_retry(path, group, case, fields):
    path = Path(path)
    with (path.parent/'retry-required.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text())
        rows = [item for item in data['cases'] if item['group'] == group and item['case'] == case]
        if len(rows) != 1:
            raise ValueError('retry receipt must contain exactly one matching case')
        rows[0].update(fields)
        temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        temp.replace(path)
