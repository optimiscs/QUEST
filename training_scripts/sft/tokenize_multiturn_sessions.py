"""One loss-masked multi-turn record per existing session, without truncation."""
import collections
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
from inference import native_tools
from clean_harness_trajectories import file_sha
from optimize_summary_data import write, jsonl
from clean_harness_trajectories import sha

TYPES = ('question_to_compression', 'question_to_answer',
         'compression_to_compression', 'compression_to_answer')


def classify(record):
    initial = record['messages'][1]['content']
    compressed = 'RESEARCH STATE SUMMARY (prev_state)' in initial
    final = json.loads(record['messages'][-1]['content'])
    if not isinstance(final.get('answer'), str) or not final['answer'].strip():
        raise ValueError('Expected an answer-ending selected session')
    return 'compression_to_answer' if compressed else 'question_to_answer'


def fixed_system_template(original):
    old = '{%- if enable_thinking is undefined or enable_thinking is true %}'
    assert original.count(old) == 1
    # enable_thinking still controls the generation prefix. Only the system
    # instruction is held fixed; research behavior and all reasoning text stay
    # unchanged. The same versioned tokenizer MUST be loaded when serving.
    new = ("{# Keep the system prefix stable across research and final calls. #}\n"
           "{%- if consistent_system_prompt|default(true) or enable_thinking is undefined or enable_thinking is true %}")
    result = original.replace(old, new)
    old_block = "reasoning_content + '\\n</think>\\n\\n' + content"
    assert result.count(old_block) == 1
    # An empty research thought must end directly after the generation prefix
    # <think>\n. An extra newline would merge into a different BPE token and
    # make a single multi-turn token sequence inconsistent at that boundary.
    return result.replace(old_block,
        "reasoning_content + ('\\n' if reasoning_content or not message.tool_calls else '') + '</think>\\n\\n' + content")


def encode_session(record, tokenizer, limit=32768):
    messages = native_tools.prepare_messages(record['messages'], for_template=True)
    def render(history, generation=False, final=False):
        return tokenizer.apply_chat_template(history, tools=record['tools'], tokenize=False,
            enable_thinking=not final, add_generation_prompt=generation)
    text = render(messages, final=True)
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) > limit:
        raise ValueError(f'Session exceeds {limit}; requires a separately audited boundary split, never truncation')
    labels = [-100] * len(ids)
    spans = []
    for i, message in enumerate(messages):
        if message['role'] != 'assistant': continue
        final = i == len(messages) - 1
        prefix = render(messages[:i], generation=True, final=final)
        complete = render(messages[:i+1], final=final)
        assert complete.startswith(prefix) and text.startswith(complete), 'Unstable multi-turn template'
        prompt_ids = tokenizer.encode(prefix, add_special_tokens=False)
        complete_ids = tokenizer.encode(complete, add_special_tokens=False)
        start, end = len(prompt_ids), len(complete_ids)
        assert ids[:start] == prompt_ids, 'Training prefix differs from serving policy call'
        assert ids[:end] == complete_ids, 'Completion token boundary differs'
        assert end > start and all(x == -100 for x in labels[start:end])
        labels[start:end] = ids[start:end]
        spans.append({'assistant_index': i, 'start': start, 'end': end, 'final': final})
    return {'session_id': record['metadata']['id'], 'sample_type': classify(record),
            'input_ids': ids, 'attention_mask': [1] * len(ids), 'labels': labels,
            'assistant_spans': spans}


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer
    source, out = (Path(x).resolve() for x in sys.argv[1:3])
    out.mkdir(exist_ok=False)
    for name in ('tokenizer', 'logs', 'snapshot', 'sources'):
        (out / name).mkdir()
    original_tokenizer = ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'
    for name in ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja',
                 'vocab.json', 'merges.txt', 'special_tokens_map.json', 'added_tokens.json'):
        path = original_tokenizer / name
        if path.is_file(): shutil.copy2(path, out / 'tokenizer' / name)
    template_path = out / 'tokenizer/chat_template.jinja'
    template_path.write_text(fixed_system_template(template_path.read_text()))
    tokenizer = AutoTokenizer.from_pretrained(out / 'tokenizer', local_files_only=True)
    old_targets = {}
    for batch in pq.ParquetFile(source / 'tokenized-turns.parquet').iter_batches(batch_size=64):
        for row in batch.to_pylist():
            old_targets[(row['session_id'], row['assistant_index'])] = row['labels'][row['prompt_tokens']:]
    records = [json.loads(line) for line in (source / 'candidates1024.jsonl').open()]
    assert len(records) == len({r['metadata']['id'] for r in records}) == 1024
    encoded, lengths, counts = [], [], collections.Counter()
    checks, loss_tokens = 0, 0
    repairs = []
    for record in records:
        original_messages = record['messages']
        record['messages'] = native_tools.prepare_messages(original_messages)
        record['metadata']['converted_sha256'] = sha(record['messages'])
        row = encode_session(record, tokenizer)
        for span in row['assistant_spans']:
            target = row['labels'][span['start']:span['end']]
            old_target = old_targets[(row['session_id'], span['assistant_index'])]
            if target != old_target:
                old_message = original_messages[span['assistant_index']]
                assert old_message.get('tool_calls') and old_message.get('content', '').strip() == '<think>'
                assert not old_message.get('reasoning_content')
                old_text, new_text = tokenizer.decode(old_target), tokenizer.decode(target)
                marker = '\n</think>\n\n<think>\n\n'
                assert old_text.startswith(marker)
                assert new_text == '</think>\n\n' + old_text[len(marker):], 'Non-format target change'
                repairs.append({'id': row['session_id'], 'assistant_index': span['assistant_index'],
                    'reason': 'Remove orphan empty think delimiter and normalize empty tool-turn thinking boundary',
                    'old_target_tokens': len(old_target), 'new_target_tokens': len(target)})
            checks += 1
        lengths.append(len(row['input_ids']))
        loss_tokens += sum(x != -100 for x in row['labels'])
        counts[row['sample_type']] += 1
        source_map = Path(record['metadata']['source_map'])
        destination = out / 'sources' / row['session_id']
        destination.mkdir()
        for name in ('sources.json', 'source-provenance.json'):
            p = source_map.parent / name
            if p.exists(): shutil.copy2(p, destination / name)
        record['metadata'].update(source_map=str(destination / 'sources.json'),
            sample_type=row['sample_type'], training_unit='intact_multiturn_session', tokens=len(row['input_ids']))
        encoded.append(row)
        if len(encoded) % 64 == 0:
            print(json.dumps({'sessions': len(encoded), 'max_tokens': max(lengths), 'checked_assistant_targets': checks}), flush=True)
    assert checks == len(old_targets)
    pq.write_table(pa.Table.from_pylist(encoded), out / 'tokenized-multiturn.parquet', compression='zstd')
    jsonl(out / 'candidates1024.jsonl', records)
    by_id = {r['metadata']['id']: r for r in records}
    samples = []
    for line in (source / 'sample16-static.jsonl').open():
        old = json.loads(line); r = by_id[old['metadata']['id']]
        samples.append(dict(r, metadata=dict(r['metadata'], case=old['metadata']['case'])))
    jsonl(out / 'sample16-static.jsonl', samples)
    sorted_lengths = sorted(lengths)
    report = {'sessions': 1024, 'training_rows': len(encoded), 'assistant_targets': checks,
        'unchanged_targets': checks - len(repairs), 'format_only_target_repairs': repairs,
        'all_local_policy_prefixes_equal': True,
        'max_tokens': max(lengths), 'min_tokens': min(lengths),
        'median_tokens': (sorted_lengths[511] + sorted_lengths[512]) / 2,
        'p95_tokens': sorted_lengths[int(len(lengths) * .95)],
        'total_input_tokens': sum(lengths), 'loss_tokens': loss_tokens,
        'cutoff': 32768, 'overlength': 0, 'split_sessions': 0, 'truncated': 0,
        'types': {t: counts[t] for t in TYPES}, 'observed_type_count': len(counts),
        'types_by_kind': {kind: {t: sum(r['metadata']['kind'] == kind and classify(r) == t for r in records)
                               for t in TYPES} for kind in ('objective', 'openended')},
        'parent': str(source), 'same_1024_ids_and_order': True,
        'upstream_acceptance_reused': True, 'task_content_unchanged': True,
        'format_repaired_sessions': len({r['id'] for r in repairs}),
        'tokenizer_path': str(out / 'tokenizer'),
        'template_change': 'Keep system reasoning instruction constant; final generation thinking remains disabled.',
        'chat_template_sha256': file_sha(template_path), 'training_started': False}
    write(out / 'multiturn-report.json', report)
    write(out / 'contract.json', {'source_selection_sha256': file_sha(source / 'candidates1024.jsonl'),
        'chat_template_sha256': file_sha(template_path), 'exporter_sha256': file_sha(Path(__file__)),
        'old_template_sha256': file_sha(original_tokenizer / 'chat_template.jinja'),
        'native_tools_sha256': file_sha(ROOT / 'inference/native_tools.py'),
        'required_serving_tokenizer': str(out / 'tokenizer'),
        'max_sequence_length': 32768, 'training_unit': 'intact_multiturn_session'})
    shutil.copy2(__file__, out / 'snapshot' / Path(__file__).name)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
