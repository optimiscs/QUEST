import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training_scripts/sft'))
from optimization_quality import evidence_bundle, validate_review, validate_rubric


def fixtures():
    rubric = {'requirements': [{'id': 'R1', 'text': 'Identify name', 'type': 'fact', 'question_quote': 'name'}],
              'citations_required': False}
    bundle = {'targets': [{'step': 2}, {'step': 4}], 'rule_issues': [],
              'evidence': [{'unit': 'E3', 'step': 3, 'source_ids': ['S1'], 'text': 'The name is Ada.'}]}
    review = {'verdict': 'pass', 'reviewed_assistant_steps': [2, 4], 'issues': [],
              'requirements': [{'id': 'R1', 'status': 'pass', 'evidence': [{'unit': 'E3', 'quote': 'name is Ada'}]}]}
    return rubric, bundle, review


def test_review_requires_real_quotes_and_complete_coverage():
    r,b,v=fixtures();assert validate_review(v,r,b)=='pass'
    broken=copy.deepcopy(v);broken['requirements'][0]['evidence'][0]['quote']='name is Alice'
    with pytest.raises(ValueError,match='inexact'):validate_review(broken,r,b)
    broken=copy.deepcopy(v);broken['reviewed_assistant_steps']=[4]
    with pytest.raises(ValueError,match='all_reviewed'):validate_review(broken,r,b)
    broken=copy.deepcopy(v);broken['requirements']=[]
    with pytest.raises(ValueError,match='coverage'):validate_review(broken,r,b)


def test_future_evidence_and_unanchored_rubric_are_rejected():
    r,b,v=fixtures();v['verdict']='reject';v['issues']=[{'step':2,'reason':'bad claim','evidence':[{'unit':'E3','quote':'Ada'}]}]
    with pytest.raises(ValueError,match='future'):validate_review(v,r,b)
    validate_rubric(r,'What is the name?')
    with pytest.raises(ValueError,match='anchored'):validate_rubric(r,'Which city?')


def test_mentioning_an_id_does_not_make_whole_search_result_its_evidence():
    record={'metadata':{'question':'Q','has_memory':False},'messages':[
        {'role':'system','content':'S'}, {'role':'user','content':'Q'},
        {'role':'assistant','tool_calls':[{'id':'t','function':{'name':'search','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'t','content':'Title: Page\nLink: S1\nSnipptes: mentions S9'},
        {'role':'assistant','content':'{"answer":"Fact [S9]"}'}]}
    bundle=evidence_bundle(record)
    assert bundle['evidence'][0]['source_ids']==['S1']
    assert bundle['rule_issues'][0]['ids']==['S9']
