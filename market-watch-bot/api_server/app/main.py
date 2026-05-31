from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_server.app.api.routers import router
from common.config import Settings, load_settings

MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def create_app(settings: Settings | None = None) -> FastAPI:
    api = FastAPI(title="Market Watch API", version="0.1.0")
    if settings is not None:
        api.state.settings = settings
    api.add_middleware(
        CORSMiddleware,
        allow_origins=(
            settings.api_cors_origins if settings is not None else ["http://localhost:5173"]
        ),
        allow_origin_regex=(
            r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}):5173$"
        ),
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
