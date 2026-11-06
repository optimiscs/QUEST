"""Run 16 fixed questions through the existing observed summary-mode harness."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def environment(run, case):
    env = dict(os.environ,
        QUEST_AB_PROJECT=str(ROOT / 'workspace'), QUEST_AB_GROUP_ROOT=str(run),
        QUEST_AUDIT_CASE=case, QUEST_AUDIT_MODE='agent', QUEST_AB_NO_GAIA='true',
        QUEST_AB_MAX_TURNS='100', QUEST_AB_MEMORY_THRESHOLD='40000',
        QUEST_AB_MEMORY_BASE='http://127.0.0.1:19300/v1',
        QUEST_AB_POLICY_MODEL='qwen38-27b', QUEST_AB_POLICY_MODEL_PATH=str(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'),
        QUEST_SOURCE_IDS='true', QUEST_NATIVE_TOOL_CALLS='true', ENABLE_PYTHON_TOOL='false', ENABLE_SCHOLAR_TOOL='false',
        QUEST_VISIT_USE_LOCAL_27B='true', VISIT_LOCAL_MODEL_NAME='qwen38-27b',
        VISIT_EXPERIMENT_METHOD='', VISIT_EXPERIMENT_DELIVERY='summary',
        VISIT_LOCAL_DISABLE_THINKING='true', VISIT_LOCAL_MAX_OUTPUT_TOKENS='4096', VISIT_MAX_CONTENT_TOKENS='16000',
        VISIT_PAGE_CONCURRENCY='2', QUEST_FINAL_MAX_TOKENS='8192', QUEST_FINAL_ANSWER_PROFILE='',
        MEMORY_STRATEGY='condenser', QUEST_SEARCH_VECTOR_URL='', OMP_NUM_THREADS='2',
        PYTHONUNBUFFERED='1', NO_PROXY='127.0.0.1,localhost')
    for name in ('VISIT_BM25_POOL_URL', 'VISIT_EMBEDDING_URL', 'VISIT_RERANKER_URL'):
        env.pop(name, None)
    return env


def main():
    run = Path(sys.argv[1]).resolve()
    for name in ('logs', 'traces', 'results', 'cache'):
        (run / name).mkdir(exist_ok=True)
    static = [json.loads(s) for s in (run / 'sample16-static.jsonl').read_text().splitlines()]
    assert len(static) == 16
    results = []
    def execute(record):
        case = record['metadata']['case']
        env = environment(run, case)
        started = time.time()
        with (run / 'logs' / (case + '-console.log')).open('x') as log:
            process = subprocess.Popen([str(ROOT / 'workspace/env/bin/python'), str(ROOT / 'inference/scripts/observe_retrieval_ab.py')],
                                       env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=30)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
                code = 'timeout'
        return {'case': case, 'exit_code': code, 'seconds': time.time() - started}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for future in concurrent.futures.as_completed([pool.submit(execute, r) for r in static]):
            results.append(future.result())
            tmp = run / 'rollout-status.tmp'
            tmp.write_text(json.dumps({'completed': len(results), 'total': 16, 'results': results}, indent=2))
            tmp.replace(run / 'rollout-status.json')
            print(json.dumps(results[-1]), flush=True)


if __name__ == '__main__':
    main()
