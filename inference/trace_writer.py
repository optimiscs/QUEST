"""Thread-safe private JSONL writer used by the tracing adapters."""
import json
import os
import threading
from pathlib import Path


class TraceWriter:
    def __init__(self, path, secrets):
        self.path = Path(path)
        self.secrets = tuple(secrets)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)

    def write(self, record):
        line = json.dumps(record, ensure_ascii=False, default=str)
        for secret in self.secrets:
            line = line.replace(secret, '[REDACTED]')
        with self.lock:
            fd = os.open(self.path, os.O_APPEND | os.O_WRONLY)
            try:
                data = (line + '\n').encode()
                while data:
                    count = os.write(fd, data)
                    if count <= 0:
                        raise OSError('unable to write trace')
                    data = data[count:]
            finally:
                os.close(fd)
