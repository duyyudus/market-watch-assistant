from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_server.app.api.routers import router
from common.config import Settings, load_settings
from common.logging import setup_logging

MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


@asynccontextmanager
async def _lifespan(api: FastAPI) -> AsyncIterator[None]:
    # Configure logging once the server is actually starting (not on bare import
    # of the module), so the API process logs to its own api.log file.
    app_settings = getattr(api.state, "settings", None) or load_settings()
    api.state.settings = app_settings
    setup_logging(app_settings, component="api")
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        try:
            settings = load_settings()
        except ValueError as exc:
            if "DATABASE_URL" not in str(exc):
                raise
            settings = Settings()

    api = FastAPI(title="Market Watch API", version="0.1.0", lifespan=_lifespan)
    api.state.settings = settings
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_origin_regex=settings.api_cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.middleware("http")
    async def require_write_auth(request: Request, call_next):
        if request.method not in MUTATING_METHODS:
            return await call_next(request)
        app_settings = getattr(request.app.state, "settings", None)
        if app_settings is None:
            app_settings = load_settings()
            request.app.state.settings = app_settings

        cors_headers = {}
        origin = request.headers.get("origin")
        if origin:
            cors_headers["Access-Control-Allow-Origin"] = origin
            cors_headers["Access-Control-Allow-Credentials"] = "true"

        if not app_settings.api_auth_token:
            return JSONResponse(
                status_code=503,
                content={"detail": "API_AUTH_TOKEN is not configured"},
                headers=cors_headers,
            )
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing bearer token"},
                headers=cors_headers,
            )
        token = authorization.removeprefix("Bearer ").strip()
        if token != app_settings.api_auth_token:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid bearer token"},
                headers=cors_headers,
            )
        return await call_next(request)

    api.include_router(router)
    return api


app = create_app()
