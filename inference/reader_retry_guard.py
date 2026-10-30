"""Cross-process Jina retry budget and proxy circuit breaker."""
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import requests

local = threading.local()

class GuardRejected(requests.exceptions.RequestException):
    pass

class Guard:
    def __init__(self):
        base = os.getenv('QUEST_READER_COORDINATION_DIR') or (str(Path(os.environ['QUEST_AB_GROUP_ROOT']) / 'reader-coordination') if os.getenv('QUEST_AB_GROUP_ROOT') else str(Path(os.getenv('SHARED_CACHE_DIR', tempfile.gettempdir())) / 'quest-reader-coordination'))
        Path(base).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = str(Path(base) / 'retry-guard.sqlite3')
        self.route = hashlib.sha256(os.getenv('HTTPS_PROXY', '').encode()).hexdigest()
        self.attempts = 0
        self.probe = False
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS state (route TEXT PRIMARY KEY, tokens REAL, updated REAL, failures INTEGER, open_until REAL, probe_until REAL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def before(self):
        now=time.time(); capacity=float(os.getenv('QUEST_READER_RETRY_CAPACITY','60')); refill=float(os.getenv('QUEST_READER_RETRY_REFILL_PER_SECOND','1'))
        if self.attempts >= 3:
            raise GuardRejected('Jina per-read request budget exhausted')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT tokens,updated,failures,open_until,probe_until FROM state WHERE route=?',(self.route,)).fetchone()
            tokens,updated,failures,open_until,probe_until=row or (capacity,now,0,0,0)
            tokens=min(capacity,tokens+max(0,now-updated)*refill)
            if open_until > now or (open_until and probe_until > now):
                c.execute('ROLLBACK');raise GuardRejected('Jina proxy circuit open')
            if self.attempts and tokens < 1:
                c.execute('ROLLBACK');raise GuardRejected('Jina shared retry budget exhausted')
            if self.attempts:tokens-=1
            self.probe=bool(open_until)
            if self.probe:probe_until=now+float(os.getenv('QUEST_READER_PROBE_LEASE_SECONDS','180'))
            c.execute('INSERT OR REPLACE INTO state VALUES (?,?,?,?,?,?)',(self.route,tokens,now,failures,open_until,probe_until));c.execute('COMMIT')
        self.attempts+=1

    def finish(self, proxy_error=False):
        now=time.time();threshold=int(os.getenv('QUEST_READER_CIRCUIT_THRESHOLD','3'));cooldown=float(os.getenv('QUEST_READER_CIRCUIT_COOLDOWN','30'))
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT tokens,updated,failures,open_until,probe_until FROM state WHERE route=?',(self.route,)).fetchone()
            if row:
                tokens,updated,failures,open_until,probe_until=row
                if proxy_error:
                    failures+=1
                    if failures>=threshold or self.probe:open_until=now+cooldown;probe_until=0
                else:
                    failures=0;open_until=0;probe_until=0
                c.execute('UPDATE state SET failures=?,open_until=?,probe_until=? WHERE route=?',(failures,open_until,probe_until,self.route))
            c.execute('COMMIT')
        self.probe=False
