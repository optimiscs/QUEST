"""BrowseComp 25%: five SFT endpoints, pooled BM25, local 4B memory/judge."""
import concurrent.futures,fcntl,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
import requests
from openai import OpenAI
R=Path(__file__).resolve().parents[2];W=R/'workspace';RUN=W/'strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';PY=W/'env/bin/python';PORTS=[18210,18201,18202,18203,18204]

def save(path,data):
 t=path.with_suffix('.tmp');t.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');t.replace(path)

def health(port):
 try:
  r=requests.get(f'http://127.0.0.1:{port}/v1/models',timeout=3);return r.ok and {'QWEN35-BASE','QWEN35-SFT10'} <= {x['id'] for x in r.json()['data']}
 except (requests.RequestException,ValueError,KeyError):return False

def parse_verdict(raw):
 m=re.search(r'(?im)^\s*correct:\s*(yes|no)\b',raw)
 return None if not m else m.group(1).lower()=='yes'

def contradictory_judgment(raw):
 extracted=re.search(r'(?im)^\s*extracted_final_answer:\s*(.*)$',raw)
 return parse_verdict(raw) is True and extracted is not None and extracted.group(1).strip().strip('"\'').casefold()=='none'

def visible_judge_response(result):
 messages=result.get('messages',[])
 raw=str(messages[-1].get('content','') or '') if messages else str(result.get('prediction','') or '')
 visible=raw.rsplit('</think>',1)[-1].split('<think>',1)[0]
 visible=re.sub(r'<tool_call>.*?</tool_call>','',visible,flags=re.S).split('<tool_call>',1)[0]
 return visible.strip()

def judge(case,port,ref,result_path,receipt_tag='local-judge',prior_raw=None):
 start=time.time();result=json.loads(Path(result_path).read_text().splitlines()[-1]);response=visible_judge_response(result)
 prompt=(RUN/'configs/grader-template.txt').read_text().format(question=ref['question'],correct_answer=ref['answer'],response=response)
 try:
  client=OpenAI(base_url=f'http://127.0.0.1:{port}/v1',api_key='EMPTY',timeout=300)
  if prior_raw is None:
   r=client.chat.completions.create(model='QWEN35-BASE',messages=[{'role':'user','content':prompt}],temperature=0,max_tokens=1200,extra_body={'chat_template_kwargs':{'enable_thinking':False}})
   raw=r.choices[0].message.content or ''
  else:raw=prior_raw
  initial_raw=None
  if contradictory_judgment(raw):
   initial_raw=raw
   correction=client.chat.completions.create(model='QWEN35-BASE',messages=[{'role':'user','content':prompt},{'role':'assistant','content':raw},{'role':'user','content':'Your judgment is inconsistent: extracted_final_answer is None, but correct is yes. Apply the original matching criteria. If no exact final answer can be extracted, it cannot match the reference answer. Return the complete consistent judgment in the original required fields. Do not solve the question.'}],temperature=0,max_tokens=1200,extra_body={'chat_template_kwargs':{'enable_thinking':False}})
   raw=correction.choices[0].message.content or ''
  verdict=None if contradictory_judgment(raw) else parse_verdict(raw);retry_raw=None
  if verdict is None and raw.strip() and initial_raw is None:
   retry=client.chat.completions.create(model='QWEN35-BASE',messages=[{'role':'user','content':prompt},{'role':'assistant','content':raw},{'role':'user','content':'Complete your judgment with exactly one final line: correct: yes or correct: no. Apply the criteria above; do not solve the question.'}],temperature=0,max_tokens=64,extra_body={'chat_template_kwargs':{'enable_thinking':False}})
   retry_raw=retry.choices[0].message.content or '';verdict=parse_verdict(retry_raw)
  out={'judge_model':'QWEN35-BASE','duration_s':time.time()-start,'raw':raw,'initial_raw':initial_raw,'format_retry_raw':retry_raw,'status':'scored' if verdict is not None else 'unavailable','is_correct':verdict,'judgment':'BrowseComp 官方判分提示；本地 4B 裁判' if verdict is not None else '本地裁判输出无法解析或判词矛盾'}
 except Exception as exc:out={'judge_model':'QWEN35-BASE','duration_s':time.time()-start,'raw':locals().get('raw'),'status':'unavailable','is_correct':None,'judgment':'裁判调用失败: '+type(exc).__name__}
 out.update(response_filter='visible_final_only',graded_response=response,source_result_path=str(result_path),source_result_sha256=hashlib.sha256(Path(result_path).read_bytes()).hexdigest(),prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
 save(RUN/'checks'/f'{case}-{receipt_tag}.json',out);return out

def main():
 with (RUN/'controller.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  p=RUN/'status.json'
  if p.exists():raise RuntimeError('run already exists; refusing to overwrite')
  refs={x['case']:x for x in json.loads((RUN/'judge/ground-truth/references.json').read_text())};cases=sorted(refs);rows={c:{'agent_state':'pending','judge_state':'pending'} for c in cases};agents={};judges={};executor=concurrent.futures.ThreadPoolExecutor(max_workers=10)
  def publish():save(p,{'epoch':time.time(),'total':len(cases),'cases':rows})
  publish();print('waiting for 5 SFT/base endpoints and 64-worker pool',flush=True)
  while True:
   try:h=requests.get('http://127.0.0.1:18215/health',timeout=3).json()
   except (requests.RequestException,ValueError):h={}
   if h.get('workers')==64 and all(health(port) for port in PORTS):break
   time.sleep(5)
  print('preflight health passed',flush=True);last=0
  while True:
   for case,(proc,gpu) in list(agents.items()):
    rc=proc.poll()
    if rc is None:continue
    del agents[case];row=rows[case];row.update(agent_state='terminal',agent_returncode=rc,agent_ended_epoch=time.time(),judge_state='unavailable')
    files=list((RUN/'results'/case).rglob('iter1.jsonl'))
    if rc==0 and len(files)==1:
     row['result_path']=str(files[0]);log=(RUN/'logs'/f'{case}-agent.stdout.log').read_text(errors='replace')
     if 'All Jina keys are exhausted or invalid' in log:row['judgment']='Jina 密钥池不可用；保留轨迹，待重跑'
     elif re.search(r'\[visit\] Error:.*(?:18215|BM25 pool|/prepare)',log,re.I):row['judgment']='BM25 共享池出错；保留轨迹，待重跑'
     else:row['judge_state']='pending'
    print('agent done',case,'rc',rc,'judge',row['judge_state'],flush=True)
   for case,(future,gpu) in list(judges.items()):
    if not future.done():continue
    del judges[case]
    try:out=future.result();rows[case].update(judge_state=out['status'],is_correct=out.get('is_correct'),judgment=out['judgment'])
    except Exception as exc:rows[case].update(judge_state='unavailable',judgment='裁判错误: '+type(exc).__name__)
    print('judge done',case,rows[case]['judge_state'],flush=True)
   slots=[sum(g==i for _,g in agents.values())+sum(g==i for _,g in judges.values()) for i in range(5)]
   for case in cases:
    if len(judges)>=10:break
    row=rows[case]
    if row.get('agent_state')!='terminal' or row.get('judge_state')!='pending' or case in judges:continue
    available=[i for i in range(5) if slots[i]<8 and health(PORTS[i])]
    if not available:break
    gpu=min(available,key=lambda i:(slots[i],i));row['judge_state']='running';judges[case]=(executor.submit(judge,case,PORTS[gpu],refs[case],row['result_path']),gpu);slots[gpu]+=1
   for case in cases:
    if rows[case]['agent_state']!='pending':continue
    available=[i for i in range(5) if slots[i]<8 and health(PORTS[i])]
    if not available:break
    gpu=min(available,key=lambda i:(slots[i],i));port=PORTS[gpu];(RUN/'configs'/f'{case}-server_endpoints.conf').write_text(f'HOSTNAME_LIST=127.0.0.1\nPORTS={port}\n')
    env=dict(os.environ,QUEST_NATIVE_TOOL_CALLS=os.getenv('QUEST_NATIVE_TOOL_CALLS','true'),QUEST_AB_PROJECT=str(W),QUEST_AB_GROUP_ROOT=str(RUN),QUEST_AUDIT_CASE=case,QUEST_AUDIT_MODE='agent',QUEST_AB_NO_GAIA='true',QUEST_AB_MAX_TURNS='100',QUEST_AB_MEMORY_BASE=f'http://127.0.0.1:{port}/v1',QUEST_TOOL_PROMPT_PROFILE=str(R/'inference/tool_prompts/portable_v3.json'),VISIT_EXPERIMENT_METHOD='bm25',VISIT_EXPERIMENT_DELIVERY='direct',VISIT_PAGE_CONCURRENCY='16',VISIT_BM25_POOL_URL='http://127.0.0.1:18215',VISIT_EXPERIMENT_AUDIT=str(RUN/'logs'/f'{case}-retrieval.jsonl'))
    with (RUN/'logs'/f'{case}-agent.stdout.log').open('w') as out:proc=subprocess.Popen([str(PY),'-u',str(R/'inference/scripts/observe_retrieval_ab.py')],cwd=RUN,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
    agents[case]=(proc,gpu);slots[gpu]+=1;rows[case].update(agent_state='running',agent_pid=proc.pid,agent_started_epoch=time.time(),gpu=gpu,port=port)
   if time.monotonic()-last>=10:publish();last=time.monotonic()
   if not agents and not judges and all(v['agent_state']=='terminal' and v['judge_state'] not in ('pending','running') for v in rows.values()):break
   time.sleep(2)
  executor.shutdown();publish();print('BrowseComp run complete',flush=True)
if __name__=='__main__':main()
