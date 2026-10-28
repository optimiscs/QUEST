import ast, importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class EvalPathTests(unittest.TestCase):
 def test_live_path_uses_repo_adapter(self):
  file=ROOT/'evaluation/official_dataset/run.py';spec=importlib.util.spec_from_file_location('quest_official_runner',file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  self.assertEqual(mod.key_rotation_dir(),ROOT/'inference/key_rotation')
  self.assertTrue((mod.key_rotation_dir()/'sitecustomize.py').is_file())
  tree=ast.parse(file.read_text()); fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
  assignments=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='key_rotation' for t in n.targets)]
  self.assertEqual(len(assignments),1)
  self.assertIsInstance(assignments[0].value,ast.Call)
  self.assertEqual(assignments[0].value.func.id,'key_rotation_dir')
if __name__=='__main__':unittest.main()
