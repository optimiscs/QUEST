"""Bounded paired replay on real failed-tool contexts; does not execute tools."""
import concurrent.futures, importlib.util, json, os, re, sys, time
from pathlib import Path
from openai import OpenAI
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO/'inference'))
spec=importlib.util.spec_from_file_location('gaia_plugin',REPO/'evaluation/official_dataset/run_gaia_prompt.py');plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin);plugin.install()
import react_agent
from tool_prompt_plugin import apply
BASE=REPO/'workspace/strict-reproduction/gaia-bm25-5gpu-base-20261029-r1'
DEST=Path(os.environ.get('QUEST_REPLAY_OUTPUT',str(REPO/'workspace/strict-reproduction/gaia-toolprompt-replay-20261029-r1.json')))
profiles={}
for name in os.environ.get('QUEST_REPLAY_PROFILES','portable_v1,portable_v2').split(','):
 os.environ['QUEST_TOOL_PROMPT_PROFILE']=str(REPO/'inference/tool_prompts'/f'{name}.json')
 profiles[name]=react_agent.build_system_prompt(True)+react_agent.today_date()
cases=['row0001','row0002','row0005','row0008','row0010','row0012','row0014','row0028']
contexts={}
for case in cases:
 for line in (BASE/'logs'/f'{case}-agent-events.jsonl').open():
  x=json.loads(line)
  if x.get('event')=='span_start' and x.get('kind')=='policy_model':
   msgs=x.get('input',{}).get('msgs',[])
   if msgs and any('Invalid tool call format' in str(m.get('content','')) for m in msgs if m.get('role')=='user'):
    contexts[case]=msgs;break
if set(contexts)!=set(cases): raise RuntimeError('missing recorded contexts')

def run(item):
 case,variant,port=item
 msgs=[dict(x) for x in contexts[case]];msgs[0]['content']=profiles[variant]
 client=OpenAI(api_key='EMPTY',base_url=f'http://127.0.0.1:{port}/v1',timeout=600)
 try:
  r=client.chat.completions.create(model='QWEN35-BASE',messages=msgs,temperature=1,top_p=.95,presence_penalty=1.1,max_tokens=4096,seed=42,stop=['\n<tool_response>','<tool_response>'])
  content=r.choices[0].message.content or ''; calls=react_agent.visible_tool_calls(content); valid=False; name=None
  if calls:
   raw=re.sub(r'<code>.*?</code>','',calls[-1],flags=re.DOTALL).strip()
   try:
    obj=json.loads(raw);name=obj.get('name');valid=isinstance(name,str) and isinstance(obj.get('arguments',{}),dict)
   except (ValueError,AttributeError):pass
  return {'case':case,'profile':variant,'tool_call':bool(calls),'json_valid':valid,'tool_name':name,'finish_reason':r.choices[0].finish_reason,'content':content}
 except Exception as exc:return {'case':case,'profile':variant,'error':repr(exc)}
items=[(c,v,[18210,18201,18202,18203,18204][i%5]) for i,c in enumerate(cases) for v in profiles]
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for res in pool.map(run,items):
  results.append(res);print(res['case'],res['profile'],'valid',res.get('json_valid'),'call',res.get('tool_call'),'finish',res.get('finish_reason'),flush=True)
  tmp=DEST.with_suffix('.tmp');tmp.write_text(json.dumps({'cases':cases,'max_tokens':4096,'seed':42,'results':results},ensure_ascii=False,indent=2));tmp.replace(DEST)
