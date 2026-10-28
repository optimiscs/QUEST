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



MANIFEST = 'QUEST_COMPAT_MANIFEST.json'


def inventory(root):
    """Hash file bytes and record symlink targets without following links."""
    entries = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        directory = Path(directory)
        for name in sorted(dirs + files):
            path = directory / name
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            if path.is_symlink():
                entries[relative] = {'symlink': os.readlink(path)}
            elif path.is_file():
                entries[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            elif not path.is_dir():
                raise ValueError('unsupported file type: '+relative)
    return entries


def verify_materialized(name, output):
    """Detect changes relative to the saved manifest; no network or evaluation."""
    output = output.resolve(strict=True)
    manifest_path = output / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('missing or unsafe compatibility manifest')
    manifest = json.loads(manifest_path.read_text())
    patch_digest = hashlib.sha256((PATCHES/(name+'-compat.patch')).read_bytes()).hexdigest()
    if (manifest.get('upstream') != name or manifest.get('revision') != PINS[name]
            or manifest.get('patch_sha256') != patch_digest
            or manifest.get('source_modified') is not False or manifest.get('compat_copy') is not True):
        raise ValueError('manifest does not match pinned source and patch')
    recorded = manifest.get('files')
    if not isinstance(recorded, dict):
        raise ValueError('legacy manifest lacks file inventory; recreate compatibility copy')
    actual = inventory(output)
    if actual != recorded:
        differences = sorted(k for k in actual.keys() | recorded.keys() if actual.get(k) != recorded.get(k))
        raise ValueError('compatibility copy changed: '+', '.join(differences[:20]))
    return {'output':str(output),'upstream':name,'revision':PINS[name],
            'patch_sha256':patch_digest,'files_verified':len(actual)}


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
        (scratch/MANIFEST).write_text(json.dumps({'upstream':name,'revision':revision,'patch_sha256':digest,'source_modified':False,'compat_copy':True,'files':inventory(scratch)},indent=2,sort_keys=True)+'\n')
        os.rename(scratch,output)
    except BaseException:
        shutil.rmtree(scratch,ignore_errors=True)
        raise
    return {'output':str(output),'upstream':name,'revision':revision,'patch_sha256':digest}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark',choices=PINS)
    parser.add_argument('--source',type=Path,help='Clean checkout at pinned upstream commit')
    parser.add_argument('--verify-only',action='store_true',help='Verify a previously materialized copy without running it')
    parser.add_argument('--output',type=Path,required=True,help='Fresh output directory')
    args=parser.parse_args()
    if args.verify_only:
        if args.source:parser.error('--source is not used with --verify-only')
        result=verify_materialized(args.benchmark,args.output)
    else:
        if not args.source:parser.error('--source is required unless --verify-only is set')
        result=materialize(args.benchmark,args.source,args.output)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
