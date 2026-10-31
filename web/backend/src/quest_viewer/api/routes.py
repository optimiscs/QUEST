import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, text

from quest_viewer.api.schemas import Manifest, RunInfo, TaskPage, TraceDocument, WorkspaceStatus
from quest_viewer.api.vllm_metrics import scrape_all
from quest_viewer.db.models import Report, Run, Trace, TracePayload

router = APIRouter(prefix="/api/v1")


@router.get("/vllm/metrics")
async def vllm_metrics(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await scrape_all()


def factory(request: Request):
    return request.app.state.sessions


def require_run(session, run_id):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def cache_headers(revision: str):
    return {"ETag": f'"{revision}"', "Cache-Control": "private, no-cache"}


def not_modified(request: Request, revision: str) -> bool:
    return f'"{revision}"' in request.headers.get("if-none-match", "").split(", ")


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request):
    with factory(request)() as session:
        session.execute(text("SELECT 1 FROM runs LIMIT 1"))
    return {"status": "ok"}


@router.get("/runs", response_model=Manifest)
def runs(request: Request):
    with factory(request)() as session:
        rows = session.scalars(select(Run).where(Run.listed.is_(True)).order_by(Run.position)).all()
        return {"datasets": [row.metadata_json for row in rows if not row.metadata_json.get("hiddenDefault")]}


@router.get("/workspace-status", response_model=WorkspaceStatus)
def workspace_status(request: Request):
    with factory(request)() as session:
        return {"datasets": dict(session.execute(select(Run.id, Run.counts)).all())}


@router.get("/runs/{run_id}", response_model=RunInfo)
def run_info(request: Request, run_id: str, response: Response):
    with factory(request)() as session:
        row = require_run(session, run_id)
        if not_modified(request, row.revision):
            return Response(status_code=304, headers=cache_headers(row.revision))
        response.headers.update(cache_headers(row.revision))
        return {
            "id": row.id,
            "revision": row.revision,
            "metadata": row.metadata_json,
            "run": row.run_json,
            "counts": row.counts,
        }


@router.get("/runs/{run_id}/traces", response_model=TaskPage)
def task_page(
    request: Request, run_id: str, cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
):
    with factory(request)() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        run = require_run(session, run_id)
        rows = session.execute(
            select(Trace.position, Trace.summary)
            .where(Trace.run_id == run_id, Trace.position >= cursor)
            .order_by(Trace.position)
            .limit(limit + 1)
        ).all()
        return {
            "runRevision": run.revision,
            "items": [r.summary for r in rows[:limit]],
            "nextCursor": rows[limit].position if len(rows) > limit else None,
        }


@router.get("/runs/{run_id}/traces/{trace_id}", response_model=TraceDocument)
def trace_detail(request: Request, run_id: str, trace_id: str, response: Response):
    with factory(request)() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        trace = session.get(Trace, (run_id, trace_id))
        if trace is None:
            raise HTTPException(404, "Trace not found")
        if not_modified(request, trace.revision):
            return Response(status_code=304, headers=cache_headers(trace.revision))
        body = session.scalar(
            select(TracePayload.body).where(TracePayload.run_id == run_id, TracePayload.trace_id == trace_id)
        )
        response.headers.update(cache_headers(trace.revision))
        return body


@router.get("/runs/{run_id}/traces/{trace_id}/session-stats")
def session_stats(request: Request, run_id: str, trace_id: str, response: Response):
    """Return the latest imported measurements for one trajectory."""
    with factory(request)() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        trace = session.get(Trace, (run_id, trace_id))
        if trace is None:
            raise HTTPException(404, "Trace not found")
        if not_modified(request, trace.revision):
            return Response(status_code=304, headers=cache_headers(trace.revision))
        body = session.scalar(
            select(TracePayload.body).where(TracePayload.run_id == run_id, TracePayload.trace_id == trace_id)
        )
        response.headers.update(cache_headers(trace.revision))
        return {
            "traceId": trace_id,
            "revision": trace.revision,
            "sessionStats": body.get("sessionStats", {}),
            "timing": body.get("timing", {}),
        }


@router.get("/runs/{run_id}/export")
def export_run(request: Request, run_id: str):
    with factory(request)() as session:
        require_run(session, run_id)

    def chunks() -> Iterator[str]:
        with factory(request)() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            row = require_run(session, run_id)
            header = dict(row.envelope_json, run=row.run_json)
            yield json.dumps(header, ensure_ascii=False)[:-1] + ',"cases":['
            query = (
                select(TracePayload.body)
                .join(Trace, (Trace.run_id == TracePayload.run_id) & (Trace.id == TracePayload.trace_id))
                .where(Trace.run_id == run_id)
                .order_by(Trace.position)
            )
            for index, body in enumerate(session.scalars(query.execution_options(yield_per=1))):
                yield ("," if index else "") + json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            yield "]}"

    return StreamingResponse(
        chunks(),
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=quest-traces.json",
            "Cache-Control": "no-store",
        },
    )


@router.get("/reports/{name}")
def report(request: Request, name: str):
    with factory(request)() as session:
        row = session.get(Report, name)
        if row is None:
            raise HTTPException(404, "Report not found")
        if not_modified(request, row.revision):
            return Response(status_code=304, headers=cache_headers(row.revision))
        return Response(
            json.dumps(row.body, ensure_ascii=False),
            media_type="application/json",
            headers=cache_headers(row.revision),
        )
