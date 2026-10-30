import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'evaluation'))
from browsecomp_plus.quest_adapter import build_run, evidence_metrics
from browsecomp_plus.scripts_evaluation.evaluate_with_openai import extract_citations_from_response, compute_citation_metrics, create_judge_prompt


def event_file(tmp_path, complete=True):
    events=[{'event':'process_start'},
            {'event':'span_start','kind':'tool','span_id':'1','input':{'tool_name':'search'}},
            {'event':'span_end','kind':'tool','span_id':'1','output':'Title: Document 12\nLink: bm25://12\nScore: 1\n\nTitle: Document 42\nLink: bm25://42\nScore: 0.9'},
            {'event':'span_start','kind':'tool','span_id':'2','input':{'tool_name':'visit'}},
            {'event':'span_end','kind':'tool','span_id':'2','output':'Link: bm25://99'}]
    if complete:events.append({'event':'process_done'})
    path=tmp_path/'events.jsonl';path.write_text(''.join(json.dumps(x)+'\n' for x in events));return path


def test_complete_trace_matches_official_evidence(tmp_path):
    pred={'filename':'775','prediction':'Answer [12] [44]', 'num_rounds':99}
    run=build_run(pred,event_file(tmp_path));assert run['retrieved_docids']==['12','42']
    assert run['tool_call_counts']['search']==1
    result=evidence_metrics(run,{'775':['12','13']},extract_citations_from_response,compute_citation_metrics)
    assert result['retrieval_recall']==0.5
    assert result['citation_metrics']['precision']==0.5
    assert result['citation_metrics']['recall']==0.5


def test_partial_trace_never_claims_full_recall(tmp_path):
    run=build_run({'filename':'775','prediction':'answer'},event_file(tmp_path,False))
    result=evidence_metrics(run,{'775':['12','13']},extract_citations_from_response,compute_citation_metrics)
    assert result['retrieval_recall'] is None and result['observed_recall_lower_bound']==0.5


def test_legacy_context_is_marked_partial_and_ignores_prompt(tmp_path):
    pred={'filename':'775','prediction':'answer','messages':[{'role':'system','content':'Link: bm25://99'}, {'role':'user','content':'<tool_response>\nLink: bm25://12\n</tool_response>'}]}
    run=build_run(pred,None)
    assert run['retrieved_docids']==['12'] and not run['retrieval_trace']['complete']
    assert run['tool_call_counts']=={}


def test_missing_qrels_and_missing_answer_are_unscored(tmp_path):
    run=build_run({'filename':'775','prediction':'answer not found.'},event_file(tmp_path))
    assert run['status']=='incomplete'
    out=evidence_metrics(run,{},extract_citations_from_response,compute_citation_metrics)
    assert out['reason']=='missing_query_evidence' and out['retrieval_recall'] is None
    out=evidence_metrics(run,{'775':['12']},extract_citations_from_response,compute_citation_metrics)
    assert out['citation_metrics'] is None


def test_judge_uses_official_prompt():
    prompt=create_judge_prompt('question','answer','gold')
    assert '[response]: answer' in prompt and '[correct_answer]: gold' in prompt
    assert 'extracted_final_answer:' in prompt and 'Verdict: A' not in prompt


def test_calibration_includes_final_bin():
    from browsecomp_plus.scripts_evaluation.evaluate_with_openai import calculate_calibration_error
    assert calculate_calibration_error([100.0]*100,[False]*100)==100.0


def test_judge_failure_is_retained_as_unscored(tmp_path, monkeypatch):
    from browsecomp_plus.scripts_evaluation import evaluate_with_openai as evaluator
    input_dir=tmp_path/'input';input_dir.mkdir()
    (input_dir/'run_775.json').write_text(json.dumps({'query_id':'775','status':'completed','retrieved_docids':['12'],'retrieval_trace':{'complete':True},'result':[{'type':'output_text','output':'answer [12]'}]}))
    gold=tmp_path/'gold.jsonl';gold.write_text(json.dumps({'query_id':'775','query':'q','answer':'a'})+'\n')
    qrel=tmp_path/'qrel.txt';qrel.write_text('775 Q0 12 1\n')
    class Responses:
        def create(self, **kwargs):raise RuntimeError('judge unavailable')
    class Client:
        def __init__(self,**kwargs):self.responses=Responses()
    monkeypatch.setattr(evaluator.openai,'OpenAI',Client)
    monkeypatch.delenv('AZURE_OPENAI_ENDPOINT',raising=False)
    monkeypatch.setenv('OPENAI_API_KEY','dummy')
    monkeypatch.setattr(sys,'argv',['eval','--input_dir',str(input_dir),'--ground_truth',str(gold),'--eval_dir',str(tmp_path/'out'),'--qrel_evidence',str(qrel)])
    evaluator.main()
    summary=json.loads(next((tmp_path/'out').rglob('evaluation_summary.json')).read_text())
    detail=json.loads(next((tmp_path/'out').rglob('run_775_eval.json')).read_text())
    assert summary['Accuracy (%)'] is None and summary['Unscored']==1
    assert summary['Calibration Error (%)'] is None
    assert detail['judge_result']['correct'] is None and detail['retrieval']['recall']==1.0
