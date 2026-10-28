#!/usr/bin/env python3
"""Create a fresh, pinned benchmark compatibility copy without editing upstream.

Only public upstream Git-tracked files are archived. No datasets, credentials,
results, or git metadata are copied. Does not run an evaluation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

PINS = {
    'simple-evals':'652c89d0ca9df547706735883097e9537d40dc47',
    'hle':'22ed3074b1e7b134bcbc09028d0ba320839b0655',
    'widesearch':'9825ba7b140b71d81b364793f86dabe4cfed6749',
    'mind2web2':'1fcbfda98bf5c669daa2ed0a27f1d2f2499475ee',
    'liveresearchbench':'ffb27c9d7a091a0b0f10cbcebc061fc3ba025b63',
}
PATCHES = Path(__file__).resolve().parent/'patches'


def git(*args, cwd=None, env=None):
    return subprocess.run(['git', *map(str,args)], cwd=cwd, env=env, text=True, capture_output=True, check=True)


def materialize(name, source, output):
    source=source.resolve(strict=True)
    output=output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('refusing to overwrite output: '+str(output))
    output.parent.mkdir(parents=True,exist_ok=True)
    revision=git('-C',source,'rev-parse','HEAD').stdout.strip()
    if revision != PINS[name]:
        raise ValueError(f'upstream revision mismatch for {name}: {revision}')
    if git('-C',source,'status','--porcelain','--untracked-files=no').stdout.strip():
        raise ValueError('tracked upstream source is modified')
    patch=PATCHES/(name+'-compat.patch')
    digest=hashlib.sha256(patch.read_bytes()).hexdigest()
    scratch=Path(tempfile.mkdtemp(prefix='.quest-compat-',dir=output.parent))
    try:
        # Streaming avoids loading the whole source archive into memory.
        proc=subprocess.Popen(['git','-C',str(source),'archive','--format=tar',revision],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
                archive.extractall(scratch,filter='data')
        except BaseException:
            proc.terminate()
            proc.stdout.close()
            proc.stderr.close()
            proc.wait()
            raise
        proc.stdout.close()
        err=proc.stderr.read()
        proc.stderr.close()
        code=proc.wait()
        if code:raise RuntimeError('git archive failed: '+err.decode(errors='replace')[-1000:])
        env=dict(os.environ,GIT_CEILING_DIRECTORIES=str(output.parent.resolve()))
        git('apply','--check',patch,cwd=scratch,env=env)
        git('apply',patch,cwd=scratch,env=env)
        (scratch/'QUEST_COMPAT_MANIFEST.json').write_text(json.dumps({'upstream':name,'revision':revision,'patch_sha256':digest,'source_modified':False,'compat_copy':True},indent=2)+'\n')
        os.rename(scratch,output)
    except BaseException:
        shutil.rmtree(scratch,ignore_errors=True)
        raise
    return {'output':str(output),'upstream':name,'revision':revision,'patch_sha256':digest}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark',choices=PINS)
    parser.add_argument('--source',type=Path,required=True,help='Clean checkout at pinned upstream commit')
    parser.add_argument('--output',type=Path,required=True,help='Fresh output directory')
    args=parser.parse_args()
    print(json.dumps(materialize(args.benchmark,args.source,args.output),indent=2))

if __name__=='__main__':main()
