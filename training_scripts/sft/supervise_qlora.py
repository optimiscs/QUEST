#!/usr/bin/env python3
"""Explicitly launch an observed LlamaFactory SFT run with checkpoint safeguards.

This is an opt-in launcher, not a scheduler. It performs no automatic retries.
Use a dedicated output directory and keep every attempt's log and checkpoints.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import yaml
from safetensors import safe_open


def latest_checkpoint(output, ranks):
    """Find the newest fully saved adapter checkpoint or fail closed."""
    candidates=[]
    for p in output.glob('checkpoint-*'):
        tail=p.name.removeprefix('checkpoint-')
        if p.is_dir() and tail.isdigit():candidates.append((int(tail),p))
    if not candidates:return None
    step,path=max(candidates)
    rng=['rng_state.pth'] if ranks==1 else [f'rng_state_{i}.pth' for i in range(ranks)]
    required=['adapter_model.safetensors','adapter_config.json','optimizer.pt','scheduler.pt','trainer_state.json',*rng]
    missing=[n for n in required if not (path/n).is_file() or not (path/n).stat().st_size]
    if missing:raise ValueError(f'Incomplete latest checkpoint {path}: {missing}; preserve and inspect before retry')
    json.loads((path/'adapter_config.json').read_text())
    with safe_open(path/'adapter_model.safetensors',framework='pt',device='cpu') as adapter:
        if not adapter.keys():raise ValueError('adapter contains no tensors')
    state=json.loads((path/'trainer_state.json').read_text())
    if state.get('global_step')!=step:raise ValueError('checkpoint directory and trainer step disagree')
    if isinstance(state.get('max_steps'),int) and step>=state['max_steps']:
        raise ValueError('checkpoint reached max_steps; inspect final evaluation and outputs before restart')
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--state-dir',type=Path,required=True,help='Private attempt logs and STOP/PAUSE markers')
    parser.add_argument('--env-dir',type=Path,required=True,help='Python environment containing torchrun and LlamaFactory')
    parser.add_argument('--llamafactory',type=Path,required=True,help='Unmodified LlamaFactory checkout')
    parser.add_argument('--resource-tb',type=Path,required=True)
    parser.add_argument('--world-size',type=int,default=4)
    args=parser.parse_args()
    if args.world_size<1:parser.error('--world-size must be positive')
    config=args.config.resolve(strict=True);envdir=args.env_dir.resolve(strict=True);source=args.llamafactory.resolve(strict=True)
    state_dir=args.state_dir.resolve();state_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    settings=yaml.safe_load(config.read_text())
    if not isinstance(settings,dict) or not settings.get('output_dir'):raise ValueError('config must have output_dir')
    output=Path(settings['output_dir']).expanduser().resolve()
    if settings.get('deepspeed'):raise ValueError('checkpoint inspection currently supports non-ZeRO LoRA only')
    if settings.get('resume_from_checkpoint'):raise ValueError('remove manual resume_from_checkpoint; this launcher chooses the latest verified checkpoint')
    with (state_dir/'training.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if any((state_dir/x).exists() for x in ('PAUSE','STOP')):raise SystemExit('PAUSE/STOP marker exists')
        if (state_dir/'success.json').exists():raise SystemExit('Run already completed')
        checkpoint=latest_checkpoint(output,args.world_size)
        if checkpoint is None and output.exists() and any(output.iterdir()):
            raise ValueError('nonempty output has no verified checkpoint; inspect or choose a fresh output directory')
        attempt=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+f'-{os.getpid()}'
        attempt_dir=state_dir/'attempts'/attempt;attempt_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
        env=dict(os.environ,QUEST_ATTEMPT_DIR=str(attempt_dir),QUEST_CONFIG=str(config),QUEST_RESOURCE_TB=str(args.resource_tb.resolve()),PYTHONUNBUFFERED='1')
        if checkpoint:env['QUEST_RESUME_CHECKPOINT']=str(checkpoint)
        else:env.pop('QUEST_RESUME_CHECKPOINT',None)
        torchrun=envdir/'bin/torchrun';observer=Path(__file__).with_name('observe_training.py')
        command=[str(torchrun),'--standalone','--nnodes=1',f'--nproc-per-node={args.world_size}',str(observer)]
        receipt={'attempt':attempt,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'command':command,'config':str(config),'resume_candidate':str(checkpoint) if checkpoint else None}
        (attempt_dir/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
        monitor=None;child=None;received=[]
        def stop_child(signum,frame):
            received.append(signum)
            if child and child.poll() is None:
                try:os.killpg(child.pid,signum)
                except ProcessLookupError:pass
        previous={n:signal.signal(n,stop_child) for n in (signal.SIGTERM,signal.SIGINT)}
        try:
            with (attempt_dir/'gpu-memory.csv').open('w') as gpu,(attempt_dir/'train.log').open('w') as log:
                monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,index,memory.used,memory.total,utilization.gpu','--format=csv','-lms','1000'],stdout=gpu,stderr=subprocess.STDOUT)
                child=subprocess.Popen(command,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                if received and child.poll() is None:os.killpg(child.pid,received[-1])
                receipt['torchrun_pid']=child.pid
                (attempt_dir/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
                rc=child.wait()
        except BaseException as exc:
            receipt.update(status='launcher_error',error_type=type(exc).__name__,error=str(exc))
            raise
        finally:
            if monitor and monitor.poll() is None:
                monitor.terminate()
                try:monitor.wait(timeout=15)
                except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
            for sig,handler in previous.items():signal.signal(sig,handler)
            receipt.update(finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),signals=received)
            if child and child.poll() is not None:receipt['exitcode']=child.returncode
            (attempt_dir/'exit.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if rc==0 and not received:(state_dir/'success.json').write_text(json.dumps(receipt,indent=2)+'\n')
        raise SystemExit(rc if not received else 128+received[0])

if __name__=='__main__':main()
