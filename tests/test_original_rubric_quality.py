import copy
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training_scripts/sft'))
from original_rubric_quality import (index_tree, aggregate, validate_assessment,
                                    OriginalRubrics, prepare_payload, digest)
from optimize_summary_data import Pipeline


def node(name,children=None,critical=False,strategy='parallel'):
    return {'node_name':name,'description':name,'critical':critical,
            'critical_type':'CRITICAL' if critical else 'NON-CRITICAL',
            'aggregation_strategy':strategy if children else '', 'children':children or []}


def rubric(tree):
    return {'status':'ready','origin':'released_objective_rubric','original_tree':tree,
            'question':'Use official sources.','tree_sha256':digest(tree),**index_tree(tree)}


def fixture():
    r=rubric({'root':node('root',[node('Use official sources.',critical=True),node('Name provided')])})
    p={'question':'Use official sources.','required_node_ids':['N0','N1','N2'],
       'required_leaf_ids':['N1','N2'],'required_assistant_steps':[2,4],
       'rule_issues':[], 'evidence_blocks':[{'id':'E3:0','unit':'E3','step':3,
           'text':'Official university biography confirms Ada.','source_ids':['S1'],'start':0,'end':43}]}
    a={'reviewed_node_ids':['N0','N1','N2'],'rubric_conflicts':[],
       'leaf_checks':[{'id':'N1','status':'pass','basis':'tool_evidence','reason':'Official biography',
                      'references':['E3:0']},
                      {'id':'N2','status':'pass','basis':'answer_form','reason':'Name present','references':[]}],
       'trajectory_gate':{'verdict':'pass','reviewed_assistant_steps':[2,4],'issues':[]}}
    return r,p,a


def test_tree_is_unchanged_and_critical_failure_gates_parent():
    tree={'root':node('root',[node('critical',critical=True),node('soft')])};before=copy.deepcopy(tree)
    r=rubric(tree);out=aggregate(r,{'N1':{'status':'fail'},'N2':{'status':'pass'}})
    assert tree==before
    assert out['root_scores']=={'N0':0.0}
    assert out['nodes']['N1']['critical'] is True


def test_original_sequential_aggregation_skips_later_siblings():
    r=rubric({'root':node('root',[node('first'),node('second')],strategy='sequential')})
    result=aggregate(r,{'N1':{'status':'fail'},'N2':{'status':'pass'}})
    assert result['nodes']['N2']['status']=='skipped'
    assert result['nodes']['N2']['score']==0
    assert not result['full_credit']


def test_original_parallel_average_and_full_credit():
    r=rubric({'root':node('root',[node('first'),node('second')])})
    assert aggregate(r,{'N1':{'status':'fail'},'N2':{'status':'pass'}})['root_scores']['N0']==.5
    assert aggregate(r,{'N1':{'status':'pass'},'N2':{'status':'pass'}})['full_credit']


def test_ambiguous_original_structure_is_quarantined_not_repaired():
    tree={'root':node('root',[node('child')],strategy='')}
    with pytest.raises(ValueError,match='ambiguous_original_aggregation'):index_tree(tree)
    tree['root']['aggregation_strategy']='parallel';tree['root']['critical_type']='CRITICAL'
    with pytest.raises(ValueError,match='conflicting_original_critical'):index_tree(tree)


def test_task_and_trajectory_gates_are_separate():
    r,p,a=fixture();result=validate_assessment(a,r,p)
    assert result['status']=='pass'
    assert result['task_gate']['leaf_checks'][0]['resolved_evidence'][0]['text']==p['evidence_blocks'][0]['text']
    a['trajectory_gate']['verdict']='reject'
    a['trajectory_gate']['issues']=[{'step':4,'reason':'Unsupported extra assertion','references':[]}]
    result=validate_assessment(a,r,p)
    assert result['task_gate']['status']=='pass'
    assert result['trajectory_gate']['verdict']=='reject'
    assert result['status']=='reject'


def test_question_rubric_conflict_is_quarantined_without_dropping_node():
    r,p,a=fixture();a['rubric_conflicts']=[{'node_id':'N1','question_quote':'official sources',
                                         'rubric_quote':'official sources','reason':'fixture conflict'}]
    out=validate_assessment(a,r,p)
    assert out['status']=='quarantine' and len(out['task_gate']['leaf_checks'])==2
    a['rubric_conflicts'][0]['rubric_quote']='invented requirement'
    with pytest.raises(ValueError,match='unanchored'):validate_assessment(a,r,p)


@pytest.mark.parametrize('mutation,error',[
    (lambda a:a['reviewed_node_ids'].pop(),'original_node_coverage'),
    (lambda a:a['leaf_checks'].pop(),'original_leaf_coverage'),
    (lambda a:a['leaf_checks'][0].update(references=['E999']),'invalid_evidence_block'),
    (lambda a:a['leaf_checks'][0].update(references=[]),'pass_without_tool_evidence'),
    (lambda a:a['trajectory_gate'].update(reviewed_assistant_steps=[4]),'assistant_steps'),
])
def test_incomplete_or_fabricated_reviews_cannot_pass(mutation,error):
    r,p,a=fixture();mutation(a)
    with pytest.raises(ValueError,match=error):validate_assessment(a,r,p)


def test_future_evidence_is_invalid_for_intermediate_assertions():
    r,p,a=fixture();a['trajectory_gate'].update(verdict='reject',issues=[
        {'step':2,'reason':'Claim before observation','references':['E3:0']}])
    with pytest.raises(ValueError,match='future_evidence'):validate_assessment(a,r,p)


def test_missing_original_rubric_never_calls_llm(tmp_path):
    (tmp_path/'original-rubric-index.json').write_text(json.dumps({'questions':{}}))
    for name in ('rubrics','decisions'):(tmp_path/name).mkdir()
    p=Pipeline.__new__(Pipeline);p.out=tmp_path;p.contract_sha='new-original-contract'
    p.original_rubrics=OriginalRubrics(tmp_path);p.locks={'q':threading.Lock()}
    def forbidden(*args,**kwargs):raise AssertionError('Must not synthesize missing rubric')
    p.call=forbidden
    out=p.review({'metadata':{'id':'id','question_sha256':'q','kind':'openended','stratum':0}})
    assert out['status']=='quarantine' and out['reason']=='original_rubric_not_found'


def test_old_contract_decision_cannot_be_reused(tmp_path):
    (tmp_path/'decisions').mkdir();(tmp_path/'decisions/id.json').write_text(json.dumps({'status':'pass','contract':'old'}))
    p=Pipeline.__new__(Pipeline);p.out=tmp_path;p.contract_sha='new'
    with pytest.raises(RuntimeError,match='different review contract'):
        p.review({'metadata':{'id':'id'}})


def test_original_rubric_snapshot_mutation_cannot_go_unnoticed(tmp_path):
    original={'status':'ready','original_tree':{'unchanged':'value'}}
    (tmp_path/'tree.json').write_text(json.dumps(original))
    (tmp_path/'original-rubric-index.json').write_text(json.dumps({'questions':{
        'q':{'kind':'objective','file':'tree.json','record_sha256':digest(original)}}}))
    store=OriginalRubrics(tmp_path)
    assert store.lookup({'kind':'objective','question_sha256':'q'})==original
    (tmp_path/'tree.json').write_text(json.dumps({'status':'ready','original_tree':{}}))
    with pytest.raises(ValueError,match='snapshot_hash_mismatch'):
        store.lookup({'kind':'objective','question_sha256':'q'})


def test_evidence_blocks_retain_exact_text_and_offsets():
    r,p,a=fixture();text='x'*1100
    bundle={'question':'Q','evidence':[{'unit':'E3','text':text,'step':3,'source_ids':['S1']}],
            'targets':[],'required_assistant_steps':[],'sources':{},'unverified_inherited_memory':'','rule_issues':[]}
    result=prepare_payload({},r,bundle)
    assert ''.join(b['text'] for b in result['evidence_blocks'])==text
    for b in result['evidence_blocks']:assert b['text']==text[b['start']:b['end']]
