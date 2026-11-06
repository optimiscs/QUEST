"""Publish real regression logs via the existing viewer importer.

The staging directory aliases caseNN to the legacy rowNNNN input convention;
source events and result files remain unchanged. Quality review is not exposed
as benchmark correctness.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from summary_events import read_events

ROOT=Path(__file__).resolve().parents[2]


def main():
    run=Path(sys.argv[1]).resolve();site=ROOT/'web/trace-viewer';ident=run.name
    stage=run/'viewer-inputs';(stage/'logs').mkdir(parents=True,exist_ok=True)
    label=os.environ.get('QUEST_SFT_VIEWER_LABEL','SFT 1024 · 摘要回归 16 · 27B')
    while True:
        states={}
        completed=json.loads((run/'rollout-status.json').read_text()) if (run/'rollout-status.json').exists() else {'results':[]}
        done={r['case']:r for r in completed['results']}
        for i in range(16):
            case=f'case{i:02d}';alias=f'row{i:04d}'
            source=run/'logs'/(case+'-agent-events.jsonl');link=stage/'logs'/(alias+'-agent-events.jsonl')
            if source.exists():
                if link.is_symlink():link.unlink()
                events,receipt=read_events(run,case)
                pending=link.with_suffix('.tmp')
                pending.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events))
                pending.replace(link)
                (stage/(case+'-event-provenance.json')).write_text(json.dumps(receipt,indent=2)+'\n')
            results=list((run/'results'/case).rglob('iter1.jsonl'))
            state={'agent_state':'terminal' if case in done else 'running','judge_state':'unavailable',
                   'judgment':'摘要模式质量审核；不是独立测试集或官方准确率。'}
            if results:state['result_path']=str(results[0])
            states[alias]=state
        temp=stage/'status.tmp';temp.write_text(json.dumps({'cases':states}));temp.replace(stage/'status.json')
        dest=site/'datasets'/ident
        subprocess.run([sys.executable,str(ROOT/'web/build_gaia.py'),'--run-root',str(stage),'--output-dir',str(dest),
                        '--label',label,'--benchmark','QUEST SFT regression','--requested-cases','16',
                        '--include-running','--replace-existing'],check=True,stdout=subprocess.DEVNULL)
        with (site/'datasets/index.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            path=site/'datasets/index.json';index=json.loads(path.read_text())
            if not any(r['id']==ident for r in index['datasets']):
                index['datasets'].append({'id':ident,'label':label,'description':'从1024条候选中固定抽取12条客观、4条开放任务；摘要模式，短ID，native tools。非独立测试集。',
                    'folder':'datasets/'+ident,'data':'datasets/'+ident+'/traces.json','benchmark':'QUEST SFT regression','visible':True})
                temp=path.with_suffix('.tmp');temp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
        print(json.dumps({'published':ident,'completed':len(done),'total':16}),flush=True)
        if len(done)==16 or '--once' in sys.argv:return
        time.sleep(20)


if __name__=='__main__':main()
