"""Benchmark real recorded GAIA visits using the actual Visit and BM25 code.

Reader responses are frozen locally; Jina/network time is intentionally not
included. Simulated agents are separate processes, as in the running system.
"""
import argparse
import contextlib
import hashlib
import io
import json
import math
import multiprocessing
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
OUT = REPO/'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1/checks/bm25-concurrency'
sys.path.insert(0, str(REPO/'inference'))


def warm_agent(_):
    import tool_visit  # noqa: F401
    import retrieval_experiment  # noqa: F401
    time.sleep(0.3)
    return os.getpid()


def run_case(row, page_workers, pool_url):
    import tool_visit
    import retrieval_experiment
    os.environ['VISIT_PAGE_CONCURRENCY'] = str(page_workers)
    os.environ['VISIT_EXPERIMENT_METHOD'] = 'bm25'
    os.environ['VISIT_EXPERIMENT_DELIVERY'] = 'direct'
    if pool_url: os.environ['VISIT_BM25_POOL_URL'] = pool_url
    else: os.environ.pop('VISIT_BM25_POOL_URL',None)
    pages = {x['url']:x['text'] for x in row['pages']}
    visit = tool_visit.Visit.__new__(tool_visit.Visit)
    visit.cache = None
    page_data = []
    lock = threading.Lock()
    def frozen_read(url, goal):
        start = time.monotonic()
        selected,audit = retrieval_experiment.select(pages[url],goal,'bm25')
        record = {'url':url,'seconds':time.monotonic()-start,'reason':audit['reason'],
                  'indices':audit.get('selected_indices'),
                  'selected_sha256':hashlib.sha256(selected.encode()).hexdigest()}
        with lock: page_data.append(record)
        return visit._experiment_direct_response(url,goal,selected)
    visit.readpage_jina = frozen_read
    start = time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):
        response = visit.call({'url':[x['url'] for x in row['pages']], 'goal':row['goal']})
    seconds = time.monotonic()-start
    if len(page_data) != len(row['pages']):
        raise RuntimeError('visit did not process every recorded page')
    return {'case':row['case'],'seconds':seconds,'pages':page_data,
            'response_sha256':hashlib.sha256(response.encode()).hexdigest()}


def percentile(values, p):
    return sorted(values)[math.ceil(len(values)*p)-1] if values else None


def reserve_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def pool_service(workers):
    port=reserve_port()
    log=OUT/f'pool-{workers}.log'
    with log.open('w') as output:
        proc=subprocess.Popen([sys.executable,'-u',str(REPO/'inference/bm25_pool_service.py'),
                               '--workers',str(workers),'--queue-limit','128','--port',str(port)],
                              cwd=REPO,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if proc.poll() is not None: raise RuntimeError(f'pool server exited; see {log}')
            try:
                if requests.get(f'http://127.0.0.1:{port}/health',timeout=1).ok: break
            except requests.RequestException: pass
            time.sleep(.2)
        else: raise RuntimeError(f'pool server not ready; see {log}')
        url=f'http://127.0.0.1:{port}'
        def warm(_):
            response=requests.post(url+'/prepare',json={'text':'warmup text '*600,'goal':'warmup','need_bm25':True},timeout=120)
            response.raise_for_status()
        with ThreadPoolExecutor(max_workers=workers) as executor: list(executor.map(warm,range(workers)))
        yield url
    finally:
        proc.terminate()
        try: proc.wait(timeout=20)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()


def run_trial(agent_pool, rows, page_workers, pool_url, reference):
    start=time.monotonic()
    futures=[agent_pool.submit(run_case,row,page_workers,pool_url) for row in rows]
    result=[f.result() for f in futures]
    wall=time.monotonic()-start
    pages=[p for case in result for p in case['pages']]
    multi=[case['seconds'] for case in result if len(case['pages'])>1]
    mismatch=[]
    if reference is not None:
        for item in result:
            old=reference[item['case']]
            old_pages={p['url']:p for p in old['pages']}
            if item['response_sha256'] != old['response_sha256']:
                mismatch.append({'case':item['case'],'type':'response'})
            for page in item['pages']:
                prior=old_pages[page['url']]
                if page['indices'] != prior['indices'] or page['selected_sha256'] != prior['selected_sha256'] or page['reason'] != prior['reason']:
                    mismatch.append({'case':item['case'],'type':'selection','url':page['url']})
    return {'wall_seconds':wall,'pages_per_second':len(pages)/wall,
            'page_p50_s':statistics.median(x['seconds'] for x in pages),
            'page_p95_s':percentile([x['seconds'] for x in pages],.95),
            'case_p50_s':statistics.median(x['seconds'] for x in result),
            'case_p95_s':percentile([x['seconds'] for x in result],.95),
            'multi_case_p50_s':statistics.median(multi) if multi else None,
            'multi_case_p95_s':percentile(multi,.95),'multi_cases':len(multi),
            'cases':len(result),'pages':len(pages),'mismatches':mismatch},result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--agent-workers',type=int,default=24)
    parser.add_argument('--pool-workers',default='1,4,8,16')
    parser.add_argument('--page-workers',default='1,2,4')
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--limit',type=int,default=0,help='limit cases for a smoke run')
    args=parser.parse_args()
    rows=[json.loads(x) for x in (OUT/'gaia32-recorded-pages.jsonl').open()]
    if args.limit: rows=rows[:args.limit]
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
                      TOKENIZERS_PARALLELISM='false',VISIT_CACHE_ENABLED='false',
                      CACHE_DIR='/tmp/quest-bm25-benchmark')
    source_files=[REPO/'inference/tool_visit.py',REPO/'inference/retrieval_experiment.py',
                  REPO/'inference/bm25_pool_service.py',Path(__file__)]
    source_hashes={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    meta={'dataset_sha256':hashlib.sha256((OUT/'gaia32-recorded-pages.jsonl').read_bytes()).hexdigest(),
          'cases':len(rows),'pages':sum(len(x['pages']) for x in rows),'agent_workers':args.agent_workers,
          'network_included':False,'source_sha256':source_hashes,'repeats':args.repeats}
    results=[]
    def save():
        (OUT/'benchmark-results.json').write_text(json.dumps({'metadata':meta,'results':results},ensure_ascii=False,indent=2)+'\n')
    def record(mode, workers, page_workers, repeat, trial, raw):
        entry={'mode':mode,'pool_workers':workers,'page_workers':page_workers,'repeat':repeat,**trial,'per_case':raw}
        results.append(entry)
        print('trial',json.dumps({k:v for k,v in entry.items() if k!='per_case'},ensure_ascii=False),flush=True)
        save()
    with ProcessPoolExecutor(max_workers=args.agent_workers,mp_context=multiprocessing.get_context('spawn')) as agents:
        list(agents.map(warm_agent,range(args.agent_workers)))
        baseline,raw=run_trial(agents,rows,1,None,None)
        reference={x['case']:x for x in raw}
        record('inline',0,1,0,baseline,raw)
        for page_workers in map(int,args.page_workers.split(',')):
            if page_workers == 1: continue
            trial,raw=run_trial(agents,rows,page_workers,None,reference)
            record('inline',0,page_workers,0,trial,raw)
        for workers in map(int,args.pool_workers.split(',')):
            with pool_service(workers) as url:
                for repeat in range(args.repeats):
                    for page_workers in map(int,args.page_workers.split(',')):
                        trial,raw=run_trial(agents,rows,page_workers,url,reference)
                        record('pool',workers,page_workers,repeat,trial,raw)
        for page_workers in map(int,args.page_workers.split(',')):
            trial,raw=run_trial(agents,rows,page_workers,None,reference)
            record('inline',0,page_workers,1,trial,raw)
    current={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    meta['source_unchanged'] = current == source_hashes
    save()
    if not meta['source_unchanged']: raise RuntimeError('benchmark source changed during run; results need rerun')


if __name__=='__main__': main()
