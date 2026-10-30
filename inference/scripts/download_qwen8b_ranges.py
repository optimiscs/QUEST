"""Supplement live HF downloads with verified resumable HTTP range transfers.

Uses separate partial files and publishes a shard only after its SHA-256
matches Hugging Face's LFS metadata. Existing snapshots are never overwritten.
"""
import concurrent.futures
import hashlib
import json
import os
import glob
from pathlib import Path
import threading
import time

from huggingface_hub import HfApi
import requests

ROOT=Path(__file__).resolve().parents[2]/'workspace'
MODELS=('Qwen3-Embedding-8B','Qwen3-Reranker-8B')
WORK=ROOT/'strict-reproduction/gaia-retrieval-ab-20261029-r1'/os.environ.get('QWEN_RANGE_WORK','range-downloads')
CHUNK=8*1024*1024
WORKERS=max(1,min(12,int(os.environ.get('QWEN_RANGE_WORKERS','12'))))
WORK.mkdir(parents=True,exist_ok=True)


def transfer(model,entry):
    name=entry.rfilename;target=ROOT/'models'/model/name
    if target.exists():
        print('already available',model,name,flush=True);return
    part=WORK/(model+'-'+name+'.part');state=part.with_suffix('.json')
    size=entry.size;sha=entry.lfs.sha256
    count=(size+CHUNK-1)//CHUNK
    if state.exists():
        data=json.loads(state.read_text())
        if data.get('sha256')!=sha or data.get('chunk')!=CHUNK:raise RuntimeError('partial manifest mismatch')
        done=set(data['done'])
    else: done=set()
    fd=os.open(part,os.O_CREAT|os.O_RDWR,0o600);os.ftruncate(fd,size)
    lock=threading.Lock();url=f'https://www.modelscope.cn/models/Qwen/{model}/resolve/master/{name}'
    # A live HF snapshot stores a contiguous prefix in its own incomplete
    # file. Copy complete chunks into our independent staging file. The final
    # full-shard SHA-256 remains mandatory before publication.
    if os.environ.get('QWEN_RANGE_SEED_HF') == '1' and not done:
        pattern=str(ROOT/'models'/model/'.cache/huggingface/download'/f'*.{sha}.*.incomplete')
        candidates=glob.glob(pattern)
        if len(candidates)==1:
            source=candidates[0]
            prefix=min(os.path.getsize(source)//CHUNK,count)
            with open(source,'rb') as handle:
                for index in range(prefix):
                    data=handle.read(CHUNK)
                    if len(data)!=CHUNK:break
                    written=0
                    while written<len(data):
                        n=os.pwrite(fd,data[written:],index*CHUNK+written)
                        if n<=0:raise OSError('seed write failed')
                        written+=n
                    done.add(index)
            if done:
                tmp=state.with_suffix('.tmp');tmp.write_text(json.dumps({'sha256':sha,'chunk':CHUNK,'done':sorted(done)}));tmp.replace(state)
                print('seeded HF prefix',model,name,len(done),'/',count,flush=True)
    def fetch(i):
        if target.exists():return
        start=i*CHUNK;end=min(size,start+CHUNK)-1
        for attempt in range(8):
            try:
                response=requests.get(url,headers={'Range':f'bytes={start}-{end}'},timeout=(20,90))
                expected=f'bytes {start}-{end}/{size}'
                if response.status_code!=206 or response.headers.get('Content-Range')!=expected or len(response.content)!=end-start+1:
                    raise ValueError('invalid range response')
                written=0
                while written<len(response.content):
                    n=os.pwrite(fd,response.content[written:],start+written)
                    if n<=0:raise OSError('range write failed')
                    written+=n
                with lock:
                    done.add(i)
                    tmp=state.with_suffix('.tmp');tmp.write_text(json.dumps({'sha256':sha,'chunk':CHUNK,'done':sorted(done)}));tmp.replace(state)
                    if len(done)%50==0:print('progress',model,name,len(done),'/',count,flush=True)
                return
            except (requests.RequestException,ValueError) as exc:
                if attempt==7:raise RuntimeError(f'{model}/{name} range {i} failed: {type(exc).__name__}') from exc
                time.sleep(min(2**attempt,20))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(fetch,(i for i in range(count) if i not in done)))
    finally:os.close(fd)
    if target.exists():print('original download won',model,name,flush=True);return
    if len(done)!=count:raise RuntimeError('incomplete range download')
    digest=hashlib.sha256()
    with part.open('rb') as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=sha:raise RuntimeError('SHA-256 mismatch')
    try:os.link(part,target)
    except FileExistsError:pass
    part.unlink();state.unlink(missing_ok=True)
    print('verified shard',model,name,flush=True)


if __name__=='__main__':
    selected=os.environ.get('QWEN_RANGE_MODEL')
    if selected and selected not in MODELS:raise ValueError('unsupported model')
    selected_file=os.environ.get('QWEN_RANGE_FILE')
    for model in ([selected] if selected else MODELS):
        info=HfApi().model_info('Qwen/'+model,files_metadata=True,timeout=60)
        for file in sorted(info.siblings,key=lambda x:x.rfilename):
            if file.rfilename.endswith('.safetensors') and file.lfs and (not selected_file or file.rfilename==selected_file):
                transfer(model,file)
