"""Run the QUEST open-ended evaluator and preserve an auditable status.

The caller provides explicit input files and an API key in the environment.
No score is considered complete unless every requested (prompt, iteration) has
exactly one finite result, matching the original criteria identifier.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'{path.name} must contain nonempty JSON objects')
    return rows


def validate_inputs(criteria, candidates, references):
    prompts = {}
    for row in criteria:
        prompt, ident = row.get('prompt'), row.get('id')
        weights, dimensions = row.get('dimension_weight'), row.get('criterions')
        if not isinstance(prompt, str) or not prompt or ident is None or prompt in prompts:
            raise ValueError('criteria prompt/id missing or duplicated')
        if not isinstance(weights,dict) or not isinstance(dimensions,dict) or not weights or set(weights)!=set(dimensions):
            raise ValueError('criteria incomplete or weights invalid')
        if any(isinstance(v,bool) for v in weights.values()):raise ValueError('criteria incomplete or weights invalid')
        try: values=[float(v) for v in weights.values()]
        except (TypeError,ValueError):raise ValueError('criteria incomplete or weights invalid')
        if any(not math.isfinite(v) or v<0 for v in values) or abs(sum(values)-1)>0.02 or any(not isinstance(x,list) or not x for x in dimensions.values()):
            raise ValueError('criteria incomplete or weights invalid')
        for dimension, items in dimensions.items():
            names=set(); criterion_weights=[]
            for item in items:
                if not isinstance(item,dict):raise ValueError('invalid criterion')
                name,explanation=item.get('criterion'),item.get('explanation')
                if not isinstance(name,str) or not name.strip() or name in names or not isinstance(explanation,str) or not explanation.strip():
                    raise ValueError('criterion title/explanation missing or duplicated')
                weight=item.get('weight')
                if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or weight<0:
                    raise ValueError('invalid criterion weight')
                names.add(name);criterion_weights.append(weight)
            if sum(criterion_weights)<=0:raise ValueError('criterion weights must have positive sum')
        prompts[prompt] = {'id':ident,'dimensions':dimensions,'weights':weights}

    def match(row, role):
        termination = str(row.get('termination','')).lower()
        content = row.get('prediction',row.get('answer',''))
        if not isinstance(content,str) or len(content.strip())<100 or 'answer not found' in content.lower() or 'answer not found' in termination or 'timeout' in termination:
            raise ValueError(role+' has incomplete or failed answer; refusing to score')
        question=row.get('question')
        matches=[prompt for prompt in prompts if isinstance(question,str) and question.startswith(prompt)]
        if len(matches)!=1:
            raise ValueError(role+' question must match exactly one criteria prompt')
        return matches[0]

    expected={}
    for row in candidates:
        prompt=match(row,'candidate')
        iteration=row.get('iter')
        if not isinstance(iteration,(str,int,type(None))) or isinstance(iteration,bool):
            raise ValueError('candidate iteration must be a string, integer or null')
        key=(prompt,iteration)
        if key in expected:raise ValueError('duplicate candidate prompt/iteration')
        expected[key]=prompts[prompt]
    ref_prompts=[match(row,'reference') for row in references]
    if len(ref_prompts)!=len(set(ref_prompts)):
        raise ValueError('duplicate reference prompt')
    if set(prompt for prompt,_ in expected)-set(ref_prompts):
        raise ValueError('candidate lacks matching reference')
    return expected


def validate_results(rows, expected):
    seen=set()
    for row in rows:
        if not isinstance(row,dict):return False
        key=(row.get('query'),row.get('iter'))
        try:
            if key not in expected or key in seen or row.get('id')!=expected[key]['id']:return False
            score=row.get('final_score');total_a=row.get('total_score_a');total_b=row.get('total_score_b')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (score,total_a,total_b)):return False
            if not 0<=score<=1 or not 0<=total_a<=10 or not 0<=total_b<=10 or total_a+total_b<=0:return False
            if not math.isclose(score,total_a/(total_a+total_b),rel_tol=1e-6,abs_tol=1e-6):return False
            criteria=expected[key]['dimensions'];details=row.get('detailed_evaluations')
            if not isinstance(details,dict) or set(details)!=set(criteria):return False
            recomputed_a=0.0;recomputed_b=0.0
            for dimension,items in criteria.items():
                actual=details.get(dimension)
                if not isinstance(actual,list) or len(actual)!=len(items):return False
                expected_items={item['criterion']:item for item in items};received=set()
                sum_a=0.0;sum_b=0.0;weight_sum=0.0
                for item in actual:
                    if not isinstance(item,dict):return False
                    name=item.get('criterion_name')
                    if name not in expected_items or name in received or item.get('category')!=dimension:return False
                    weight=item.get('weight');a=item.get('score_a');b=item.get('score_b')
                    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (weight,a,b)):return False
                    if not 0<=a<=10 or not 0<=b<=10 or not math.isclose(weight,expected_items[name]['weight'],rel_tol=1e-6,abs_tol=1e-6):return False
                    sum_a+=a*weight;sum_b+=b*weight;weight_sum+=weight
                    received.add(name)
                if weight_sum<=0:return False
                dimension_weight=float(expected[key]['weights'][dimension])
                recomputed_a+=sum_a/weight_sum*dimension_weight
                recomputed_b+=sum_b/weight_sum*dimension_weight
            if not math.isclose(total_a,recomputed_a,rel_tol=1e-6,abs_tol=1e-6):return False
            if not math.isclose(total_b,recomputed_b,rel_tol=1e-6,abs_tol=1e-6):return False
            seen.add(key)
        except (TypeError,ValueError):return False
    return seen == set(expected)


def main(argv=None, runner=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('criteria','candidate','reference','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    paths={k:getattr(args,k).resolve() for k in ('criteria','candidate','reference','out')}
    for name in ('criteria','candidate','reference'):
        if not paths[name].is_file() or not paths[name].stat().st_size:raise ValueError(name+' missing or empty')
    expected=validate_inputs(read_jsonl(paths['criteria']),read_jsonl(paths['candidate']),read_jsonl(paths['reference']))
    log=paths['out'].with_suffix('.log');status=paths['out'].with_suffix('.status.json')
    snapshot_dir=paths['out'].with_suffix('.inputs')
    if any(p.exists() or p.is_symlink() for p in (paths['out'],log,status,snapshot_dir)):
        raise FileExistsError('refusing to overwrite score output, log, status or input snapshots')
    env=os.environ.copy();env['PYTHONUNBUFFERED']='1';env['QUEST_DEEPSEEK_COMPAT']='1';env.setdefault('DEEPSEEK_API_BASE','https://api.deepseek.com/v1')
    if not env.get('DEEPSEEK_API_KEY'):raise RuntimeError('DEEPSEEK_API_KEY must be set')
    paths['out'].parent.mkdir(parents=True,exist_ok=True)
    snapshot_dir.mkdir(mode=0o700,exist_ok=False)
    snapshots={}
    for name in ('criteria','candidate','reference'):
        snapshot=snapshot_dir/(name+'.jsonl')
        fd=os.open(snapshot,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(paths[name].read_bytes())
        snapshots[name]=snapshot
    # Validate exactly the bytes that the evaluator will read.
    expected=validate_inputs(read_jsonl(snapshots['criteria']),read_jsonl(snapshots['candidate']),read_jsonl(snapshots['reference']))
    input_hashes={k:sha(snapshots[k]) for k in ('criteria','candidate','reference')}
    script=ROOT/'task/open_ended_eval/evaluate_criteria_args_parallel_open_ended.py'
    cmd=[sys.executable,str(script),'--model','deepseek-flash','--prompt_to_eval',str(snapshots['criteria']),
         '--answer_to_eval',str(snapshots['candidate']),'--ref_to_eval',str(snapshots['reference']),
         '--output_file',str(paths['out']),'--hostname_list','localhost','--ports','8000','--max_workers','1']
    exit_code=None;error_type=None
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            try:
                proc=(runner or subprocess.run)(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=900)
                exit_code=proc.returncode
            except (OSError,subprocess.TimeoutExpired) as exc:
                error_type=type(exc).__name__
    except BaseException:
        raise
    rows=[];valid=False
    if paths['out'].is_file():
        try:
            rows=read_jsonl(paths['out']);valid=validate_results(rows,expected)
        except (ValueError,OSError):error_type=error_type or 'InvalidScoreOutput'
    try:
        input_hashes_after={k:sha(snapshots[k]) for k in input_hashes}
    except OSError:
        input_hashes_after=None
    if input_hashes_after != input_hashes:error_type='InputSnapshotChanged'
    if exit_code==0 and not valid and error_type is None:error_type='ResultCoverageMismatch'
    complete=exit_code==0 and valid and error_type is None
    meta={'exit_code':exit_code,'error_type':error_type,'result_rows':len(rows),
          'valid_scores':len(rows) if valid else 0,'expected_scores':len(expected),'complete':complete,
          'input_sha256':input_hashes, 'input_sha256_after':input_hashes_after,
          'input_snapshots':{k:str(snapshots[k]) for k in ('criteria','candidate','reference')},
          'output_sha256':sha(paths['out']) if paths['out'].is_file() else None}
    fd=os.open(status,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(meta,stream,indent=2)
    print(json.dumps(meta))
    return 0 if complete else 1

if __name__=='__main__':sys.exit(main())
