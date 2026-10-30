"""Exercise task-result validation without model or network dependencies."""
import ast
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'task/open_ended_task/generate_longform_tasks.py'


def load_iteration(result):
    tree = ast.parse(SOURCE.read_text())
    func = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'run_single_iteration')
    class Agent:
        def __init__(self, **kwargs):
            pass
        def _run(self, data, model):
            return result
    namespace = {'asyncio': asyncio, 'sample_subcategory_with_weights': lambda *args: ('category', 'question'),
                 'sample_complexity_class_with_weights': lambda *args: 'complex',
                 'sample_keywords_from_csv': lambda *args, **kwargs: [],
                 'MultiTurnReactAgent': Agent, 'llm_cfg': {}, 'executor': None}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['run_single_iteration']


def run(result):
    async def execute():
        return await load_iteration(result)(0, {('category', 'question'): 0}, threading.Lock(),
                                            threading.Lock(), {}, {}, 'mock', asyncio.Semaphore(1))
    return asyncio.run(execute())


def test_complete_proposal_is_returned():
    payload = {'prediction': {'json': {'conceptual_breadth': 'a', 'logical_nesting': 'b',
                                      'exploration': 'c', 'proposed_question': 'd'}}}
    assert run(payload) == payload


@pytest.mark.parametrize('prediction', [None, 'not json', {}, {'proposed_question': ' '}])
def test_incomplete_proposal_fails(prediction):
    with pytest.raises(ValueError, match='did not produce a valid proposed question'):
        run({'prediction': {'json': prediction}})
