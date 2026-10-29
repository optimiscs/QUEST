import multiprocessing as mp
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'inference'))
import reader_singleflight


def worker(url, start, queue, counter):
    start.wait()
    def fetch():
        with counter.get_lock(): counter.value += 1
        time.sleep(0.5)
        return 'actual content'
    queue.put(reader_singleflight.run(url, fetch))


def test_overlapping_processes_share_one_fetch_and_later_request_refetches(monkeypatch, tmp_path):
    monkeypatch.setenv('QUEST_READER_COORDINATION_DIR', str(tmp_path))
    ctx=mp.get_context('fork');start=ctx.Event();q=ctx.Queue();counter=ctx.Value('i',0)
    workers=[ctx.Process(target=worker,args=('https://example.test/x',start,q,counter)) for _ in range(5)]
    for p in workers:p.start()
    start.set()
    for p in workers:p.join(5);assert p.exitcode==0
    assert [q.get(timeout=1) for _ in workers]==['actual content']*5
    assert counter.value==1
    assert reader_singleflight.run('https://example.test/x',lambda:'fresh')=='fresh'
