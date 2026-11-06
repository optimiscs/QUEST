import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training_scripts/sft'))
from inherit_upstream_data import verify_conversion,select_rows
from inference.source_ids import SourceRegistry
from select_summary1024 import FINAL_PROMPT


def fixture(tmp_path):
    registry=SourceRegistry(tmp_path)
    registry.compact('https://example.test/bio',origin='search_result')
    original=[{'role':'system','content':'old system'}, {'role':'user','content':'Who?'},
              {'role':'assistant','content':'','tool_calls':[{'id':'c1','type':'function','function':{
                  'name':'search','arguments':'{"query":["name"]}'}}]},
              {'role':'tool','tool_call_id':'c1','content':'1. [Bio](https://example.test/bio)\nAda.'},
              {'role':'assistant','content':'{"answer": "Ada (https://example.test/bio)"}'}]
    messages=copy.deepcopy(original)
    messages[0]['content']='current harness system'
    messages[3]['content']='Title: Bio\nLink: S1\nSnipptes:\nAda.'
    messages[4]['content']='{"answer": "Ada (S1)"}'
    messages.insert(-1,{'role':'user','content':FINAL_PROMPT})
    return original,{'messages':messages,'metadata':{'source_map':str(registry.path)}}


def test_upstream_acceptance_can_survive_representation_only_changes(tmp_path):
    old,new=fixture(tmp_path)
    assert verify_conversion(old,new)['status']=='pass'


def test_literal_bill_number_in_evidence_is_not_an_unseen_source(tmp_path):
    old,new=fixture(tmp_path)
    old[3]['content'] += '\nBill S3386; course S241.'
    new['messages'][3]['content'] += '\nBill S3386; course S241.'
    assert verify_conversion(old,new)['status']=='pass'
    new['messages'][-1]['content']='{"answer":"Ada (S999)"}'
    with pytest.raises(ValueError): verify_conversion(old,new)


@pytest.mark.parametrize('index,content',[(1,'Different question'),(3,'Title: Bio\nLink: S1\nSnipptes:\nAlice.'),
                                       (-1,'{"answer": "Alice (S1)"}')])
def test_substantive_edits_cannot_inherit_acceptance(tmp_path,index,content):
    old,new=fixture(tmp_path);new['messages'][index]['content']=content
    with pytest.raises(ValueError,match='substantive_message_change'):verify_conversion(old,new)


def test_flexible_mix_requires_explicit_selection_flag_and_deduplicates():
    rows=[]
    for kind,n in [('objective',1024),('openended',80)]:
        for i in range(n):rows.append({'metadata':{'id':kind+str(i),'question_sha256':kind+str(i),
                                                  'kind':kind,'stratum':i%4}})
    rows.append(copy.deepcopy(rows[0]))
    strict,_=select_rows(rows,set())
    flexible,_=select_rows(rows,set(),flexible=True)
    assert len(strict)==848
    assert len(flexible)==1024
    assert len({r['metadata']['question_sha256'] for r in flexible})==1024
    assert sum(r['metadata']['kind']=='openended' for r in flexible)==80
