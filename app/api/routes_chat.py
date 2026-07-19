"""Fan assistant chat endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..security import sanitize_text
from ..services.knowledge import UnknownVenueError
from .schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["assistant"])


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Deliberately a sync `def`: FastAPI runs it in the threadpool, so the
# (potentially slow) model call never blocks the event loop.
@router.post("/chat")
def chat(request: Request, payload: ChatRequest) -> dict:
    state = request.app.state
    if not state.rate_limiter.allow(f"chat:{_client_key(request)}"):
        raise HTTPException(status_code=429, detail="Too many requests - please slow down.")

    max_turns = state.settings.max_history_turns * 2  # user+assistant pairs
    history = [
        {"role": turn.role, "content": sanitize_text(turn.content, 2000)}
        for turn in payload.history[-max_turns:]
    ]
    try:
        return state.assistant.answer(
            message=payload.message,
            venue_id=payload.venue_id,
            language=payload.language,
            accessible=payload.accessible,
            location_zone=payload.location_zone,
            history=history,
        )
    except UnknownVenueError:
        raise HTTPException(status_code=404, detail="Unknown venue") from None
