import importlib.util,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('retry_qlora',ROOT/'training_scripts/sft/retry_qlora.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RetryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=self.root/'state'
  self.args=SimpleNamespace(state_dir=self.state,config=self.root/'config',env_dir=self.root/'env',
    llamafactory=self.root/'source',resource_tb=self.root/'tb',world_size=4,retry_delay=0)
 def tearDown(self):self.tmp.cleanup()
 def fake_launcher(self, outcomes):
  state=self.state; calls=[]
  class FakeChild:
   def __init__(self, command, **kwargs):
    self.number=len(calls);calls.append(command);self.rc=outcomes[self.number]
   def wait(self, timeout=None):
    if self.rc=='no_receipt':return 1
    a=state/'attempts'/str(self.number);a.mkdir(parents=True)
    (a/'exit.json').write_text(json.dumps({'torchrun_pid':100,'exitcode':self.rc,'signals':[]}))
    (a/'train.log').write_text('synthetic failure log')
    if self.rc==0:(state/'success.json').write_text('{}')
    return self.rc
   def poll(self):return None
   def send_signal(self,signum):pass
   def terminate(self):pass
  return FakeChild,calls
 def test_failure_then_success(self):
  fake,calls=self.fake_launcher([1,0])
  with patch.object(m.subprocess,'Popen',fake),patch.object(m,'validate_resume',return_value=None):self.assertEqual(m.run(self.args),'stopped_or_completed')
  self.assertEqual(len(calls),2)
  self.assertEqual(len((self.state/'retry-watchdog/failures.jsonl').read_text().splitlines()),1)
 def test_stops_after_three_failures(self):
  fake,calls=self.fake_launcher([1,1,1])
  with patch.object(m.subprocess,'Popen',fake),patch.object(m,'validate_resume',return_value=None):self.assertEqual(m.run(self.args),'failure_limit')
  self.assertEqual(len(calls),3)
  fake,more=self.fake_launcher([0])
  with patch.object(m.subprocess,'Popen',fake),patch.object(m,'validate_resume',return_value=None):self.assertEqual(m.run(self.args),'failure_limit')
  self.assertEqual(more,[])
 def test_incomplete_checkpoint_stops_before_retry(self):
  fake,calls=self.fake_launcher([1,0])
  with patch.object(m.subprocess,'Popen',fake),patch.object(m,'validate_resume',side_effect=ValueError('incomplete')):
   self.assertEqual(m.run(self.args),'checkpoint_requires_inspection')
  self.assertEqual(len(calls),1)
 def test_real_checkpoint_preflight_rejects_incomplete(self):
  output=self.root/'output';(output/'checkpoint-50').mkdir(parents=True)
  self.args.config.write_text('output_dir: '+str(output)+'\n')
  with self.assertRaises(ValueError):m.validate_resume(self.args)
 def test_stop_marker_while_child_running_prevents_retry(self):
  state=self.state;calls=[]
  class RunningChild:
   def __init__(self,command,**kw):calls.append(command);self.done=False
   def wait(self,timeout=None):
    if not self.done:
     (state/'STOP').touch();raise m.subprocess.TimeoutExpired('synthetic',timeout)
    return -15
   def poll(self):return None
   def terminate(self):self.done=True
   def send_signal(self,signum):self.done=True
  with patch.object(m.subprocess,'Popen',RunningChild):
   self.assertEqual(m.run(self.args),'stopped_or_completed')
  self.assertEqual(len(calls),1)
 def test_no_receipt_never_retries(self):
  fake,calls=self.fake_launcher(['no_receipt'])
  with patch.object(m.subprocess,'Popen',fake):self.assertEqual(m.run(self.args),'no_unambiguous_attempt_receipt')
  self.assertEqual(len(calls),1)
 def test_oom_does_not_retry(self):
  attempts=self.state/'attempts';a=attempts/'run';a.mkdir(parents=True)
  (a/'exit.json').write_text(json.dumps({'torchrun_pid':100,'exitcode':1,'signals':[]}))
  (a/'train.log').write_text('torch.cuda.OutOfMemoryError: CUDA out of memory')
  self.assertEqual(m.classify(self.state,set(),1),'oom_or_nonfinite_requires_inspection')
 def test_missing_log_does_not_retry(self):
  a=self.state/'attempts'/'run';a.mkdir(parents=True)
  (a/'exit.json').write_text(json.dumps({'torchrun_pid':100,'exitcode':1,'signals':[]}))
  self.assertEqual(m.classify(self.state,set(),1),'missing_training_log')
 def test_pause_prevents_launch(self):
  self.state.mkdir();(self.state/'PAUSE').touch()
  fake,calls=self.fake_launcher([0])
  with patch.object(m.subprocess,'Popen',fake):self.assertEqual(m.run(self.args),'stopped_or_completed')
  self.assertEqual(calls,[])
 def test_corrupt_history_never_launches(self):
  d=self.state/'retry-watchdog';d.mkdir(parents=True);(d/'failures.jsonl').write_text('broken')
  fake,calls=self.fake_launcher([0])
  with patch.object(m.subprocess,'Popen',fake):
   with self.assertRaises(ValueError):m.run(self.args)
  self.assertEqual(calls,[])
if __name__=='__main__':unittest.main()
