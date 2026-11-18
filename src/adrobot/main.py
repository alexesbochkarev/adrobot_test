from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from adrobot.allocation import EditorError
from adrobot.campaigns import router as campaigns_router
from adrobot.config import Settings
from adrobot.db import create_db_engine
from adrobot.editor_api import router as editor_router
from adrobot.health import router as health_router
from adrobot.keitaro import KeitaroClient, KeitaroError
from adrobot.sync import SyncError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings.database_url)
        app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.state.settings = settings
        app.state.keitaro = None
        http_client = None
        if settings.keitaro_base_url and settings.keitaro_api_key:
            http_client = httpx.Client(
                base_url=str(settings.keitaro_base_url).rstrip("/") + "/admin_api/v1/",
                headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
                timeout=httpx.Timeout(20, connect=5),
                follow_redirects=False,
            )
            app.state.keitaro = KeitaroClient(http_client)
        try:
            yield
        finally:
            if http_client:
                http_client.close()
            engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(campaigns_router, prefix="/api/v1")
    app.include_router(editor_router, prefix="/api/v1")

    @app.exception_handler(SyncError)
    async def sync_error(_request: Request, error: SyncError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status, content={"detail": {"code": error.code, **error.details}}
        )

    @app.exception_handler(EditorError)
    async def editor_error(_request: Request, error: EditorError) -> JSONResponse:
        code = 409 if error.code == "stale_revision" else 422
        return JSONResponse(status_code=code, content={"detail": {"code": error.code}})

    @app.exception_handler(StaleDataError)
    @app.exception_handler(IntegrityError)
    async def conflict_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {"code": "concurrent_change"}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": {"code": "database_error"}})

    @app.exception_handler(KeitaroError)
    async def keitaro_error(_request: Request, error: KeitaroError) -> JSONResponse:
        code = 503 if error.code == "keitaro_not_configured" else 502
        return JSONResponse(status_code=code, content={"detail": {"code": error.code}})

    return app
