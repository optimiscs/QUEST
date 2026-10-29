"""Bounded-memory, transactional import of existing normalized trajectory packages."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ijson
from ijson.common import ObjectBuilder
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from quest_viewer.db.models import Report, Run, Source, Trace, TracePayload

SUMMARY_FIELDS = (
    "id",
    "index",
    "topicZh",
    "topic",
    "field",
    "fieldZh",
    "durationSeconds",
    "stats",
    "correct",
    "inProgress",
    "interrupted",
    "score",
    "scoredDimensions",
)


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def read_envelope(path: Path) -> dict:
    """Preserve all top-level fields except cases without materializing the cases array."""
    result = {}
    builder = None
    field = None
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream, use_float=True):
            if prefix == "" and event == "map_key":
                field = value
                builder = None if field == "cases" else ObjectBuilder()
            elif builder is not None and prefix:
                builder.event(event, value)
                if prefix == field and event in (
                    "end_map",
                    "end_array",
                    "string",
                    "number",
                    "boolean",
                    "null",
                ):
                    result[field] = builder.value
                    builder = None
    if not isinstance(result.get("run"), dict):
        raise ValueError(f"Missing run object: {path}")
    return result


def import_run(factory, run_id: str, path: Path, metadata: dict, position: int, force=False) -> bool:
    path = path.resolve(strict=True)
    before = path.stat()
    with factory.begin() as session:
        # Serialize writers of the same run, including independent importer processes.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": run_id})
        source = session.get(Source, run_id)
        current = session.get(Run, run_id)
        if (
            not force
            and source
            and source.path == str(path)
            and source.mtime_ns == before.st_mtime_ns
            and source.size == before.st_size
            and current.metadata_json == metadata
            and current.position == position
        ):
            current.listed = True
            return False
        envelope = read_envelope(path)
        run = envelope.pop("run")
        if current is None:
            current = Run(
                id=run_id,
                metadata_json=metadata,
                run_json=run,
                envelope_json=envelope,
                counts={},
                revision="pending",
                position=position,
            )
            session.add(current)
            session.flush()
        existing = dict(session.execute(select(Trace.id, Trace.revision).where(Trace.run_id == run_id)).all())
        # Positions may change in a new snapshot. Move existing positions out of the target range first.
        session.execute(text("UPDATE traces SET position = -position - 1 WHERE run_id = :id"), {"id": run_id})
        counts = dict.fromkeys(["total", "pass", "fail", "running", "stopped", "error"], 0)
        stopped = metadata.get("lifecycleOverride") == "stopped" or run.get("stopped")
        seen = set()
        versions = []
        with path.open("rb") as stream:
            for idx, case in enumerate(ijson.items(stream, "cases.item", use_float=True)):
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise ValueError(f"Invalid case at position {idx}: {path}")
                case_id = case["id"]
                if (
                    not case_id
                    or len(case_id) > 255
                    or case_id in seen
                    or not isinstance(case.get("steps"), list)
                ):
                    raise ValueError(f"Duplicate ID or invalid steps: {case_id}")
                seen.add(case_id)
                revision = digest(case)
                versions.append((case_id, revision))
                summary = {key: case[key] for key in SUMMARY_FIELDS if key in case}
                summary["revision"] = revision
                values = dict(run_id=run_id, id=case_id, position=idx, summary=summary, revision=revision)
                session.execute(
                    insert(Trace)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[Trace.run_id, Trace.id],
                        set_={k: v for k, v in values.items() if k not in ("run_id", "id")},
                    )
                )
                if existing.get(case_id) != revision:
                    session.execute(
                        insert(TracePayload)
                        .values(run_id=run_id, trace_id=case_id, body=case)
                        .on_conflict_do_update(
                            index_elements=[TracePayload.run_id, TracePayload.trace_id], set_={"body": case}
                        )
                    )
                counts["total"] += 1
                status = (
                    ("stopped" if stopped else "running")
                    if case.get("inProgress")
                    else (
                        "pass"
                        if case.get("correct") is True
                        else "fail"
                        if case.get("correct") is False
                        else "error"
                    )
                )
                counts[status] += 1
        if not seen:
            raise ValueError(f"Empty package: {path}")
        session.execute(delete(Trace).where(Trace.run_id == run_id, Trace.id.not_in(seen)))
        after = path.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError(f"Source changed during import, retry next cycle: {path}")
        current.listed = True
        current.metadata_json = metadata
        current.run_json = run
        current.envelope_json = envelope
        current.position = position
        current.counts = counts
        # generatedAt alone must not invalidate unchanged content.
        current.revision = digest([run, metadata, versions])
        session.merge(
            Source(
                run_id=run_id,
                path=str(path),
                mtime_ns=before.st_mtime_ns,
                size=before.st_size,
                imported_at=datetime.now(UTC),
            )
        )
    return True


def import_site(factory, site: Path, force=False) -> dict:
    site = site.resolve(strict=True)
    manifest = json.loads((site / "datasets/index.json").read_text())
    entries = [
        ("default-en", site / "data/traces.json", {"id": "default-en", "hiddenDefault": True}),
        (
            "default-zh",
            site.parent / "trace-viewer-zh/data/traces.json",
            {"id": "default-zh", "hiddenDefault": True},
        ),
    ]
    for item in manifest["datasets"]:
        run_id = item["id"]
        if run_id in {entry[0] for entry in entries}:
            raise ValueError(f"Duplicate or reserved run ID: {run_id}")
        path = (site / (item.get("data") or f"datasets/{run_id}/traces.json")).resolve()
        if not path.is_relative_to(site):
            raise ValueError(f"Source outside site: {path}")
        entries.append((run_id, path, item))
    result = {"updated": [], "unchanged": [], "errors": {}}
    for position, (run_id, path, metadata) in enumerate(entries):
        try:
            changed = import_run(factory, run_id, path, metadata, position, force)
            result["updated" if changed else "unchanged"].append(run_id)
        except (ValueError, OSError) as exc:
            result["errors"][run_id] = str(exc)
    # Removal from the manifest hides navigation, preserving archived deep links and data.
    with factory.begin() as session:
        session.execute(update(Run).values(listed=Run.id.in_([entry[0] for entry in entries])))
    # Dashboard publishers produce small JSON files beside the run directories.
    for path in (site / "datasets").glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            body = json.loads(path.read_text())
            with factory.begin() as session:
                stmt = insert(Report).values(name=path.name, body=body, revision=digest(body))
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[Report.name],
                        set_={"body": stmt.excluded.body, "revision": stmt.excluded.revision},
                    )
                )
        except (ValueError, OSError) as exc:
            result["errors"][path.name] = str(exc)
    return result
