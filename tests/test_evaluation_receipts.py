import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'evaluation'))
from score_receipts import classify


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_browsecomp_requires_valid_judge(tmp_path):
    path = tmp_path / 'results' / 'run_1_eval.json'
    put(path, {'is_completed': True, 'judge_result': {'parse_error': True, 'correct': False}})
    assert classify('browsecomp_plus', tmp_path)['status'] == 'needs_audit'
    put(path, {'is_completed': True, 'judge_result': {'parse_error': False, 'correct': False}})
    result = classify('browsecomp_plus', tmp_path)
    assert result['status'] == 'scored' and result['is_correct'] is False


def test_mind2web_browser_failure_overrides_zero(tmp_path):
    put(tmp_path/'results/a/b/answer_1/results/out.json', {'final_score': 0.0, 'eval_breakdown': [{}]})
    log = tmp_path/'results/a/b/answer_1/logs/out.log'
    log.parent.mkdir(parents=True)
    log.write_text('BrowserType.launch: Target page has been closed')
    assert classify('mind2web2', tmp_path)['status'] == 'failed'
    log.write_text('verification completed')
    assert classify('mind2web2', tmp_path)['score'] == 0.0


def test_widesearch_official_format_zero_is_recorded(tmp_path):
    put(tmp_path/'result.json', {'score': 0.0, 'msg': 'response_df is None'})
    result = classify('widesearch', tmp_path)
    assert result['status'] == 'scored'
    assert 'official_zero_unparseable_response' in result['limitations']


def test_drb_requires_valid_race_not_just_exit_code(tmp_path):
    path = tmp_path/'results/race/run/raw_results.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'error': 'judge failed'})+'\n')
    assert classify('drbench', tmp_path)['status'] == 'failed'
    path.write_text(json.dumps({'overall_score': 0.42})+'\n')
    result = classify('drbench', tmp_path)
    assert result['score'] == 0.42
    assert 'fact_not_evaluated' in result['limitations']


def test_reconcile_preserves_finished_and_marks_dead_observer(tmp_path):
    from reconcile_run import reconcile
    root=tmp_path/'run'
    status=root/'bench/status.json'
    put(status, {'cases': {'row0000': {'agent_state':'terminal', 'result_path':'saved.jsonl'}, 'row0001': {'agent_state':'running', 'agent_pid':99999999}}})
    put(root/'bench/checks/row0000-score-receipt.json', {'status':'scored', 'score':0.5})
    report=reconcile(root, tmp_path/'backup')
    data=json.loads(status.read_text())
    assert data['cases']['row0000']['result_path']=='saved.jsonl'
    assert data['cases']['row0001']['agent_state']=='interrupted'
    assert report['benchmarks']['bench']['interrupted']==1
    assert json.loads((root/'scoring-status.json').read_text())['bench/row0000']['state']=='scored'
    assert json.loads((tmp_path/'backup/bench/status.json').read_text())['cases']['row0001']['agent_state']=='running'


def test_summary_keeps_failed_judgments_out_of_wrong_count():
    from result_summary import summarize
    rows=[{'file':'a','question':'q1','is_correct':True}, {'file':'a','question':'q2','is_correct':None}, {'file':'b','question':'q1','is_correct':False}, {'file':'b','question':'q2','is_correct':True}]
    result=summarize(rows,['a','b'])
    assert result['best_at_k']['best@1']['unscored']==1
    assert result['best_at_k']['best@1']['accuracy'] is None
    assert result['best_at_k']['best@2']['accuracy']==1.0
    assert result['by_file']['a']['accuracy'] is None


def test_liveresearch_missing_depth_never_fabricates_total(tmp_path):
    incremental=tmp_path/'results/run/incremental'
    for criterion, result in [('presentation', {'summary': {'average_pass_rate':80}, 'evaluations': {'x':{}}}), ('coverage', {'summary': {'percentage_addressed':70}, 'evaluations': {'x':{}}}), ('consistency', {'score':90}), ('citation', {'score':60})]:
        p=incremental/f'{criterion}_results.jsonl'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({f'{criterion}_grading_results':result})+'\n')
    result=classify('liveresearchbench',tmp_path)
    assert result['status']=='needs_audit'
    assert result['dimensions']['coverage']==70
    assert 'missing_depth' in result['limitations']
    assert 'score' not in result


def test_hle_and_browsecomp_unparseable_judge_is_unscored(monkeypatch):
    from hle import judge as hle
    from browsecomp import eval as browse
    monkeypatch.setattr(hle, 'call_litellm_for_judgment', lambda *args: 'unparseable response')
    data={'question':'q', 'messages':[{'role':'assistant','content':'<answer>x</answer>'}]}
    result=hle.process_single_question(data, 1, 'iter1.jsonl', {'q':{'id':'1','answer':'y'}}, False)
    assert result['is_correct'] is None
    monkeypatch.setattr(browse, 'call_litellm_for_judgment', lambda *args: 'unparseable response')
    result=browse.process_single_question({'question':'q','prediction':'x'},1,'iter1.jsonl',{'q':'y'},False)
    assert result['is_correct'] is None


def test_browsecomp_plus_incomplete_response_is_not_wrong(tmp_path):
    path = tmp_path / 'results' / 'run_1_eval.json'
    put(path, {'is_completed': False, 'judge_result': {'parse_error': True, 'correct': False}})
    result=classify('browsecomp_plus',tmp_path)
    assert result['status']=='no_answer' and 'is_correct' not in result


def test_missing_completion_cannot_authorize_browsecomp_score(tmp_path):
    put(tmp_path/'results/run_1_eval.json', {'judge_result': {'parse_error': False, 'correct': True}})
    assert classify('browsecomp_plus', tmp_path)['status'] == 'needs_audit'


def test_boolean_and_malformed_scores_are_not_valid(tmp_path):
    put(tmp_path/'result.json', {'score': True})
    assert classify('widesearch', tmp_path)['status'] == 'needs_audit'
    race = tmp_path/'results/race/run/raw_results.jsonl'
    race.parent.mkdir(parents=True)
    race.write_text('true\n')
    assert classify('drbench', tmp_path)['status'] == 'failed'
    race.write_text('{"overall_score": true}\n')
    assert classify('drbench', tmp_path)['status'] == 'needs_audit'
