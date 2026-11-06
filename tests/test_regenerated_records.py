import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training_scripts/sft'))
from regenerate_optimization import record_from_events
from tokenize_summary_sessions import policy_views


def make_run(tmp_path, final_source='S1'):
    case='generated';source=tmp_path/'traces'/case/case/'iter1';source.mkdir(parents=True)
    (source/'sources.json').write_text(json.dumps({'S1':'https://evidence.test'}))
    (source/'source-provenance.json').write_text(json.dumps({'S1':{'origins':['search_result']}}))
    schemas=[{'type':'function','function':{'name':'search','parameters':{'type':'object','properties':{'query':{'type':'array','items':{'type':'string'}}},'required':['query']}}}]
    initial=[{'role':'system','content':'Use source IDs such as S123.'},{'role':'user','content':'What number?'}]
    call={'id':'t','type':'function','function':{'name':'search','arguments':'{"query":["number"]}'}}
    answer='42 ['+final_source+']'
    events=[{'event':'span_end','span_id':'p1','kind':'policy_model','api_request_context':{'messages':initial,'tools':schemas},
             'api_request_options':{'tool_choice':'auto'},'api_response':{'choices':[{'finish_reason':'tool_calls',
              'message':{'content':None,'reasoning':'Search for the number.','tool_calls':[call]}}]}},
            {'event':'span_end','kind':'tool','output':'Title: Source\nLink: S1\nSnipptes: The number is 42.'},
            {'event':'span_end','span_id':'p2','kind':'policy_model','api_request_context':{'messages':[
                initial[0],{'role':'user','content':'Question and compressed state: verified number 42 [S1]'},
                {'role':'user','content':'Research is complete. Return JSON.'}],'tools':schemas},
             'api_request_options':{'tool_choice':'none'},'api_response':{'choices':[{'finish_reason':'stop',
              'message':{'content':json.dumps({'answer':answer})}}]}}]
    (tmp_path/'logs').mkdir();(tmp_path/'logs'/f'{case}-agent-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    result=tmp_path/'results'/case/'model'/'iter1.jsonl';result.parent.mkdir(parents=True)
    result.write_text(json.dumps({'prediction':answer})+'\n')
    return {'case':case,'question':'What number?','question_sha256':'q','kind':'openended','stratum':1},schemas


def test_generated_record_uses_actual_prompt_after_memory(tmp_path):
    meta,schemas=make_run(tmp_path);row=record_from_events(tmp_path,meta,schemas)
    views=list(policy_views(row))
    assert len(views)==2 and views[0][1][1]['content']=='What number?'
    assert 'compressed state' in views[1][1][1]['content']
    assert 'compressed state' not in row['messages'][1]['content']


def test_generated_record_rejects_unseen_final_source(tmp_path):
    meta,schemas=make_run(tmp_path,'S99')
    with pytest.raises(ValueError,match='unknown_source'):record_from_events(tmp_path,meta,schemas)
