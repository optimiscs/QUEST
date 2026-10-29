import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
os.environ.setdefault('VISIT_CACHE_ENABLED','false')
import requests
import tool_visit


def reader(monkeypatch,bounded=True):
 monkeypatch.setattr(tool_visit,'JINA_API_KEYS','unit-test-placeholder')
 monkeypatch.setenv('VISIT_READER_BOUNDED_RETRIES','true' if bounded else 'false')
 return tool_visit.Visit.__new__(tool_visit.Visit)


def test_permanent_failure_is_returned_after_one_request(monkeypatch):
 visit=reader(monkeypatch);calls=[]
 def get(*args,**kwargs):calls.append(kwargs);return SimpleNamespace(status_code=404,text='{"message":"page not found"}')
 monkeypatch.setattr(tool_visit.requests,'get',get)
 assert visit.html_readpage_jina('https://example.test/missing')=='[visit] Error (HTTP 404): page not found'
 assert len(calls)==1


def test_transient_failure_still_recovers_with_original_page_text(monkeypatch):
 visit=reader(monkeypatch);responses=iter([SimpleNamespace(status_code=503,text='temporary outage'),SimpleNamespace(status_code=200,text='unaltered evidence')]);calls=[]
 def get(*args,**kwargs):calls.append(kwargs);return next(responses)
 monkeypatch.setattr(tool_visit.requests,'get',get)
 assert visit.html_readpage_jina('https://example.test/page')=='unaltered evidence'
 assert len(calls)==2


def test_timeouts_and_reader_422_have_one_shared_three_attempt_budget(monkeypatch):
 visit=reader(monkeypatch)
 for timeout in [True,False]:
  calls=[]
  def get(*args,**kwargs):
   calls.append(kwargs)
   if timeout:raise requests.exceptions.Timeout('test')
   return SimpleNamespace(status_code=422,text='{"message":"upstream page navigation timeout"}')
  monkeypatch.setattr(tool_visit.requests,'get',get)
  assert visit.html_readpage_jina('https://example.test/slow').startswith('[visit] Error')
  assert len(calls)==3


def test_bounded_mode_is_opt_in_and_does_not_multiply_retries(monkeypatch):
 visit=reader(monkeypatch,False);calls=[]
 def get(*args,**kwargs):calls.append(kwargs);return SimpleNamespace(status_code=404,text='missing')
 monkeypatch.setattr(tool_visit.requests,'get',get)
 assert 'HTTP 404' in visit.html_readpage_jina('https://example.test/missing')
 assert len(calls)==3


def test_transient_errors_use_exponential_full_jitter(monkeypatch):
 visit=reader(monkeypatch);calls=[];delays=[];responses=iter([503,503,200])
 monkeypatch.setattr(tool_visit.requests,'get',lambda *a,**k: (calls.append(1) or SimpleNamespace(status_code=next(responses),text='page')))
 monkeypatch.setattr(tool_visit.random,'uniform',lambda low,high: (delays.append((low,high)) or high))
 monkeypatch.setattr(tool_visit.time,'sleep',lambda delay:None)
 assert visit.html_readpage_jina('https://example.test/')=='page'
 assert delays==[(0.0,0.5),(0.0,1.0)] and len(calls)==3
