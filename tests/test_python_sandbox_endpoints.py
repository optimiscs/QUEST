import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
from tool_python import _get_sandbox_fusion_endpoints


def test_local_default_and_explicit_endpoints(monkeypatch, tmp_path):
    for key in ('PYTHON_NODES_CONF', 'SANDBOX_FUSION_ENDPOINT', 'SANDBOX_FUSION_ENDPOINTS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr('tool_python.DEFAULT_PYTHON_NODES_CONF', str(tmp_path / 'absent'))
    assert _get_sandbox_fusion_endpoints() == ['http://127.0.0.1:8080']
    monkeypatch.setenv('SANDBOX_FUSION_ENDPOINT', 'http://example:9999')
    assert _get_sandbox_fusion_endpoints() == ['http://example:9999']
    monkeypatch.delenv('SANDBOX_FUSION_ENDPOINT')
    monkeypatch.setenv('PYTHON_NODES_CONF', str(tmp_path / 'absent'))
    assert _get_sandbox_fusion_endpoints() == []
