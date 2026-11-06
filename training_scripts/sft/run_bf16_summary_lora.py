"""Run longest-example BF16 smoke, then one epoch; never fall back to quantization."""
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / 'workspace/envs/llamafactory-v095-qlora'
LF = ROOT / 'workspace/strict-reproduction/llamafactory-v095-qlora32k-20261027-r1/LlamaFactory'


def main():
    run = Path(sys.argv[1]).resolve(strict=True)
    def record(stage, **fields):
        value = {'stage': stage, 'epoch_time': time.time(), **fields}
        path = run / 'checks/workflow-status.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2))
        temporary.replace(path)
        pointer = ROOT / 'workspace/strict-reproduction/active-sft-optimization.json'
        if pointer.exists():
            current = json.loads(pointer.read_text())
            if current.get('training_workflow') == str(run):
                current.update(training_phase=stage, training_running=stage == 'train_running')
                if stage in ('train_running', 'complete'): current['training_started'] = True
                pointer.write_text(json.dumps(current, indent=2))
        print(json.dumps(value), flush=True)
    with (run / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            preparation = json.loads((run / 'checks/preparation.json').read_text())
            data = Path(preparation['selection'])
            audit = json.loads((data / 'audit-all1024/report.json').read_text())
            assert audit['sessions'] == audit['protocol_pass'] == audit['identical_current_rebuild'] == 1024
            assert audit['conversion_counts'] == {'pass': 1024}
            assert audit['target_encoding_pass'] == 1024 and audit['all_prefixes_equal']
            assert audit['checked_prefixes'] == preparation.get('assistant_targets', preparation['training_rows'])
            assert preparation['quantization'] is None
            env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', PYTHONNOUSERSITE='1',
                HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                HF_HOME=str(run / 'hf-cache'), HF_DATASETS_CACHE=str(run / 'hf-cache/datasets'),
                TMPDIR='/root/autodl-tmp/quest27tmp', TOKENIZERS_PARALLELISM='false',
                OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True',
                CUDA_HOME='/usr/local/cuda', PYTHONPATH=str(LF / 'src'), PYTHONUNBUFFERED='1',
                QUEST_REQUIRE_BF16_LORA='1',
                QUEST_HARNESS_TOKENIZER_DIR=str(run / 'bf16-model-with-harness-tokenizer'))
            env['PATH'] = f'/usr/local/cuda/bin:{ENV / "bin"}:' + env.get('PATH', '')
            Path(env['TMPDIR']).mkdir(exist_ok=True)
            def launch(mode):
                state = run / (mode + '-state')
                command = [str(ENV / 'bin/python'), str(ROOT / 'training_scripts/sft/supervise_qlora.py'),
                    '--config', str(run / 'configs' / (mode + '.yaml')), '--state-dir', str(state),
                    '--env-dir', str(ENV), '--llamafactory', str(LF),
                    '--resource-tb', str(state / 'tensorboard'), '--world-size', '1']
                record(mode + '_running', state=str(state))
                with (run / 'logs' / (mode + '-supervisor.log')).open('x') as log:
                    subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
            launch('smoke')
            smoke = run / 'smoke-output'
            state = json.loads((smoke / 'trainer_state.json').read_text())
            metrics = json.loads((smoke / 'train_results.json').read_text())
            assert state['global_step'] == 1 and math.isfinite(metrics['train_loss'])
            for name in ('adapter_model.safetensors', 'optimizer.pt', 'scheduler.pt'):
                assert (smoke / 'checkpoint-1' / name).is_file()
            from safetensors import safe_open
            import torch
            with safe_open(smoke / 'adapter_model.safetensors', framework='pt', device='cpu') as handle:
                assert any(torch.count_nonzero(handle.get_tensor(key)).item() > 0 for key in handle.keys() if 'lora_B' in key)
            record('smoke_passed', loss=metrics['train_loss'], max_tokens=preparation['max_tokens'])
            if (run / 'STOP').exists():
                record('stopped_before_training')
                return
            launch('train')
            cfg = yaml.safe_load((run / 'configs/train.yaml').read_text())
            output = Path(cfg['output_dir'])
            state = json.loads((output / 'trainer_state.json').read_text())
            assert state['global_step'] == preparation['optimizer_steps'] and state['epoch'] >= 0.999
            assert (output / 'adapter_model.safetensors').is_file()
            record('complete', output=str(output), global_step=state['global_step'], epoch=state['epoch'])
        except Exception as exc:
            record('stopped' if (run / 'STOP').exists() else 'failed',
                   error=type(exc).__name__ + ': ' + str(exc), quantized_fallback=False)
            raise


if __name__ == '__main__':
    main()
