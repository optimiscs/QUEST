import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1]/'inference/scripts/monitor_gaia_bad_cases.py'
spec = importlib.util.spec_from_file_location('monitor_gaia_bad_cases',path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_only_terminal_actionable_bad_cases_and_retry_results():
    metrics = {'groups': {'g': {'cases': {
        'a': {'agent_state':'terminal','judge_state':'scored','is_correct':False},
        'b': {'agent_state':'terminal','judge_state':'scored','is_correct':False},
        'c': {'agent_state':'running','judge_state':'unavailable','is_correct':None},
        'd': {'agent_state':'terminal','judge_state':'unavailable','is_correct':None},
        'e': {'agent_state':'terminal','judge_state':'scored','is_correct':True},
    }}}}
    controller = {'groups': {'g': {key:{'result_path':'/original/'+key} for key in 'abcde'}}}
    retries = {'cases':[{'group':'g','case':'b','status':'pending_retry'},
                        {'group':'g','case':'e','status':'completed','is_correct':False,'result_path':'/retry/e'}]}
    items = module.collect(metrics,controller,retries)
    assert [(x['case'],x['reason']) for x in items] == [('a','incorrect'),('d','unscored'),('e','incorrect')]
    assert next(x for x in items if x['case']=='e')['source'] == '/retry/e'
    assert module.collect(metrics,controller,retries) == items


def test_new_retry_produces_new_fingerprint():
    metrics={'groups':{'g':{'cases':{'a':{'agent_state':'terminal','judge_state':'scored','is_correct':False}}}}}
    controller={'groups':{'g':{'a':{'result_path':'/old'}}}}
    first=module.collect(metrics,controller,{'cases':[]})[0]['fingerprint']
    retry={'cases':[{'group':'g','case':'a','status':'completed','is_correct':False,'result_path':'/new'}]}
    assert module.collect(metrics,controller,retry)[0]['fingerprint'] != first


def test_only_worker_confirmed_scheduled_cases_are_recorded():
    cases=[{'fingerprint':'a'},{'fingerprint':'b'}]
    assert module.processed_fingerprints({'processed':['a','unknown']},cases) == {'a'}
    assert module.processed_fingerprints({'processed':'a'},cases) == set()
    assert module.processed_fingerprints(None,cases) == set()
