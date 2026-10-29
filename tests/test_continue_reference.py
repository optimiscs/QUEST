import importlib.util, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('continue_reference',ROOT/'contrib/deepseek_data/continue_reference.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ContinuationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
  self.source=self.p/'sessions.jsonl';self.trace=self.p/'trace.json';self.output=self.p/'reference.jsonl'
  self.source.write_text(json.dumps({'is_final':True,'question':'Question','messages':[{'role':'user','content':'Question'}]})+'\n')
 def tearDown(self):self.tmp.cleanup()
 def client(self,finish='stop',text='a'*120):
  def create(**kw):
   return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text),finish_reason=finish)],usage=None)
  return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
 def test_valid_is_private_provisional_and_cannot_overwrite(self):
  m.run(self.source,self.trace,self.output,self.client())
  ref=json.loads(self.output.read_text());self.assertEqual(ref['reference_kind'],'provisional_continuation')
  self.assertEqual(json.loads(self.trace.read_text())['status'],'completed_provisional')
  self.assertEqual(self.trace.stat().st_mode&0o777,0o600);self.assertEqual(self.output.stat().st_mode&0o777,0o600)
  with self.assertRaises(FileExistsError):m.run(self.source,self.trace,self.output,self.client())
 def test_truncation_retains_trace_but_exports_nothing(self):
  with self.assertRaises(ValueError):m.run(self.source,self.trace,self.output,self.client(finish='length'))
  self.assertFalse(self.output.exists());self.assertEqual(json.loads(self.trace.read_text())['status'],'invalid_response')
 def test_unfinished_session_never_calls_model(self):
  self.source.write_text(json.dumps({'is_final':False})+'\n')
  with self.assertRaises(ValueError):m.run(self.source,self.trace,self.output,self.client())
  self.assertFalse(self.trace.exists())
if __name__=='__main__':unittest.main()
