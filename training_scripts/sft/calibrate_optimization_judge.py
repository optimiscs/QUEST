"""Final-answer evaluator fixtures from the completed regression, never SFT rows."""
import concurrent.futures
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from optimize_summary_data import Pipeline, write
from optimization_quality import RUBRIC_PROMPT, REVIEW_PROMPT, VERIFY_PROMPT, validate_rubric, validate_review
from inference.source_ids import referenced_ids


def main():
    source=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
    client=Pipeline.__new__(Pipeline);client.args=SimpleNamespace(endpoint='http://127.0.0.1:19300')
    fixtures=[('case02','fresh','pass'),('case04','fresh','pass'),('case10','fresh','pass'),
              ('case01','fresh','not_pass'),('case11','static','not_pass')]
    def check(spec):
        case,kind,expected=spec;payload=json.loads((source/'quality'/(case+'-'+kind+'-input.json')).read_text())
        rubric,rr=client.call(RUBRIC_PROMPT,{'question':payload['question']},2048)
        validate_rubric(rubric,payload['question'])
        evidence=[{'unit':f'E{i}','step':i,'source_ids':sorted(referenced_ids(text)), 'text':text} for i,text in enumerate(payload['tool_observations'])]
        if kind=='fresh':maps=source/'traces'/case/case/'iter1/sources.json'
        else:
            sample=next(r for r in map(json.loads,(source/'sample16-aligned-v2.jsonl').read_text().splitlines()) if r['metadata']['case']==case)
            maps=Path(sample['metadata']['source_map'])
        bundle={'question':payload['question'],'evidence':evidence,'targets':[{'step':len(evidence)+1,'final':True,
                'content':json.dumps({'answer':payload['answer']}),'reasoning':'','tool_calls':[]}],
                'unverified_inherited_memory':'','rule_issues':[], 'sources':json.loads(maps.read_text()),
                'required_assistant_steps':[len(evidence)+1]}
        try:
            phases=[]
            for phase,system in (('primary',REVIEW_PROMPT),('challenge',VERIFY_PROMPT)):
                for attempt in range(2):
                    judgment,raw=client.call(system,dict(bundle,rubric=rubric))
                    try:verdict=validate_review(judgment,rubric,bundle)
                    except ValueError as exc:
                        write(out/(case+f'-{kind}-{phase}-invalid-{attempt}.json'),{'judgment':judgment,'error':str(exc)})
                        if attempt==1:raise
                        system+='\nValidation failed: '+str(exc)+'. Follow the exact step list and copy short literal evidence quotes.'
                        continue
                    break
                phases.append({'phase':phase,'verdict':verdict,'judgment':judgment})
                if verdict!='pass':break
            result={'case':case,'kind':kind,'expected':expected,'verdict':verdict,
                    'matched':verdict=='pass' if expected=='pass' else verdict!='pass',
                    'rubric':rubric,'judgment':judgment,'raw':raw,'phases':phases}
        except (ValueError,KeyError,TypeError) as exc:
            result={'case':case,'kind':kind,'expected':expected,'verdict':'invalid_review','matched':False,
                    'error':str(exc),'rubric':rubric,'judgment':locals().get('judgment')}
        write(out/(case+'-'+kind+'.json'),result);return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(check,fixtures))
    report={'scope':'Final-answer-only fixtures; no fabricated trace is exported to training.',
            'all_matched':all(r['matched'] for r in results),
            'cases':[{k:r[k] for k in ('case','kind','expected','verdict','matched')} for r in results]}
    write(out/'report.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
