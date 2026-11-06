"""Build per-policy-call labels with the same native template used by vLLM.

The authoritative unit is 1024 sessions; each assistant target is supervised
once, with that call's exact prompt and thinking setting. No vendor converter.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inference import native_tools
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
from clean_harness_trajectories import dump, sha, file_sha


def policy_views(record):
    """Use recorded prompts across memory boundaries, never rebuild them."""
    messages=native_tools.prepare_messages(record['messages'])
    if record.get('training_views'):
        expected={i for i,m in enumerate(messages) if m['role']=='assistant'}
        views=record['training_views']
        if len(views)!=len(expected) or {v['history_step'] for v in views}!=expected:
            raise ValueError('Recorded views must supervise each assistant target exactly once')
        for view in views:
            i=view['history_step'];actual=native_tools.prepare_messages(view['messages'])
            if actual[-1]!=messages[i]:raise ValueError('Recorded target differs from canonical history')
            yield i,actual,view['final'],view['tools']
    else:
        for i,m in enumerate(messages):
            if m['role']=='assistant':yield i,messages[:i+1],i==len(messages)-1,record['tools']


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer
    run = Path(sys.argv[1]).resolve()
    tokenizer = AutoTokenizer.from_pretrained(str(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'), local_files_only=True)
    records = [json.loads(s) for s in (run / 'candidates1024.jsonl').open()]
    output = run / 'tokenized-turns.parquet'
    if output.exists(): raise FileExistsError(output)
    schema = pa.schema([('session_id', pa.string()), ('assistant_index', pa.int32()),
                        ('input_ids', pa.list_(pa.int32())), ('attention_mask', pa.list_(pa.int8())),
                        ('labels', pa.list_(pa.int32())), ('prompt_tokens', pa.int32()), ('final', pa.bool_())])
    count = 0; maximum = 0; loss_tokens = 0
    with pq.ParquetWriter(output, schema, compression='zstd') as writer:
        for record in records:
            messages = native_tools.prepare_messages(record['messages'])
            record['messages'] = messages
            lengths = []
            for i, view_messages, final, view_tools in policy_views(record):
                formatted = native_tools.prepare_messages(view_messages, for_template=True)
                kw = dict(tools=view_tools, enable_thinking=not final)
                prefix = tokenizer.apply_chat_template(formatted[:-1], tokenize=False, add_generation_prompt=True, **kw)
                complete = tokenizer.apply_chat_template(formatted, tokenize=False, add_generation_prompt=False, **kw)
                if not complete.startswith(prefix): raise ValueError('Target is not an extension of the serving prompt')
                prompt_ids = tokenizer.encode(prefix, add_special_tokens=False)
                target_ids = tokenizer.encode(complete[len(prefix):], add_special_tokens=False)
                if not target_ids: raise ValueError('Empty supervised target')
                ids = prompt_ids + target_ids
                if len(ids) > 65536: raise ValueError('Overlength; replace session rather than truncate')
                labels = [-100] * len(prompt_ids) + target_ids
                writer.write_table(pa.Table.from_pylist([{'session_id': record['metadata']['id'], 'assistant_index': i,
                    'input_ids': ids, 'attention_mask': [1]*len(ids), 'labels': labels,
                    'prompt_tokens': len(prompt_ids), 'final': final}], schema=schema))
                count += 1; loss_tokens += len(target_ids); maximum = max(maximum, len(ids)); lengths.append(len(ids))
            record['metadata'].update(tokens=max(lengths), converted_sha256=sha(messages))
            if len(records) and count % 100 < len(lengths): print(json.dumps({'turns': count, 'max_tokens': maximum}), flush=True)
    by_id = {r['metadata']['id']: r for r in records}
    # Keep the original selection immutable as an audit input.
    with (run / 'sft1024-summary-native.jsonl').open('x') as stream:
        for record in records: stream.write(json.dumps(record, ensure_ascii=False)+'\n')
    samples = [json.loads(s) for s in (run / 'sample16-static.jsonl').open()]
    with (run / 'sample16-aligned.jsonl').open('x') as stream:
        for sample in samples:
            current = dict(by_id[sample['metadata']['id']])
            current['metadata'] = dict(current['metadata'], case=sample['metadata']['case'])
            stream.write(json.dumps(current,ensure_ascii=False)+'\n')
    dump(run / 'tokenization-report.json', {'sessions':len(records), 'supervised_turns':count, 'max_tokens':maximum,
        'min_session_max_tokens':min(r['metadata']['tokens'] for r in records), 'loss_tokens':loss_tokens,
        'overlength':0, 'truncated':0, 'quality_status':'pending',
        'initial_selection_token_counts_superseded':True,
        'native_tools_sha256':file_sha(ROOT/'inference/native_tools.py'),
        'chat_template_sha256':file_sha(ROOT/'workspace/models/Qwen3.8-27B-NVFP4/chat_template.jinja')})


if __name__ == '__main__': main()
