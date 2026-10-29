import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware

from quest_viewer.api.routes import router
from quest_viewer.config import Settings
from quest_viewer.db.session import create_session_factory

logger = logging.getLogger("quest_viewer")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    engine, sessions = create_session_factory(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="QUEST Viewer API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.state.sessions = sessions
    app.state.engine = engine
    app.include_router(router)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = uuid.uuid4().hex
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - start) * 1000,
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.exception("Database request failed")
        return JSONResponse(
            {"error": {"code": "database_unavailable", "message": "Database unavailable"}}, status_code=503
        )

    dist = settings.frontend_dir.resolve()
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        @app.get("/trace-viewer/", include_in_schema=False)
        @app.get("/trace-viewer-zh/", include_in_schema=False)
        def index():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

        # Explicit allowlist: source JSON, credentials and arbitrary paths are never served.
        for page in dist.glob("*.html"):
            if page.name != "index.html":

                def page_handler(page=page):
                    return FileResponse(page, headers={"Cache-Control": "no-cache"})

                app.add_api_route("/" + page.name, page_handler, include_in_schema=False)
    return app
