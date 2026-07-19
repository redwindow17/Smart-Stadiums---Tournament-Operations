"""Request/response schemas. Every inbound field is length- and
pattern-constrained so malformed or oversized input is rejected before any
business logic runs."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    venue_id: str = Field(pattern=_ID_PATTERN)
    language: Literal["auto", "en", "es", "fr"] = "auto"
    accessible: bool = False
    location_zone: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    history: List[HistoryTurn] = Field(default_factory=list, max_length=12)


class IncidentRequest(BaseModel):
    venue_id: str = Field(pattern=_ID_PATTERN)
    zone_id: str = Field(pattern=_ID_PATTERN)
    category: Literal[
        "medical", "crowd_crush", "fire_hazard", "security", "lost_child",
        "accessibility", "technical", "cleaning", "lost_item",
    ]
    description: str = Field(min_length=1, max_length=500)
    severity: Optional[int] = Field(default=None, ge=1, le=5)
