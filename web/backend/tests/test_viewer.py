import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from quest_viewer.app import create_app
from quest_viewer.config import Settings
from quest_viewer.db.models import Run, Trace
from quest_viewer.ingestion.importer import import_run


@pytest.fixture
def env(tmp_path):
    url = os.environ.get("VIEWER_TEST_DATABASE_URL")
    if not url or not url.split("?")[0].endswith("_test"):
        pytest.fail("Set VIEWER_TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    app = create_app(Settings(database_url=url, frontend_dir=tmp_path / "not-built"))
    run_id = "test-" + uuid4().hex
    package = {
        "generatedAt": "2026-10-29",
        "run": {"name": "test", "stopped": True},
        "provenance": {"source": "original"},
        "cases": [
            {
                "id": "trace-245",
                "index": 245,
                "topicZh": "test",
                "correct": True,
                "stats": {"steps": 1},
                "groundTruth": "answer",
                "scoreReceipt": {"preserved": True},
                "steps": [
                    {"n": 1, "thought": "private body\u0000" * 100, "tool": {"stdout": "complete output"}}
                ],
            },
            {"id": "trace-02", "index": 2, "inProgress": True, "steps": [], "correct": None},
        ],
    }
    path = tmp_path / "traces.json"
    path.write_text(json.dumps(package))
    metadata = {"id": run_id, "lifecycleOverride": "stopped"}
    import_run(app.state.sessions, run_id, path, metadata, 0)
    with TestClient(app) as client:
        yield client, app.state.sessions, run_id, path, package, metadata
    with app.state.sessions.begin() as session:
        session.execute(delete(Run).where(Run.id == run_id))
    app.state.engine.dispose()


def test_summary_detail_cache_export(env):
    client, _, run_id, _, package, _ = env
    base = f"/api/v1/runs/{run_id}"
    info = client.get(base)
    assert info.status_code == 200
    assert client.get(base, headers={"If-None-Match": info.headers["etag"]}).status_code == 304
    assert info.json()["counts"]["pass"] == 1
    assert info.json()["counts"]["stopped"] == 1
    first = client.get(base + "/traces?limit=1").json()
    assert "steps" not in first["items"][0]
    assert "groundTruth" not in first["items"][0]
    assert "private body" not in json.dumps(first)
    second = client.get(base + f"/traces?cursor={first['nextCursor']}&limit=1").json()
    assert second["items"][0]["id"] == "trace-02"
    assert second["nextCursor"] is None
    detail = client.get(base + "/traces/trace-245")
    assert detail.json() == package["cases"][0]
    assert (
        client.get(base + "/traces/trace-245", headers={"If-None-Match": detail.headers["etag"]}).status_code
        == 304
    )
    assert client.get(base + "/export").json() == package
    assert client.get(base + "/traces/missing").status_code == 404
    assert client.get(base + "/traces?limit=201").status_code == 422
    assert client.get("/datasets/arbitrary/traces.json").status_code == 404


def test_import_idempotent_and_rollback(env):
    client, factory, run_id, path, package, metadata = env
    assert import_run(factory, run_id, path, metadata, 0) is False
    old_revision = client.get(f"/api/v1/runs/{run_id}").json()["revision"]
    package["generatedAt"] = "new timestamp"
    path.write_text(json.dumps(package))
    assert import_run(factory, run_id, path, metadata, 0) is True
    assert client.get(f"/api/v1/runs/{run_id}").json()["revision"] == old_revision
    package["cases"].append(package["cases"][0])
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match="Duplicate"):
        import_run(factory, run_id, path, metadata, 0)
    with factory() as session:
        assert list(
            session.scalars(select(Trace.position).where(Trace.run_id == run_id).order_by(Trace.position))
        ) == [0, 1]
    assert client.get(f"/api/v1/runs/{run_id}").json()["revision"] == old_revision


def test_replace_reorder_and_revision(env):
    client, factory, run_id, path, package, metadata = env
    base = f"/api/v1/runs/{run_id}"
    before = client.get(base + "/traces/trace-245")
    package["cases"].reverse()
    package["cases"][1]["steps"][0]["thought"] = "changed body"
    path.write_text(json.dumps(package))
    import_run(factory, run_id, path, metadata, 0)
    assert client.get(base + "/traces").json()["items"][0]["id"] == "trace-02"
    after = client.get(base + "/traces/trace-245", headers={"If-None-Match": before.headers["etag"]})
    assert after.status_code == 200
    assert after.json()["steps"][0]["thought"] == "changed body"
    package["cases"].pop()
    path.write_text(json.dumps(package))
    import_run(factory, run_id, path, metadata, 0)
    assert client.get(base + "/traces/trace-245").status_code == 404


def test_stopped_unscored_counts_and_source_containment(env, tmp_path):
    from quest_viewer.ingestion.importer import import_site

    client, factory, run_id, path, package, metadata = env
    package["cases"] = [
        dict(id=f"t-{i}", steps=[], **value)
        for i, value in enumerate(
            [
                {"correct": True},
                {"correct": False},
                {"correct": None},
                {"inProgress": True},
            ]
        )
    ]
    path.write_text(json.dumps(package))
    import_run(factory, run_id, path, metadata, 0)
    assert client.get(f"/api/v1/runs/{run_id}").json()["counts"] == {
        "total": 4,
        "pass": 1,
        "fail": 1,
        "error": 1,
        "running": 0,
        "stopped": 1,
    }
    site = tmp_path / "site"
    (site / "datasets").mkdir(parents=True)
    for value in ["../outside.json", "datasets/link.json"]:
        (site / "datasets/index.json").write_text(
            json.dumps({"datasets": [{"id": "outside", "data": value}]})
        )
        outside = tmp_path / "outside.json"
        outside.write_text("{}")
        link = site / "datasets/link.json"
        if not link.exists():
            link.symlink_to(outside)
        with pytest.raises(ValueError, match="outside site"):
            import_site(factory, site)
