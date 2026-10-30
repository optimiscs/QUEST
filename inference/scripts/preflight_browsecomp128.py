import requests,time,subprocess,os
from pathlib import Path
r=Path(__file__).resolve().parents[2];run=r/'workspace/strict-reproduction/browsecomp-27b-rerank64-16-128-20261029-r1';deadline=time.monotonic()+900
for port in range(18300,18304):
 while time.monotonic()<deadline:
  try:
   resp=requests.post(f'http://127.0.0.1:{port}/v1/chat/completions',json={'model':'QWEN38-27B-NVFP4','messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':32,'temperature':1,'top_p':0.95,'chat_template_kwargs':{'enable_thinking':False}},timeout=180)
   resp.raise_for_status();assert resp.json()['choices'];print('inference ok',port,flush=True);break
  except Exception as e:print('waiting',port,type(e).__name__,flush=True);time.sleep(5)
 else:raise RuntimeError(f'inference preflight failed {port}')
with (run/'server-logs/controller.log').open('a') as f:p=subprocess.Popen([str(r/'workspace/env/bin/python'),'-u',str(r/'inference/scripts/run_browsecomp128_27b.py')],stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=r,env=os.environ.copy())
print('controller started',p.pid,flush=True)
