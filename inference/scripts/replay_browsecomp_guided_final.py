"""Probe local JSON-constrained final response on an existing failed trajectory."""
import json,sys,time
from pathlib import Path
from openai import OpenAI
R=Path(__file__).resolve().parents[2];run=R/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';case='row0039';state=json.loads((run/'status.json').read_text())['cases'][case];v=json.loads(Path(state['result_path']).read_text().splitlines()[-1]);messages=v['messages']+[{'role':'user','content':'The research turn limit has been reached. Do not call tools. Using only the information already available, return your best short exact answer in a JSON object. If you cannot determine it, answer Unknown.'}]
c=OpenAI(base_url='http://127.0.0.1:18210/v1',api_key='EMPTY',timeout=600);started=time.monotonic()
try:
 r=c.chat.completions.create(model='QWEN35-SFT10',messages=messages,temperature=0,max_tokens=2048,response_format={'type':'json_schema','json_schema':{'name':'final_answer','strict':True,'schema':{'type':'object','properties':{'answer':{'type':'string','maxLength':256}},'required':['answer'],'additionalProperties':False}}},extra_body={'chat_template_kwargs':{'enable_thinking':False}})
 text=r.choices[0].message.content or '';out={'seconds':time.monotonic()-started,'response':text,'finish_reason':r.choices[0].finish_reason,'no_tools_executed':True}
 try:out['answer']=json.loads(text).get('answer');print('valid_json',isinstance(out['answer'],str),'finish',out['finish_reason'],flush=True)
 except ValueError as e:out['parse_error']=str(e);print('invalid_json','finish',out['finish_reason'],flush=True)
except Exception as e:out={'error':type(e).__name__,'message':str(e)[:500],'no_tools_executed':True};print('error',type(e).__name__,flush=True)
p=run/'checks'/f'{case}-guided-final-replay-v2.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
