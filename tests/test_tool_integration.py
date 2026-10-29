import os, sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'inference'))
os.environ.setdefault('VISIT_CACHE_ENABLED','false')
os.environ.setdefault('CACHE_DIR','/tmp/quest-test-import')
import tool_visit, tool_memory

class ToolIntegrationTests(unittest.TestCase):
 def test_experiment_flash_summary_requests_no_thinking(self):
  calls=[]
  class FakeOpenAI:
   def __init__(self,**kwargs):self.chat=SimpleNamespace(completions=self)
   def create(self,**kwargs):
    calls.append(kwargs)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"evidence":"e","summary":"s"}'))])
  with patch.dict(os.environ,{'VISIT_EXPERIMENT_METHOD':'bm25','VISIT_EXPERIMENT_DELIVERY':'summary','VISIT_LOCAL_PROMPT_ENABLED':'false','SUMMARY_MODEL_NAME':'deepseek-flash'}),patch.object(tool_visit,'OpenAI',FakeOpenAI):
   tool_visit.Visit.__new__(tool_visit.Visit).call_server([{'role':'user','content':'q'}],max_retries=1)
  self.assertEqual(calls[0]['extra_body'],{'thinking':{'type':'disabled'}})
 def test_experiment_direct_bypasses_summary_and_old_cache(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit)
  visit.cache=SimpleNamespace(get_useful_information=lambda *a: (_ for _ in ()).throw(AssertionError('stale summary used')), get_content_by_url=lambda *a:None)
  visit.html_readpage_jina=lambda url:'Fresh evidence for the goal.'
  visit.call_server=lambda *a,**k: (_ for _ in ()).throw(AssertionError('summary should not run'))
  with patch.dict(os.environ,{'VISIT_EXPERIMENT_METHOD':'bm25','VISIT_EXPERIMENT_DELIVERY':'direct'}):
   result=visit.call({'url':'https://example.com','goal':'evidence'})
  self.assertIn('Fresh evidence',result)
 def test_experiment_accepts_list_goal(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit);visit.cache=None
  visit.html_readpage_jina=lambda url:'Fresh evidence.'
  with patch.dict(os.environ,{'VISIT_EXPERIMENT_METHOD':'bm25','VISIT_EXPERIMENT_DELIVERY':'direct'}):
   result=visit.call({'url':['https://example.com'],'goal':['find evidence']})
  self.assertIn('find evidence',result);self.assertIn('Fresh evidence',result)
 def test_experiment_summary_uses_selected_content(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit); visit.cache=None
  visit.html_readpage_jina=lambda url:'The original page'
  seen=[]
  visit.call_server=lambda messages,**kwargs: (seen.append(messages) or '{"evidence":"found","summary":"result"}')
  with patch.dict(os.environ,{'VISIT_EXPERIMENT_METHOD':'bm25','VISIT_EXPERIMENT_DELIVERY':'summary'}), patch('retrieval_experiment.select',return_value=('selected text',{'reason':'selected'})):
   result=visit.readpage_jina('https://example.com','goal')
  self.assertIn('found',result)
  self.assertIn('selected text',str(seen)); self.assertNotIn('The original page',str(seen))
 def test_visit_and_memory_use_independent_aliases(self):
  calls=[]
  class FakeOpenAI:
   def __init__(self, **kwargs):self.chat=SimpleNamespace(completions=self)
   def create(self, **kwargs):
    calls.append(kwargs)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"evidence":"e","summary":"s"}'))])
  env={'VISIT_LOCAL_PROMPT_ENABLED':'true','MEMORY_LOCAL_PROMPT_ENABLED':'true','VISIT_LOCAL_MODEL_NAME':'QWEN38-SUMMARY','MEMORY_LOCAL_MODEL_NAME':'QWEN38-MEMORY','LOCAL_PROMPT_MODEL_NAME':'legacy'}
  with patch.dict(os.environ,env),patch.object(tool_visit,'OpenAI',FakeOpenAI),patch.object(tool_memory,'OpenAI',FakeOpenAI):
   tool_visit.Visit.__new__(tool_visit.Visit).call_server([{'role':'user','content':'q'}])
   tool_memory.Memory.__new__(tool_memory.Memory).call_api_with_litellm([{'role':'user','content':'q'}])
  self.assertEqual([c['model'] for c in calls],['QWEN38-SUMMARY','QWEN38-MEMORY'])
 def test_cached_visit_accepts_valid_json_after_retry(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit);cached=[]
  visit.cache=SimpleNamespace(set=lambda *args:cached.append(args))
  responses=iter(['invalid-json-response','{"evidence":"original evidence","summary":"short summary"}'])
  visit.call_server=lambda *args,**kwargs:next(responses)
  with patch.object(tool_visit,'truncate_to_tokens',lambda text,**kwargs:text):
   result=visit._process_content_to_summary('https://example.test','goal','page content')
  self.assertIn('original evidence',result);self.assertIn('short summary',result);self.assertEqual(len(cached),1)
 def test_empty_model_response_returns_failure_without_cache(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit);cached=[]
  visit.cache=SimpleNamespace(set=lambda *args:cached.append(args))
  visit.html_readpage_jina=lambda url:'page content'
  visit.call_server=lambda *args,**kwargs:None
  with patch.object(tool_visit,'truncate_to_tokens',lambda text,**kwargs:text):
   result=visit.readpage_jina('https://example.test','goal')
  self.assertIn('could not be processed',result);self.assertEqual(cached,[])
 def test_uncached_visit_retries_and_rejects_invalid_output(self):
  visit=tool_visit.Visit.__new__(tool_visit.Visit);cached=[]
  visit.cache=SimpleNamespace(set=lambda *args:cached.append(args))
  visit.html_readpage_jina=lambda url:'page content'
  responses=iter(['first invalid output','second invalid output'])
  visit.call_server=lambda *args,**kwargs:next(responses)
  with patch.object(tool_visit,'truncate_to_tokens',lambda text,**kwargs:text):
   result=visit.readpage_jina('https://example.test','goal')
  self.assertIn('could not be processed',result);self.assertEqual(cached,[])
if __name__=='__main__':unittest.main()
