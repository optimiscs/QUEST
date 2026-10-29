import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
os.environ.setdefault('VISIT_CACHE_ENABLED','false')
from tool_memory import Memory


def test_batched_memory_preserves_order_and_all_unicode_event_content(monkeypatch):
 tool=object.__new__(Memory);tool.tokenizer=object();tool.token_threshold=600
 tool.count_tokens=len;tool._extract_json_from_response=lambda raw:json.loads(raw) if not raw.startswith('[Memory]') else None
 observed=[]
 def summarize(messages):
  text=messages[0]['content'];section=text.split('events:\n',1)[1].split('\n\nprev_state:',1)[0];events=json.loads(section)
  observed.extend(events);return '{"version":"dr_state","information_state":{}}'
 tool.call_api_with_litellm=summarize
 monkeypatch.setenv('MEMORY_INPUT_TOKEN_BUDGET','600')
 events=[{'role':'assistant','content':'证据α\\"[]{}'*180},{'role':'assistant','content':'second source'}]
 before=json.dumps(events,ensure_ascii=False)
 result=tool.call({'events':events,'prev_state':None})
 assert json.loads(result)['version']=='dr_state'
 assert ''.join(event['content'] for event in observed)==''.join(event['content'] for event in events)
 assert json.dumps(events,ensure_ascii=False)==before
 assert len(observed)>len(events)


def test_failed_batch_never_returns_partial_state_or_changes_original(monkeypatch):
 tool=object.__new__(Memory);tool.tokenizer=object();tool.token_threshold=None;tool.count_tokens=len
 tool._extract_json_from_response=lambda raw:None
 tool.call_api_with_litellm=lambda messages:'invalid JSON'
 monkeypatch.setenv('MEMORY_INPUT_TOKEN_BUDGET','500');monkeypatch.delenv('MEMORY_RETRY_INVALID_JSON',raising=False)
 original=[{'role':'assistant','content':'source '*300}]
 result=tool.call({'events':original,'prev_state':None})
 assert result.startswith('[Memory] Bounded batch 1 failed')
 assert original==[{'role':'assistant','content':'source '*300}]


def test_budget_too_small_fails_without_calling_model(monkeypatch):
 tool=object.__new__(Memory);tool.tokenizer=object();tool.token_threshold=None;tool.count_tokens=len
 def unexpected(_messages):
  raise AssertionError('model must not be called when even one character cannot fit')
 tool.call_api_with_litellm=unexpected
 monkeypatch.setenv('MEMORY_INPUT_TOKEN_BUDGET','1')
 result=tool.call({'events':[{'role':'assistant','content':'abc'}],'prev_state':None})
 assert 'Input budget cannot fit' in result
