import importlib.util, os, unittest
from unittest.mock import patch
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'inference/summary_utils.py'
spec=importlib.util.spec_from_file_location('summary_utils',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SummaryTests(unittest.TestCase):
 def test_retry_response_is_actually_parsed(self):
  calls=[]
  def retry(msgs, max_retries):calls.append(max_retries);return '```json\n{"evidence":"E","summary":"S"}\n```'
  result,success=m.parse_summary_with_retry('invalid',retry,[],max_retries=2)
  self.assertTrue(success);self.assertEqual(result['evidence'],'E');self.assertEqual(calls,[2])
 def test_both_invalid_fail(self):
  result,success=m.parse_summary_with_retry('bad',lambda *a,**k:'also bad',[],max_retries=1)
  self.assertFalse(success);self.assertIsNone(result)
 def test_configurable_content_limit(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(m.visit_max_content_tokens(),95000)
  with patch.dict(os.environ,{'VISIT_MAX_CONTENT_TOKENS':'8192'}):self.assertEqual(m.visit_max_content_tokens(),8192)
  with patch.dict(os.environ,{'VISIT_MAX_CONTENT_TOKENS':'0'}):
   with self.assertRaises(ValueError):m.visit_max_content_tokens()
 def test_initial_valid_does_not_retry(self):
  def fail(*args,**kwargs):raise AssertionError('unexpected retry')
  self.assertEqual(m.parse_summary_with_retry('{"summary":"ok"}',fail,[],max_retries=1),({'summary':'ok'},True))
if __name__=='__main__':unittest.main()
