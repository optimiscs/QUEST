import json
import multiprocessing

from inference.retry_manifest import complete_retry


def test_parallel_retries_preserve_each_others_receipts(tmp_path):
    manifest = tmp_path/'retry-required.json'
    manifest.write_text(json.dumps({'cases': [{'group': 'g', 'case': str(i), 'status': 'pending_retry'} for i in range(12)]}))
    workers = [multiprocessing.Process(target=complete_retry, args=(manifest, 'g', str(i), {'status': 'completed', 'is_correct': bool(i % 2)})) for i in range(12)]
    for worker in workers: worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    rows = json.loads(manifest.read_text())['cases']
    assert all(row['status'] == 'completed' and row['is_correct'] == bool(int(row['case']) % 2) for row in rows)
