import collections
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training_scripts/sft'))
from optimize_summary_data import Pipeline


def pipeline(tmp_path, count=12):
    p=Pipeline.__new__(Pipeline)
    p.out=tmp_path
    (tmp_path/'decisions').mkdir()
    p.args=SimpleNamespace(workers=2)
    p.original_meta={}
    p.plan=[{'id':str(i),'question_sha256':str(i),'kind':'objective','stratum':0}
            for i in range(count)]
    p.convert=lambda m:{'metadata':m}
    p.progress=lambda stage:([],collections.Counter())
    return p


def test_fast_worker_reaches_next_batch_while_first_review_is_blocked(tmp_path):
    p=pipeline(tmp_path)
    slow_started=threading.Event();beyond_first_batch=threading.Event()
    reviewed=[];lock=threading.Lock()
    def review(row):
        ident=row['metadata']['id']
        if ident=='0':
            slow_started.set()
            # With a four-item batch barrier, item 4 cannot start until this
            # request completes. The streaming scheduler must start it now.
            assert beyond_first_batch.wait(5), 'slow request blocked replenishment'
        else:
            assert slow_started.wait(5)
            if ident=='4':beyond_first_batch.set()
        with lock:reviewed.append(ident)
    p.review=review
    p.fill_reserve()
    assert sorted(reviewed,key=int)==[str(i) for i in range(12)]


def test_resume_skips_completed_original_duplicate_and_full_strata(tmp_path):
    p=pipeline(tmp_path,6)
    p.original_meta={'0':{}}
    (tmp_path/'decisions/1.json').write_text(json.dumps({'status':'review'}))
    (tmp_path/'decisions/4.json').write_text(json.dumps({'status':'error'}))
    p.plan[3]['stratum']=1
    p.progress=lambda stage:([{'metadata':{'question_sha256':'2'}}],
                              collections.Counter({('objective',1):192}))
    reviewed=[]
    p.review=lambda row:reviewed.append(row['metadata']['id'])
    p.fill_reserve()
    assert sorted(reviewed)==['4','5']


def test_refill_rechecks_quota_and_still_drains_submitted_work(tmp_path):
    p=pipeline(tmp_path)
    p.args.workers=1
    progress_calls=0
    def progress(stage):
        nonlocal progress_calls
        progress_calls+=1
        return [],collections.Counter({('objective',0):192 if progress_calls>1 else 0})
    p.progress=progress
    reviewed=[]
    p.review=lambda row:reviewed.append(row['metadata']['id'])
    p.fill_reserve()
    assert reviewed==['0','1']
