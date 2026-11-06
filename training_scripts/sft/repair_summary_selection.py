"""Rebuild a frozen selection from original messages without selecting new IDs."""
import collections
import json
import os
from pathlib import Path
import sqlite3
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
sys.path.insert(0, str(ROOT))
from optimize_summary_data import Pipeline, write, jsonl, sha
from clean_harness_trajectories import schemas_from_source, file_sha
from inherit_upstream_data import verify_conversion


def main():
    from transformers import AutoTokenizer
    prior, out = (Path(arg).resolve() for arg in sys.argv[1:3])
    out.mkdir(exist_ok=False)
    os.environ['QUEST_SOURCE_IDS'] = 'true'
    for name in ('sources', 'records', 'rules', 'inheritance-checks', 'logs', 'snapshot'):
        (out / name).mkdir()
    files = ['inference/source_ids.py', 'inference/native_tools.py',
             'training_scripts/sft/inherit_upstream_data.py', __file__]
    contract = {'mode': 'summary', 'parent': str(prior),
                'parent_selection_sha256': file_sha(prior / 'candidates1024.jsonl'),
                'source_hashes': {f: file_sha(ROOT / f) for f in files},
                'selection_unchanged': True, 'task_acceptance': 'inherited_upstream',
                'local_llm_rejudgment': False, 'purpose': 'lossless URL delimiter repair and self-contained source maps'}
    write(out / 'contract.json', contract)
    for f in files:
        path = ROOT / f
        (out / 'snapshot' / path.name).write_bytes(path.read_bytes())
    p = Pipeline.__new__(Pipeline)
    p.out = out
    p.source = ROOT / 'workspace/strict-reproduction/sft-summary1024-20261101-r1'
    p.db = sqlite3.connect((p.source / 'pool.sqlite').as_uri() + '?mode=ro', uri=True)
    p.schemas = [s for s in schemas_from_source() if s['function']['name'] in ('search', 'visit')]
    p.contract_sha = sha(contract)
    p.tokenizer = AutoTokenizer.from_pretrained(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4', local_files_only=True)
    before = [json.loads(line) for line in (prior / 'candidates1024.jsonl').open()]
    assert len(before) == 1024
    rows, changes = [], []
    for old in before:
        ident = old['metadata']['id']
        row = p.convert(old['metadata'])
        if row is None:
            raise ValueError(f'Repair failed; selection will not be silently replaced: {ident}')
        original = json.loads(zlib.decompress(p.db.execute('SELECT messages FROM pool WHERE id=?', (ident,)).fetchone()[0]))
        check = verify_conversion(original, row)
        row['metadata'] = dict(old['metadata'], **row['metadata'])
        row['metadata'].update(quality_status='upstream_accepted_harness_checked',
                               conversion_receipt=str(out / 'inheritance-checks' / (ident + '.json')))
        write(Path(row['metadata']['conversion_receipt']), check)
        write(out / 'records' / (ident + '.json'), row)
        source_map = Path(row['metadata']['source_map'])
        assert source_map.is_file() and source_map.is_relative_to(out)
        if row['messages'] != old['messages']:
            changes.append({'id': ident, 'old_sha256': sha(old['messages']), 'new_sha256': sha(row['messages']),
                            'changed_message_indices': [i for i, (a, b) in enumerate(zip(old['messages'], row['messages'])) if a != b]})
        rows.append(row)
        if len(rows) % 64 == 0:
            print(json.dumps({'rebuilt': len(rows), 'changed': len(changes)}), flush=True)
    assert [r['metadata']['id'] for r in rows] == [r['metadata']['id'] for r in before]
    by_id = {r['metadata']['id']: r for r in rows}
    samples = []
    for line in (prior / 'sample16-static.jsonl').open():
        old = json.loads(line)
        row = by_id[old['metadata']['id']]
        samples.append(dict(row, metadata=dict(row['metadata'], case=old['metadata']['case'])))
    jsonl(out / 'candidates1024.jsonl', rows)
    jsonl(out / 'sample16-static.jsonl', samples)
    write(out / 'repair-report.json', {'sessions': len(rows), 'same_order_and_ids': True,
        'conversion_receipts_passed': len(rows), 'self_contained_source_maps': len(rows),
        'changed_sessions': len(changes), 'changes': changes,
        'kind_counts': dict(collections.Counter(r['metadata']['kind'] for r in rows)),
        'training_started': False})


if __name__ == '__main__':
    main()
