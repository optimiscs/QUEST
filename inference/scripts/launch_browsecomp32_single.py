"""Start the evaluation, adaptive concurrency and both status publishers."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'workspace/strict-reproduction/browsecomp-v11-bf16-lora-summary32-singlemodel-20261101-r1'
PYTHON = ROOT / 'workspace/env/bin/python'


def existing_pid(path, identities):
    try:
        pid = int(json.loads(path.read_text())['pid'])
        stat = Path(f'/proc/{pid}/stat').read_text()
        if stat[stat.rfind(')') + 2:].split()[0] in ('Z', 'X'): return None
        command = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        if any(identity in command for identity in identities): return pid
    except (OSError, ValueError, KeyError): pass
    return None


def main():
    limit = RUN / 'agent-concurrency-limit'
    if not limit.exists(): limit.write_text('4\n')
    jobs = [
        ('launcher', [str(RUN/'start-evaluation.sh')], ('start-evaluation.sh', 'run_browsecomp32_lora.py'), 'launch.log'),
        ('publisher', [str(RUN/'start-viewer-publisher.sh')], ('start-viewer-publisher.sh', 'publish_browsecomp128_27b.py'), 'viewer-publisher.log'),
        ('comparison', [str(PYTHON), str(ROOT/'inference/scripts/monitor_browsecomp32_single.py')], ('monitor_browsecomp32_single.py',), 'paired-monitor.log'),
        ('ramp', [str(PYTHON), str(ROOT/'inference/scripts/ramp_browsecomp32_single.py')], ('ramp_browsecomp32_single.py',), 'concurrency-ramp.log'),
    ]
    started = {}
    for name, command, identities, logfile in jobs:
        pidfile = RUN/'checks'/(name+'-pid.json')
        pid = existing_pid(pidfile, identities)
        if not pid:
            if name == 'launcher' and (RUN/'status.json').exists():
                raise RuntimeError('Evaluation status already exists; inspect it before starting another run')
            with (RUN/'logs'/logfile).open('a') as log:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            pid = process.pid
            pidfile.write_text(json.dumps({'pid': pid, 'started_epoch': time.time()}, indent=2))
        started[name] = pid
    print(json.dumps({'processes': started, 'status': str(RUN/'status.json'),
                      'concurrency': str(limit)}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
