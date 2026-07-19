"""Fan assistant chat endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ..security import sanitize_text
from .deps import rate_limited, venue_or_404
from .schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["assistant"])

_HISTORY_TURN_MAX_CHARS = 2000


# Deliberately a sync `def`: FastAPI runs it in the threadpool, so the
# (potentially slow) model call never blocks the event loop.
@router.post("/chat", dependencies=[Depends(rate_limited("chat"))])
def chat(request: Request, payload: ChatRequest) -> dict[str, Any]:
    state = request.app.state
    venue_or_404(payload.venue_id)  # fail fast with a clean 404

    max_turns = state.settings.max_history_turns * 2  # user+assistant pairs
    history = [
        {"role": turn.role, "content": sanitize_text(turn.content, _HISTORY_TURN_MAX_CHARS)}
        for turn in payload.history[-max_turns:]
    ]
    return state.assistant.answer(
        message=payload.message,
        venue_id=payload.venue_id,
        language=payload.language,
        accessible=payload.accessible,
        location_zone=payload.location_zone,
        history=history,
    )
