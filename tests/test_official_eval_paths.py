import ast, importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class EvalPathTests(unittest.TestCase):
 def test_source_override_still_checks_revision_and_dirty_state(self):
  from unittest.mock import patch
  file=ROOT/'evaluation/official_dataset/run.py';spec=importlib.util.spec_from_file_location('quest_runner_config',file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  source=Path('/tmp/custom-author-sources')
  with patch.object(mod.subprocess,'check_output',side_effect=[mod.PINS['hle'][1]+'\n','']) as check:
   result,revision=mod.verify_source('hle',source)
   self.assertEqual(result,source/'hle');self.assertEqual(revision,mod.PINS['hle'][1]);self.assertEqual(check.call_args_list[0].args[0][2],str(source/'hle'))
  with patch.object(mod.subprocess,'check_output',side_effect=['incorrect\n','']):
   with self.assertRaises(RuntimeError):mod.verify_source('hle',source)
  with patch.object(mod.subprocess,'check_output',side_effect=[mod.PINS['hle'][1]+'\n',' M scorer.py\n']):
   with self.assertRaises(RuntimeError):mod.verify_source('hle',source)
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
