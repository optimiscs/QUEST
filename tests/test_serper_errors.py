import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
from tool_search import Search

class Response:
 def __init__(self,status,body=b'{}'):self.status=status;self.body=body
 def read(self):return self.body
class Conn:
 def __init__(self,response):self.response=response
 def request(self,*a,**k):pass
 def getresponse(self):return self.response

def test_rate_limit_is_not_reported_as_no_results():
 with patch('tool_search.http.client.HTTPSConnection',return_value=Conn(Response(429))):
  s=Search.__new__(Search).google_search_with_serp('test')
 assert '429' in s and 'rate limited' in s and not s.startswith('No results')

def test_unavailable_http_error_is_explicit():
 with patch('tool_search.http.client.HTTPSConnection',return_value=Conn(Response(503,b'not-json'))):
  s=Search.__new__(Search).google_search_with_serp('test')
 assert '503' in s and s.startswith('[Search Error]')

def test_transient_error_is_not_cached():
 class Cache:
  def __init__(self):self.writes=[]
  def get(self,query):return None
  def set(self,query,result):self.writes.append((query,result))
 tool=Search.__new__(Search);tool.cache=Cache()
 tool.google_search_with_serp=lambda query:'[Search Error] Search service temporarily rate limited (HTTP 429); retry later.'
 assert tool.search_with_serp('test').startswith('[Search Error]')
 assert not tool.cache.writes
