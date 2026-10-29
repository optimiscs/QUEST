import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
import retrieval_model_server as server


class Batch(dict):
    def to(self, device):
        return Batch({key:value.to(device) for key,value in self.items()})


class Tokenizer:
    def encode(self,text,add_special_tokens=False):return [1,2]
    def convert_tokens_to_ids(self,token):return {'no':0,'yes':1}[token]
    def __call__(self,texts,return_tensors=None,**kwargs):
        ids=[[1,2] for _ in texts]
        if return_tensors:return Batch(input_ids=torch.tensor(ids),attention_mask=torch.ones(len(ids),2,dtype=torch.long))
        return {'input_ids':ids}
    def pad(self,inputs,**kwargs):
        ids=inputs['input_ids'];return Batch(input_ids=torch.tensor(ids),attention_mask=torch.ones(len(ids),len(ids[0]),dtype=torch.long))


class Model:
    def to(self,device):return self
    def eval(self):return self
    def __call__(self,**inputs):
        batch,seq=inputs['input_ids'].shape
        return SimpleNamespace(last_hidden_state=torch.ones(batch,seq,4),logits=torch.ones(batch,seq,3))


@pytest.mark.parametrize('role',['embedding','reranker'])
def test_scoring_service_preflights_and_serves(role,monkeypatch):
    monkeypatch.setattr(server.AutoTokenizer,'from_pretrained',lambda *a,**k:Tokenizer())
    monkeypatch.setattr(server.AutoModel,'from_pretrained',lambda *a,**k:Model())
    monkeypatch.setattr(server.AutoModelForCausalLM,'from_pretrained',lambda *a,**k:Model())
    client=TestClient(server.create_app(role,'/test',batch_size=2,device='cpu'))
    assert client.get('/health').json()['role']==role
    result=client.post('/score',json={'goal':'q','passages':['a','b','c']})
    assert result.status_code==200
    assert len(result.json()['scores'])==3


@pytest.mark.parametrize('role,batch_size,max_length', [('invalid', 1, 10), ('embedding', 0, 10), ('reranker', 1, 0)])
def test_rejects_invalid_config_before_loading_model(role, batch_size, max_length, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('model must not load for invalid configuration')
    monkeypatch.setattr(server.AutoTokenizer, 'from_pretrained', unexpected)
    with pytest.raises(ValueError):
        server.create_app(role, '/test', batch_size=batch_size, max_length=max_length, device='cpu')


def test_reranker_requires_room_for_document_tokens(monkeypatch):
    monkeypatch.setattr(server.AutoTokenizer, 'from_pretrained', lambda *a, **k: Tokenizer())
    monkeypatch.setattr(server.AutoModelForCausalLM, 'from_pretrained', lambda *a, **k: Model())
    with pytest.raises(ValueError, match='no space'):
        server.create_app('reranker', '/test', max_length=4, device='cpu')
