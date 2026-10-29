#!/usr/bin/env python3
"""Restore a verified historical source archive without overwriting any path."""
import argparse,hashlib,json,os,tarfile,tempfile,shutil
from pathlib import Path
here=Path(__file__).resolve().parents[1]/"workspace/strict-reproduction/source-consolidation-20261028-r1"
p=argparse.ArgumentParser();p.add_argument("name",choices=["official-baseline","sft-overlay"]);p.add_argument("--destination",type=Path,help="New restore directory (required except with --verify-only)");p.add_argument("--verify-only",action="store_true");a=p.parse_args()
m=json.loads((here/"archives"/(a.name+".manifest.json")).read_text());archive=here/"archives"/(a.name+".tar.gz")
def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
 return h.hexdigest()
if sha(archive)!=m["archive_sha256"]:raise SystemExit("archive checksum mismatch")
if not a.verify_only and a.destination is None:
 raise SystemExit("--destination is required; historical paths are no longer active")
dest=a.destination
if not a.verify_only and (dest.exists() or dest.is_symlink()):raise SystemExit("destination exists; refusing to overwrite")
parent=Path(tempfile.gettempdir()) if a.verify_only else dest.parent
if not a.verify_only: parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix=".quest-restore-",dir=parent) as tmp:
 with tarfile.open(archive,"r:gz") as t:t.extractall(tmp,filter="data")
 source=Path(tmp)/Path(m["source"]).name
 files={str(q.relative_to(source)):sha(q) for q in source.rglob("*") if q.is_file() and not q.is_symlink()}
 links={str(q.relative_to(source)):os.readlink(q) for q in source.rglob("*") if q.is_symlink()}
 if files!=m["file_sha256"] or links!=m["symlinks"]:raise SystemExit("restore verification failed")
 if not a.verify_only:
  if dest.exists() or dest.is_symlink():raise SystemExit("destination appeared during verification")
  os.rename(source,dest)
 print(json.dumps({"archive":a.name,"files":len(files),"verified":True,"restored":not a.verify_only,"destination":str(dest) if dest else None}))
