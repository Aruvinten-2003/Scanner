"""Application factory, service lifecycle, health checks and privacy boundaries."""

import asyncio
from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from starlette.responses import JSONResponse

from app.config import Settings
from app.dependencies import AdmissionControl
from app.routes import ROUTERS
from app.services.openai_service import OpenAIService
from app.services.retrieval_service import RetrievalService
from app.services.supabase_service import SupabaseService
from app.utils.errors import error_response, install_error_handlers
from app.utils.logging import configure_logging


class PrivacyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    body.extend(event.get("body", b""))
                    if len(body) > 16384:
                        return await error_response(413, "request_too_large", "The request body is too large.")(scope, receive, send)
                    if not event.get("more_body", False):
                        break
        except TimeoutError:
            return await error_response(408, "request_timeout", "The request body took too long.")(scope, receive, send)
        consumed, started = False, False
        request_id = str(uuid4())

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        async def safe_send(event):
            nonlocal started
            if event["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in event.get("headers", []) if k.lower() != b"cache-control"]
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer"), (b"x-request-id", request_id.encode())])
                event["headers"] = headers
                route = getattr(scope.get("route"), "path", "unmatched")
                logging.getLogger("scanner").info("request", extra={
                    "event": "request_completed", "route": route, "status": event["status"], "request_id": request_id,
                })
            await send(event)
        try:
            await self.app(scope, replay, safe_send)
        except Exception:
            if not started:
                await error_response(500, "internal_error", "Scanner could not complete this request.")(scope, receive, safe_send)


def create_app(settings: Settings | None = None, *, database=None, ai=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(settings.log_level)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            app.state.database = database or SupabaseService(settings, client)
            app.state.ai = ai or OpenAIService(settings, client)
            app.state.retrieval = RetrievalService(settings, app.state.database, app.state.ai)
            yield

    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
                  docs_url="/docs" if settings.app_env != "production" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.app_env != "production" else None)
    app.state.settings = settings
    app.state.admission = AdmissionControl(settings.requests_per_minute, settings.processing_concurrency)
    install_error_handlers(app)
    app.add_middleware(PrivacyMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
                       expose_headers=["X-Request-ID"])

    @app.get("/health", tags=["health"])
    @app.get(settings.api_prefix + "/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready():
        configured = settings.supabase_ready and settings.ai_ready
        return JSONResponse({"status": "ready" if configured else "not_configured"},
                            status_code=200 if configured else 503)

    for router in ROUTERS:
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
