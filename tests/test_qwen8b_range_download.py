import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

path=Path(__file__).resolve().parents[1]/'inference/scripts/download_qwen8b_ranges.py'
spec=importlib.util.spec_from_file_location('range_download',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_ranges_are_checked_and_verified_before_publication(tmp_path,monkeypatch):
    payload=b'abcdefghijklmno'; model='test-model'; name='model.safetensors'
    (tmp_path/'models'/model).mkdir(parents=True);work=tmp_path/'partials';work.mkdir()
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'WORK',work);monkeypatch.setattr(module,'CHUNK',4)
    def get(url,headers,timeout):
        start,end=map(int,headers['Range'].removeprefix('bytes=').split('-'))
        return SimpleNamespace(status_code=206,headers={'Content-Range':f'bytes {start}-{end}/{len(payload)}'},content=payload[start:end+1])
    monkeypatch.setattr(module.requests,'get',get)
    entry=SimpleNamespace(rfilename=name,size=len(payload),lfs=SimpleNamespace(sha256=hashlib.sha256(payload).hexdigest()))
    module.transfer(model,entry)
    assert (tmp_path/'models'/model/name).read_bytes()==payload
    assert not list(work.iterdir())


def test_live_hf_prefix_is_copied_then_whole_shard_verified(tmp_path,monkeypatch):
    payload=b'abcdefghijklmno';model='test-model';name='model.safetensors';sha=hashlib.sha256(payload).hexdigest()
    cache=tmp_path/'models'/model/'.cache/huggingface/download';cache.mkdir(parents=True)
    (cache/f'prefix.{sha}.x.incomplete').write_bytes(payload[:9])
    work=tmp_path/'partials';work.mkdir()
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'WORK',work);monkeypatch.setattr(module,'CHUNK',4);monkeypatch.setenv('QWEN_RANGE_SEED_HF','1')
    requests=[]
    def get(url,headers,timeout):
        start,end=map(int,headers['Range'].removeprefix('bytes=').split('-'));requests.append(start)
        return SimpleNamespace(status_code=206,headers={'Content-Range':f'bytes {start}-{end}/{len(payload)}'},content=payload[start:end+1])
    monkeypatch.setattr(module.requests,'get',get)
    entry=SimpleNamespace(rfilename=name,size=len(payload),lfs=SimpleNamespace(sha256=sha))
    module.transfer(model,entry)
    assert (tmp_path/'models'/model/name).read_bytes()==payload
    assert sorted(requests)==[8,12]
