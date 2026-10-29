"""Retry unavailable local judge formats without changing original receipts."""
import fcntl,json,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'inference/scripts'))
from run_browsecomp25_sft import RUN,judge
refs={x['case']:x for x in json.loads((RUN/'judge/ground-truth/references.json').read_text())}
with (RUN/'checks/judge-recovery.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 while True:
  rows=json.loads((RUN/'status.json').read_text())['cases'];pending=[]
  for case,row in rows.items():
   old=RUN/'checks'/f'{case}-local-judge.json';new=RUN/'checks'/f'{case}-local-judge-retry.json'
   if row.get('agent_state')=='terminal' and row.get('judge_state')=='unavailable' and row.get('result_path') and old.exists() and not new.exists():pending.append((case,row,old))
  if pending:
   case,row,old=pending[0];original=json.loads(old.read_text());prior=original.get('raw');prior=prior if isinstance(prior,str) and prior.strip() else None
   result=judge(case,18210,refs[case],row['result_path'],receipt_tag='local-judge-retry',prior_raw=prior)
   print('judge recovery',case,result['status'],flush=True)
   time.sleep(2);continue
  if all(v['agent_state']=='terminal' and v['judge_state'] not in ('pending','running') for v in rows.values()):
   # The controller publishes the authoritative state under this lock. Wait
   # for its final write before applying recovered verdicts atomically.
   with (RUN/'controller.lock').open('a+') as controller_lock:
    fcntl.flock(controller_lock,fcntl.LOCK_EX)
    path=RUN/'status.json';state=json.loads(path.read_text());recovered=0
    for case,row in state['cases'].items():
     p=RUN/'checks'/f'{case}-local-judge-retry.json'
     if row.get('judge_state')!='unavailable' or not p.exists():continue
     x=json.loads(p.read_text())
     if x.get('status')=='scored' and isinstance(x.get('is_correct'),bool):
      row.update(judge_state='scored',is_correct=x['is_correct'],judgment='BrowseComp 官方判分提示；本地 4B 裁判格式重试',judge_recovery_path=str(p));recovered+=1
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)
   (RUN/'checks/judge-recovery-complete.json').write_text(json.dumps({'epoch':time.time(),'recovered':recovered,'note':'All eligible unavailable judgments attempted; original receipts retained.'})+'\n')
   break
  time.sleep(30)
