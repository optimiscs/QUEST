"""Start a prepared 128-case run after each model has served real inference."""
import os,subprocess,time,requests
from pathlib import Path
R=Path(__file__).resolve().parents[2];run=Path(os.environ['QUEST_BROWSE128_RUN']);ports=[int(x) for x in os.environ['QUEST_BROWSE128_PORTS'].split(',')];deadline=time.monotonic()+1800
s=requests.Session();s.trust_env=False
for port in ports:
 while time.monotonic()<deadline:
  try:
   r=s.post(f'http://127.0.0.1:{port}/v1/chat/completions',json={'model':'QWEN38-27B-NVFP4','messages':[{'role':'user','content':'Reply OK.'}],'temperature':1,'top_p':0.95,'max_tokens':32,'chat_template_kwargs':{'enable_thinking':False}},timeout=90);r.raise_for_status();assert r.json()['choices'][0]['message'].get('content');print('generation preflight passed',port,flush=True);break
  except Exception as e:print('waiting for generation',port,type(e).__name__,str(e)[:160],flush=True);time.sleep(10)
 else:raise SystemExit(f'preflight failed for port {port}')
while time.monotonic()<deadline:
 try:
  assert s.get('http://127.0.0.1:18215/health',timeout=5).json()['workers']==64
  r=s.post('http://127.0.0.1:18314/score',json={'goal':'When opened?','passages':['The bridge opened in 1984.','A train stopped.']},timeout=90);r.raise_for_status();assert len(r.json()['scores'])==2;print('BM25 and reranker preflight passed',flush=True);break
 except Exception as e:print('waiting for retrieval',type(e).__name__,str(e)[:160],flush=True);time.sleep(10)
else:raise SystemExit('retrieval preflight failed')
for name,script in [('controller','run_browsecomp128_27b.py'),('viewer','publish_browsecomp128_27b.py')]:
 with (run/f'{name}.log').open('a') as f:p=subprocess.Popen([str(R/'workspace/env/bin/python'),'-u',str(R/'inference/scripts'/script)],cwd=R,env=os.environ.copy(),stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 print(name,'started pid',p.pid,flush=True)
