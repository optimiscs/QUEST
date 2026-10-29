"""Shared non-ZeRO LoRA checkpoint and configuration validation."""
import json
from pathlib import Path
import yaml
from safetensors import safe_open


def output_from_config(config):
    settings = yaml.safe_load(Path(config).read_text())
    if not isinstance(settings, dict) or not settings.get("output_dir"):
        raise ValueError("config must have output_dir")
    return settings, Path(settings["output_dir"]).expanduser().resolve()


def validate_training_states(path, rng_files):
    """Safely deserialize checkpoint state on CPU; reject unrecognized objects."""
    import numpy as np
    import torch
    try:
        from numpy._core.multiarray import _reconstruct
    except ImportError:
        from numpy.core.multiarray import _reconstruct
    allowed = [_reconstruct, np.ndarray, np.dtype, type(np.dtype('uint32'))]
    def load(name):
        try:
            with torch.serialization.safe_globals(allowed):
                return torch.load(path / name, map_location='cpu', weights_only=True)
        except Exception as exc:
            raise ValueError('checkpoint state cannot be safely loaded: '+name) from exc
    optim = load('optimizer.pt')
    if not isinstance(optim, dict) or not isinstance(optim.get('state'), dict) or not isinstance(optim.get('param_groups'), list) or not optim['param_groups']:
        raise ValueError('invalid optimizer state')
    parameter_ids = []
    for group in optim['param_groups']:
        if not isinstance(group, dict) or not isinstance(group.get('params'), list):
            raise ValueError('invalid optimizer parameter group')
        parameter_ids.extend(group['params'])
    if not parameter_ids or any(not isinstance(x, int) or isinstance(x, bool) for x in parameter_ids):
        raise ValueError('invalid optimizer parameter identifiers')
    known = set(parameter_ids)
    if len(known) != len(parameter_ids) or any(not isinstance(k, int) or isinstance(k, bool) or k not in known or not isinstance(v, dict)
                                               for k, v in optim['state'].items()):
        raise ValueError('optimizer state and parameter groups disagree')
    scheduler = load('scheduler.pt')
    if not isinstance(scheduler, dict) or not isinstance(scheduler.get('last_epoch'), int) or isinstance(scheduler['last_epoch'], bool):
        raise ValueError('invalid scheduler state')
    for name in rng_files:
        rng = load(name)
        if not isinstance(rng, dict) or not {'python','numpy','cpu','cuda'}.issubset(rng):
            raise ValueError('invalid RNG state: '+name)
        if not isinstance(rng['python'], tuple) or not isinstance(rng['numpy'], tuple) or not torch.is_tensor(rng['cpu']) or rng['cpu'].numel()==0:
            raise ValueError('invalid RNG state: '+name)
        cuda = rng['cuda']
        if not ((torch.is_tensor(cuda) and cuda.numel()>0) or
                (isinstance(cuda, (list, tuple)) and cuda and all(torch.is_tensor(x) and x.numel()>0 for x in cuda))):
            raise ValueError('invalid CUDA RNG state: '+name)


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
    validate_training_states(path,rng)
    if isinstance(state.get('max_steps'),int) and step>=state['max_steps']:
        raise ValueError('checkpoint reached max_steps; inspect final evaluation and outputs before restart')
    return path
