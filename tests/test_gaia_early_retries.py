import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'inference/scripts/run_gaia_early_retries.py'
spec = importlib.util.spec_from_file_location('early_retries', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_counts_running_original_tasks_by_actual_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RUN', tmp_path)
    root = tmp_path/'hybrid-direct'/'configs'
    root.mkdir(parents=True)
    (root/'row0001-server_endpoints.conf').write_text('HOSTNAME_LIST=127.0.0.1\nPORTS=18202\n')
    state = {'groups': {'hybrid-direct': {'row0001': {'agent_state':'running'}, 'row0002': {'agent_state':'terminal'}}}}
    (tmp_path/'controller-state.json').write_text(json.dumps(state))
    assert module.original_load()[18202] == 1
    state['groups']['hybrid-direct']['row0002']['agent_state'] = 'pending'
    (tmp_path/'controller-state.json').write_text(json.dumps(state))
    with pytest.raises(RuntimeError):
        module.original_load()
