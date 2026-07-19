"""Shared FastAPI dependencies and helpers used by every router.

Centralising these keeps the route modules free of duplicated lookup /
throttling code and gives each concern exactly one implementation to test.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request

from ..services import knowledge


def venue_or_404(venue_id: str) -> dict[str, Any]:
    """Resolve a venue id or fail with a clean 404 (no internals leaked)."""
    try:
        return knowledge.get_venue(venue_id)
    except knowledge.UnknownVenueError:
        raise HTTPException(status_code=404, detail="Unknown venue") from None


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting."""
    return request.client.host if request.client else "unknown"


def rate_limited(scope: str) -> Callable[[Request], None]:
    """Dependency factory: enforce the per-client sliding-window limit.

    Usage: ``@router.post(..., dependencies=[Depends(rate_limited("chat"))])``.
    Scoping the key per endpoint group means chat traffic cannot starve
    incident reporting and vice versa.
    """

    def _enforce(request: Request) -> None:
        limiter = request.app.state.rate_limiter
        if not limiter.allow(f"{scope}:{client_key(request)}"):
            raise HTTPException(status_code=429, detail="Too many requests - please slow down.")

    return _enforce
