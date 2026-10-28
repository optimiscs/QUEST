import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from safetensors.numpy import save_file
ROOT=Path(__file__).resolve().parents[1];FILE=ROOT/'training_scripts/sft/supervise_qlora.py';spec=importlib.util.spec_from_file_location('supervise_qlora',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SupervisorTests(unittest.TestCase):
 def make_checkpoint(self,root,step,ranks=4,max_steps=100):
  p=root/f'checkpoint-{step}';p.mkdir(parents=True)
  for n in ['adapter_model.safetensors','adapter_config.json','optimizer.pt','scheduler.pt',*[f'rng_state_{i}.pth' for i in range(ranks)]]:(p/n).write_text('x')
  save_file({'lora':np.array([1.0],dtype=np.float32)},str(p/'adapter_model.safetensors'))
  (p/'adapter_config.json').write_text('{}')
  (p/'trainer_state.json').write_text(json.dumps({'global_step':step,'max_steps':max_steps}));return p
 def test_checkpoint_integrity_and_completion(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);self.assertIsNone(m.latest_checkpoint(root,4));c=self.make_checkpoint(root,50)
   self.assertEqual(m.latest_checkpoint(root,4),c)
   (c/'rng_state_2.pth').unlink()
   with self.assertRaisesRegex(ValueError,'Incomplete'):m.latest_checkpoint(root,4)
   (c/'rng_state_2.pth').write_text('x');(c/'trainer_state.json').write_text('{"global_step": 49, "max_steps":100}')
   with self.assertRaisesRegex(ValueError,'disagree'):m.latest_checkpoint(root,4)
   (c/'trainer_state.json').write_text('{"global_step": 50, "max_steps":50}')
   with self.assertRaisesRegex(ValueError,'max_steps'):m.latest_checkpoint(root,4)
 def test_pause_prevents_launch(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);env=root/'env';(env/'bin').mkdir(parents=True);source=root/'source';source.mkdir();state=root/'state';state.mkdir();(state/'PAUSE').touch()
   sentinel=root/'launched';torchrun=env/'bin/torchrun';torchrun.write_text('#!/bin/sh\ntouch "'+str(sentinel)+'"\n');torchrun.chmod(0o755)
   cfg=root/'train.yaml';cfg.write_text('output_dir: '+str(root/'output')+'\n')
   cmd=[sys.executable,str(FILE),'--config',str(cfg),'--state-dir',str(state),'--env-dir',str(env),'--llamafactory',str(source),'--resource-tb',str(root/'tb')]
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertIn('PAUSE/STOP',r.stderr);self.assertFalse(sentinel.exists())
if __name__=='__main__':unittest.main()
