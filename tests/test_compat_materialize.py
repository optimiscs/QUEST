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
    with self.assertRaises(FileExistsError):m.materialize('fake',src,out)
    (src/'file.txt').write_text('dirty\n')
    with self.assertRaises(ValueError):m.materialize('fake',src,root/'dirty')
if __name__=='__main__':unittest.main()
