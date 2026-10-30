"""Uniform official-rubric regrading of final visible answers, never thoughts.

Original results/receipts remain intact. Each case gets one filtered-response
receipt, with the existing single format retry if a verdict is unparseable.
"""
import concurrent.futures
import fcntl
import hashlib
import json
import time
from pathlib import Path
from run_browsecomp25_sft import RUN,PORTS,judge,save


def result_for(row,case):
 path=row.get('result_path')
 final=RUN/'checks'/f'{case}-final-answer-recovery.json'
 if final.exists():
  recovered=json.loads(final.read_text())
  if recovered.get('status')=='scored' and recovered.get('recovery_result_path'):path=recovered['recovery_result_path']
 return path


def main():
 refs={x['case']:x for x in json.loads((RUN/'judge/ground-truth/references.json').read_text())}
 with (RUN/'checks/visible-response-judge.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
   futures={}
   while True:
    rows=json.loads((RUN/'status.json').read_text())['cases']
    for case,(future,port) in list(futures.items()):
     if not future.done():continue
     del futures[case]
     try:out=future.result();print('visible judge',case,out['status'],out.get('is_correct'),flush=True)
     except Exception as exc:print('visible judge error',case,type(exc).__name__,flush=True)
    ports=[port for port in PORTS if port not in {port for _,port in futures.values()}]
    missing=[]
    for case,row in rows.items():
     if row.get('agent_state')!='terminal' or not row.get('result_path'):continue
     path=result_for(row,case);digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
     receipt=RUN/'checks'/f'{case}-visible-response-judge.json'
     if receipt.exists():
      old=json.loads(receipt.read_text())
      if old.get('source_result_sha256')==digest and old.get('response_filter')=='visible_final_only':continue
     missing.append(case)
     if case in futures or not ports:continue
     port=ports.pop(0);futures[case]=(executor.submit(judge,case,port,refs[case],path,receipt_tag='visible-response-judge'),port)
    if not missing and not futures and all(row['agent_state']=='terminal' for row in rows.values()) and (RUN/'checks/final-answer-recovery-complete.json').exists():
     receipts=[json.loads((RUN/'checks'/f'{case}-visible-response-judge.json').read_text()) for case in rows]
     save(RUN/'checks/visible-response-judge-complete.json',{'epoch':time.time(),'total':len(receipts),'scored':sum(x.get('status')=='scored' for x in receipts),'correct':sum(x.get('status')=='scored' and x.get('is_correct') is True for x in receipts),'unavailable':sum(x.get('status')!='scored' for x in receipts),'response_filter':'visible_final_only','original_receipts_preserved':True})
     break
    time.sleep(2)


if __name__=='__main__':main()
