import importlib.util, os, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('quest_prompt_test',ROOT/'inference/prompt.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class LocalRoleTests(unittest.TestCase):
 def test_role_overrides_and_legacy_fallback(self):
  with patch.dict(os.environ,{'VISIT_LOCAL_MODEL_NAME':'summary','MEMORY_LOCAL_MODEL_NAME':'memory','LOCAL_PROMPT_MODEL_NAME':'legacy'},clear=True):
   self.assertEqual(p.get_local_served_model_name(role='visit'),'summary')
   self.assertEqual(p.get_local_served_model_name(role='memory'),'memory')
   self.assertEqual(p.get_local_served_model_name(),'legacy')
  with patch.dict(os.environ,{'LOCAL_PROMPT_MODEL_NAME':'legacy'},clear=True):
   self.assertEqual(p.get_local_served_model_name(role='visit'),'legacy')
   self.assertEqual(p.get_local_served_model_name(role='memory'),'legacy')
if __name__=='__main__':unittest.main()
