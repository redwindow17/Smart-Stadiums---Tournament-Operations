"""FastAPI application factory.

`create_app()` takes explicit settings so tests can build isolated instances
(e.g. with a tiny rate limit). The module-level ``app`` is what uvicorn runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import routes_chat, routes_meta, routes_ops
from .config import Settings, load_settings
from .security import SECURITY_HEADERS, SlidingWindowRateLimiter
from .services.assistant import Assistant
from .services.incidents import IncidentLog

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title="StadiumIQ",
        description="GenAI matchday copilot for FIFA World Cup 2026 venues",
        version=__version__,
    )
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)
    app.state.assistant = Assistant(settings)
    app.state.incidents = IncidentLog()

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            # Swagger UI pulls its assets from a CDN, so CSP would blank the
            # /docs page; every other header still applies there.
            if header == "Content-Security-Policy" and request.url.path.startswith(("/docs", "/redoc")):
                continue
            response.headers.setdefault(header, value)
        return response

    app.include_router(routes_meta.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_ops.router)

    # Mounted last: API routes above always win over static files.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
