"""Read-only instrumentation around official LlamaFactory run_exp."""
import gzip, hashlib, json, os, time, traceback
from pathlib import Path
import torch, yaml
from transformers import TrainerCallback
from torch.utils.tensorboard import SummaryWriter
from llamafactory.train.tuner import run_exp

A = Path(os.environ['QUEST_ATTEMPT_DIR'])
C = Path(os.environ['QUEST_CONFIG'])
rank = int(os.environ['RANK'])
start = time.monotonic()
status = {'rank': rank, 'complete': False, 'global_step': 0}
events = (A / f'events-rank{rank}.jsonl').open('a', buffering=1)
trace = gzip.open(A / f'forwards-rank{rank}.jsonl.gz', 'at', compresslevel=1)
hooks = []
resource = SummaryWriter(str(Path(os.environ['QUEST_RESOURCE_TB']) / f'rank{rank}'))

def record(event, **values):
    d = dict(event=event, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), elapsed_s=round(time.monotonic()-start, 3), **values)
    if torch.cuda.is_initialized():
        d.update(allocated_MiB=torch.cuda.memory_allocated()/1048576, reserved_MiB=torch.cuda.memory_reserved()/1048576, peak_allocated_MiB=torch.cuda.max_memory_allocated()/1048576, peak_reserved_MiB=torch.cuda.max_memory_reserved()/1048576)
    events.write(json.dumps(d, default=str)+'\n')
    status.update(d)
    p = A / f'status-rank{rank}.json'
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(status, indent=2, default=str))
    tmp.replace(p)

class Observe(TrainerCallback):
    def on_train_begin(self, args, state, control, model=None, **kwargs):
        self.state = state
        self.step_start = time.monotonic()
        status.update(max_steps=state.max_steps, output_dir=args.output_dir)
        def pre(m, a, kw):
            self.forward_start=time.monotonic()
            ids=kw['input_ids'].detach().cpu().contiguous()
            labels=kw['labels'].detach().cpu().contiguous()
            flag=kw.get('skip_logits')
            self.pending=dict(mode='train' if m.training else 'eval', global_step=state.global_step,
                tensor_tokens=ids.shape[-1], input_tokens=int(kw['attention_mask'].sum().item()),
                loss_tokens=int((labels != -100).sum().item()),
                input_sha256=hashlib.sha256(ids.numpy().tobytes()).hexdigest(),
                labels_sha256=hashlib.sha256(labels.numpy().tobytes()).hexdigest(),
                skip_logits=None if flag is None else bool(flag.item() if hasattr(flag, 'item') else flag))
        def post(m, a, kw, out):
            d=dict(self.pending, loss=float(out.loss.detach()), forward_seconds=time.monotonic()-self.forward_start,
                logits_materialized=out.logits is not None, loss_requires_grad=out.loss.requires_grad)
            trace.write(json.dumps(d)+'\n'); trace.flush()
        hooks.extend([model.register_forward_pre_hook(pre,with_kwargs=True),model.register_forward_hook(post,with_kwargs=True)])
        record('train_begin', global_step=state.global_step, max_steps=state.max_steps, world_size=args.world_size)
    def on_step_begin(self,args,state,control,**kw):
        self.step_start=time.monotonic()
        record('step_begin',global_step=state.global_step, next_step=state.global_step+1)
    def on_step_end(self,args,state,control,**kw):
        record('step_end',global_step=state.global_step,epoch=state.epoch,step_seconds=time.monotonic()-self.step_start)
        for tag, val in [('allocated_MiB',torch.cuda.memory_allocated()/1048576),('peak_allocated_MiB',torch.cuda.max_memory_allocated()/1048576),('peak_reserved_MiB',torch.cuda.max_memory_reserved()/1048576)]:
            resource.add_scalar('resources/'+tag,val,state.global_step)
        resource.flush()
    def on_log(self,args,state,control,logs=None,**kw):
        record('metrics',global_step=state.global_step,epoch=state.epoch,metrics=logs)
    def on_evaluate(self,args,state,control,metrics=None,**kw):
        record('eval_end',global_step=state.global_step,metrics=metrics)
    def on_save(self,args,state,control,**kw):
        ck=Path(args.output_dir)/f'checkpoint-{state.global_step}'
        (ck/f'observer-rank{rank}-saved.json').write_text(json.dumps({'step':state.global_step,'rank':rank,'utc':time.time()}))
        record('checkpoint_saved',global_step=state.global_step,path=str(ck))
    def on_train_end(self,args,state,control,**kw):
        record('train_end',global_step=state.global_step)

try:
    config = yaml.safe_load(C.read_text())
    if os.environ.get('QUEST_RESUME_CHECKPOINT'):
        config['resume_from_checkpoint'] = os.environ['QUEST_RESUME_CHECKPOINT']
    run_exp(config,callbacks=[Observe()])
    status['complete']=True
    record('run_success')
except BaseException as e:
    record('run_error',error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc())
    raise
finally:
    for h in hooks: h.remove()
    trace.close(); resource.close(); events.close()
