"""Start 27B instances with the virtualenv tools and a non-FlashInfer sampler."""
import os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2];w=root/'workspace';run=w/'strict-reproduction/browsecomp-27b-rerank64-16-128-20261029-r1';v=w/'env/bin/vllm'
env=os.environ.copy();env['CUDA_HOME']=str(w/'env/lib/python3.12/site-packages/nvidia/cu13');env['PATH']=env['CUDA_HOME']+'/bin:'+str(w/'env/bin')+':'+env.get('PATH','');env['TOKENIZERS_PARALLELISM']='false';env['VLLM_USE_FLASHINFER_SAMPLER']='0'
env['OMP_NUM_THREADS']='1';env['MKL_NUM_THREADS']='1'
for gpu in range(4):
 e=env.copy();e['CUDA_VISIBLE_DEVICES']=str(gpu)
 args=[str(x) for x in [v,'serve',w/'models/Qwen3.8-27B-NVFP4','--served-model-name','QWEN38-27B-NVFP4','--host','127.0.0.1','--port',18300+gpu,'--language-model-only','--enable-auto-tool-choice','--tool-call-parser','qwen3_coder','--reasoning-parser','qwen3','--tool-strict-level','parameter','--tensor-parallel-size',1,'--dtype','bfloat16','--max-model-len',65536,'--max-num-seqs',8,'--attention-backend','TRITON_ATTN','--gpu-memory-utilization',0.94,'--disable-custom-all-reduce']]
 with (run/'server-logs'/f'gpu{gpu}-sampler-fix.log').open('a') as f:p=subprocess.Popen(args,env=e,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=root)
 print('GPU',gpu,'PID',p.pid,flush=True)
