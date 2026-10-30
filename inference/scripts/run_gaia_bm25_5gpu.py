"""GAIA32 BM25 direct evidence with local 4B memory on five vLLM servers."""
import contextlib, fcntl, importlib.util, json, os, subprocess, sys, time
import re, hashlib
from pathlib import Path
import requests

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO/'workspace'
ID = os.environ.get('QUEST_GAIA_RUN_ID', 'gaia-bm25-5gpu-base-20261029-r1')
if not re.fullmatch(r'[a-z0-9-]+', ID):
    raise ValueError('invalid run ID')
RUN = PROJECT/'strict-reproduction'/ID
SOURCE = PROJECT/'strict-reproduction/gaia-sft32-27b-2plus2-20261028-r2'
SITE = REPO/'web/trace-viewer'
PORTS = [18210,18201,18202,18203,18204]
PYTHON = PROJECT/'env/bin/python'
CASES = [f'row{i:04d}' for i in range(32)]

def write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)

def healthy(port):
    try:
        r=requests.get(f'http://127.0.0.1:{port}/v1/models',timeout=3)
        return r.ok and {x['id'] for x in r.json()['data']} == {'QWEN35-BASE'}
    except (requests.RequestException,ValueError,KeyError):
        return False

def main():
    RUN.mkdir(parents=True,exist_ok=True)
    lock=(RUN/'controller.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (RUN/'status.json').exists():
        raise RuntimeError('existing status: refusing to overwrite or silently restart')
    scorer_dir=PROJECT/'strict-reproduction/official-sources/gaia-leaderboard'
    rev=subprocess.check_output(['git','-C',str(scorer_dir),'rev-parse','HEAD'],text=True).strip()
    if rev!='9f133d71362e77b3539f1514f31b9c101a545fec': raise RuntimeError('unexpected scorer revision')
    spec=importlib.util.spec_from_file_location('official_gaia_scorer',scorer_dir/'scorer.py')
    scorer=importlib.util.module_from_spec(spec); spec.loader.exec_module(scorer)
    refs=json.loads((SOURCE/'judge/ground-truth/gaia-103-org.json').read_text())
    refs={x['Question']:x for x in refs}
    for d in ('configs','logs','checks','judge/ground-truth','results','traces','cache'):(RUN/d).mkdir(parents=True,exist_ok=True)
    profile = os.environ.get('QUEST_TOOL_PROMPT_PROFILE')
    if profile:
        raw = Path(profile).read_bytes()
        (RUN/'configs'/'tool-prompt-profile.json').write_bytes(raw)
        write(RUN/'checks'/'tool-prompt-profile.json', {'sha256': hashlib.sha256(raw).hexdigest(), 'source': profile})
    (RUN/'judge/ground-truth/gaia-103-org.json').write_bytes((SOURCE/'judge/ground-truth/gaia-103-org.json').read_bytes())
    for case in CASES:(RUN/'configs'/f'{case}.jsonl').write_bytes((SOURCE/'configs'/f'{case}.jsonl').read_bytes())
    rows={c:{'agent_state':'pending','judge_state':'pending'} for c in CASES}
    write(RUN/'experiment.json',{'method':'bm25','delivery':'direct','memory_model':'QWEN35-BASE','policy_model':'QWEN35-BASE','tool_prompt_profile':os.environ.get('QUEST_TOOL_PROMPT_PROFILE') or None,'max_turns':int(os.environ.get('QUEST_AB_MAX_TURNS','400')),'visit_page_concurrency':int(os.environ.get('VISIT_PAGE_CONCURRENCY','1')),'bm25_pool_url':os.environ.get('VISIT_BM25_POOL_URL') or None,'memory_threshold':40000,'max_model_len':65536,'ports':PORTS,'max_num_seqs_per_gpu':8,'max_tasks_per_gpu':8,'cases':32,'chunk_target_cl100k':400,'chunk_overlap_cl100k':64,'top_k':8,'budget_cl100k':8000,'short_page_bypass_cl100k':2000,'temperature':1,'top_p':0.95,'presence_penalty':1.1,'scorer_revision':rev})
    running={}
    def publish():
        write(RUN/'status.json',{'epoch':time.time(),'total':32,'cases':rows})
        dest=SITE/'datasets'/ID
        profile_name = Path(os.environ['QUEST_TOOL_PROMPT_PROFILE']).stem if os.environ.get('QUEST_TOOL_PROMPT_PROFILE') else ''
        label = 'GAIA32 BM25 4B 基座 · '+profile_name if profile_name else 'GAIA32 BM25 五卡 4B 基座'
        if os.environ.get('VISIT_BM25_POOL_URL'): label += ' · 网页并发共享池'
        result=subprocess.run([str(PYTHON),str(REPO/'web/build_gaia.py'),'--run-root',str(RUN),'--output-dir',str(dest),'--label',label,'--include-running','--replace-existing'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=120)
        if result.returncode: print('viewer build failed:',result.stderr[-1500:],flush=True)
        index_path=SITE/'datasets/index.json'
        index=json.loads(index_path.read_text())
        if (dest/'traces.json').exists() and not any(x.get('id')==ID for x in index['datasets']):
            index['datasets'].append({'id':ID,'label':label,'description':'BM25 原文直送 4B 基座；历史记忆使用本地 4B 基座','folder':'datasets/'+ID,'data':'datasets/'+ID+'/traces.json','benchmark':'GAIA32','visible':True})
            write(index_path,index)
        print('status',sum(x['agent_state']=='terminal' for x in rows.values()),'/32 running',len(running),'scored',sum(x['judge_state']=='scored' for x in rows.values()),flush=True)
    publish()
    print('Waiting for all five vLLM endpoints.',flush=True)
    while not all(healthy(p) for p in PORTS): time.sleep(5)
    print('All five endpoints healthy.',flush=True)
    last=0
    while True:
        for case,(proc,gpu) in list(running.items()):
            rc=proc.poll()
            if rc is None: continue
            del running[case]
            row=rows[case]; row.update(agent_state='terminal',agent_returncode=rc,judge_state='unavailable',agent_ended_epoch=time.time())
            files=list((RUN/'results'/case).rglob('iter1.jsonl'))
            if rc==0 and len(files)==1:
                record=json.loads(files[0].read_text().splitlines()[-1]); answer=record.get('prediction'); ref=refs.get(record.get('question'))
                row['result_path']=str(files[0])
                log=(RUN/'logs'/f'{case}-agent.stdout.log').read_text(errors='replace')
                if 'All Jina keys are exhausted or invalid' in log:
                    row['judgment']='Jina 密钥池不可用；需重跑，保留轨迹'
                elif os.environ.get('VISIT_BM25_POOL_URL') and re.search(r'\[visit\] Error:.*(?:18215|BM25 pool|/prepare)', log, re.IGNORECASE):
                    row['judgment']='共享 BM25 服务错误；需重跑，保留轨迹'
                elif ref and isinstance(answer,str) and answer.strip() and answer.strip().lower() not in ('answer not found.','no answer found.'):
                    with (RUN/'logs'/f'{case}-scorer.log').open('w') as out, contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
                        row.update(judge_state='scored',is_correct=bool(scorer.question_scorer(answer,ref['answer'])),judgment='GAIA official normalized exact match')
            print('finished',case,'exit',rc,'judge',row['judge_state'],flush=True)
        slots=[sum(g==i for _,g in running.values()) for i in range(5)]
        for case in CASES:
            if rows[case]['agent_state']!='pending':continue
            avail=[i for i in range(5) if slots[i]<8 and healthy(PORTS[i])]
            if not avail: break
            gpu=min(avail,key=lambda i:(slots[i],i)); port=PORTS[gpu]
            (RUN/'configs'/f'{case}-server_endpoints.conf').write_text(f'HOSTNAME_LIST=127.0.0.1\nPORTS={port}\n')
            env=dict(os.environ,QUEST_AB_PROJECT=str(PROJECT),QUEST_AB_GROUP_ROOT=str(RUN),QUEST_AUDIT_CASE=case,QUEST_AUDIT_MODE='agent',VISIT_EXPERIMENT_METHOD='bm25',VISIT_EXPERIMENT_DELIVERY='direct',VISIT_EXPERIMENT_AUDIT=str(RUN/'logs'/f'{case}-retrieval.jsonl'),QUEST_AB_POLICY_BASE='true',QUEST_AB_MEMORY_BASE=f'http://127.0.0.1:{port}/v1')
            with (RUN/'logs'/f'{case}-agent.stdout.log').open('w') as out:
                proc=subprocess.Popen([str(PYTHON),'-u',str(REPO/'inference/scripts/observe_retrieval_ab.py')],cwd=RUN,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
            running[case]=(proc,gpu); slots[gpu]+=1
            rows[case].update(agent_state='running',agent_pid=proc.pid,agent_started_epoch=time.time(),gpu=gpu,port=port)
        if time.monotonic()-last>=30: publish(); last=time.monotonic()
        if not running and all(x['agent_state']=='terminal' for x in rows.values()): break
        time.sleep(3)
    publish()
    print('GAIA32 complete.',flush=True)

if __name__=='__main__': main()
