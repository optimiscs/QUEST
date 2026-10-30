import importlib.util
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'inference/scripts/restore_gaia_retrieval.py'
spec = importlib.util.spec_from_file_location('restore_gaia_retrieval', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_restore_reactivates_only_verified_keys(tmp_path):
    (tmp_path / 'api_key_pool.json').write_text(json.dumps({'jina': ['a', 'b', 'c']}))
    (tmp_path / 'key_rotation_state.json').write_text(json.dumps({'jina': {'current': 1, 'exhausted': [0, 1, 2]}, 'serper': {'exhausted': [2]}}))
    class Response:
        def __init__(self, code): self.status_code = code
        def close(self): pass
    statuses = iter([402, 200, 401])
    result, restored = module.restore_pool(tmp_path, lambda *a, **kw: Response(next(statuses)))
    assert result == [402, 200, 401] and restored
    state = json.loads((tmp_path / 'key_rotation_state.json').read_text())
    assert state['jina'] == {'current': 1, 'exhausted': [0, 2]}
    assert state['serper'] == {'exhausted': [2]}


def test_no_usable_key_does_not_mutate_state(tmp_path):
    (tmp_path / 'api_key_pool.json').write_text(json.dumps({'jina': ['a']}))
    state = tmp_path / 'key_rotation_state.json'
    state.write_text('{"jina":{"exhausted":[0]}}')
    class Response:
        status_code = 402
        def close(self): pass
    result, restored = module.restore_pool(tmp_path, lambda *a, **kw: Response())
    assert result == [402] and not restored
    assert state.read_text() == '{"jina":{"exhausted":[0]}}'
