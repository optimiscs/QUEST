import importlib.util, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('compat_materialize',ROOT/'evaluation/official_dataset/compat/materialize.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class CompatTests(unittest.TestCase):
 def test_pinned_clean_source_patch_and_no_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);src=root/'src';src.mkdir();patches=root/'patches';patches.mkdir();out=root/'result'
   def git(*args):return subprocess.run(['git','-C',str(src),*args],check=True,capture_output=True,text=True).stdout
   git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Test')
   (src/'file.txt').write_text('original\n');git('add','file.txt');git('commit','-qm','initial');commit=git('rev-parse','HEAD').strip()
   (src/'file.txt').write_text('changed\n');(patches/'fake-compat.patch').write_text(git('diff'));git('checkout','--','file.txt')
   with patch.object(m,'PINS',{'fake':commit}),patch.object(m,'PATCHES',patches):
    result=m.materialize('fake',src,out)
    self.assertEqual((out/'file.txt').read_text(),'changed\n');self.assertEqual((src/'file.txt').read_text(),'original\n')
    self.assertFalse((out/'.git').exists());self.assertTrue(result['patch_sha256'])
    self.assertEqual(m.verify_materialized('fake',out)['files_verified'],1)
    self.assertIn('independently',m.verify_against_source('fake',src,out)['verification'])
    import hashlib, json
    (out/'file.txt').write_text('forged\n')
    manifest=out/m.MANIFEST
    forged=json.loads(manifest.read_text())
    forged['files']['file.txt']['sha256']=hashlib.sha256((out/'file.txt').read_bytes()).hexdigest()
    manifest.write_text(json.dumps(forged))
    self.assertEqual(m.verify_materialized('fake',out)['files_verified'],1)
    with self.assertRaises(ValueError):m.verify_against_source('fake',src,out)
    (out/'file.txt').write_text('changed\n')
    forged['files']['file.txt']['sha256']=hashlib.sha256((out/'file.txt').read_bytes()).hexdigest()
    manifest.write_text(json.dumps(forged))
    (out/'file.txt').write_text('tampered\n')
    with self.assertRaises(ValueError):m.verify_materialized('fake',out)
    (out/'file.txt').write_text('changed\n')
    (out/'extra.py').write_text('extra')
    with self.assertRaises(ValueError):m.verify_materialized('fake',out)
    (out/'extra.py').unlink()
    manifest=out/m.MANIFEST
    import json
    old=json.loads(manifest.read_text());old.pop('files');manifest.write_text(json.dumps(old))
    with self.assertRaises(ValueError):m.verify_materialized('fake',out)
    with self.assertRaises(FileExistsError):m.materialize('fake',src,out)
    (src/'file.txt').write_text('dirty\n')
    with self.assertRaises(ValueError):m.materialize('fake',src,root/'dirty')
if __name__=='__main__':unittest.main()
