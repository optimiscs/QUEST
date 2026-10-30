import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
from tool_memory import Memory

def make_memory(responses):
 m=Memory.__new__(Memory);m.token_threshold=None;m.tokenizer=None;m.count_tokens=lambda _:100
 seen=[]
 def call(msgs):seen.append(msgs);return next(responses)
 m.call_api_with_litellm=call
 return m,seen

def test_invalid_json_retries_once_without_silent_repair(monkeypatch):
 monkeypatch.setenv('MEMORY_RETRY_INVALID_JSON','true');m,seen=make_memory(iter(['{"version":"dr_state"','{"version":"dr_state"}']))
 assert m.call({'events':[]})=='{"version":"dr_state"}'
 assert len(seen)==2 and 'invalid JSON' in seen[-1][-1]['content']

def test_invalid_retry_preserves_original_and_valid_never_retries(monkeypatch):
 monkeypatch.setenv('MEMORY_RETRY_INVALID_JSON','true');m,seen=make_memory(iter(['{bad','[1,2]']))
 assert m.call({'events':[]})=='{bad' and len(seen)==2
 m,seen=make_memory(iter(['{"version":"dr_state"}']))
 assert m.call({'events':[]})=='{"version":"dr_state"}' and len(seen)==1
