"""Compare every imported body against its source, including unknown fields and control characters."""

import json
from pathlib import Path

import ijson
from quest_viewer.config import Settings
from quest_viewer.db.models import Source, Trace, TracePayload
from quest_viewer.db.session import create_session_factory
from quest_viewer.ingestion.importer import digest
from sqlalchemy import select

engine, factory = create_session_factory(Settings())
count = 0
errors = []
advanced = []
try:
    with factory() as session:
        sources = session.scalars(select(Source)).all()
        for source in sources:
            path = Path(source.path)
            before = path.stat()
            if (before.st_mtime_ns, before.st_size) != (source.mtime_ns, source.size):
                advanced.append(source.run_id)
                query = (
                    select(TracePayload.body, Trace.revision)
                    .join(Trace, (Trace.run_id == TracePayload.run_id) & (Trace.id == TracePayload.trace_id))
                    .where(Trace.run_id == source.run_id)
                )
                for body, revision in session.execute(query.execution_options(yield_per=1)):
                    if digest(body) != revision:
                        errors.append(f"{source.run_id}/{body['id']}: stored snapshot mismatch")
                    count += 1
                continue
            with path.open("rb") as stream:
                for case in ijson.items(stream, "cases.item", use_float=True):
                    body = session.scalar(
                        select(TracePayload.body).where(
                            TracePayload.run_id == source.run_id, TracePayload.trace_id == case["id"]
                        )
                    )
                    if digest(body) != digest(case):
                        errors.append(f"{source.run_id}/{case['id']}: body mismatch")
                    count += 1
    print(
        json.dumps(
            {"runs": len(sources), "traces": count, "sourcesAdvanced": advanced, "errors": errors},
            ensure_ascii=False,
        )
    )
    raise SystemExit(bool(errors))
finally:
    engine.dispose()
