#!/usr/bin/env python3
"""Record official DRBench API inputs and outputs without replacing functions."""
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time

log = Path(sys.argv[1])
args = sys.argv[2:]
secret_values = [v for k, v in os.environ.items() if ('KEY' in k or 'TOKEN' in k) and len(v) >= 16]
lock = threading.Lock()
active = {}

def write(item):
    line = json.dumps(item, ensure_ascii=False, default=str)
    for secret in secret_values: line = line.replace(secret, '[REDACTED]')
    with lock:
        with log.open('a') as f: f.write(line + '\n')

def observe(frame, event, arg):
    if event not in ('call', 'return'): return
    code = frame.f_code
    if not (code.co_filename.endswith('/utils/api.py') and code.co_name in ('_post', 'scrape_url')): return
    key = (threading.get_ident(), id(frame))
    try:
        if event == 'call':
            active[key] = time.monotonic()
            loc = frame.f_locals
            data = loc.get('payload') if code.co_name == '_post' else {'url': loc.get('url')}
            write({'event': 'start', 'function': code.co_name, 'input': data, 'epoch': time.time(), 'thread': key[0]})
        else:
            start = active.pop(key, time.monotonic())
            write({'event': 'end', 'function': code.co_name, 'output': arg, 'seconds': time.monotonic()-start, 'epoch': time.time(), 'thread': key[0]})
    except Exception as exc:
        write({'event': 'observer_error', 'error': repr(exc)})

sys.setprofile(observe)
threading.setprofile(observe)
try:
    if args[0] == '-m':
        sys.argv = args[1:]
        runpy.run_module(args[1], run_name='__main__', alter_sys=True)
    else:
        sys.argv = args
        runpy.run_path(args[0], run_name='__main__')
finally:
    sys.setprofile(None)
    threading.setprofile(None)
