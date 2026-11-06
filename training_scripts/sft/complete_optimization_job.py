"""Durable optimization -> export -> parity -> live regression; no SFT launch."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'training_scripts/sft'))
from optimize_summary_data import write,Pipeline


def main():
    source=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
    review_workers=int(os.environ.get('QUEST_SFT_REVIEW_WORKERS','4'))
    inherit_upstream=os.environ.get('QUEST_SFT_ACCEPTANCE_MODE')=='upstream'
    if review_workers<1:raise ValueError('QUEST_SFT_REVIEW_WORKERS must be positive')
    (out/'logs').mkdir(parents=True,exist_ok=True)
    def run_script(script,args,logname):
        # The environment's dataset libraries live in the existing training
        # environment; use them only for artifact export, never launch a trainer.
        code="import sys,runpy;sys.path.append('/root/autodl-tmp/Quest/workspace/envs/llamafactory-v095-qlora/lib/python3.12/site-packages');sys.argv="+repr([script]+[str(x) for x in args])+";runpy.run_path("+repr(str(ROOT/'training_scripts/sft'/script))+",run_name='__main__')"
        with (out/'logs'/logname).open('a') as log:
            subprocess.run([sys.executable,'-u','-c',code],cwd=ROOT,env=dict(os.environ,OMP_NUM_THREADS='2'),
                           stdout=log,stderr=subprocess.STDOUT,check=True)
    try:
        if inherit_upstream:
            run_script('inherit_upstream_data.py',['--source',source,'--output',out,'--flexible-mix'],'upstream-screening.log')
        else:
            run_script('optimize_summary_data.py',['--source',source,'--output',out,'--run','--workers',str(review_workers)],'full-review.log')
        if not (out/'candidates1024.jsonl').exists():
            write(out/'job-result.json',{'status':'incomplete','reason':'See status.json and generation receipts; quota not met.',
                                       'training_started':False});return
        run_script('tokenize_summary_sessions.py',[out],'tokenization.log')
        run_script('check_summary_parity.py',[out],'parity.log')
        sys.path.append(str(ROOT/'workspace/envs/llamafactory-v095-qlora/lib/python3.12/site-packages'))
        from datasets import Dataset,DatasetDict
        ds=Dataset.from_parquet(str(out/'tokenized-turns.parquet'),cache_dir=str(out/'dataset-cache'))
        sessions=set();finals=collections.Counter();loss_tokens=0
        for row in ds:
            n=row['prompt_tokens'];assert row['labels'][:n]==[-100]*n
            assert row['labels'][n:]==row['input_ids'][n:]
            sessions.add(row['session_id']);loss_tokens+=len(row['input_ids'])-n
            if row['final']:finals[row['session_id']]+=1
        assert len(sessions)==1024 and set(finals.values())=={1} and set(finals)==sessions
        DatasetDict({'train':ds}).save_to_disk(str(out/'tokenized-dataset'))
        write(out/'training-data-contract.json',{'sessions':1024,'training_rows':len(ds),'loss_tokens':loss_tokens,
            'tokenized_path':str(out/'tokenized-dataset'),'loss_mask':'assistant target only; captured views across memory boundaries',
            'truncation':False,'training_started':False,
            'task_acceptance':'inherited_upstream' if inherit_upstream else 'original_rubric_review',
            'factual_verification':'upstream acceptance reused; local harness and conversion checks only' if inherit_upstream else 'summary-grounded review, not independent source verification'})
        live=out/(out.name+'-validation16');live.mkdir(exist_ok=True);(live/'configs').mkdir(exist_ok=True)
        for name in ('sample16-static.jsonl','sample16-aligned-v2.jsonl'):shutil.copy2(out/name,live/name)
        samples=list(map(json.loads,(out/'sample16-aligned-v2.jsonl').read_text().splitlines()))
        for row in samples:
            m=row['metadata'];case=m['case']
            (live/'configs'/(case+'.jsonl')).write_text(json.dumps({'question':m['question'],'answer':'','filename':case})+'\n')
            (live/'configs'/(case+'-server_endpoints.conf')).write_text('HOSTNAME_LIST=127.0.0.1\nPORTS=19300\n')
        run_script('run_summary16.py',[live],'live-controller.log')
        run_script('audit_summary16_runtime.py',[live],'live-audit.log')
        from regenerate_optimization import record_from_events
        client=Pipeline.__new__(Pipeline);client.out=out/'live-quality';client.args=SimpleNamespace(endpoint='http://127.0.0.1:19300')
        from original_rubric_quality import OriginalRubrics
        client.original_rubrics=OriginalRubrics(out)
        client.locks=collections.defaultdict(__import__('threading').Lock)
        from clean_harness_trajectories import sha
        client.contract_sha=sha(json.loads((out/'contract.json').read_text()))
        for name in ('decisions','reviews','rubrics'):(client.out/name).mkdir(parents=True,exist_ok=True)
        assessments=[]
        for sample in samples:
            meta=sample['metadata']
            try:
                row=record_from_events(live,meta,sample['tools'])
                decision=client.review(row);assessments.append({'case':meta['case'],'status':decision['status']})
            except Exception as exc:
                assessments.append({'case':meta['case'],'status':'needs_review','reason':str(exc)[:500]})
        write(out/'live-quality-report.json',{'cases':assessments,'scope':'16 training questions, same base model; not held-out accuracy or post-SFT evaluation'})
        env=dict(os.environ,QUEST_SFT_VIEWER_LABEL=out.name+' · 摘要回归 16')
        subprocess.run([sys.executable,str(ROOT/'training_scripts/sft/publish_summary16.py'),str(live),'--once'],cwd=ROOT,env=env,check=True)
        write(out/'job-result.json',{'status':'data_export_and_regression_complete','sessions':1024,
            'live_quality_counts':dict(collections.Counter(r['status'] for r in assessments)),
            'training_started':False,'finished_epoch':time.time()})
    except Exception as exc:
        write(out/'job-result.json',{'status':'error','error':type(exc).__name__+':'+str(exc)[:1000],
                                   'training_started':False,'epoch':time.time()})
        raise


if __name__=='__main__':main()
