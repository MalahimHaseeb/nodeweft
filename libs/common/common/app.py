from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from common.config import CommonSettings
from common.errors import register_error_handlers
from common.responses import error_response, success_response

LifecycleHook = Callable[[FastAPI], Awaitable[None]]


def create_service_app(
    title: str,
    settings: CommonSettings,
    on_startup: Optional[LifecycleHook] = None,
    on_shutdown: Optional[LifecycleHook] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if on_startup:
            await on_startup(app)
        try:
            yield
        finally:
            if on_shutdown:
                await on_shutdown(app)
            await app.state.redis.aclose()

    hide_docs = settings.is_production
    app = FastAPI(
        title=title,
        lifespan=lifespan,
        docs_url=None if hide_docs else "/docs",
        redoc_url=None,
        openapi_url=None if hide_docs else "/openapi.json",
    )
    app.state.settings = settings
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    register_error_handlers(app)

    @app.middleware("http")
    async def guard_request(request: Request, call_next):
        declared_length = request.headers.get("content-length", "")
        if declared_length.isdigit() and int(declared_length) > settings.max_body_bytes:
            return error_response("PAYLOAD_TOO_LARGE", "Request body is too large", 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/health")
    async def health():
        return success_response({"status": "ok"})

    return app
