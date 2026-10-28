#!/usr/bin/env python3
"""Opt-in bounded retries around supervise_qlora; never modifies data or source.

Only an attempt with a new exit receipt and a failed torchrun is retryable.
The latest checkpoint is checked by the existing supervisor before every launch.
No process is started merely by importing this module.
"""
import argparse
import fcntl
import importlib.util
import json
import math
import re
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

SUPERVISOR = Path(__file__).with_name('supervise_qlora.py')
WINDOW_SECONDS = 2 * 60 * 60
MAX_FAILURES = 3


def blocked(state):
    return any((state / name).exists() for name in ('PAUSE', 'STOP', 'success.json'))


def read_failures(path, now):
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(not isinstance(x, dict) or not isinstance(x.get('timestamp'), (int, float))
           or isinstance(x.get('timestamp'), bool) or not math.isfinite(x['timestamp'])
           or x['timestamp'] > now for x in entries):
        raise ValueError('invalid retry history; refusing to launch')
    return [x for x in entries if 0 <= now - x['timestamp'] < WINDOW_SECONDS]


def classify(state, before, returncode):
    """Require one newly written terminal receipt from a genuinely launched job."""
    attempts = state / 'attempts'
    after = {p.name for p in attempts.iterdir() if p.is_dir()} if attempts.exists() else set()
    new = after - before
    if len(new) != 1:
        return 'no_unambiguous_attempt_receipt'
    path = attempts / next(iter(new)) / 'exit.json'
    if not path.is_file():
        return 'missing_exit_receipt'
    receipt = json.loads(path.read_text())
    if receipt.get('signals'):
        return 'signaled'
    if receipt.get('status') == 'launcher_error':
        return 'launcher_error'
    if not isinstance(receipt.get('torchrun_pid'), int):
        return 'not_launched'
    if receipt.get('exitcode') != returncode or returncode == 0:
        return 'receipt_mismatch'
    log = path.parent / 'train.log'
    if not log.is_file():
        return 'missing_training_log'
    abnormal = re.compile(r'cuda out of memory|torch\.cuda\.outofmemoryerror|'
                          r'[\"\'](?:loss|grad_norm)[\"\']\s*:\s*(?:nan|inf|-inf)\b', re.I)
    with log.open(errors='replace') as stream:
        if any(abnormal.search(line) for line in stream):
            return 'oom_or_nonfinite_requires_inspection'
    return 'failed_torchrun'



def validate_resume(args):
    """Check the checkpoint without launching; supervisor checks again under lock."""
    import yaml
    settings = yaml.safe_load(args.config.read_text())
    if not isinstance(settings, dict) or not settings.get('output_dir'):
        raise ValueError('invalid training config')
    output = Path(settings['output_dir']).expanduser().resolve()
    spec = importlib.util.spec_from_file_location('quest_sft_supervisor', SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkpoint = module.latest_checkpoint(output, args.world_size)
    if checkpoint is None and output.exists() and any(output.iterdir()):
        raise ValueError('nonempty output has no verified checkpoint')
    return str(checkpoint) if checkpoint else None


def run(args):
    state = args.state_dir.resolve()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    watchdog = state / 'retry-watchdog'
    watchdog.mkdir(mode=0o700, exist_ok=True)
    history = watchdog / 'failures.jsonl'
    lockfd = os.open(watchdog / 'lock', os.O_CREAT | os.O_RDWR, 0o600)
    child = None
    received = []
    def stop(signum, _frame):
        received.append(signum)
        if child and child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass
    previous = {}
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
        while True:
            if blocked(state) or received:
                return 'stopped_or_completed'
            now = time.time()
            if len(read_failures(history, now)) >= MAX_FAILURES:
                return 'failure_limit'
            attempts = state / 'attempts'
            before = {p.name for p in attempts.iterdir() if p.is_dir()} if attempts.exists() else set()
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            logfile = watchdog / (stamp + '-' + str(os.getpid()) + '-' + str(time.monotonic_ns()) + '.log')
            fd = os.open(logfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            command = [sys.executable, str(SUPERVISOR), '--config', str(args.config),
                       '--state-dir', str(state), '--env-dir', str(args.env_dir),
                       '--llamafactory', str(args.llamafactory), '--resource-tb', str(args.resource_tb),
                       '--world-size', str(args.world_size)]
            with os.fdopen(fd, 'w') as log:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                while True:
                    try:
                        rc = child.wait(timeout=5)
                        break
                    except subprocess.TimeoutExpired:
                        if (blocked(state) or received) and child.poll() is None:
                            try:
                                child.terminate()
                            except ProcessLookupError:
                                pass
            if blocked(state) or received:
                return 'stopped_or_completed'
            if rc == 0:
                return 'missing_success_marker'
            reason = classify(state, before, rc)
            if reason != 'failed_torchrun':
                return reason
            entry = {'timestamp':time.time(), 'exit_code':rc, 'classification':reason,
                     'supervisor_log':str(logfile)}
            fd = os.open(history, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'a') as stream:
                stream.write(json.dumps(entry)+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            if len(read_failures(history, time.time())) >= MAX_FAILURES:
                return 'failure_limit'
            try:
                validate_resume(args)
            except (ValueError, OSError, json.JSONDecodeError):
                return 'checkpoint_requires_inspection'
            deadline = time.monotonic() + args.retry_delay
            while time.monotonic() < deadline:
                if blocked(state) or received:
                    return 'stopped_or_completed'
                time.sleep(min(5, max(0, deadline-time.monotonic())))
            # The supervisor checks the checkpoint again under its output lock.
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        os.close(lockfd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('config', 'state-dir', 'env-dir', 'llamafactory', 'resource-tb'):
        p.add_argument('--'+flag, type=Path, required=True)
    p.add_argument('--world-size', type=int, default=4)
    p.add_argument('--retry-delay', type=float, default=900, help='Seconds between failed attempts; default 15 minutes')
    a = p.parse_args()
    if a.world_size < 1 or not 0 <= a.retry_delay <= 86400:
        p.error('--world-size must be positive and --retry-delay between 0 and 86400')
    status = run(a)
    print(json.dumps({'status':status}))
    return 0 if status == 'stopped_or_completed' else 1


if __name__ == '__main__':
    sys.exit(main())
