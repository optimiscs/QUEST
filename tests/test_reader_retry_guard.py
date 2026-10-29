import os
import sys
import time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
from reader_retry_guard import Guard,GuardRejected

@pytest.fixture(autouse=True)
def config(monkeypatch,tmp_path):
 monkeypatch.setenv('QUEST_READER_COORDINATION_DIR',str(tmp_path))
 monkeypatch.setenv('QUEST_READER_RETRY_CAPACITY','1')
 monkeypatch.setenv('QUEST_READER_RETRY_REFILL_PER_SECOND','0')
 monkeypatch.setenv('QUEST_READER_CIRCUIT_COOLDOWN','0.1')

def test_global_budget_shared_between_guards():
 a=Guard();a.before();a.finish();a.before();a.finish()
 b=Guard();b.before();b.finish()
 with pytest.raises(GuardRejected,match='shared retry budget'):b.before()

def test_proxy_circuit_half_open_and_recovery():
 for _ in range(3):
  g=Guard();g.before();g.finish(proxy_error=True)
 with pytest.raises(GuardRejected,match='circuit open'):Guard().before()
 time.sleep(.12);probe=Guard();probe.before()
 with pytest.raises(GuardRejected,match='circuit open'):Guard().before()
 probe.finish();Guard().before()

def test_rotated_keys_count_against_read_budget(monkeypatch):
 monkeypatch.setenv('QUEST_READER_RETRY_CAPACITY','20')
 g=Guard()
 for _ in range(3):g.before();g.finish()
 with pytest.raises(GuardRejected,match='per-read'):g.before()
