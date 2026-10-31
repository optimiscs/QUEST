from types import SimpleNamespace

import pytest

from inference.sandbox_preflight import check_sandbox_endpoints


def test_preflight_requires_real_success_for_every_endpoint(monkeypatch):
    visited = []
    def run(request, endpoint, **kwargs):
        visited.append(endpoint)
        return SimpleNamespace(run_result=SimpleNamespace(return_code=0, stdout='323\n'))
    monkeypatch.setattr('inference.sandbox_preflight.run_code', run)
    check_sandbox_endpoints(['http://one', 'http://two'])
    assert visited == ['http://one', 'http://two']


def test_preflight_fails_closed(monkeypatch):
    monkeypatch.setattr('inference.sandbox_preflight.run_code', lambda *a, **k: SimpleNamespace(
        run_result=SimpleNamespace(return_code=1, stdout='323')))
    with pytest.raises(RuntimeError, match='preflight failed'):
        check_sandbox_endpoints(['http://broken'])
    with pytest.raises(RuntimeError, match='no sandbox endpoint'):
        check_sandbox_endpoints([])
