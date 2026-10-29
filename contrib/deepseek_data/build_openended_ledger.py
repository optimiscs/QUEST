"""Build an open-ended ledger from validated scoring and trajectory evidence."""
import argparse
import json
from pathlib import Path
try:
    from .evidence import digest, validate
except ImportError:
    from evidence import digest, validate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('score', 'candidate', 'sessions', 'reference', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--reference-kind', choices=['independent_agent', 'provisional_generator'], required=True)
    a = p.parse_args()
    paths = {name: getattr(a, name).resolve() for name in ('score', 'candidate', 'sessions', 'reference', 'out')}
    paths['status'] = paths['score'].with_suffix('.status.json')
    if paths['out'].exists():
        raise FileExistsError('refusing to overwrite ledger')
    result = validate(*(paths[k] for k in ('score', 'candidate', 'reference', 'sessions', 'status')), a.reference_kind)
    row = {k: result[k] for k in ('task_id', 'rollout_id', 'score', 'score_status')}
    row.update(kind='openended', reference_kind=a.reference_kind)
    for role in ('score', 'candidate', 'reference', 'sessions', 'status'):
        row[role + '_path'] = str(paths[role])
        row[role + '_sha256'] = digest(paths[role])
    with paths['out'].open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({'score': result['score'], 'status': result['score_status'], 'threshold': 0.475}))


if __name__ == '__main__':
    main()
