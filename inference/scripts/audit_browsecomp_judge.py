"""Screen local judge outputs for potential answer-extraction inconsistencies.

This creates a review queue, never changes a score. String checks are only
screening heuristics; they cannot judge semantic equivalence.
"""
import json,re,time,unicodedata
from pathlib import Path
R=Path(__file__).resolve().parents[2]/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1'
OUT=R/'checks/judge-review-queue.json'
PUBLIC=Path(__file__).resolve().parents[2]/'web/trace-viewer/datasets/browsecomp-sft-25pct-pool64-20261029-r1-judge-review.json'
def norm(s):
 s=''.join(c for c in unicodedata.normalize('NFKD',str(s)).casefold() if not unicodedata.combining(c))
 return re.sub(r'[^\w]','',s)

def review_flags(receipt,visible,reference):
 gold=norm(reference);visible_norm=norm(visible)
 match=re.search(r'(?im)^\s*extracted_final_answer:\s*(.*)$',receipt.get('raw') or '')
 extracted=norm(match.group(1)) if match else '';flags=[]
 if receipt.get('is_correct') is True and gold and gold not in visible_norm:flags.append('correct_but_reference_text_absent')
 if gold and extracted==gold and gold not in visible_norm:flags.append('judge_extraction_equals_reference_but_absent_from_response')
 if receipt.get('is_correct') is False and gold:
  if gold in visible_norm:flags.append('incorrect_but_reference_text_present')
  if extracted==gold:flags.append('incorrect_but_extracted_answer_matches_reference')
 return flags

def review_counts(cases):
 unreviewed=sum('review' not in x for x in cases)
 follow_up=sum(x.get('review',{}).get('status')=='needs_independent_verdict' for x in cases)
 return {'unreviewed':unreviewed,'needs_independent_verdict':follow_up,'unresolved':unreviewed+follow_up}

def scan():
 rows=json.loads((R/'status.json').read_text())['cases'];refs={x['case']:x for x in json.loads((R/'judge/ground-truth/references.json').read_text())};out=[];checked=0
 for case,row in rows.items():
  if row.get('agent_state')!='terminal' or not row.get('result_path'):continue
  receipt=R/'checks'/f'{case}-local-judge.json'
  if row.get('judge_state')=='unavailable':
   candidate=R/'checks'/f'{case}-local-judge-retry.json'
   if candidate.exists():receipt=candidate
  final=R/'checks'/f'{case}-final-answer-recovery.json'
  if final.exists():
   try:
    recovered=json.loads(final.read_text())
    if recovered.get('status')=='scored' and recovered.get('recovery_result_path'):
     row=dict(row,result_path=recovered['recovery_result_path']);receipt=Path(recovered['judge_receipt'])
   except (OSError,ValueError,KeyError,TypeError):pass
  if not receipt.exists():continue
  try:
   data=json.loads(receipt.read_text());native=json.loads(Path(row['result_path']).read_text().splitlines()[-1]);answer=refs[case]['answer'];messages=native.get('messages',[])
  except (OSError,ValueError,KeyError,IndexError):continue
  if data.get('status')!='scored':continue
  checked+=1;raw=messages[-1].get('content','') if messages else '';visible=raw.rsplit('</think>',1)[-1].split('<think>',1)[0];flags=review_flags(data,visible,answer)
  if flags:out.append({'case':case,'flags':flags,'judge_receipt':str(receipt),'result_path':row['result_path']})
 notes_path=R/'checks/judge-review-notes.json'
 try:notes=json.loads(notes_path.read_text()) if notes_path.exists() else {}
 except (OSError,ValueError):notes={}
 for row in out:
  if row['case'] in notes:row['review']=notes[row['case']]
 return {'epoch':time.time(),'checked':checked,**review_counts(out),'cases':out,'limitations':'Text matching is only a review filter; absent/present substrings do not establish correctness or semantic equivalence.'}
def main():
 while True:
  try:
   data=scan();payload=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
   for destination in (OUT,PUBLIC):
    tmp=destination.with_suffix('.tmp');tmp.write_text(payload);tmp.replace(destination)
   print('checked',data['checked'],'review',len(data['cases']),'unresolved',data['unresolved'],flush=True)
   rows=json.loads((R/'status.json').read_text())['cases']
   if all(x['agent_state']=='terminal' and x['judge_state'] not in ('pending','running') for x in rows.values()) and (R/'checks/judge-recovery-complete.json').exists() and (R/'checks/final-answer-recovery-complete.json').exists():break
  except (OSError,ValueError,KeyError) as e:print('audit error',repr(e),flush=True)
  time.sleep(60)

if __name__=='__main__':main()
