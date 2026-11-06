"""Compare local training prompts with the live server's token IDs."""
import json
from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'training_scripts/sft'))
from inference import native_tools
from clean_harness_trajectories import dump, sha
from tokenize_summary_sessions import policy_views


def main():
    from transformers import AutoTokenizer
    run = Path(sys.argv[1]).resolve()
    tokenizer = AutoTokenizer.from_pretrained(str(ROOT/'workspace/models/Qwen3.8-27B-NVFP4'), local_files_only=True)
    samples = []
    for source, dest in [('sft1024-summary-native.jsonl','sft1024-summary-native-v2.jsonl'),
                         ('sample16-aligned.jsonl','sample16-aligned-v2.jsonl')]:
        with (run/dest).open('x') as stream:
            for line in (run/source).open():
                row = json.loads(line)
                row['messages'] = native_tools.prepare_messages(row['messages'])
                row['metadata']['converted_sha256'] = sha(row['messages'])
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                if source.startswith('sample16'): samples.append(row)
    checks = []
    for row in samples:
        for i,messages,final,view_tools in policy_views(row):
            payload = {'model':'qwen38-27b','messages':native_tools.prepare_messages(messages[:-1]),
                       'tools':view_tools,'add_generation_prompt':True,'add_special_tokens':False,
                       'chat_template_kwargs':{'enable_thinking':not final}}
            response = requests.post('http://127.0.0.1:19300/tokenize',json=payload,timeout=60)
            response.raise_for_status()
            remote = response.json()['tokens']
            text = tokenizer.apply_chat_template(native_tools.prepare_messages(messages[:-1],for_template=True),
                tools=view_tools,enable_thinking=not final,tokenize=False,add_generation_prompt=True)
            local = tokenizer.encode(text,add_special_tokens=False)
            checks.append({'case':row['metadata']['case'],'assistant_index':i,'final':final,
                           'tokens':len(local),'equal':local==remote,'local_sha256':sha(local),'server_sha256':sha(remote)})
    dump(run/'parity-report.json',{'checked_prompts':len(checks),'all_equal':all(x['equal'] for x in checks),'checks':checks})
    print(json.dumps({'checked_prompts':len(checks),'equal':sum(x['equal'] for x in checks)}),flush=True)
    if not all(x['equal'] for x in checks): raise RuntimeError('Server/training token mismatch')


if __name__ == '__main__':main()
