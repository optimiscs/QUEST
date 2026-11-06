"""Resume stalled consumers from recorded requests, preserving every prior log."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from summary_events import read_events

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def main():
    run = Path(sys.argv[1]).resolve()
    retry = run / 'stream-recovery'; retry.mkdir(exist_ok=False)
    saved = run / 'pre-stream-recovery'; saved.mkdir(exist_ok=False)
    status = json.loads((run / 'rollout-status.json').read_text())
    finished = {r['case'] for r in status['results']}
    workers = {}; controller = None
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            cmd = (proc / 'cmdline').read_bytes().split(b'\0')
            if str(ROOT / 'inference/scripts/observe_retrieval_ab.py').encode() in cmd:
                env = dict(x.decode().split('=', 1) for x in (proc / 'environ').read_bytes().split(b'\0') if b'=' in x)
                if env.get('QUEST_AB_GROUP_ROOT') == str(run) and env.get('QUEST_AUDIT_CASE') not in finished:
                    workers[env['QUEST_AUDIT_CASE']] = (int(proc.name), env)
            if b'training_scripts/sft/run_summary16.py' in cmd and str(run.relative_to(ROOT)).encode() in cmd:
                controller = int(proc.name)
        except (OSError, UnicodeDecodeError): continue
    assert controller and len(workers) == 16 - len(finished), (controller, sorted(workers))
    stopped = [controller] + [pid for pid, env in workers.values()]
    for pid in stopped: os.kill(pid, signal.SIGSTOP)
    prepared = False
    try:
        shutil.copytree(run / 'configs', retry / 'configs')
        (retry / 'logs').mkdir(); (saved / 'logs').mkdir()
        receipts = []
        for case, (pid, env) in sorted(workers.items()):
            events, _ = read_events(run, case)
            pending = [e for e in events if e['event'] == 'span_start' and e.get('kind') == 'policy_model'][-1]
            messages = pending['input']['msgs']
            rounds = sum(e['event'] == 'span_end' and e.get('kind') == 'policy_model' for e in events)
            item = json.loads((run / 'configs' / (case + '.jsonl')).read_text().splitlines()[0])
            for suffix in ('-agent-events.jsonl', '-console.log'):
                shutil.copy2(run / 'logs' / (case + suffix), saved / 'logs' / (case + suffix))
            shutil.copytree(run / 'traces' / case, retry / 'traces' / case)
            memory_files = sorted((run / 'traces' / case).rglob('condenser_call_*.json'), key=lambda p: p.stat().st_mtime)
            memory = json.loads(memory_files[-1].read_text()).get('state') if memory_files else None
            record = dict(item, messages=messages, num_rounds=rounds, termination='temporal save', prediction='',
                          rollout_idx=1, memory_state=memory)
            result = retry / 'results' / case / 'qwen38-27b' / case / 'iter1.jsonl'
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps(record, ensure_ascii=False) + '\n')
            write_json(saved / (case + '-checkpoint.json'), record)
            receipts.append({'case': case, 'old_pid': pid, 'resume_round': rounds,
                             'pending_span': pending['span_id'], 'pending_generation_discarded': True})
        for name in ('session_telemetry.py', 'react_agent.py', 'tool_memory.py', 'native_tools.py'):
            target = retry / 'harness-snapshot' / name; target.parent.mkdir(exist_ok=True)
            shutil.copy2(ROOT / 'inference' / name, target)
        write_json(retry / 'recovery-contract.json', {
            'reason': 'Quadratic SDK logprob event accumulation left CPU consumers behind GPU completion.',
            'changes': ['Accumulate all logprobs once without unused per-token history events.',
                        'Respect the complete-context memory trigger on the older subset.'],
            'cases': receipts, 'original_completed': status['completed'],
            'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (retry / 'harness-snapshot').iterdir()},
            'sampling_unchanged': True, 'round_budget_includes_previous_rounds': True})
        prepared = True
    finally:
        for pid in stopped:
            try: os.kill(pid, signal.SIGKILL if prepared else signal.SIGCONT)
            except ProcessLookupError: pass
    running = {}
    for case, (pid, env) in sorted(workers.items()):
        env.update(QUEST_AB_GROUP_ROOT=str(retry), QUEST_AB_RESUME_MESSAGES='true', QUEST_AUDIT_SEQ_BASE='1000000')
        log = (retry / 'logs' / (case + '-console.log')).open('w')
        child = subprocess.Popen([str(ROOT / 'workspace/env/bin/python'), str(ROOT / 'inference/scripts/observe_retrieval_ab.py')],
                                 cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        running[case] = (child, log, time.monotonic())
        print(json.dumps({'resumed': case, 'pid': child.pid}), flush=True)
    while running:
        for case, (child, log, started) in list(running.items()):
            for suffix in ('-agent-events.jsonl', '-console.log'):
                source = retry / 'logs' / (case + suffix)
                if source.exists():
                    target = run / 'logs' / (case + suffix); temp = target.with_suffix('.tmp')
                    temp.write_bytes((saved / 'logs' / (case + suffix)).read_bytes() + source.read_bytes())
                    temp.replace(target)
            code = child.poll()
            if code is None and time.monotonic() - started > 3600:
                child.kill(); code = child.wait()
            if code is None: continue
            log.close()
            source = retry / 'results' / case / 'qwen38-27b' / case / 'iter1.jsonl'
            result = json.loads(source.read_text().splitlines()[-1])
            if result.get('termination') == 'temporal save': code = code or 1
            else:
                target = run / 'results' / case / 'qwen38-27b' / case / 'iter1.jsonl'
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix('.tmp'); temp.write_bytes(source.read_bytes()); temp.replace(target)
                shutil.copytree(retry / 'traces' / case, run / 'traces' / case, dirs_exist_ok=True)
            status['results'].append({'case': case, 'exit_code': code, 'seconds': time.monotonic() - started,
                                      'resumed': True, 'seconds_scope': 'recovery process only'})
            status['completed'] = len(status['results']); write_json(run / 'rollout-status.json', status)
            del running[case]
            print(json.dumps(status['results'][-1]), flush=True)
        time.sleep(5)


if __name__ == '__main__':
    main()
