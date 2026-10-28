"""Strict Pydantic adapter for QUEST evaluator; raises on invalid model output."""
import os,json,asyncio,datetime
from pathlib import Path
from openai import AsyncOpenAI
class DeepSeekJudge:
 def __init__(self,key,log_path,base_url="https://api.deepseek.com/v1",model="deepseek-flash"):
  self.client=AsyncOpenAI(api_key=key,base_url=base_url,timeout=180);self.model=model;self.path=Path(log_path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=asyncio.Lock()
 async def response(self,count_token=False,**kwargs):
  fmt=kwargs.pop("response_format",None);msgs=list(kwargs.pop("messages"));kwargs.pop("model",None)
  params={"model":self.model,"messages":msgs,"extra_body":{"thinking":{"type":"disabled"}},"max_tokens":8192}
  if fmt is not None:
   schema=fmt.model_json_schema(); params["messages"]=[{"role":"system","content":"Return only a valid JSON object matching this JSON Schema: "+json.dumps(schema,ensure_ascii=False)}]+msgs;params["response_format"]={"type":"json_object"}
  try:
   r=await self.client.chat.completions.create(**params);content=r.choices[0].message.content or "";usage={"input_tokens":r.usage.prompt_tokens,"output_tokens":r.usage.completion_tokens} if r.usage else {};result=fmt.model_validate_json(content) if fmt is not None else content
   record={"status":"ok","time":datetime.datetime.now(datetime.timezone.utc).isoformat(),"messages":params["messages"],"response":content,"usage":usage,"schema":fmt.__name__ if fmt is not None else None}
  except Exception as e:
   record={"status":"error","time":datetime.datetime.now(datetime.timezone.utc).isoformat(),"messages":params["messages"],"error_type":type(e).__name__,"response":locals().get("content")};
   async with self.lock:
    with self.path.open("a") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n")
   raise
  async with self.lock:
   with self.path.open("a") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n")
  return (result,usage) if count_token else result

 async def async_response(self, count_token=False, **kwargs):
  return await self.response(count_token=count_token, **kwargs)
