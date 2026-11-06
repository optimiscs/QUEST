"""Select summary-mode sessions without dropping memory-bearing examples.

Produces a provisional 1024-session set and fixed 16-question regression input.
Quality and train/inference parity remain pending the recorded validation run.
"""
import collections
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
from clean_harness_trajectories import DATASETS, Rejected, dump, eval_questions, file_sha, parse_trajectory, question_key, schemas_from_source, sha
from replay_cleaning_pilot import compact_known, search_format
from inference import native_tools, source_ids
import prompt

FINAL_PROMPT = ('Research is complete. Do not call tools. Using only the evidence already obtained, '
                'return a JSON object with an answer string in the requested format. '
                'If evidence is insufficient, use "Unknown".')


def main():
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'pool.sqlite').exists():
        raise FileExistsError('Use a new selection directory')
    os.environ['QUEST_SOURCE_IDS'] = 'true'
    schemas = [s for s in schemas_from_source() if s['function']['name'] in {'search', 'visit'}]
    db = sqlite3.connect(out / 'pool.sqlite')
    db.execute('CREATE TABLE pool (id TEXT PRIMARY KEY,q TEXT,kind TEXT,turns INTEGER,memory INTEGER,meta TEXT,messages BLOB)')
    eval_keys, _ = eval_questions(ROOT / 'evaluation')
    counts = collections.defaultdict(collections.Counter)
    for kind, ds in DATASETS.items():
        for file in sorted((ROOT / 'workspace/datasets' / ds / 'data').glob('*.parquet')):
            index = 0
            for batch in pq.ParquetFile(file).iter_batches(batch_size=32, columns=['messages']):
                for row in batch.to_pylist():
                    original = row['messages']; rowno = index; index += 1
                    counts[kind]['raw'] += 1
                    try:
                        native, features = parse_trajectory(original, schemas, allow_memory=True)
                        question = re.split(r'\n\s*=+\s*\nRESEARCH STATE SUMMARY', native[1]['content'], maxsplit=1)[0].strip()
                        q = question_key(question)
                        if q in eval_keys:
                            raise Rejected('exact_eval_question')
                        memory = 'RESEARCH STATE SUMMARY (prev_state)' in native[1]['content']
                        ident = sha(original)
                        meta = {'id': ident, 'question_sha256': q, 'question': question, 'kind': kind,
                                'file': str(file), 'row': rowno, 'visible_tool_calls': features['tool_calls'],
                                'has_memory': memory, 'session_type': 'post_condenser_session' if memory else 'full_visible_session',
                                'repairs': features['repairs'], 'quality_status': 'unverified'}
                        db.execute('INSERT OR IGNORE INTO pool VALUES (?,?,?,?,?,?,?)',
                                   (ident, q, kind, features['tool_calls'], int(memory), json.dumps(meta), zlib.compress(json.dumps(native, ensure_ascii=False).encode())))
                        counts[kind]['protocol_valid'] += 1
                    except Rejected as exc:
                        counts[kind][str(exc)] += 1
            db.commit()
            print(json.dumps({'kind': kind, 'file': file.name, 'counts': dict(counts[kind])}), flush=True)
    tokenizer = AutoTokenizer.from_pretrained(str(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'), local_files_only=True)
    selected = []; seen = set(); rejection = collections.Counter(); strata = {}
    for kind, target in [('objective', 768), ('openended', 256)]:
        # Keep all alternate sessions available until after protocol/ID validation.
        records = list(db.execute('SELECT id,q,turns,memory FROM pool WHERE kind=? ORDER BY turns,id', (kind,)))
        bins = [records[len(records)*i//4:len(records)*(i+1)//4] for i in range(4)]
        strata[kind] = []
        for b, pool in enumerate(bins):
            # Alternate memory-bearing and full-history sessions where available.
            groups = [[r for r in pool if r[3] == m] for m in (0, 1)]
            for group in groups:
                group.sort(key=lambda r: sha(('summary1024-v1', r[0])))
            ordered = []
            for i in range(max(map(len, groups))):
                for group in groups:
                    if i < len(group): ordered.append(group[i])
            picked = 0
            for ident, q, turns, memory in ordered:
                if q in seen:
                    continue
                meta_raw, blob = db.execute('SELECT meta,messages FROM pool WHERE id=?', (ident,)).fetchone()
                meta = json.loads(meta_raw); messages = json.loads(zlib.decompress(blob))
                folder = out / 'source-maps' / ident
                registry = source_ids.SourceRegistry(folder)
                date_match = re.search(r'Current date:\s*([^\n]*)', messages[0]['content'])
                messages[0]['content'] = native_tools.system_prompt(prompt.SYSTEM_PROMPT) + (date_match[1] if date_match else '')
                converted = [registry.context(messages[0], 'system'), registry.context(messages[1], 'user')]
                pending = None
                try:
                    for message in messages[2:]:
                        if message['role'] == 'assistant':
                            converted.append(compact_known(registry, message))
                            calls = message.get('tool_calls', [])
                            pending = calls[0]['function']['name'] if calls else None
                        else:
                            body = registry.render(search_format(message['content'])) if pending == 'search' else registry.compact(message['content'])
                            converted.append(dict(message, content=body))
                    converted.insert(-1, {'role': 'user', 'content': FINAL_PROMPT})
                    api_messages = native_tools.prepare_messages(converted)
                    template_messages = native_tools.prepare_messages(converted, for_template=True)
                    token_ids = tokenizer.apply_chat_template(template_messages, tools=schemas, tokenize=True, add_generation_prompt=False, return_dict=False)
                    if len(token_ids) > 65536:
                        raise ValueError('over_65536_no_truncation')
                    registry.context(api_messages, 'static_export')
                except ValueError as exc:
                    rejection[str(exc)] += 1
                    continue
                meta.update(stratum=b, tokens=len(token_ids), source_map=str(registry.path),
                            converted_sha256=sha(api_messages), tools_sha256=sha(schemas))
                selected.append({'messages': api_messages, 'tools': schemas, 'metadata': meta})
                seen.add(q); picked += 1
                if picked == target // 4:
                    break
            strata[kind].append({'stratum': b, 'available_rows': len(pool), 'turn_min': pool[0][2], 'turn_max': pool[-1][2], 'selected': picked})
            print(json.dumps({'kind': kind, 'stratum': b, 'selected': picked}), flush=True)
            if picked != target // 4:
                dump(out / 'incomplete.json', {'strata': strata, 'rejections': dict(rejection)})
                raise RuntimeError('Insufficient candidates in stratum; do not relax silently')
    assert len(selected) == len(seen) == 1024
    with (out / 'candidates1024.jsonl').open('x') as stream:
        for record in selected: stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    sample = []
    for kind, n in [('objective', 3), ('openended', 1)]:
        for b in range(4):
            group = [r for r in selected if r['metadata']['kind'] == kind and r['metadata']['stratum'] == b]
            group.sort(key=lambda r: sha(('summary16-v1', r['metadata']['id'])))
            sample.extend(group[:n])
    configs = out / 'configs'; configs.mkdir(exist_ok=True)
    with (out / 'sample16-static.jsonl').open('x') as stream:
        for i, record in enumerate(sample):
            meta = record['metadata']; case = f'case{i:02d}'
            record['metadata']['case'] = case
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            # No reference answer, state summary, or old evidence enters fresh rollout.
            item = {'question': meta['question'], 'answer': '', 'filename': case}
            (configs / (case + '.jsonl')).write_text(json.dumps(item, ensure_ascii=False) + '\n')
            (configs / (case + '-server_endpoints.conf')).write_text('HOSTNAME_LIST=127.0.0.1\nPORTS=19300\n')
    report = {'selected': len(selected), 'sample16': len(sample), 'counts': {k: dict(v) for k,v in counts.items()},
              'strata': strata, 'rejections': dict(rejection), 'memory_sessions': sum(r['metadata']['has_memory'] for r in selected),
              'tokens_min': min(r['metadata']['tokens'] for r in selected), 'tokens_max': max(r['metadata']['tokens'] for r in selected),
              'quality_status': 'pending_summary_mode_validation', 'sample16_is_heldout_benchmark': False,
              'source_hashes': {f: file_sha(ROOT / 'inference' / f) for f in ['react_agent.py','native_tools.py','source_ids.py','tool_visit.py','prompt.py']}}
    dump(out / 'selection-report.json', report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
