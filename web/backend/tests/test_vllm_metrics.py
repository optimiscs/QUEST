from quest_viewer.api.vllm_metrics import parse_metrics


def test_prometheus_parser_preserves_absence_and_aggregates_labels():
    result = parse_metrics("""
# HELP vllm:num_requests_running running
vllm:num_requests_running{model_name="demo",engine="0"} 2
vllm:num_requests_running{model_name="demo",engine="1"} 3
vllm:prefix_cache_hits_total{model_name="demo"} 40
vllm:time_to_first_token_seconds_bucket{model_name="demo",le="1.0"} 2
vllm:time_to_first_token_seconds_bucket{model_name="demo",le="+Inf"} 3
vllm:time_to_first_token_seconds_count{model_name="demo"} 3
vllm:time_to_first_token_seconds_sum{model_name="demo"} 3.5
vllm:kv_cache_usage_perc{model_name="demo"} NaN
""")
    assert result["model"] == "demo"
    assert result["values"] == {"num_requests_running": 5, "prefix_cache_hits_total": 40}
    hist = result["histograms"]["time_to_first_token_seconds"]
    assert hist["buckets"] == {"1.0": 2, "+Inf": 3}
    assert hist["count"] == 3 and hist["sum"] == 3.5


def test_discovers_python_wrapped_vllm_and_openai_server(tmp_path):
    from quest_viewer.api.vllm_metrics import _local_endpoints

    one = tmp_path / "1"
    one.mkdir()
    (one / "environ").write_bytes(b"CUDA_VISIBLE_DEVICES=2\0")
    two = tmp_path / "2"
    two.mkdir()
    (two / "environ").write_bytes(b"")
    processes = [
        (one, ["python", "-m", "vllm.entrypoints.openai.api_server", "--port", "19251"]),
        (two, ["python", "/env/bin/vllm", "serve", "model", "--port=19013"]),
        (two, ["python", "-c", "vllm.entrypoints.openai.api_server --port 9999"]),
    ]
    rows = _local_endpoints(processes)
    assert [(x["port"], x["gpu"]) for x in rows] == [(19251, "2"), (19013, "自动")]


def test_ssh_discovery_uses_existing_session_identity_and_loopback_forward(tmp_path):
    from quest_viewer.api.vllm_metrics import _ssh_sessions

    sessions = _ssh_sessions(
        [
            (
                tmp_path,
                [
                    "ssh",
                    "-N",
                    "-i",
                    "/tmp/key",
                    "-L",
                    "127.0.0.1:19013:127.0.0.1:19014",
                    "-p",
                    "29723",
                    "root@example.com",
                ],
            )
        ]
    )
    assert len(sessions) == 1
    args, forwards = next(iter(sessions.values()))
    assert "-i" in args and "/tmp/key" in args
    assert forwards == {19014: 19013}
    assert _ssh_sessions([(tmp_path, ["ssh", "root@example.com", "echo hi"])]) == {}


def test_explicit_endpoints_are_not_allowed_to_override_ssh_commands(monkeypatch):
    import json

    from quest_viewer.api import vllm_metrics

    monkeypatch.setattr(vllm_metrics, "_processes", lambda: iter(()))
    monkeypatch.setenv(
        "VIEWER_VLLM_ENDPOINTS",
        json.dumps(
            [
                {
                    "server": "manual",
                    "port": 9000,
                    "_ssh": ["unsafe"],
                    "_local_port": 80,
                }
            ]
        ),
    )
    monkeypatch.setattr(vllm_metrics, "_DISCOVERY_CACHE", {"until": 0.0, "endpoints": [], "warnings": []})
    rows, warnings = vllm_metrics.endpoints()
    assert rows == [{"server": "manual", "gpu": None, "role": None, "port": 9000}]
    assert warnings == []
