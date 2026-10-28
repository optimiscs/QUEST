#!/usr/bin/env python3
"""Score explicit GAIA submission records with the pinned upstream scorer."""
import argparse, contextlib, hashlib, importlib.util, json, subprocess, sys
from pathlib import Path
ROOT = Path('/root/autodl-tmp/Quest/quest4b-gaia-20261027')
SOURCE = ROOT/'strict-reproduction/official-sources/gaia-leaderboard'
PIN = '9f133d71362e77b3539f1514f31b9c101a545fec'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--submission', type=Path, required=True, help='JSONL: task_id, model_answer; missing predictions must be omitted')
    p.add_argument('--reference', type=Path, required=True, help='Explicit JSON array of GAIA references: task_id, answer')
    p.add_argument('--out', type=Path, required=True, help='New output directory; never reused')
    a = p.parse_args()
    revision = subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
    status = subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain','--untracked-files=no'],text=True).strip()
    if revision != PIN or status: raise SystemExit('Official GAIA source mismatch or modified')
    submission, reference = a.submission.resolve(strict=True), a.reference.resolve(strict=True)
    predictions = load(submission)
    refs = json.loads(reference.read_text())
    if not isinstance(refs,list) or not predictions: raise ValueError('Expected nonempty submission and reference array')
    refmap = {}
    for row in refs:
        ident=row.get('task_id'); answer=row.get('answer',row.get('Final answer'))
        if not isinstance(ident,str) or ident in refmap or not isinstance(answer,str): raise ValueError('Invalid/duplicate reference')
        refmap[ident]=answer
    seen=set()
    for row in predictions:
        ident=row.get('task_id'); answer=row.get('model_answer')
        if not isinstance(ident,str) or ident in seen or ident not in refmap or not isinstance(answer,str) or not answer.strip(): raise ValueError('Invalid, missing, empty, unknown, or duplicate prediction')
        seen.add(ident)
    spec=importlib.util.spec_from_file_location('gaia_official_scorer',SOURCE/'scorer.py')
    scorer=importlib.util.module_from_spec(spec); spec.loader.exec_module(scorer)
    a.out.mkdir(parents=True,exist_ok=False)
    results=[]
    with (a.out/'official-scorer.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        for row in predictions:
            ident=row['task_id']; outcome=bool(scorer.question_scorer(row['model_answer'],refmap[ident]))
            results.append({'task_id':ident,'model_answer':row['model_answer'],'correct':outcome})
    (a.out/'scores.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in results))
    manifest={'benchmark':'GAIA','method':'upstream question_scorer, normalized exact match','source_commit':PIN,'scorer_sha256':sha(SOURCE/'scorer.py'),'submission_sha256':sha(submission),'reference_sha256':sha(reference),'source_modified':False,'scored':len(results),'correct':sum(x['correct'] for x in results),'judge_model':None,'submission_path':str(submission),'reference_path':str(reference)}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
if __name__ == '__main__': main()
