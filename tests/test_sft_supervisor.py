import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from safetensors.numpy import save_file
ROOT=Path(__file__).resolve().parents[1];FILE=ROOT/'training_scripts/sft/supervise_qlora.py';spec=importlib.util.spec_from_file_location('supervise_qlora',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SupervisorTests(unittest.TestCase):
 def make_checkpoint(self,root,step,ranks=4,max_steps=100):
  p=root/f'checkpoint-{step}';p.mkdir(parents=True)
  for n in ['adapter_model.safetensors','adapter_config.json','optimizer.pt','scheduler.pt',*[f'rng_state_{i}.pth' for i in range(ranks)]]:(p/n).write_text('x')
  save_file({'lora':np.array([1.0],dtype=np.float32)},str(p/'adapter_model.safetensors'))
  (p/'adapter_config.json').write_text('{}')
  torch.save({'state':{},'param_groups':[{'params':[0]}]},p/'optimizer.pt')
  torch.save({'last_epoch':step},p/'scheduler.pt')
  for i in range(ranks):
   torch.save({'python':(3,(),None),'numpy':('MT19937',np.array([1],dtype=np.uint32),0,0,0.0),
               'cpu':torch.zeros(2,dtype=torch.uint8),'cuda':[torch.zeros(2,dtype=torch.uint8)]},p/f'rng_state_{i}.pth')
  (p/'trainer_state.json').write_text(json.dumps({'global_step':step,'max_steps':max_steps}));return p
 def test_checkpoint_integrity_and_completion(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);self.assertIsNone(m.latest_checkpoint(root,4));c=self.make_checkpoint(root,50)
   self.assertEqual(m.latest_checkpoint(root,4),c)
   (c/'rng_state_2.pth').unlink()
   with self.assertRaisesRegex(ValueError,'Incomplete'):m.latest_checkpoint(root,4)
   torch.save({'python':(3,(),None),'numpy':('MT19937',np.array([1],dtype=np.uint32),0,0,0.0),'cpu':torch.zeros(2,dtype=torch.uint8),'cuda':[torch.zeros(2,dtype=torch.uint8)]},c/'rng_state_2.pth');(c/'trainer_state.json').write_text('{"global_step": 49, "max_steps":100}')
   with self.assertRaisesRegex(ValueError,'disagree'):m.latest_checkpoint(root,4)
   (c/'trainer_state.json').write_text('{"global_step": 50, "max_steps":50}')
   with self.assertRaisesRegex(ValueError,'max_steps'):m.latest_checkpoint(root,4)
 def test_nonempty_corrupt_optimizer_and_rng_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);c=self.make_checkpoint(root,50)
   optimizer=(c/'optimizer.pt').read_bytes()
   (c/'optimizer.pt').write_bytes(b'not-empty-but-invalid')
   with self.assertRaisesRegex(ValueError,'safely loaded'):m.latest_checkpoint(root,4)
   (c/'optimizer.pt').write_bytes(optimizer)
   (c/'rng_state_1.pth').write_bytes(b'not-empty-but-invalid')
   with self.assertRaisesRegex(ValueError,'safely loaded'):m.latest_checkpoint(root,4)
 def test_optimizer_state_must_reference_known_parameters(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);c=self.make_checkpoint(root,50)
   torch.save({'state':{2:{}},'param_groups':[{'params':[0]}]},c/'optimizer.pt')
   with self.assertRaisesRegex(ValueError,'disagree'):m.latest_checkpoint(root,4)
   torch.save({'state':{},'param_groups':[{'params':[0,0]}]},c/'optimizer.pt')
   with self.assertRaisesRegex(ValueError,'disagree'):m.latest_checkpoint(root,4)
 def test_same_output_cannot_be_locked_twice(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);output=root/'output'
   with m.output_lock(output):
    with self.assertRaises(BlockingIOError):
     with m.output_lock(output):pass
    with m.output_lock(root/'other-output'):pass
   with m.output_lock(output):pass
 def test_child_retains_output_lock_if_launcher_exits(self):
  with tempfile.TemporaryDirectory() as d:
   output=Path(d)/'output'
   with m.output_lock(output) as (_,fd):
    child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE,pass_fds=(fd,))
   try:
    with self.assertRaises(BlockingIOError):
     with m.output_lock(output):pass
   finally:
    child.stdin.close();child.wait(timeout=10)
   with m.output_lock(output):pass
 def test_pause_prevents_launch(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);env=root/'env';(env/'bin').mkdir(parents=True);source=root/'source';source.mkdir();state=root/'state';state.mkdir();(state/'PAUSE').touch()
   sentinel=root/'launched';torchrun=env/'bin/torchrun';torchrun.write_text('#!/bin/sh\ntouch "'+str(sentinel)+'"\n');torchrun.chmod(0o755)
   cfg=root/'train.yaml';cfg.write_text('output_dir: '+str(root/'output')+'\n')
   cmd=[sys.executable,str(FILE),'--config',str(cfg),'--state-dir',str(state),'--env-dir',str(env),'--llamafactory',str(source),'--resource-tb',str(root/'tb')]
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertIn('PAUSE/STOP',r.stderr);self.assertFalse(sentinel.exists())
if __name__=='__main__':unittest.main()
