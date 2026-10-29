"""Start pooled BM25 comparison only after the ongoing V3 run finishes."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
import requests
repo=Path(__file__).resolve().parents[2]
source=repo/'workspace/strict-reproduction/gaia-bm25-5gpu-base-toolprompt-v3-20261029-r1'
name='gaia-bm25-5gpu-base-v3-pool8-page2-20261029-r1'
target=repo/'workspace/strict-reproduction'/name
url='http://127.0.0.1:18215'
with (source/'controller.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 rows=json.loads((source/'status.json').read_text())['cases']
 if len(rows)!=32 or any(x.get('agent_state')!='terminal' for x in rows.values()):raise RuntimeError('V3 stopped before all 32 tasks became terminal')
 if (target/'status.json').exists():raise RuntimeError('target run already exists; refusing duplicate')
 def health():
  try:
   r=requests.get(url+'/health',timeout=3);r.raise_for_status();return r.json()
  except (requests.RequestException,ValueError):return None
 h=health()
 if h is None:
  with (repo/'workspace/strict-reproduction/gaia-bm25-pool8-service.log').open('a') as output:
   subprocess.Popen(['bash',str(repo/'inference/scripts/start_shared_bm25_pool.sh')],cwd=repo,env=dict(os.environ,QUEST_BM25_WORKERS='8',QUEST_BM25_QUEUE_LIMIT='128',QUEST_BM25_PORT='18215'),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
  for _ in range(60):
   time.sleep(2);h=health()
   if h:break
 if not h or h.get('workers')!=8 or h.get('queue_limit')!=128:raise RuntimeError('BM25 pool is unavailable or has unexpected worker/queue configuration')
 target.mkdir(parents=True,exist_ok=True)
 env=dict(os.environ,QUEST_GAIA_RUN_ID=name,QUEST_TOOL_PROMPT_PROFILE=str(repo/'inference/tool_prompts/portable_v3.json'),QUEST_AB_MAX_TURNS='100',VISIT_PAGE_CONCURRENCY='2',VISIT_BM25_POOL_URL=url)
 with (target/'controller.log').open('a') as output:
  p=subprocess.Popen([sys.executable,'-u',str(repo/'inference/scripts/run_gaia_bm25_5gpu.py')],env=env,cwd=repo,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 print('Started V3 pooled BM25 controller',p.pid,flush=True)
 env=dict(os.environ,QUEST_COMPARISON_ORIGINAL=source.name,QUEST_COMPARISON_OPTIMIZED=name,QUEST_COMPARISON_OUTPUT=str(repo/'web/trace-viewer/datasets/gaia-v3-bm25-pool-comparison.json'))
 with (target/'comparison.log').open('a') as output:
  p=subprocess.Popen([sys.executable,'-u',str(repo/'inference/scripts/publish_gaia_toolprompt_comparison.py')],env=env,cwd=repo,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 print('Started tool/accuracy comparison publisher',p.pid,flush=True)
 with (target/'performance.log').open('a') as output:
  p=subprocess.Popen([sys.executable,'-u',str(repo/'inference/scripts/publish_gaia_bm25_performance.py')],cwd=repo,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 print('Started BM25 performance comparison publisher',p.pid,flush=True)
