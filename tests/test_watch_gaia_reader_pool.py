import importlib.util
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'inference/scripts/watch_gaia_reader_pool.py'
spec = importlib.util.spec_from_file_location('watch_gaia_reader_pool', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_new_key_prevents_pause(tmp_path):
    (tmp_path/'api_key_pool.json').write_text(json.dumps({'jina': ['a', 'b', 'c']}))
    (tmp_path/'key_rotation_state.json').write_text(json.dumps({'jina': {'exhausted': [0, 1]}}))
    assert not module.exhausted(tmp_path)
    (tmp_path/'key_rotation_state.json').write_text(json.dumps({'jina': {'exhausted': [0, 1, 2]}}))
    assert module.exhausted(tmp_path)
