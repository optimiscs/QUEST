"""Bounded, tool-free finalization for legacy 100-turn BrowseComp cases.

Original trajectory and score are retained; only separately scored recovered
results are exposed as an explicitly labeled overlay.
"""
import copy,fcntl,json,re,sys,time
from pathlib import Path
from openai import OpenAI
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'inference'));sys.path.insert(0,str(R/'inference/scripts'))
from react_agent import extract_non_thinking_answer,visible_tool_calls
from run_browsecomp25_sft import RUN,judge
PROMPT="The research turn limit has been reached. Do not call any tools. Using only the information already available, give your best final answer inside one <answer>...</answer> block and follow the question's requested format."

def eligible(result,stdout):
 if result.get('num_rounds')!=100 or result.get('termination')!='answer not found.' or '[Final answer] Retrying final-answer format' in stdout:return False
 messages=result.get('messages') or [];last=messages[-1].get('content','') if messages else ''
 visible=last.rsplit('</think>',1)[-1].split('<think>',1)[0]
 # A completed official-format final response should not be replaced.
 if re.search(r'(?im)^\s*(?:\*\*)?exact answer\s*:',visible):return False
 return bool(visible_tool_calls(last))

def save(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)

def recover(case,row,result):
 check=RUN/'checks'/f'{case}-final-answer-recovery.json';existing=RUN/'checks'/f'{case}-finalizer-replay.json'
 if existing.exists():
  replay=json.loads(existing.read_text());attempts=replay.get('attempts',[])
  if len(attempts)>=2 and not any(x.get('answer') for x in attempts):
   save(check,{'case':case,'status':'no_answer','attempts':attempts,'source_result':row['result_path'],'source':'existing_finalizer_replay'});return
 msgs=copy.deepcopy(result.get('messages',[]));attempts=[];answer=None;client=OpenAI(base_url='http://127.0.0.1:18210/v1',api_key='EMPTY',timeout=600)
 for i in range(2):
  print('finalization request started',case,'attempt',i+1,flush=True)
  msgs.append({'role':'user','content':PROMPT});started=time.monotonic()
  try:
   response=client.chat.completions.create(model='QWEN35-SFT10',messages=msgs,stop=['\n<tool_response>','<tool_response>'],temperature=1,top_p=.95,presence_penalty=1.1,max_tokens=16000)
   content=response.choices[0].message.content or '';answer=extract_non_thinking_answer(content);msgs.append({'role':'assistant','content':content});attempts.append({'attempt':i+1,'seconds':time.monotonic()-started,'output':content,'answer':answer,'tool_calls_executed':False})
   print('finalization request finished',case,'attempt',i+1,'answer_found',bool(answer),flush=True)
   if answer:break
  except Exception as e:attempts.append({'attempt':i+1,'error_type':type(e).__name__,'tool_calls_executed':False});break
 if not answer:save(check,{'case':case,'status':'no_answer','attempts':attempts,'source_result':row['result_path']});return
 refs={x['case']:x for x in json.loads((RUN/'judge/ground-truth/references.json').read_text())}
 outdir=RUN/'checks'/'final-answer-recovery'/case;outdir.mkdir(parents=True,exist_ok=True);res=copy.deepcopy(result);res.update(messages=msgs,prediction=answer,termination='final answer recovered without tools');new=outdir/'iter1.jsonl';new.write_text(json.dumps(res,ensure_ascii=False)+'\n');receipt=judge(case,18210,refs[case],str(new),receipt_tag='final-answer-judge')
 save(check,{'case':case,'status':receipt['status'],'is_correct':receipt.get('is_correct'),'attempts':attempts,'source_result':row['result_path'],'recovery_result_path':str(new),'judge_receipt':str(RUN/'checks'/f'{case}-final-answer-judge.json')})

if __name__=='__main__':
 with (RUN/'checks/final-answer-recovery.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  while True:
   rows=json.loads((RUN/'status.json').read_text())['cases'];pending=[]
   for c,v in rows.items():
    if v.get('agent_state')!='terminal' or v.get('judge_state') in ('pending','running') or not v.get('result_path') or (RUN/'checks'/f'{c}-final-answer-recovery.json').exists():continue
    try:
     d=json.loads(Path(v['result_path']).read_text().splitlines()[-1]);stdout=(RUN/'logs'/f'{c}-agent.stdout.log').read_text(errors='replace')
     if eligible(d,stdout):pending.append((c,v,d))
    except (OSError,ValueError,KeyError,IndexError):continue
   if pending:
    c,v,d=pending[0]
    try:recover(c,v,d);print('finalization attempted',c,flush=True)
    except Exception as exc:print('finalization error',c,type(exc).__name__,flush=True);save(RUN/'checks'/f'{c}-final-answer-recovery.json',{'case':c,'status':'error','error_type':type(exc).__name__})
    time.sleep(2);continue
   if all(v['agent_state']=='terminal' and v['judge_state'] not in ('pending','running') for v in rows.values()):
    (RUN/'checks/final-answer-recovery-complete.json').write_text(json.dumps({'epoch':time.time()})+'\n');break
   time.sleep(30)
