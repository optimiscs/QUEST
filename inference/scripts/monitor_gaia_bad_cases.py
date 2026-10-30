"""Local 10-minute monitor for newly completed GAIA bad cases.

The service reads the existing experiment state and starts at most one Codex
worker. It does not change experiment results, restart services, or log keys.
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN = REPO/'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'
ROOT = RUN/'bad-case-monitor'
METRICS = REPO/'web/trace-viewer/datasets/gaia-retrieval-ab-metrics.json'
STATE = ROOT/'seen.json'
SCHEMA = {'type':'object','properties':{'processed':{'type':'array','items':{'type':'string'}},
         'summary':{'type':'string'},'modified_files':{'type':'array','items':{'type':'string'}}},
         'required':['processed','summary','modified_files'],'additionalProperties':False}


def read_json(path):
    return json.loads(Path(path).read_text())


def collect(metrics, controller, retries):
    """Return stable identities for terminal failures, excluding pending retries."""
    receipts = {(x['group'], x['case']): x for x in retries.get('cases', [])}
    found = []
    for group, data in metrics.get('groups', {}).items():
        for case, visible in data.get('cases', {}).items():
            row = controller.get('groups', {}).get(group, {}).get(case, {})
            retry = receipts.get((group, case), {})
            if retry.get('status') in ('pending_retry','running_retry'):
                continue
            if retry.get('status') == 'completed':
                correct, judged, terminal = retry.get('is_correct'), 'scored', True
                source = retry.get('result_path', '')
            else:
                correct = visible.get('is_correct')
                judged = visible.get('judge_state')
                terminal = visible.get('agent_state') == 'terminal'
                source = row.get('result_path') or str(row.get('agent_pid', ''))
            reason = 'incorrect' if judged == 'scored' and correct is False else 'unscored' if terminal and judged in ('unavailable','unscored','error') else None
            if not terminal or not reason:
                continue
            identity = {'group':group,'case':case,'reason':reason,'source':source}
            identity['fingerprint'] = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            found.append(identity)
    return sorted(found, key=lambda x:(x['group'],x['case']))


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)


def snapshot():
    return collect(read_json(METRICS),read_json(RUN/'controller-state.json'),read_json(RUN/'checks/retry-required.json'))


def log(event, **fields):
    line = {'time':datetime.now(timezone.utc).isoformat(),'event':event,**fields}
    with (ROOT/'monitor-events.jsonl').open('a') as handle:
        handle.write(json.dumps(line,ensure_ascii=False)+'\n')


def worker_prompt(cases):
    return f'''在当前工作区检查 GAIA32 检索对照实验中新出现的 bad case。实验目录：{RUN}；对照页数据：{METRICS}。
本次新增案例（group、case、reason 和结果路径；不含密钥）：{json.dumps(cases,ensure_ascii=False)}
逐条读取对应轨迹、日志、评分结果和相关源码，区分模型回答错误、评分不可用、工具或实现错误。只有证据支持存在可推广的流程或代码缺陷时才修改代码并运行适当测试；不要针对具体答案调参、泄露参考答案或改变官方评分规则。保留历史结果和轨迹；不要停止或重启现有评估、模型服务或其他用户进程，不要修改密钥、覆盖数据集、提交或发布。记录发现、修改、验证结果和仍需处理的问题；没有可操作的新问题时保持简短。不要在输出中泄露任何密钥。最后返回符合输出 schema 的 JSON，processed 只填写实际完成分析案例的 fingerprint；无法分析的案例不要列入 processed。'''


def processed_fingerprints(report, scheduled):
    if not isinstance(report,dict) or not isinstance(report.get('processed'),list):
        return set()
    allowed = {x['fingerprint'] for x in scheduled}
    return {x for x in report['processed'] if isinstance(x,str) and x in allowed}


def main(interval):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(ROOT,0o700)
    with (ROOT/'daemon.lock').open('a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('bad-case monitor is already running')
        if not STATE.exists():
            initial = snapshot()
            atomic_json(STATE, {'seen':[x['fingerprint'] for x in initial]})
            log('initialized', existing_cases=len(initial))
        atomic_json(ROOT/'output-schema.json',SCHEMA)
        deadline = time.monotonic()+interval
        worker = None
        scheduled = []
        result_path = None
        while True:
            now = time.monotonic()
            if worker is not None and worker.poll() is not None:
                rc = worker.returncode
                processed = set()
                if rc == 0 and result_path:
                    try: processed = processed_fingerprints(read_json(result_path), scheduled)
                    except (OSError,ValueError): pass
                if processed:
                    data = read_json(STATE)
                    data['seen'] = sorted(set(data.get('seen',[])) | processed)
                    atomic_json(STATE,data)
                log('worker_finished', exit_code=rc, cases=len(scheduled),processed=len(processed))
                worker = None
                scheduled = []
            if now >= deadline:
                while deadline <= now: deadline += interval
                if worker is not None:
                    log('check_skipped_worker_active')
                else:
                    try:
                        seen = set(read_json(STATE).get('seen',[]))
                        candidates = [x for x in snapshot() if x['fingerprint'] not in seen]
                        cases = candidates[:8]
                        log('checked', new_cases=len(candidates), scheduled_cases=len(cases))
                        if cases:
                            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                            output = ROOT/f'worker-{stamp}.log'
                            result_path = ROOT/f'worker-{stamp}.json'
                            with output.open('w') as handle:
                                worker = subprocess.Popen(['codex','-a','never','exec','-s','danger-full-access','--skip-git-repo-check','--ephemeral','--output-schema',str(ROOT/'output-schema.json'),'-o',str(result_path),'-C',str(REPO),worker_prompt(cases)],
                                    cwd=REPO,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
                            scheduled = cases
                            log('worker_started', cases=len(cases),pid=worker.pid,log_file=str(output))
                    except (OSError,ValueError,KeyError) as exc:
                        log('check_failed', error_type=type(exc).__name__)
            time.sleep(min(5,max(0.05,deadline-time.monotonic())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval',type=int,default=600)
    args = parser.parse_args()
    if args.interval < 60: raise SystemExit('interval must be at least 60 seconds')
    main(args.interval)
