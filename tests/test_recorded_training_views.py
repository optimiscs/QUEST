import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training_scripts/sft'))
from tokenize_summary_sessions import policy_views


def test_memory_rewrite_does_not_leak_later_state_into_earlier_target():
    system={'role':'system','content':'system'};question={'role':'user','content':'question'}
    a={'role':'assistant','content':'first action'};b={'role':'assistant','content':'final'}
    memory={'role':'user','content':'compressed state from later observations'}
    row={'messages':[system,question,a,b],'tools':[], 'training_views':[
        {'history_step':2,'messages':[system,question,a],'tools':[],'final':False},
        {'history_step':3,'messages':[system,memory,b],'tools':[],'final':True}]}
    views=list(policy_views(row))
    assert views[0][1][1]==question
    assert views[1][1][1]==memory
    row['training_views'][1]['history_step']=2
    with pytest.raises(ValueError,match='exactly once'):list(policy_views(row))


def test_recorded_view_cannot_swap_in_a_different_target():
    row={'messages':[{'role':'user','content':'q'},{'role':'assistant','content':'a'}], 'tools':[],
         'training_views':[{'history_step':1,'messages':[{'role':'user','content':'q'},
             {'role':'assistant','content':'fabricated'}],'tools':[],'final':True}]}
    with pytest.raises(ValueError,match='differs'):list(policy_views(row))
