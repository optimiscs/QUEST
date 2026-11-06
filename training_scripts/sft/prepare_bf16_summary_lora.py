"""Prepare nonquantized BF16 LoRA using the audited native-token training data."""
import collections
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    import yaml
    from datasets import Dataset, DatasetDict
    from transformers import AutoTokenizer
    data, run, base = (Path(arg).resolve() for arg in sys.argv[1:4])
    run.mkdir(exist_ok=False)
    for name in ('configs', 'checks', 'logs'):
        (run / name).mkdir()
    multiturn = (data / 'multiturn-report.json').exists()
    serving = data / 'tokenizer' if multiturn else ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'
    original_tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(serving, local_files_only=True)
    assert original_tokenizer.get_vocab() == tokenizer.get_vocab(), 'Base embedding vocabulary differs'
    config = json.loads((base / 'config.json').read_text())
    assert not config.get('quantization_config')
    index = json.loads((base / 'model.safetensors.index.json').read_text())
    dtype_counts = collections.Counter()
    keys = set()
    for filename in set(index['weight_map'].values()):
        path = base / filename
        with path.open('rb') as stream:
            size = struct.unpack('<Q', stream.read(8))[0]
            header = json.loads(stream.read(size))
        for key, tensor in header.items():
            if key == '__metadata__': continue
            assert tensor['dtype'] == 'BF16', (key, tensor['dtype'])
            assert 8 + size + tensor['data_offsets'][1] <= path.stat().st_size
            assert index['weight_map'][key] == filename
            keys.add(key)
            dtype_counts[tensor['dtype']] += 1
    assert keys == set(index['weight_map'])
    # An isolated view preserves the untouched BF16 weights and the exact
    # serving tokenizer. No quantized tensor is loaded or dequantized.
    model = run / 'bf16-model-with-harness-tokenizer'
    model.mkdir()
    for path in base.iterdir():
        if path.is_file() and path.suffix in ('.json', '.jinja', '.txt', '.safetensors'):
            (model / path.name).symlink_to(path)
    for name in ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja',
                 'vocab.json', 'merges.txt', 'special_tokens_map.json', 'added_tokens.json'):
        source = serving / name
        if source.is_file():
            (model / name).unlink(missing_ok=True)
            shutil.copy2(source, model / name)
    parquet = 'tokenized-multiturn.parquet' if multiturn else 'tokenized-turns.parquet'
    ds = Dataset.from_parquet(str(data / parquet), cache_dir=str(run / 'dataset-cache'))
    sessions, finals, lengths = set(), collections.Counter(), []
    loss_tokens = 0
    assistant_targets = 0
    for row in ds:
        if multiturn:
            expected_labels = [-100] * len(row['input_ids'])
            for span in row['assistant_spans']:
                expected_labels[span['start']:span['end']] = row['input_ids'][span['start']:span['end']]
                if span['final']: finals[row['session_id']] += 1
            assert row['labels'] == expected_labels
            assistant_targets += len(row['assistant_spans'])
        else:
            n = row['prompt_tokens']
            assert row['labels'][:n] == [-100] * n and row['labels'][n:] == row['input_ids'][n:]
            if row['final']: finals[row['session_id']] += 1
            assistant_targets += 1
        assert len(row['labels']) == len(row['input_ids']) and all(row['attention_mask'])
        sessions.add(row['session_id'])
        lengths.append(len(row['input_ids']))
        loss_tokens += sum(x != -100 for x in row['labels'])
    assert len(sessions) == 1024 and set(finals) == sessions and set(finals.values()) == {1}
    assert max(lengths) <= 32768
    train = ds.select_columns(['input_ids', 'attention_mask', 'labels'])
    DatasetDict(train=train).save_to_disk(str(run / 'tokenized-dataset'))
    longest = max(range(len(ds)), key=lambda i: lengths[i])
    # Two backward passes accumulate into one optimizer update at the maximum
    # sequence length; the smoke adapter is never used to initialize training.
    DatasetDict(train=train.select([longest, longest])).save_to_disk(str(run / 'smoke-dataset'))
    cfg = yaml.safe_load((ROOT / 'training_scripts/sft/examples/lora27b_32k_single_gpu.yaml').read_text())
    cfg.update(model_name_or_path=str(model), dataset='quest_summary1024_native', dataset_dir=str(run / 'configs'),
               do_eval=False, eval_strategy='no', val_size=0.0,
               output_dir=str(ROOT / 'workspace/sft-runs' / run.name),
               logging_dir=str(run / 'tensorboard/train'),
               tokenized_path=str(run / 'tokenized-dataset'),
               lora_rank=32, lora_alpha=64, learning_rate=5e-5,
               per_device_train_batch_size=1, gradient_accumulation_steps=32,
               num_train_epochs=1.0, logging_steps=1, logging_first_step=True,
               dataloader_num_workers=2, save_total_limit=3, save_steps=4 if multiturn else 25,
               run_name=run.name, report_to=['tensorboard'])
    assert not cfg.get('quantization_bit') and cfg['bf16'] is True
    (run / 'configs/train.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
    smoke = dict(cfg, output_dir=str(run / 'smoke-output'), tokenized_path=str(run / 'smoke-dataset'),
                 logging_dir=str(run / 'tensorboard/smoke'),
                 gradient_accumulation_steps=2, max_steps=1, warmup_ratio=0.0, save_steps=1,
                 run_name='quest27b-bf16-lora-longest-smoke', report_to=[])
    (run / 'configs/smoke.yaml').write_text(yaml.safe_dump(smoke, sort_keys=False))
    report = {'sessions': len(sessions), 'training_rows': len(ds), 'loss_tokens': loss_tokens,
        'max_tokens': max(lengths), 'total_input_tokens': sum(lengths),
        'epochs': 1, 'effective_batch_size': 32,
        'batch_unit': 'intact_multiturn_sessions' if multiturn else 'assistant policy-call training rows',
        'assistant_targets': assistant_targets,
        'optimizer_steps': math.ceil(len(ds) / 32), 'r': 32, 'alpha': 64, 'learning_rate': 5e-5,
        'dtype_counts': dict(dtype_counts), 'base_weights': str(base), 'model_view': str(model),
        'base_vocabulary_matches_serving': True, 'tokenizer_source': str(serving),
        'chat_template_sha256': hashlib.sha256((serving / 'chat_template.jinja').read_bytes()).hexdigest(),
        'quantization': None, 'truncated': 0, 'selection': str(data),
        'smoke_longest_session': ds[longest]['session_id'], 'training_started': False}
    (run / 'checks/preparation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
