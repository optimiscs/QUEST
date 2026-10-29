"""Replay final-answer formatting on an existing limit-reached trajectory."""
import copy,json,os,sys,time
from pathlib import Path
from openai import OpenAI
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'inference'))
from react_agent import extract_non_thinking_answer,visible_tool_calls
run=R/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';case=sys.argv[1] if len(sys.argv)>1 else 'row0039';rows=json.loads((run/'status.json').read_text())['cases'];row=rows[case];v=json.loads(Path(row['result_path']).read_text().splitlines()[-1]);msgs=copy.deepcopy(v['messages']);out=[]
if v.get('num_rounds')!=100 or v.get('termination')!='answer not found.':raise RuntimeError('case is not an unanswered turn-limit trajectory')
client=OpenAI(base_url='http://127.0.0.1:18210/v1',api_key='EMPTY',timeout=600)
for i in range(2):
 msgs.append({'role':'user','content':"The research turn limit has been reached. Do not call any tools. Using only the information already available, give your best final answer inside one <answer>...</answer> block and follow the question's requested format."})
 started=time.monotonic()
 try:
  resp=client.chat.completions.create(model='QWEN35-SFT10',messages=msgs,stop=['\n<tool_response>','<tool_response>'],temperature=1,top_p=.95,presence_penalty=1.1,max_tokens=16000)
  text=resp.choices[0].message.content or '';answer=extract_non_thinking_answer(text)
  out.append({'attempt':i+1,'seconds':time.monotonic()-started,'finish_reason':resp.choices[0].finish_reason,'answer':answer,'output':text,'contained_tool_call':bool(visible_tool_calls(text))});msgs.append({'role':'assistant','content':text});print('attempt',i+1,'answer_found',bool(answer),'tool_call',bool(visible_tool_calls(text)),flush=True)
  if answer:break
 except Exception as e:out.append({'attempt':i+1,'error':type(e).__name__});print('request failure',type(e).__name__,flush=True);break
p=run/'checks'/f'{case}-finalizer-replay.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'case':case,'source_result':row['result_path'],'no_tools_executed':True,'attempts':out},ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
