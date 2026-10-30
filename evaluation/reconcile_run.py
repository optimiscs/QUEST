"""Reconcile a stopped QUEST benchmark run without replaying or modifying results."""
import argparse
import json
import os
import shutil
import time
from pathlib import Path


def atomic(path, data):
    tmp = path.with_name(path.name + '.reconcile.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def live_observer(pid, case):
    try:
        cmd = Path(f'/proc/{int(pid)}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        environ = Path(f'/proc/{int(pid)}/environ').read_bytes().split(b'\0')
        return 'observe-native.py' in cmd and f'QUEST_AUDIT_CASE={case}'.encode() in environ
    except (OSError, ValueError, TypeError):
        return False


def reconcile(root, backup):
    root, backup = Path(root), Path(backup)
    aggregate = {'epoch': time.time(), 'benchmarks': {}}
    scores = {}
    for path in sorted(root.glob('*/status.json')):
        obj = json.loads(path.read_text())
        if not isinstance(obj.get('cases'), dict):
            continue
        name = path.parent.name
        backup_path = backup/name/'status.json'
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if not backup_path.exists(): shutil.copy2(path, backup_path)
        for case, entry in obj['cases'].items():
            if entry.get('agent_state') == 'running' and not live_observer(entry.get('agent_pid'), case):
                entry.update(agent_state='interrupted', judge_state='unavailable', agent_error='observer process no longer exists; partial trace retained')
            receipt = path.parent/'checks'/f'{case}-score-receipt.json'
            if receipt.exists():
                try:
                    data = json.loads(receipt.read_text())
                    scores[f'{name}/{case}'] = {'state': data.get('status', 'needs_audit'), 'reconciled': True}
                except (OSError, ValueError):
                    scores[f'{name}/{case}'] = {'state': 'needs_audit', 'reason': 'invalid_receipt'}
            else:
                scores[f'{name}/{case}'] = {'state': 'interrupted' if entry.get('agent_state') == 'interrupted' else 'waiting_for_result'}
        counts = {k: sum(x.get('agent_state') == k for x in obj['cases'].values()) for k in ('running','terminal','pending','interrupted')}
        obj.update(counts, epoch=time.time())
        atomic(path, obj)
        aggregate['benchmarks'][name] = counts
    for file, data in [('status.json', aggregate), ('scoring-status.json', scores)]:
        path=root/file
        if path.exists() and not (backup/file).exists(): shutil.copy2(path, backup/file)
        atomic(path, data)
    return aggregate


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('run_root', type=Path)
    ap.add_argument('--backup', type=Path, required=True)
    args=ap.parse_args()
    print(json.dumps(reconcile(args.run_root, args.backup), ensure_ascii=False, indent=2))
