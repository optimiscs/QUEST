import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBJ = ROOT / 'task' / 'obj_task'
sys.path.insert(0, str(OBJ))

def load(name):
    spec = importlib.util.spec_from_file_location(name, OBJ / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_refined_tree_statistics_use_actual_list_children():
    module = load('refine_rubric_trees')
    tree = {'name': 'root', 'children': [{'name': str(i), 'children': []} for i in range(7)]}
    assert module.tree_statistics(tree) == {'max_depth': 2, 'max_width': 7, 'width_by_level': {1: 1, 2: 7}}

def test_serper_error_is_not_cached(monkeypatch):
    module = load('tool_search')
    class Response:
        status = 400
        def read(self): return b'{"message":"Not enough credits"}'
    class Connection:
        def __init__(self, host): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
    class Cache:
        def get(self, query): return None
        def set(self, query, result): raise AssertionError('error cached')
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    search = object.__new__(module.Search)
    search.cache = Cache()
    assert search.search_with_serp('example').startswith('[Search] Error: Serper returned HTTP 400')

def test_merge_uses_final_answer_when_self_refinement_did_not_run(tmp_path):
    import json
    module = load('merge_rubric_predictions')
    answer = {'proposed_question': 'Which item?', 'rubric_tree': {'root': {}}, 'solution': {'item': 'A'}}
    raw = '<answer>' + json.dumps(answer) + '</answer>'
    p = tmp_path / 'trajectory.json'
    p.write_text(json.dumps({'messages': [{'role': 'assistant', 'content': 'research'}, {'role': 'assistant', 'content': raw}]}))
    assert module.process_file(p)
    assert json.loads(json.loads(p.read_text())['answer']) == answer

def test_merge_refined_tree_preserves_answer_even_with_step_heading(tmp_path):
    import json
    module = load('merge_rubric_predictions')
    answer = {'proposed_question': 'Check ## STEP 4 Rubric Tree\nfor item A', 'rubric_tree': {'old': {}}, 'solution': {'item': 'A'}}
    refined = {'rubric_tree': {'new': {'description': 'criterion'}}}
    raw = '<answer>' + json.dumps(answer) + '</answer>'
    p = tmp_path / 'trajectory.json'
    p.write_text(json.dumps({'messages': [{'role': 'assistant', 'content': raw}, {'role': 'user', 'content': 'refine'}, {'role': 'assistant', 'content': json.dumps(refined)}]}))
    assert module.process_file(p)
    result = json.loads(json.loads(p.read_text())['answer'])
    assert result['proposed_question'] == answer['proposed_question']
    assert result['rubric_tree'] == refined['rubric_tree']
