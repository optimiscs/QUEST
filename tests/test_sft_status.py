import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('status_qlora',ROOT/'training_scripts/sft/status_qlora.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class StatusTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.state=self.root/'state';self.output=self.root/'output'
  self.attempt=self.state/'attempts'/'attempt-a';self.attempt.mkdir(parents=True);self.output.mkdir()
  (self.state/'checks').mkdir();(self.state/'checks/latest-launch.json').write_text(json.dumps({'attempt':'attempt-a'}))
 def tearDown(self):self.tmp.cleanup()
 def test_progress_peaks_and_conditional_eta(self):
  (self.attempt/'status-rank0.json').write_text(json.dumps({'global_step':3,'max_steps':10,'complete':False}))
  (self.attempt/'gpu-memory.csv').write_text('timestamp, index, memory.used\nt, 0, 100 MiB\nt, 0, 120 MiB\nt, 1, 70 MiB\n')
  events=[{'event':'step_end','global_step':i,'elapsed_s':i*10} for i in (1,2,3)]
  (self.attempt/'events-rank0.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
  for step in (50,5,10):(self.output/f'checkpoint-{step}').mkdir()
  result=m.summarize(self.state,self.output)
  self.assertEqual(result['checkpoints'],[5,10,50]);self.assertEqual(result['gpu_sampled_peak_mib'],{0:120.0,1:70.0})
  self.assertEqual(result['eta']['remaining_seconds_estimate'],70)
  self.assertIn('not live process verification',result['limitations'][2])
 def test_nonfinite_remains_visible_in_valid_json(self):
  (self.attempt/'status-rank0.json').write_text('{"global_step":3,"metrics":{"loss":NaN}}')
  result=m.summarize(self.state,self.output)
  self.assertEqual(result['reported_status']['metrics']['loss'],'nan')
  self.assertIn('$.reported_status.metrics.loss',result['nonfinite_fields'])
  json.dumps(result,allow_nan=False)
 def test_attempt_path_escape_is_rejected(self):
  with self.assertRaises(ValueError):m.resolve_attempt(self.state,'../outside')
 def test_missing_files_remain_unknown(self):
  result=m.summarize(self.state,self.output)
  self.assertIsNone(result['reported_status']);self.assertIsNone(result['exit_receipt'])
  self.assertIsNone(result['eta']);self.assertEqual(result['gpu_sampled_peak_mib'],{})
if __name__=='__main__':unittest.main()
