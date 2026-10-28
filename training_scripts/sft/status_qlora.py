#!/usr/bin/env python3
"""Read training status, sampled GPU peaks and TensorBoard scalars without mutation."""
import argparse
import csv
from collections import deque
import json
import math
from pathlib import Path

TAGS = ('train/loss', 'train/learning_rate', 'train/grad_norm', 'eval/loss')


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def resolve_attempt(state, name=None):
    if name is None:
        pointer = read_json(state / 'checks/latest-launch.json')
        name = pointer.get('attempt') if isinstance(pointer, dict) else None
    if name is None:
        attempts = state / 'attempts'
        candidates = sorted(p.name for p in attempts.iterdir() if p.is_dir()) if attempts.is_dir() else []
        name = candidates[-1] if candidates else None
    if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('attempt missing or invalid; specify --attempt')
    attempt = (state / 'attempts' / name).resolve(strict=True)
    if not attempt.is_relative_to((state / 'attempts').resolve()):
        raise ValueError('attempt escapes state directory')
    return attempt


def sampled_gpu_peaks(path):
    peaks = {}
    if not path.is_file():
        return peaks
    with path.open(newline='') as f:
        for row in csv.reader(f):
            try:
                gpu = int(row[1].strip())
                used = float(row[2].split()[0])
                if math.isfinite(used) and used >= 0:
                    peaks[gpu] = max(peaks.get(gpu, 0), used)
            except (ValueError, IndexError):
                continue
    return peaks


def recent_elapsed_rate(path, window=30):
    if not path.is_file():
        return None
    points = deque(maxlen=window)
    with path.open() as f:
        for line in f:
            try:
                event = json.loads(line)
                step, elapsed = event.get('global_step'), event.get('elapsed_s')
                if (event.get('event') == 'step_end' and isinstance(step, int) and not isinstance(step, bool)
                        and isinstance(elapsed, (int,float)) and not isinstance(elapsed,bool)
                        and math.isfinite(elapsed)):
                    points.append((step, elapsed))
            except (json.JSONDecodeError, AttributeError):
                continue
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    delta_step, delta_time = last[0]-first[0], last[1]-first[1]
    if delta_step <= 0 or delta_time <= 0:
        return None
    return {'steps':delta_step, 'elapsed_seconds':delta_time,
            'seconds_per_step':delta_time/delta_step,
            'scope':'same attempt, recent step-end timestamps; includes intervening evaluation/save time'}


def tensorboard_scalars(directory):
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
        accumulator = EventAccumulator(str(directory), size_guidance={'scalars': 0})
        accumulator.Reload()
        tags = set(accumulator.Tags().get('scalars', []))
        result = {}
        for tag in TAGS:
            if tag in tags:
                result[tag] = [{'step':v.step, 'value':v.value, 'wall_time':v.wall_time}
                               for v in accumulator.Scalars(tag)[-8:]]
        return {'scalars':result, 'missing_tags':[tag for tag in TAGS if tag not in tags]}
    except Exception as exc:
        return {'error_type':type(exc).__name__, 'message':str(exc)}



def sanitize_nonfinite(value, path='$', found=None):
    if found is None:
        found = []
    if isinstance(value, float) and not math.isfinite(value):
        found.append(path)
        return str(value), found
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[key], _ = sanitize_nonfinite(item, path+'.'+str(key), found)
        return result, found
    if isinstance(value, (list,tuple)):
        result = []
        for index, item in enumerate(value):
            clean, _ = sanitize_nonfinite(item, path+'['+str(index)+']', found)
            result.append(clean)
        return result, found
    return value, found


def summarize(state, output, attempt_name=None, tb_dir=None):
    state, output = state.resolve(strict=True), output.resolve(strict=True)
    attempt = resolve_attempt(state, attempt_name)
    status = read_json(attempt / 'status-rank0.json')
    exit_info = read_json(attempt / 'exit.json') or read_json(attempt / 'exitcode.json')
    steps = sorted(int(p.name.removeprefix('checkpoint-')) for p in output.glob('checkpoint-*')
                   if p.is_dir() and p.name.removeprefix('checkpoint-').isdigit())
    rate = recent_elapsed_rate(attempt / 'events-rank0.jsonl')
    eta = None
    if isinstance(status, dict) and rate and status.get('complete') is not True:
        step, maximum = status.get('global_step'), status.get('max_steps')
        if isinstance(step, int) and isinstance(maximum, int) and 0 <= step < maximum:
            eta = {'remaining_seconds_estimate':(maximum-step)*rate['seconds_per_step'],
                   'basis':'recent same-attempt step-end rate; future evaluation and checkpoint cost can differ'}
    result = {'attempt':str(attempt), 'reported_status':status, 'exit_receipt':exit_info,
              'checkpoints':steps, 'gpu_sampled_peak_mib':sampled_gpu_peaks(attempt/'gpu-memory.csv'),
              'recent_rate':rate, 'eta':eta,
              'limitations':['GPU peak is sampled, not an exact hardware maximum',
                             'checkpoint names do not prove checkpoint integrity',
                             'reported status is not live process verification']}
    if tb_dir is not None:
        result['tensorboard'] = tensorboard_scalars(tb_dir.resolve(strict=True))
    result, nonfinite = sanitize_nonfinite(result)
    result['nonfinite_fields'] = nonfinite
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--attempt',help='Attempt directory name; defaults to pointer or most recent')
    p.add_argument('--tensorboard-dir',type=Path,help='Explicit TensorBoard run directory')
    a=p.parse_args()
    print(json.dumps(summarize(a.state_dir,a.output_dir,a.attempt,a.tensorboard_dir),indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
