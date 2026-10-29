from evaluation.gaia_retrieval_decision import DIRECT, decide


def groups(correct):
    return {name:{f'row{i:04d}':{'agent_state':'terminal','judge_state':'scored','is_correct':i<correct[name]} for i in range(32)} for name in ('baseline',)+DIRECT}


def test_retries_override_old_score_before_decision():
    counts={name:10 for name in ('baseline',)+DIRECT};counts['baseline']=13
    state=groups(counts)
    assert decide(state,[])['decision']=='run_flash'
    retry=[{'group':'bm25-direct','case':'row0010','status':'completed','is_correct':True}]
    assert decide(state,retry)['decision']=='skip_flash'


def test_missing_and_pending_are_never_counted_as_wrong():
    state=groups({name:10 for name in ('baseline',)+DIRECT})
    state['baseline']['row0000']['judge_state']='unavailable'
    assert decide(state,[])['decision']=='inconclusive'
    retry=[{'group':'bm25-direct','case':'row0003','status':'pending_retry'}]
    assert decide(state,retry)['reason']=='retry_incomplete'
